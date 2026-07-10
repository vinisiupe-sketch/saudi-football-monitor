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

Pesos de pontuacao:
  Clube:
    text_similarity    0-15 (escalado, nunca resolve sozinho)
    name_exact        +15
    country_correct   +50  (sinal forte -- pais correto e determinante)
    league_correct    +25
    country_incompat  -40
    ambiguous_no_ctx  -20 (nome generico sem contexto de pais)

  Jogador:
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

Limiares:
  MIN_SCORE = 75   score minimo do melhor candidato
  MIN_GAP   = 20   diferenca minima entre 1o e 2o

Raciocinio dos pesos de clube:
  "Sporting CP" + Portugal = 15 (text) + 15 (exact) + 50 (country) = 80 >= 75
  "Sporting"   + Portugal = ~13 (text, sem exact) + 50 = 63 -- ambiguous (correto: pode ser Braga)
  "Sporting"   + Portugal + Primeira Liga = ~13 + 50 + 25 = 88 -- resolved
  "Sporting"   + sem ctx = ~13 - 20 (ambig) = -7 -- unresolved
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

    # 4. Nome generico sem contexto de pais -> penalidade
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
    found_via_team=True -> candidato encontrado dentro de um time resolvido.
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

    return candidates


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
    cache_key = f"club|{norm}|{context.country}|{context.league}"

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
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 3. Cache DB (verifica stale)
    cached = get_entity_resolution("club", norm, context.country, context.league)
    if cached and cached.get("status") not in ("stale", None):
        result = ResolutionResult(
            status=cached["status"],
            af_id=cached.get("af_id"),
            score=cached.get("score"),
            gap=cached.get("score_gap"),
            top_name=cached.get("top_name"),
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 4. Gerar + pontuar candidatos via API
    raw_candidates = await generate_club_candidates(raw_name, context, client, headers)
    scored = [score_club_candidate(c, raw_name, context) for c in raw_candidates]
    result = _pick_winner(scored, STALE_DAYS_CLUB)

    # 5. Salvar no cache DB
    cache_entity_resolution("club", norm, context.country, context.league, result)

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
    cache_key = f"player|{norm}|{context.club_from_id}|{context.club_to_id}"

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
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 3. Cache DB
    cached = get_entity_resolution("player", norm, context.club_from_id, context.club_to_id)
    if cached and cached.get("status") not in ("stale", None):
        result = ResolutionResult(
            status=cached["status"],
            af_id=cached.get("af_id"),
            score=cached.get("score"),
            gap=cached.get("score_gap"),
            top_name=cached.get("top_name"),
        )
        if _session_cache is not None:
            _session_cache[cache_key] = result
        return result

    # 4. Gerar + pontuar candidatos
    raw_candidates = await generate_player_candidates(raw_name, context, client, headers)
    scored = [
        score_player_candidate(item, raw_name, context, via_team)
        for item, via_team in raw_candidates
    ]
    result = _pick_winner(scored, STALE_DAYS_PLAYER)

    # 5. Cache DB
    cache_entity_resolution("player", norm, context.club_from_id, context.club_to_id, result)

    if _session_cache is not None:
        _session_cache[cache_key] = result
    return result


# -- Ponto de entrada principal ------------------------------------------------

async def resolve_transfer_entities(
    data: dict,
    client: httpx.AsyncClient,
    headers: dict,
    _session_cache: dict | None = None,
) -> dict:
    """
    Resolve todas as entidades de um registro de transferencia.

    Atualiza data com:
      af_team_from_id, club_from_status
      af_team_to_id,   club_to_status
      af_player_id,    player_status

    _session_cache: compartilhado entre chamadas para evitar re-resolucao.
    """
    if _session_cache is None:
        _session_cache = {}

    nat         = data.get("player_nationality") or ""
    ctx_country = data.get("context_country") or ""
    ctx_league  = data.get("context_league") or ""
    position    = data.get("player_position") or ""

    age: int | None = None
    try:
        age_str = data.get("player_age") or ""
        age = int(age_str) if age_str else None
    except (ValueError, TypeError):
        pass

    # -- Clube de origem -------------------------------------------------------
    cfrom = data.get("club_from") or ""
    if cfrom and not data.get("af_team_from_id"):
        ctx_from = EntityContext(
            country=ctx_country,
            league=ctx_league,
            nationality=nat,
        )
        r_from = await resolve_club(cfrom, ctx_from, client, headers, _session_cache)
        data["af_team_from_id"]  = r_from.af_id or ""
        data["club_from_status"] = r_from.status
        _log("club_from", cfrom, r_from)

    # -- Clube de destino ------------------------------------------------------
    # No contexto deste monitor, o destino e sempre (ou quase sempre) clube saudita.
    # Alias da warm-saudi-teams garante resolucao sem chamadas extras para clubes SPL.
    cto = data.get("club_to") or ""
    if cto and not data.get("af_team_to_id"):
        ctx_to = EntityContext(country="Saudi Arabia", league="Saudi Pro League")
        r_to = await resolve_club(cto, ctx_to, client, headers, _session_cache)
        data["af_team_to_id"]   = r_to.af_id or ""
        data["club_to_status"]  = r_to.status
        _log("club_to", cto, r_to)

    # -- Jogador ---------------------------------------------------------------
    pname = data.get("player_name") or ""
    if pname and not data.get("af_player_id"):
        ctx_player = EntityContext(
            nationality=nat,
            club_from_id=data.get("af_team_from_id") or "",
            club_to_id=data.get("af_team_to_id") or "",
            position=position,
            age=age,
        )
        r_player = await resolve_player(pname, ctx_player, client, headers, _session_cache)
        data["af_player_id"]   = r_player.af_id or ""
        data["player_status"]  = r_player.status
        _log("player", pname, r_player)

    return data


def _log(entity: str, raw_name: str, result: ResolutionResult) -> None:
    status_icons = {
        "resolved": "[OK]", "ambiguous": "[??]",
        "unresolved": "[--]", "manually_resolved": "[MN]", "stale": "[ST]",
    }
    icon = status_icons.get(result.status, "[?]")
    print(
        f"   {icon} [{entity}] '{raw_name}' -> {result.status} | "
        f"id={result.af_id} | score={result.score} | gap={result.gap}"
    )
    if result.candidates:
        for c in result.candidates[:3]:
            print(f"      [{c.score:6.1f}] {c.name} ({c.country}) {c.breakdown}")
