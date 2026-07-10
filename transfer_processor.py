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

    # ── Clube de origem ──────────────────────────────────────────────────
    cfrom = data.get("club_from") or ""
    if cfrom and not data.get("af_team_from_id"):
        for _search in (_af_norm(cfrom), cfrom):
            try:
                r = await client.get(f"{AF}/teams",
                    params={"search": _search}, headers=hdrs, timeout=8.0)
                results = r.json().get("response") or []
                if results:
                    cfrom_low = _af_norm(cfrom).lower()
                    exact_saudi = [t for t in results if _af_norm((t.get("team") or {}).get("name","")).lower() == cfrom_low and (t.get("team") or {}).get("country") == "Saudi Arabia"]
                    exact_any   = [t for t in results if _af_norm((t.get("team") or {}).get("name","")).lower() == cfrom_low]
                    saudi_any   = [t for t in results if (t.get("team") or {}).get("country") == "Saudi Arabia"]
                    chosen = (exact_saudi[0] if exact_saudi else (saudi_any[0] if saudi_any else (exact_any[0] if exact_any else results[0]))).get("team") or {}
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
                    cto_low     = _af_norm(cto).lower()
                    exact_saudi = [t for t in results if _af_norm((t.get("team") or {}).get("name","")).lower() == cto_low and (t.get("team") or {}).get("country") == "Saudi Arabia"]
                    exact_any   = [t for t in results if _af_norm((t.get("team") or {}).get("name","")).lower() == cto_low]
                    saudi_any   = [t for t in results if (t.get("team") or {}).get("country") == "Saudi Arabia"]
                    chosen = (exact_saudi[0] if exact_saudi else (saudi_any[0] if saudi_any else (exact_any[0] if exact_any else results[0]))).get("team") or {}
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

        for _season in ("2025", "2024", "2023"):
            if pid_found:
                break
            for tid in team_ids:
                try:
                    r = await client.get(f"{AF}/players",
                        params={"search": pname_norm, "team": tid, "season": _season},
                        headers=hdrs, timeout=10.0)
                    results = r.json().get("response") or []
                    if results:
                        pid_found = str((results[0].get("player") or {}).get("id") or "")
                        if pid_found:
                            print(f"   📸 AF player: '{pname}' → id {pid_found} (team={tid} s={_season})")
                            break
                except Exception as e:
                    print(f"   ⚠️  AF player '{pname}' team={tid} s={_season}: {type(e).__name__}")
            if pid_found:
                break
            for league in FALLBACK_LEAGUES:
                try:
                    r = await client.get(f"{AF}/players",
                        params={"search": pname_norm, "league": league, "season": _season},
                        headers=hdrs, timeout=10.0)
                    results = r.json().get("response") or []
                    if results:
                        pid_found = str((results[0].get("player") or {}).get("id") or "")
                        if pid_found:
                            print(f"   📸 AF player: '{pname}' → id {pid_found} (league={league} s={_season})")
                            break
                except Exception as e:
                    print(f"   ⚠️  AF player '{pname}' league={league} s={_season}: {type(e).__name__}")
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
