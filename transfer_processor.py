"""
Extrai metadados estruturados de transferência de artigos com category em ('transferencia','sondagem').
Chamado pelo pipeline de processamento e pelo endpoint de rebuild retroativo.
"""
import json
import asyncio
import re
import unicodedata
import httpx
from urllib.parse import quote as _url_quote
from processor import call_claude
from database import get_player_name_cache, set_player_name_cache

TRANSFER_SYSTEM = (
    "Você é um analista de mercado de transferências especializado na Saudi Pro League. "
    "Extraia metadados estruturados de negociação de jogador a partir de uma notícia esportiva. "
    "Responda APENAS com JSON válido, sem markdown."
)

# Tipos de negociação suportados
NEGO_TYPES = {
    "oficial":     {"label": "Oficial",     "icon": "✅", "color": "#166534", "bg": "#dcfce7", "dark_color": "#4ade80", "dark_bg": "#14532d"},
    "avancado":    {"label": "Avançado",    "icon": "⚡", "color": "#1d4ed8", "bg": "#dbeafe", "dark_color": "#93c5fd", "dark_bg": "#1e3a5f"},
    "negociacoes": {"label": "Negociações", "icon": "🤝", "color": "#b45309", "bg": "#fef3c7", "dark_color": "#fcd34d", "dark_bg": "#451a03"},
    "proposta":    {"label": "Proposta",    "icon": "📋", "color": "#9a3412", "bg": "#ffedd5", "dark_color": "#fb923c", "dark_bg": "#431407"},
    "interesse":   {"label": "Interesse",   "icon": "👁️", "color": "#374151", "bg": "#f3f4f6", "dark_color": "#d1d5db", "dark_bg": "#1f2937"},
    "emprestimo":  {"label": "Empréstimo",  "icon": "🔄", "color": "#0e7490", "bg": "#cffafe", "dark_color": "#67e8f9", "dark_bg": "#164e63"},
    "renovacao":   {"label": "Renovação",   "icon": "🔃", "color": "#6d28d9", "bg": "#ede9fe", "dark_color": "#c4b5fd", "dark_bg": "#2e1065"},
    "sondagem":    {"label": "Sondagem",    "icon": "🔍", "color": "#4b5563", "bg": "#f3f4f6", "dark_color": "#9ca3af", "dark_bg": "#1f2937"},
}


def _name_key(s: str) -> str:
    """Normaliza nome para uso como chave de cache (lowercase, sem acentos, sem pontuação extra)."""
    s = (s or "").strip().lower()
    nfd = unicodedata.normalize("NFD", s)
    s = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


async def normalize_player_name(raw_name: str, client: httpx.AsyncClient,
                                 club_hint: str = "") -> str:
    """Busca a grafia canônica do jogador no Transfermarkt.
    - Retorna o nome canônico se encontrado, ou raw_name caso contrário.
    - Resultado é cacheado em player_name_cache para evitar requisições repetidas.
    """
    if not raw_name:
        return raw_name

    key = _name_key(raw_name)

    # 1) Verifica cache
    cached = get_player_name_cache(key)
    if cached is not None:
        return cached if cached else raw_name  # '' = não encontrado, retorna original

    # 2) Busca no Transfermarkt
    canonical = ""
    tm_id = ""
    _api_ok = False  # True = API respondeu (mesmo sem resultado)
    try:
        r = await client.get(
            f"https://transfermarkt-api.fly.dev/players/search/{_url_quote(raw_name)}",
            timeout=7.0,
        )
        _api_ok = True
        if r.status_code == 200:
            results = r.json().get("results") or []
            if results:
                # Prefere jogadores ligados ao clube hint (club_from ou club_to)
                chosen = None
                if club_hint:
                    hint_low = club_hint.lower()
                    for p in results[:5]:
                        club_name = (p.get("club", {}) or {}).get("name", "") or ""
                        if hint_low in club_name.lower() or club_name.lower() in hint_low:
                            chosen = p
                            break
                if not chosen:
                    chosen = results[0]
                canonical = chosen.get("name") or ""
                tm_id = str(chosen.get("id") or "")
                print(f"   ✅ TM name: '{raw_name}' → '{canonical}'")
            else:
                print(f"   ℹ️  TM: nenhum resultado para '{raw_name}'")
        else:
            print(f"   ⚠️  TM HTTP {r.status_code} para '{raw_name}'")
            _api_ok = False
    except Exception as e:
        print(f"   ⚠️  TM erro de rede para '{raw_name}': {type(e).__name__}: {e}")

    # 3) Armazena no cache SÓ se a API respondeu (não cacheia erros de rede)
    if canonical or _api_ok:
        set_player_name_cache(key, canonical, tm_id)

    return canonical if canonical else raw_name


async def enrich_with_af_ids(data: dict, client: httpx.AsyncClient) -> dict:
    """Busca IDs de jogador e clubes na api-football.
    Usa nome sem acentos (api-football não normaliza Unicode).

    IMPORTANTE: api-football exige 'league' OU 'team' na busca por nome de jogador.
    Encontramos IDs de clube PRIMEIRO, depois usamos esses IDs para buscar o jogador.
    Fallback: ligas europeias conhecidas + Saudi Pro League (307).
    """
    import os, unicodedata as _ud

    key = os.getenv("API_FOOTBALL_KEY", "")
    if not key:
        return data
    hdrs = {"X-Apisports-Key": key}
    AF = "https://v3.football.api-sports.io"

    def _af_norm(s: str) -> str:
        """Remove acentos para busca na api-football."""
        nfd = _ud.normalize("NFD", (s or "").strip())
        return "".join(c for c in nfd if _ud.category(c) != "Mn")

    # Pontuação de país para seleção de time (evita times de países obscuros)
    _COUNTRY_SCORE = {
        "Saudi Arabia": 200,
        "England": 90, "Spain": 90, "Germany": 90, "France": 90, "Italy": 90,
        "Brazil": 88, "Portugal": 88, "Netherlands": 82, "Belgium": 78,
        "Argentina": 75, "Uruguay": 70, "Colombia": 65, "Mexico": 62,
        "Turkey": 60, "Russia": 58, "Ukraine": 55, "Greece": 52,
        "Japan": 50, "South Korea": 48, "Morocco": 48, "Egypt": 45,
        "Qatar": 42, "UAE": 42, "Bahrain": 38, "Kuwait": 38, "Oman": 35,
    }

    from difflib import SequenceMatcher as _SQT

    # Mapeamento: nacionalidade em português → nome de país na api-football
    _NAT_MAP = {
        "português": "Portugal", "portugal": "Portugal",
        "brasileiro": "Brazil", "brasil": "Brazil",
        "espanhol": "Spain", "espanha": "Spain",
        "inglês": "England", "england": "England",
        "alemão": "Germany", "alemanha": "Germany",
        "italiano": "Italy", "itália": "Italy", "italia": "Italy",
        "francês": "France", "franca": "France", "france": "France",
        "argentino": "Argentina", "argentina": "Argentina",
        "uruguaio": "Uruguay", "uruguai": "Uruguay",
        "colombiano": "Colombia", "colombia": "Colombia",
        "marroquino": "Morocco", "marrocos": "Morocco",
        "egípcio": "Egypt", "egito": "Egypt",
        "saudita": "Saudi Arabia", "arabia saudita": "Saudi Arabia",
        "croata": "Croatia", "croácia": "Croatia",
        "sérvio": "Serbia", "sérvia": "Serbia",
        "holandês": "Netherlands", "países baixos": "Netherlands",
        "belga": "Belgium", "bélgica": "Belgium",
        "japonês": "Japan", "japão": "Japan",
    }

    def _pick_team(results: list, target_name: str, nationality_hint: str = "") -> dict:
        """Seleciona o melhor time por scoring: país + similaridade de nome.
        nationality_hint: nationalidade do jogador em português (ex: 'Portugal')
        → usada para dar bônus ao país de origem do jogador quando não é saudita.
        """
        import unicodedata as _udn2
        def _simp(s):
            nfd = _udn2.normalize("NFD", (s or "").lower().strip())
            return "".join(c for c in nfd if _udn2.category(c) != "Mn")

        hint_country = _NAT_MAP.get(_simp(nationality_hint), "")
        target_low = _af_norm(target_name).lower()
        best_t, best_score = {}, -1.0
        for r in results:
            t = r.get("team") or {}
            tname = _af_norm(t.get("name") or "").lower()
            country = t.get("country") or ""
            c_score = _COUNTRY_SCORE.get(country, 5)
            # Bônus por nacionalidade do jogador (clube de origem provável)
            if hint_country and country == hint_country:
                c_score += 120
            # Similaridade entre o nome buscado e o nome retornado
            sim = _SQT(None, target_low, tname).ratio()
            # Bônus se um contém o outro (ex: "Sporting" ⊂ "Sporting CP")
            if target_low in tname or tname in target_low:
                sim = max(sim, 0.82)
            total = (c_score * 1.5) + (sim * 100)
            if total > best_score:
                best_score = total
                best_t = t
        return best_t

    # ── Clube de origem ──────────────────────────────────────────────────
    cfrom = data.get("club_from") or ""
    if cfrom and not data.get("af_team_from_id"):
        for _search in (_af_norm(cfrom), cfrom):
            try:
                r = await client.get(f"{AF}/teams",
                    params={"search": _search}, headers=hdrs, timeout=8.0)
                results = r.json().get("response") or []
                if results:
                    chosen = _pick_team(results, cfrom, data.get('player_nationality') or '')
                    tid = str(chosen.get("id") or "")
                    if tid:
                        data["af_team_from_id"] = tid
                        print(f"   🔵 AF team_from: '{cfrom}' → id {tid} ({chosen.get('name')})")
                        break
            except Exception as e:
                print(f"   ⚠️  AF team_from '{cfrom}': {type(e).__name__}")

    # ── Clube de destino (prefere Arábia Saudita) ────────────────────────
    cto = data.get("club_to") or ""
    if cto and not data.get("af_team_to_id"):
        for _search in (_af_norm(cto), cto):
            try:
                r = await client.get(f"{AF}/teams",
                    params={"search": _search}, headers=hdrs, timeout=8.0)
                results = r.json().get("response") or []
                if results:
                    chosen = _pick_team(results, cto, '')
                    tid = str(chosen.get("id") or "")
                    if tid:
                        data["af_team_to_id"] = tid
                        print(f"   🔴 AF team_to: '{cto}' → id {tid} ({chosen.get('name')})")
                        break
            except Exception as e:
                print(f"   ⚠️  AF team_to '{cto}': {type(e).__name__}")

    # ── Jogador (requer league ou team — usa IDs dos clubes acima) ───────
    pname = data.get("player_name") or ""
    if pname and not data.get("af_player_id"):
        pname_norm = _af_norm(pname)
        pid_found = ""
        team_ids = [tid for tid in [data.get("af_team_from_id"), data.get("af_team_to_id")] if tid]
        # Fallback: Saudi(307), Premier(39), La Liga(140), Serie A(135), Bundesliga(78), Ligue1(61), Primeira(94)
        FALLBACK_LEAGUES = ["307", "39", "140", "135", "78", "61", "94", "88"]

        import re as _re2
        from difflib import SequenceMatcher as _SQ

        def _name_variants(name_norm: str) -> list:
            """Variantes de busca para lidar com transliterações árabes divergentes."""
            parts = name_norm.split()
            variants = [name_norm]
            if len(parts) >= 2:
                last = parts[-1]
                if len(last) >= 3 and last != name_norm:
                    variants.append(last)
                # Sobrenome sem prefixo Al-/El-
                last_stripped = _re2.sub(r"^(al|el)([-\s])", "", last, flags=_re2.I).strip()
                if last_stripped and last_stripped != last and len(last_stripped) >= 3:
                    variants.append(last_stripped)
                # Primeiro nome como último recurso
                first = parts[0]
                if len(first) >= 4 and first != name_norm:
                    variants.append(first)
            return list(dict.fromkeys(variants))

        def _best_player_match(results: list, target_norm: str) -> str:
            """Retorna ID do melhor match fuzzy com foco em SOBRENOME.
            
            Estratégia: sobrenome é o identificador primário (peso 70%).
            - Se sobrenomes diferem muito (score < 0.65), rejeita o candidato.
            - Evita confundir 'Trincao' com 'Conceicao'.
            Mínimo de confiança final: 0.60.
            """
            best_id, best_score = "", 0.0
            target_low = target_norm.lower()
            t_parts = target_low.split()
            t_surname = t_parts[-1] if t_parts else ""
            t_first   = t_parts[0] if t_parts else ""
            for item in results:
                p = item.get("player") or {}
                rname = _af_norm(p.get("name") or "").lower()
                r_parts = rname.split()
                r_surname = r_parts[-1] if r_parts else ""
                r_first   = r_parts[0] if r_parts else ""
                # Sobrenome: identificador primário (descarta se muito diferente)
                sur_score = _SQ(None, t_surname, r_surname).ratio()
                if sur_score < 0.62:
                    continue  # sobrenomes incompatíveis → rejeita
                full_score = _SQ(None, target_low, rname).ratio()
                first_score = _SQ(None, t_first, r_first).ratio() if t_first and r_first else 0.5
                # Score composto: sobrenome (60%) + nome completo (30%) + primeiro nome (10%)
                score = sur_score * 0.60 + full_score * 0.30 + first_score * 0.10
                if score > best_score:
                    best_score = score
                    best_id = str(p.get("id") or "")
            return best_id if best_score >= 0.60 else ""

        search_variants = _name_variants(pname_norm)

        for _season in ("2025", "2024", "2023"):
            if pid_found:
                break
            for tid in team_ids:
                for _sv in search_variants:
                    try:
                        r = await client.get(f"{AF}/players",
                            params={"search": _sv, "team": tid, "season": _season},
                            headers=hdrs, timeout=10.0)
                        results = r.json().get("response") or []
                        if results:
                            pid_found = _best_player_match(results, pname_norm)
                            if pid_found:
                                print(f"   📸 AF player: '{pname}' → id {pid_found} (team={tid} s={_season} q='{_sv}')")
                                break
                    except Exception as e:
                        print(f"   ⚠️  AF player '{pname}' team={tid} s={_season}: {type(e).__name__}")
                if pid_found:
                    break
            if pid_found:
                break
            for league in FALLBACK_LEAGUES:
                for _sv in search_variants:
                    try:
                        r = await client.get(f"{AF}/players",
                            params={"search": _sv, "league": league, "season": _season},
                            headers=hdrs, timeout=10.0)
                        results = r.json().get("response") or []
                        if results:
                            pid_found = _best_player_match(results, pname_norm)
                            if pid_found:
                                print(f"   📸 AF player: '{pname}' → id {pid_found} (league={league} s={_season} q='{_sv}')")
                                break
                    except Exception as e:
                        print(f"   ⚠️  AF player '{pname}' league={league} s={_season}: {type(e).__name__}")
                if pid_found:
                    break
            if pid_found:
                break

        if pid_found:
            data["af_player_id"] = pid_found

    return data


async def extract_transfer_meta(article: dict, client: httpx.AsyncClient) -> dict | None:
    """Extrai metadados de negociação. Retorna None se o artigo não envolver transferência de jogador."""
    title = article.get("title_pt") or article.get("title_orig", "")
    body = article.get("body_pt") or article.get("body_orig", "")
    source = article.get("source_name", "")
    published = (article.get("published_at") or "")[:10]

    prompt = f"""Analise o artigo abaixo e extraia dados de transferência/negociação envolvendo jogador da Saudi Pro League.

Título: {title}
Texto: {body[:800]}
Fonte: {source}
Data publicação: {published}

Responda com este JSON exato (sem texto extra):
{{
  "is_transfer": true,
  "player_name": "nome do jogador em português ou transliteração latina",
  "player_position": "posição em português (ex: Atacante, Meia, Zagueiro, Lateral Direito, Lateral Esquerdo, Volante, Goleiro) ou null se não mencionado",
  "player_nationality": "país de origem do jogador em português (ex: Brasil, Argentina, França) ou null se não mencionado",
  "club_from": "clube de origem (de onde o jogador SAI) ou null",
  "club_to": "clube de destino (para onde o jogador VAI) ou null",
  "fee": "valor da transferência se mencionado (ex: '€50M', 'free', 'empréstimo') ou null",
  "nego_type": "um de: oficial|avancado|negociacoes|proposta|interesse|emprestimo|renovacao|sondagem"
}}

Definições de nego_type:
- oficial: transferência confirmada/assinada/anunciada
- avancado: negociações avançadas, acordo próximo, detalhes sendo finalizados
- negociacoes: negociações em andamento, conversas concretas
- proposta: proposta/oferta formal enviada (mas não aceita ainda)
- emprestimo: empréstimo (temporário, com ou sem opção de compra)
- renovacao: renovação de contrato com clube atual
- interesse: interesse declarado, mas sem negociação concreta ainda
- sondagem: sondagem inicial, rumor, monitoramento

Se o artigo NÃO envolver negociação de jogador identificável, responda apenas: {{"is_transfer": false}}"""

    try:
        raw = await call_claude(prompt, TRANSFER_SYSTEM, client, max_tokens=400)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        if not data.get("is_transfer"):
            return None
        if not data.get("player_name"):
            return None

        # Normaliza nome do jogador via Transfermarkt para grafia canônica
        club_hint = data.get("club_to") or data.get("club_from") or ""
        data["player_name"] = await normalize_player_name(
            data["player_name"], client, club_hint=club_hint
        )

        return data
    except Exception as e:
        print(f"   \u26a0\ufe0f  Erro ao extrair transferência de '{title[:50]}': {e}")
        return None


async def process_transfer_article(article: dict):
    """Extrai e salva metadados de transferência de um artigo.
    Chamado após save_article() quando category in ('transferencia','sondagem')."""
    from database import upsert_transfer_meta

    async with httpx.AsyncClient() as client:
        data = await extract_transfer_meta(article, client)

    if not data:
        return

    upsert_transfer_meta(article["id"], {
        "player_name":        data.get("player_name"),
        "player_position":    data.get("player_position"),
        "player_nationality": data.get("player_nationality"),
        "club_from":          data.get("club_from"),
        "club_to":            data.get("club_to"),
        "fee":                data.get("fee"),
        "nego_type":          data.get("nego_type"),
    })
    print(f"   \U0001f504 Transferência: {data.get('player_name')} ({data.get('nego_type')}) — {data.get('club_from')} \u2192 {data.get('club_to')}")


async def rebuild_transfers_from_history():
    """Reprocessa TODOS os artigos históricos com category em ('transferencia','sondagem').
    Chamado via POST /api/transfers/rebuild."""
    from database import get_transfer_articles_raw, upsert_transfer_meta

    articles = get_transfer_articles_raw()
    print(f"\U0001f504 Rebuild transferências: {len(articles)} artigos para processar...")

    BATCH = 5
    created = updated = skipped = 0

    async with httpx.AsyncClient() as client:
        for i in range(0, len(articles), BATCH):
            batch = articles[i:i + BATCH]
            results = await asyncio.gather(
                *[extract_transfer_meta(a, client) for a in batch],
                return_exceptions=True
            )
            for art, data in zip(batch, results):
                if isinstance(data, Exception) or not data:
                    skipped += 1
                    continue
                upsert_transfer_meta(art["id"], {
                    "player_name":        data.get("player_name"),
                    "player_position":    data.get("player_position"),
                    "player_nationality": data.get("player_nationality"),
                    "club_from":          data.get("club_from"),
                    "club_to":            data.get("club_to"),
                    "fee":                data.get("fee"),
                    "nego_type":          data.get("nego_type"),
                })
                created += 1
            print(f"   \U0001f504 Lote {i//BATCH+1}/{(len(articles)-1)//BATCH+1 if articles else 1}: {created} classificados, {skipped} ignorados")

    print(f"\U0001f504 Rebuild concluído: {created} classificados, {skipped} ignorados de {len(articles)} artigos")
    return {"classified": created, "skipped": skipped, "total": len(articles)}
