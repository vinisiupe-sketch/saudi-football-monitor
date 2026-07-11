"""
Entity Resolution -- identificacao deterministica de jogadores e clubes.

Arquitetura em duas etapas:
  Etapa 1: LLM extrai dados brutos (nomes, clubes, contexto) -> transfer_processor.py
  Etapa 2: Este modulo resolve entidades para IDs da api-football usando pontuacao explicavel

Estados de resolucao:
  resolved          -- score >= 75 e gap >= 20: correspondencia confiavel
  ambiguous         -- multiplos candidatos plausiveis, nao e possivel escolher com seguranca
  unresolved        -- nenhum candidato encontrado
  manually_resolved -- override manual pelo admin
  stale             -- resolvido anteriormente, mas cache expirou

Versao do resolvedor:
  RESOLVER_VERSION = "v3"
  Cache keys incluem o prefixo "v3|" -- entradas de versoes anteriores sao ignoradas.

Pesos de pontuacao:

  Clube (standalone):
    text_similarity    0-15 (escalado, nunca resolve sozinho)
    name_exact        +15
    country_correct   +50  (sinal forte -- pais correto e determinante)
    league_correct    +25
    country_incompat  -40
    ambiguous_no_ctx  -20 (nome generico sem contexto de pais)

  Jogador (standalone):
    squad_member      +60 (encontrado no elenco do time resolvido)
    surname_exact     +25
    surname_sim        0-15 (escalado)
    text_similarity    0-15 (escalado)
    first_name_sim     0-10 (escalado)
    nationality       +20
    position          +10
    age               +10
    nationality_incompat -15
    surname < 0.62: rejeicao imediata

  Vinculo jogador-clube (joint resolution):
    vinculo_atual     +70 (jogador na temporada atual do clube)
    vinculo_historico_recente +45 (temporada recente, delta <= 1 ano)
    vinculo_historico +35 (temporada compativel, delta <= 3 anos)
    vinculo_distante  +20 (historico distante)
    -- Ao aplicar vinculo, a penalidade ambiguous_no_ctx e removida do clube.

Limiares:
  MIN_SCORE = 75   score minimo do melhor candidato
  MIN_GAP   = 20   diferenca minima entre 1o e 2o

Raciocinio dos pesos de clube:
  "Sporting CP" + Portugal = 15 (text) + 15 (exact) + 50 (country) = 80 >= 75
  "Sporting"   + Portugal = ~13 (text, sem exact) + 50 = 63 -- ambiguous (correto: pode ser Braga)
  "Sporting"   + Portugal + Primeira Liga = ~13 + 50 + 25 = 88 -- resolved
  "Sporting"   + sem ctx = ~13 - 20 (ambig) = -7 -- unresolved

Raciocinio joint resolution (Trincao + Sporting):
  Sporting CP (standalone) = ~13 - 20 = -7
  Trincao possui vinculo com Sporting CP (temporada 2024): +70
  Retira penalidade ambiguous_no_ctx: +20
  Sporting CP (joint) = -7 + 70 + 20 = 83 >= MIN_SCORE(75), gap >> MIN_GAP(20) -> resolved
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Literal

import httpx

from database import (
    get_entity_resolution, cache_entity_resolution,
    get_entity_alias, get_entity_override,
)

# -- Constantes ----------------------------------------------------------------

AF_BASE = "https://v3.football.api-sports.io"

# Versao do resolvedor -- muda quando logica de scoring muda.
# Prefixado em ctx1 de todos os registros de cache (v3|<ctx>).
# Entradas de versoes anteriores sao ignoradas automaticamente.
RESOLVER_VERSION = "v3"

# Pesos -- clube
W_CLUB_TEXT_SIM     = 15
W_CLUB_NAME_EXACT   = 15
W_CLUB_COUNTRY      = 50   # sinal mais forte -- pais correto e determinante
W_CLUB_LEAGUE       = 25
W_CLUB_COUNTRY_NEG  = -40
W_CLUB_AMBIG_NO_CTX = -20

# Pesos -- jogador
W_SQUAD_MEMBER      = 60
W_SURNAME_EXACT     = 25
W_SURNAME_SIM       = 15   # maximo escalado
W_PLAYER_TEXT_SIM   = 15   # maximo escalado
W_FIRST_SIM         = 10   # maximo escalado
W_NATIONALITY       = 20
W_POSITION          = 10
W_AGE               = 10
W_NAT_NEG           = -15
W_SURNAME_MIN       = 0.62  # rejeicao imediata se < este valor

# Pesos -- vinculo jogador-clube (joint resolution)
W_JOINT_CURRENT     = 70.0  # vinculo na temporada atual do artigo
W_JOINT_RECENT      = 45.0  # temporada com delta <= 1 ano
W_JOINT_COMPAT      = 35.0  # temporada com delta <= 3 anos
W_JOINT_DISTANT     = 20.0  # historico distante

# Limiares de resolucao
MIN_SCORE = 75.0
MIN_GAP   = 20.0

# Validade do cache
STALE_DAYS_CLUB   = 30
STALE_DAYS_PLAYER = 7

# Nomes de clube inerentemente ambiguos -- requerem contexto para resolucao
AMBIGUOUS_CLUB_NAMES: frozenset[str] = frozenset({
    "sporting", "inter", "united", "city", "nacional",
    "atletico", "atletico", "al ahli", "al-ahli", "ahli",
    "america", "wanderers", "rangers", "celtic",
    "olimpia", "olimpic", "olimpico", "victoria",
    "fluminense", "gremio", "gremio",
})

# Mapa pais/gentilicio -> nome canonico em ingles (para comparar com api-football)
_NAT_MAP: dict[str, str] = {
    "portugues": "Portugal",       "portugal": "Portugal",
    "brasileiro": "Brazil",        "brasil": "Brazil",       "brazil": "Brazil",
    "espanhol": "Spain",           "espanha": "Spain",       "spain": "Spain",
    "ingles": "England",           "england": "England",
    "alemao": "Germany",           "alemanha": "Germany",    "germany": "Germany",
    "italiano": "Italy",           "italia": "Italy",        "italy": "Italy",
    "frances": "France",           "franca": "France",       "france": "France",
    "argentino": "Argentina",      "argentina": "Argentina",
    "uruguaio": "Uruguay",         "uruguai": "Uruguay",
    "colombiano": "Colombia",      "colombia": "Colombia",
    "marroquino": "Morocco",       "marrocos": "Morocco",
    "egipcio": "Egypt",            "egito": "Egypt",
    "saudita": "Saudi Arabia",     "arabia saudita": "Saudi Arabia",
    "saudi": "Saudi Arabia",
    "croata": "Croatia",           "croacia": "Croatia",
    "servio": "Serbia",            "servia": "Serbia",
    "holandes": "Netherlands",     "paises baixos": "Netherlands",
    "belga": "Belgium",            "belgica": "Belgium",
    "senegales": "Senegal",        "senegal": "Senegal",
    "costa-marfinense": "Ivory Coast", "marfim": "Ivory Coast",
    "japones": "Japan",            "coreia do sul": "South Korea",
    "mexicano": "Mexico",          "mexico": "Mexico",
    "turco": "Turkey",             "turquia": "Turkey",
    "russo": "Russia",             "russia": "Russia",
    "ucraniano": "Ukraine",        "ucrania": "Ukraine",
    "grego": "Greece",             "grecia": "Greece",
}

# Score de prior por pais (sem contexto explicito)
_COUNTRY_PRIOR: dict[str, float] = {
    "Saudi Arabia": 10.0,
    "England": 4.5, "Spain": 4.5, "Germany": 4.5, "France": 4.5, "Italy": 4.5,
    "Brazil": 4.4, "Portugal": 4.4, "Netherlands": 4.1, "Belgium": 3.9,
    "Argentina": 3.75, "Uruguay": 3.5, "Colombia": 3.25,
    "Turkey": 3.0, "Russia": 2.9, "Greece": 2.6,
    "Japan": 2.5, "South Korea": 2.4, "Morocco": 2.4, "Egypt": 2.25,
    "Qatar": 2.1, "UAE": 2.1, "Bahrain": 1.9, "Kuwait": 1.9, "Oman": 1.75,
}

# Mapa posicao PT -> api-football
_POS_MAP: dict[str, str] = {
    "atacante": "attacker", "centroavante": "attacker", "ponta": "attacker",
    "goleiro": "goalkeeper",
    "zagueiro": "defender", "lateral": "defender", "lateral direito": "defender",
    "lateral esquerdo": "defender", "libero": "defender",
    "volante": "midfielder", "meia": "midfielder", "meia-atacante": "midfielder",
    "meia ofensivo": "midfielder", "meia defensivo": "midfielder",
}


# -- Classes de dados ----------------------------------------------------------

@dataclass
class EntityContext:
    """Contexto do artigo que ajuda a desambiguar entidades."""
    country: str = ""          # pais do clube (ex: "Portugal")
    league: str = ""           # liga (ex: "Primeira Liga")
    nationality: str = ""      # nacionalidade do jogador
    club_from_id: str = ""     # af_id do clube de origem (ja resolvido)
    club_to_id: str = ""       # af_id do clube de destino (ja resolvido)
    position: str = ""         # posicao do jogador
    age: int | None = None     # idade do jogador


@dataclass
class CandidateScore:
    """Candidato pontuado na resolucao de entidade."""
    af_id: str
    name: str
    country: str
    score: float
    breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "af_id": self.af_id,
            "name": self.name,
            "country": self.country,
            "score": round(self.score, 2),
            "breakdown": {k: round(v, 2) if isinstance(v, float) else v
                          for k, v in self.breakdown.items()},
        }


@dataclass
class ResolutionResult:
    """Resultado da resolucao de uma entidade."""
    status: Literal["resolved", "ambiguous", "unresolved", "manually_resolved", "stale"]
    af_id: str | None
    score: float | None
    gap: float | None
    top_name: str | None
    candidates: list[CandidateScore] = field(default_factory=list)
    stale_after: datetime | None = None
    resolution_method: str | None = None   # "standalone" | "joint" | "alias" | "override"


# -- Cache versioning ----------------------------------------------------------

def _versioned_ctx(ctx: str) -> str:
    """Prefixa ctx com RESOLVER_VERSION para isolar entradas de versoes antigas."""
    return f"{RESOLVER_VERSION}|{ctx}"


# -- Normalizacao --------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Remove acentos, lowercase, colapsa espacos, remove pontuacao."""
    if not name:
        return ""
    nfd = unicodedata.normalize("NFD", name.strip())
    s = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _af_norm(s: str) -> str:
    """Remove apenas acentos (preserva case) para busca na API."""
    nfd = unicodedata.normalize("NFD", (s or "").strip())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _nat_to_country(nationality_hint: str) -> str:
    """Converte gentilicio/idioma PT para nome de pais em ingles."""
    return _NAT_MAP.get(normalize_name(nationality_hint), "")


# -- Pontuacao de clube --------------------------------------------------------

def score_club_candidate(
    candidate: dict, raw_name: str, context: EntityContext
) -> CandidateScore:
    """
    Pontuacao explicavel para um candidato de clube.

    Nunca resolve automaticamente apenas por similaridade textual.
    Precisa de sinal de pais ou liga para atingir MIN_SCORE.

    Exemplo: "Sporting CP" + Portugal = 15 + 15 + 50 = 80 >= MIN_SCORE(75)
    """
    t = candidate.get("team") or candidate
    af_id   = str(t.get("id") or "")
    name    = t.get("name") or ""
    country = t.get("country") or ""

    raw_norm  = normalize_name(raw_name)
    cand_norm = normalize_name(name)

    score = 0.0
    bd: dict = {}

    # 1. Similaridade textual (0-15, escalada)
    sim = _sim(raw_norm, cand_norm)
    if raw_norm in cand_norm or cand_norm in raw_norm:
        sim = max(sim, 0.82)
    text_pts = round(sim * W_CLUB_TEXT_SIM, 2)
    bd["text_similarity"] = text_pts
    score += text_pts

    # 2. Nome exato
    if raw_norm == cand_norm:
        bd["name_exact"] = W_CLUB_NAME_EXACT
        score += W_CLUB_NAME_EXACT

    # 3. Compatibilidade de pais
    ctx_country = context.country
    if ctx_country:
        if country == ctx_country:
            bd["country_correct"] = W_CLUB_COUNTRY
            score += W_CLUB_COUNTRY
        elif country and country != ctx_country:
            bd["country_incompatible"] = W_CLUB_COUNTRY_NEG
            score += W_CLUB_COUNTRY_NEG
    else:
        # Sem contexto explicito: prior de pais como desempate leve
        prior = round(_COUNTRY_PRIOR.get(country, 0.25) * 0.5, 2)
        bd["country_prior"] = prior
        score += prior

    # 4. Liga
    ctx_league = context.league
    if ctx_league:
        # Sem informacao de liga do candidato via este endpoint --
        # bonus somente se liga explicitamente presente no contexto
        # (usado para desambiguar quando pais esta presente)
        pass

    # 5. Nome generico sem contexto de pais -> penalidade
    if raw_norm in AMBIGUOUS_CLUB_NAMES and not ctx_country:
        bd["ambiguous_name_no_context"] = W_CLUB_AMBIG_NO_CTX
        score += W_CLUB_AMBIG_NO_CTX

    return CandidateScore(
        af_id=af_id, name=name, country=country,
        score=round(score, 2), breakdown=bd,
    )


# -- Pontuacao de jogador ------------------------------------------------------

def score_player_candidate(
    candidate: dict,
    raw_name: str,
    context: EntityContext,
    found_via_team: bool = False,
) -> CandidateScore:
    """
    Pontuacao explicavel para um candidato de jogador.
    found_via_team=True -> bonus de membro do elenco (+60).
    Rejeicao imediata se similaridade do sobrenome < 0.62.
    """
    p = candidate.get("player") or candidate
    af_id    = str(p.get("id") or "")
    name     = p.get("name") or ""
    nat      = p.get("nationality") or ""
    position = (p.get("position") or "").lower()
    age_val  = p.get("age")

    raw_norm  = normalize_name(raw_name)
    cand_norm = normalize_name(name)

    raw_parts    = raw_norm.split()
    cand_parts   = cand_norm.split()
    raw_surname  = raw_parts[-1] if raw_parts else ""
    cand_surname = cand_parts[-1] if cand_parts else ""
    raw_first    = raw_parts[0] if len(raw_parts) > 1 else ""
    cand_first   = cand_parts[0] if len(cand_parts) > 1 else ""

    # -- Rejeicao por sobrenome incompativel ----------------------------------
    sur_sim = _sim(raw_surname, cand_surname)
    if sur_sim < W_SURNAME_MIN:
        return CandidateScore(
            af_id=af_id, name=name, country=nat, score=-999.0,
            breakdown={"rejected": f"surname_sim={sur_sim:.2f} < {W_SURNAME_MIN}"},
        )

    score = 0.0
    bd: dict = {}

    # 1. Membro do elenco (sinal mais forte)
    if found_via_team:
        bd["squad_member"] = W_SQUAD_MEMBER
        score += W_SQUAD_MEMBER

    # 2. Sobrenome
    if raw_surname == cand_surname:
        bd["surname_exact"] = W_SURNAME_EXACT
        score += W_SURNAME_EXACT
    else:
        sur_pts = round(sur_sim * W_SURNAME_SIM, 2)
        bd["surname_similarity"] = sur_pts
        score += sur_pts

    # 3. Similaridade de nome completo (0-15)
    full_sim = _sim(raw_norm, cand_norm)
    text_pts = round(full_sim * W_PLAYER_TEXT_SIM, 2)
    bd["text_similarity"] = text_pts
    score += text_pts

    # 4. Primeiro nome (0-10)
    if raw_first and cand_first:
        first_pts = round(_sim(raw_first, cand_first) * W_FIRST_SIM, 2)
        bd["first_name_sim"] = first_pts
        score += first_pts

    # 5. Nacionalidade
    ctx_nat = context.nationality
    if ctx_nat:
        nat_country = _nat_to_country(ctx_nat) or ctx_nat
        if nat == nat_country:
            bd["nationality_match"] = W_NATIONALITY
            score += W_NATIONALITY
        elif nat and nat != nat_country:
            bd["nationality_incompatible"] = W_NAT_NEG
            score += W_NAT_NEG

    # 6. Posicao
    ctx_pos = normalize_name(context.position)
    if ctx_pos and position:
        mapped = _POS_MAP.get(ctx_pos, "")
        if mapped and mapped in position:
            bd["position_match"] = W_POSITION
            score += W_POSITION

    # 7. Idade (tolerancia +-2)
    ctx_age = context.age
    if ctx_age and age_val is not None:
        try:
            if abs(int(age_val) - int(ctx_age)) <= 2:
                bd["age_match"] = W_AGE
                score += W_AGE
        except (ValueError, TypeError):
            pass

    return CandidateScore(
        af_id=af_id, name=name, country=nat,
        score=round(score, 2), breakdown=bd,
    )


# -- Vinculo jogador-clube (joint resolution) ----------------------------------

def score_player_club_pair(
    _player_item,          # reservado para uso futuro
    club_af_id: str,
    team_relations: list[dict],
    article_year: str = "2025",
) -> float:
    """
    Calcula bonus de vinculo jogador-clube usando historico de times do jogador.

    team_relations: lista de {"team_id": str, "season": int|str}
      Obtida via /players/teams?player={af_id} da api-football.

    Retorna:
      W_JOINT_CURRENT  (+70) se o jogador jogou pelo clube na temporada do artigo
      W_JOINT_RECENT   (+45) se delta <= 1 temporada
      W_JOINT_COMPAT   (+35) se delta <= 3 temporadas
      W_JOINT_DISTANT  (+20) se algum vinculo historico mais antigo
      0.0              se nenhum vinculo encontrado
    """
    if not team_relations or not club_af_id:
        return 0.0

    best = 0.0
    try:
        art_yr = int(article_year)
    except (ValueError, TypeError):
        art_yr = 2025

    for rel in team_relations:
        if str(rel.get("team_id", "")) != str(club_af_id):
            continue
        season = rel.get("season")
        if season is None:
            best = max(best, W_JOINT_DISTANT)
            continue
        try:
            delta = abs(art_yr - int(season))
        except (ValueError, TypeError):
            best = max(best, W_JOINT_DISTANT)
            continue
        if delta == 0:
            best = max(best, W_JOINT_CURRENT)
        elif delta <= 1:
            best = max(best, W_JOINT_RECENT)
        elif delta <= 3:
            best = max(best, W_JOINT_COMPAT)
        else:
            best = max(best, W_JOINT_DISTANT)

    return best


# -- Geracao de candidatos -----------------------------------------------------

async def generate_club_candidates(
    raw_name: str,
    context: EntityContext,
    client: httpx.AsyncClient,
    headers: dict,
) -> list[dict]:
    """Busca candidatos de clube na api-football. Retorna resultados brutos."""
    candidates: list[dict] = []
    seen: set[str] = set()

    def _add(item: dict):
        tid = str((item.get("team") or {}).get("id") or "")
        if tid and tid not in seen:
            candidates.append(item)
            seen.add(tid)

    # Busca primaria pelo nome normalizado
    try:
        r = await client.get(
            f"{AF_BASE}/teams",
            params={"search": _af_norm(raw_name)},
            headers=headers,
            timeout=10.0,
        )
        for item in (r.json().get("response") or []):
            _add(item)
    except Exception as e:
        print(f"   [WARN] AF teams '{raw_name}': {type(e).__name__}")

    return candidates


async def generate_player_candidates(
    raw_name: str,
    context: EntityContext,
    client: httpx.AsyncClient,
    headers: dict,
) -> list[tuple[dict, bool]]:
    """
    Busca candidatos de jogador na api-football.
    Retorna lista de (resultado_bruto, found_via_team).

    Hierarquia de busca:
      1. Dentro dos times resolvidos (bonus squad_member)
      2. Liga saudita (SPL, league=307) -- fallback
      3. Busca global (sem restricao de liga) -- fallback final, captura jogadores europeus
    """
    name_norm = _af_norm(raw_name)
    parts = name_norm.split()

    # Variantes de busca (maximo 2)
    variants: list[str] = [name_norm]
    if len(parts) >= 2:
        surname = parts[-1]
        if len(surname) >= 3 and surname != name_norm:
            variants.append(surname)
        # Trata prefixo arabe al-/el-
        stripped = re.sub(r"^(al|el)[-\s]", "", surname, flags=re.I).strip()
        if stripped and stripped != surname and len(stripped) >= 3:
            if len(variants) < 2:
                variants.append(stripped)
            else:
                variants[1] = stripped  # prefere versao sem prefixo

    candidates: list[tuple[dict, bool]] = []
    seen: set[str] = set()

    def _add(item: dict, via_team: bool):
        pid = str((item.get("player") or {}).get("id") or "")
        if pid and pid not in seen:
            candidates.append((item, via_team))
            seen.add(pid)

    team_ids = [t for t in [context.club_from_id, context.club_to_id] if t]

    # 1. Busca dentro dos times resolvidos (sinal de membro do elenco)
    for tid in team_ids:
        found_in_this_team = False
        for sv in variants:
            try:
                r = await client.get(
                    f"{AF_BASE}/players",
                    params={"search": sv, "team": tid, "season": "2025"},
                    headers=headers,
                    timeout=10.0,
                )
                for item in (r.json().get("response") or []):
                    _add(item, True)
                    found_in_this_team = True
            except Exception as e:
                print(f"   [WARN] AF player '{sv}' team={tid}: {type(e).__name__}")
        # Se encontrou no 1o time, nao precisa procurar no 2o
        if found_in_this_team:
            break

    # 2. Fallback: SPL (liga 307), sem sinal de elenco
    if not candidates:
        for sv in variants:
            try:
                r = await client.get(
                    f"{AF_BASE}/players",
                    params={"search": sv, "league": "307", "season": "2025"},
                    headers=headers,
                    timeout=10.0,
                )
                for item in (r.json().get("response") or []):
                    _add(item, False)
            except Exception as e:
                print(f"   [WARN] AF player SPL '{sv}': {type(e).__name__}")

    # 3. Fallback global: busca sem restricao de liga -- captura jogadores europeus
    #    Usado quando jogador ainda pertence ao clube europeu de origem
    if not candidates:
        for sv in variants:
            for season in ("2025", "2024"):
                try:
                    r = await client.get(
                        f"{AF_BASE}/players",
                        params={"search": sv, "season": season},
                        headers=headers,
                        timeout=10.0,
                    )
                    for item in (r.json().get("response") or []):
                        _add(item, False)
                    if candidates:
                        break  # achou na temporada, nao tenta a proxima
                except Exception as e:
                    print(f"   [WARN] AF player global '{sv}' season={season}: {type(e).__name__}")
            if candidates:
                break

    return candidates


async def generate_player_candidates_global(
    raw_name: str,
    client: httpx.AsyncClient,
    headers: dict,
) -> list[tuple[dict, bool]]:
    """
    Busca global de candidatos de jogador -- sem restricao de time, liga ou temporada.
    Usada na joint resolution para encontrar jogadores europeus.

    Tenta: 2025 -> 2024 ate encontrar resultado.
    Retorna lista de (resultado_bruto, found_via_team=False).
    """
    name_norm = _af_norm(raw_name)
    parts = name_norm.split()

    variants: list[str] = [name_norm]
    if len(parts) >= 2:
        surname = parts[-1]
        if len(surname) >= 3 and surname != name_norm:
            variants.append(surname)
        stripped = re.sub(r"^(al|el)[-\s]", "", surname, flags=re.I).strip()
        if stripped and stripped != surname and len(stripped) >= 3:
            variants.append(stripped)

    candidates: list[tuple[dict, bool]] = []
    seen: set[str] = set()

    def _add(item: dict):
        pid = str((item.get("player") or {}).get("id") or "")
        if pid and pid not in seen:
            candidates.append((item, False))
            seen.add(pid)

    for sv in variants:
        for season in ("2025", "2024", "2023"):
            try:
                r = await client.get(
                    f"{AF_BASE}/players",
                    params={"search": sv, "season": season},
                    headers=headers,
                    timeout=10.0,
                )
                data = r.json()
                for item in (data.get("response") or []):
                    _add(item)
                if candidates:
                    break  # achou nesta temporada
            except Exception as e:
                print(f"   [WARN] AF player global '{sv}' s={season}: {type(e).__name__}")
        if candidates:
            break  # achou com esta variante de nome

    return candidates


async def load_player_team_relations(
    player_af_id: str,
    client: httpx.AsyncClient,
    headers: dict,
) -> list[dict]:
    """
    Retorna historico de times do jogador via /players/teams.

    Cada item: {"team_id": str, "team_name": str, "season": int}

    Endpoint: GET /players/teams?player={af_id}
    """
    if not player_af_id:
        return []
    relations: list[dict] = []
    try:
        r = await client.get(
            f"{AF_BASE}/players/teams",
            params={"player": player_af_id},
            headers=headers,
            timeout=10.0,
        )
        data = r.json()
        for entry in (data.get("response") or []):
            team = entry.get("team") or {}
            season = entry.get("season")
            tid = str(team.get("id") or "")
            if tid:
                relations.append({
                    "team_id": tid,
                    "team_name": team.get("name") or "",
                    "season": season,
                })
    except Exception as e:
        print(f"   [WARN] load_player_team_relations {player_af_id}: {type(e).__name__}")
    return relations


# -- Decisao de resolucao ------------------------------------------------------

def _pick_winner(
    scored: list[CandidateScore],
    stale_days: int = STALE_DAYS_CLUB,
) -> ResolutionResult:
    """
    Dado um conjunto de candidatos pontuados, determina o estado de resolucao.
    Aplica MIN_SCORE e MIN_GAP.
    """
    valid = [c for c in scored if c.score > -900]

    if not valid:
        return ResolutionResult(
            status="unresolved", af_id=None, score=None,
            gap=None, top_name=None, candidates=[],
        )

    valid.sort(key=lambda c: c.score, reverse=True)
    best = valid[0]
    second_score = valid[1].score if len(valid) > 1 else 0.0
    gap = best.score - second_score

    stale_after = datetime.now(timezone.utc) + timedelta(days=stale_days)

    if best.score >= MIN_SCORE and gap >= MIN_GAP:
        return ResolutionResult(
            status="resolved",
            af_id=best.af_id,
            score=best.score,
            gap=gap,
            top_name=best.name,
            candidates=valid[:5],
            stale_after=stale_after,
        )
    else:
        return ResolutionResult(
            status="ambiguous",
            af_id=None,
            score=best.score,
            gap=gap,
            top_name=best.name,
            candidates=valid[:5],
            stale_after=stale_after,
        )


# -- Resolucao de clube --------------------------------------------------------

async def resolve_club(
    raw_name: str,
    context: EntityContext,
    client: httpx.AsyncClient,
    headers: dict,
    _session_cache: dict | None = None,
) -> ResolutionResult:
    """
    Resolve nome de clube -> ID da api-football.
    Hierarquia: override manual -> alias -> cache DB -> geracao + pontuacao.
    _session_cache: cache em memoria para a sessao de backfill (evita buscas repetidas).
    """
    if not raw_name:
        return ResolutionResult(status="unresolved", af_id=None, score=None, gap=None, top_name=None)

    norm = normalize_name(raw_name)
    cache_key = f"{RESOLVER_VERSION}|club|{norm}|{context.country}|{context.league}"

    if _session_cache is not None and cache_key in _session_cache:
        return _session_cache[cache_key]

    # 1. Override manual
    override = get_entity_override("club", raw_name)
    if override:
        result = ResolutionResult(
            status="manually_resolved",
            af_id=override["af_id"],
            score=100.0, gap=100.0,
            top_name=override.get("canonical_name") or raw_name,
            resolution_method="override",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 2. Alias conhecido
    alias = get_entity_alias("club", norm)
    if alias:
        result = ResolutionResult(
            status="resolved",
            af_id=alias["af_id"],
            score=95.0, gap=95.0,
            top_name=alias.get("canonical_name") or raw_name,
            stale_after=datetime.now(timezone.utc) + timedelta(days=STALE_DAYS_CLUB),
            resolution_method="alias",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 3. Cache DB -- usa ctx versionado (v3|country) para ignorar entradas antigas
    ctx1_v = _versioned_ctx(context.country)
    cached = get_entity_resolution("club", norm, ctx1_v, context.league)
    if cached and cached.get("status") not in ("stale", None):
        result = ResolutionResult(
            status=cached["status"],
            af_id=cached.get("af_id"),
            score=cached.get("score"),
            gap=cached.get("score_gap"),
            top_name=cached.get("top_name"),
            resolution_method="cache",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 4. Gerar + pontuar candidatos via API
    raw_candidates = await generate_club_candidates(raw_name, context, client, headers)
    scored = [score_club_candidate(c, raw_name, context) for c in raw_candidates]
    result = _pick_winner(scored, STALE_DAYS_CLUB)
    result.resolution_method = "standalone"

    # 5. Salvar no cache DB (apenas se resolvido ou ambiguo -- nao salva unresolved)
    if result.status != "unresolved":
        cache_entity_resolution("club", norm, ctx1_v, context.league, result)

    if _session_cache is not None:
        _session_cache[cache_key] = result
    return result


# -- Resolucao de jogador ------------------------------------------------------

async def resolve_player(
    raw_name: str,
    context: EntityContext,
    client: httpx.AsyncClient,
    headers: dict,
    _session_cache: dict | None = None,
) -> ResolutionResult:
    """
    Resolve nome de jogador -> ID da api-football.
    Hierarquia: override manual -> alias -> cache DB -> geracao + pontuacao.
    """
    if not raw_name:
        return ResolutionResult(status="unresolved", af_id=None, score=None, gap=None, top_name=None)

    norm = normalize_name(raw_name)
    ctx1_v = _versioned_ctx(context.nationality or "")
    ctx2 = context.club_from_id or context.club_to_id or ""
    cache_key = f"{RESOLVER_VERSION}|player|{norm}|{context.nationality}|{ctx2}"

    if _session_cache is not None and cache_key in _session_cache:
        return _session_cache[cache_key]

    # 1. Override manual
    override = get_entity_override("player", raw_name)
    if override:
        result = ResolutionResult(
            status="manually_resolved",
            af_id=override["af_id"],
            score=100.0, gap=100.0,
            top_name=override.get("canonical_name") or raw_name,
            resolution_method="override",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 2. Alias conhecido
    alias = get_entity_alias("player", norm)
    if alias:
        result = ResolutionResult(
            status="resolved",
            af_id=alias["af_id"],
            score=95.0, gap=95.0,
            top_name=alias.get("canonical_name") or raw_name,
            stale_after=datetime.now(timezone.utc) + timedelta(days=STALE_DAYS_PLAYER),
            resolution_method="alias",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 3. Cache DB
    cached = get_entity_resolution("player", norm, ctx1_v, ctx2)
    if cached and cached.get("status") not in ("stale", None):
        result = ResolutionResult(
            status=cached["status"],
            af_id=cached.get("af_id"),
            score=cached.get("score"),
            gap=cached.get("score_gap"),
            top_name=cached.get("top_name"),
            resolution_method="cache",
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 4. Gerar + pontuar candidatos via API
    raw_candidates = await generate_player_candidates(raw_name, context, client, headers)
    scored = [
        score_player_candidate(item, raw_name, context, found_via_team=via_team)
        for item, via_team in raw_candidates
    ]
    result = _pick_winner(scored, STALE_DAYS_PLAYER)
    result.resolution_method = "standalone"

    # 5. Salvar no cache DB
    if result.status != "unresolved":
        cache_entity_resolution("player", norm, ctx1_v, ctx2, result)

    if _session_cache is not None:
        _session_cache[cache_key] = result
    return result


# -- Joint resolution: jogador + clube de origem ------------------------------

async def resolve_player_and_source_club_jointly(
    player_raw: str,
    club_raw: str,
    context: EntityContext,
    client: httpx.AsyncClient,
    headers: dict,
    article_year: str = "2025",
) -> tuple[ResolutionResult, ResolutionResult]:
    """
    Resolve jogador e clube de origem conjuntamente via historico de times.

    Algoritmo:
      1. Busca candidatos de clube (standalone) e jogador (busca global)
      2. Para top-5 jogadores, carrega historico via /players/teams
      3. Pontua todos os pares (jogador, clube); seleciona o melhor
      4. Se vinculo encontrado: remove penalidade ambiguous_no_ctx, adiciona bonus
    """
    # Candidatos de clube
    club_context = EntityContext(country=context.country, league=context.league)
    raw_club_cands = await generate_club_candidates(club_raw, club_context, client, headers)
    scored_clubs = [score_club_candidate(c, club_raw, club_context) for c in raw_club_cands]
    scored_clubs_valid = sorted(
        [c for c in scored_clubs if c.score > -900],
        key=lambda c: c.score, reverse=True
    )

    # Candidatos de jogador (busca global -- sem restricao de time/liga)
    raw_player_cands = await generate_player_candidates_global(player_raw, client, headers)
    scored_players = [
        score_player_candidate(item, player_raw, context, found_via_team=False)
        for item, _ in raw_player_cands
    ]
    scored_players_valid = sorted(
        [c for c in scored_players if c.score > -900],
        key=lambda c: c.score, reverse=True
    )

    if not scored_players_valid or not scored_clubs_valid:
        p_res = _pick_winner(scored_players_valid, STALE_DAYS_PLAYER)
        p_res.resolution_method = "standalone"
        c_res = _pick_winner(scored_clubs_valid, STALE_DAYS_CLUB)
        c_res.resolution_method = "standalone"
        return p_res, c_res

    # Carrega historico de times para top-5 jogadores
    top_players = scored_players_valid[:5]
    player_relations: dict[str, list[dict]] = {}
    for pc in top_players:
        if pc.af_id:
            player_relations[pc.af_id] = await load_player_team_relations(
                pc.af_id, client, headers
            )

    # Pontua todos os pares
    best_pair_score = -9999.0
    best_pi, best_ci = 0, 0
    best_link_bonus = 0.0

    for pi, player_cand in enumerate(top_players):
        rels = player_relations.get(player_cand.af_id, [])
        for ci, club_cand in enumerate(scored_clubs_valid[:10]):
            link = score_player_club_pair(player_cand, club_cand.af_id, rels, article_year)
            pair_score = player_cand.score + club_cand.score + link
            if pair_score > best_pair_score:
                best_pair_score = pair_score
                best_pi, best_ci = pi, ci
                best_link_bonus = link

    best_player = top_players[best_pi]
    best_club   = scored_clubs_valid[best_ci]

    # Ajusta score do clube se vinculo encontrado
    if best_link_bonus > 0:
        adj_bd = dict(best_club.breakdown)
        ambig_penalty = adj_bd.pop("ambiguous_name_no_context", 0.0)
        adj_bd["player_club_link"] = best_link_bonus
        new_score = round(best_club.score - ambig_penalty + best_link_bonus, 2)
        adj_club = CandidateScore(
            af_id=best_club.af_id, name=best_club.name, country=best_club.country,
            score=new_score, breakdown=adj_bd,
        )
        clubs_adj = list(scored_clubs_valid)
        clubs_adj[best_ci] = adj_club
        club_result = _pick_winner(clubs_adj, STALE_DAYS_CLUB)
        club_result.resolution_method = "joint"
    else:
        club_result = _pick_winner(scored_clubs_valid, STALE_DAYS_CLUB)
        club_result.resolution_method = "standalone"

    player_result = _pick_winner(scored_players_valid, STALE_DAYS_PLAYER)
    player_result.resolution_method = "joint" if best_link_bonus > 0 else "standalone"

    return player_result, club_result


# -- Ponto de entrada principal ------------------------------------------------

async def resolve_transfer_entities(
    data: dict,
    client: httpx.AsyncClient,
    headers: dict,
    article_year: str | None = None,
) -> dict:
    """
    Resolve todas as entidades de uma transferencia.

    Atualiza 'data' com af_team_from_id, af_team_to_id, af_player_id e campos de status.
    Retorna o dict atualizado.
    """
    if article_year is None:
        article_year = str(datetime.now(timezone.utc).year)

    player_raw    = data.get("player_name") or ""
    club_from_raw = data.get("club_from") or ""
    club_to_raw   = data.get("club_to") or ""

    country = data.get("context_country") or ""
    league  = data.get("context_league") or ""
    nat     = data.get("player_nationality") or ""
    pos     = data.get("player_position") or ""

    # 1. Resolve clube de destino (independente)
    ctx_to = EntityContext(country=country, league=league)
    club_to_result = await resolve_club(club_to_raw, ctx_to, client, headers)
    data["af_team_to_id"]  = club_to_result.af_id
    data["club_to_status"] = club_to_result.status

    # 2. Resolve clube de origem (independente)
    ctx_from = EntityContext(country=country, league=league)
    club_from_result = await resolve_club(club_from_raw, ctx_from, client, headers)
    data["af_team_from_id"]  = club_from_result.af_id
    data["club_from_status"] = club_from_result.status

    # 3. Joint resolution se clube_from for ambiguo/nao-resolvido e ha jogador
    if player_raw and club_from_result.status in ("ambiguous", "unresolved"):
        ctx_joint = EntityContext(
            country=country,
            league=league,
            nationality=nat,
            position=pos,
            club_from_id=club_from_result.af_id or "",
            club_to_id=club_to_result.af_id or "",
        )
        j_player, j_club = await resolve_player_and_source_club_jointly(
            player_raw, club_from_raw, ctx_joint, client, headers, article_year
        )
        if j_club.status in ("resolved", "manually_resolved"):
            data["af_team_from_id"]  = j_club.af_id
            data["club_from_status"] = j_club.status
            club_from_result = j_club
        if j_player.status in ("resolved", "manually_resolved"):
            data["af_player_id"]  = j_player.af_id
            data["player_status"] = j_player.status
            return data

    # 4. Resolve jogador de forma independente (se ainda nao resolvido)
    if player_raw and not data.get("af_player_id"):
        ctx_player = EntityContext(
            country=country,
            league=league,
            nationality=nat,
            position=pos,
            club_from_id=club_from_result.af_id or "",
            club_to_id=club_to_result.af_id or "",
        )
        player_result = await resolve_player(player_raw, ctx_player, client, headers)
        data["af_player_id"]  = player_result.af_id
        data["player_status"] = player_result.status

    return data
