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
    """Busca IDs de jogador e clubes na api-football e enriquece data com af_player_id,
    af_team_from_id, af_team_to_id para que logos e fotos possam ser servidos por URL direta."""
    import os
    key = os.getenv("API_FOOTBALL_KEY", "")
    if not key:
        return data
    hdrs = {"X-Apisports-Key": key}
    AF = "https://v3.football.api-sports.io"

    # ── Jogador ──────────────────────────────────────────────────────────
    pname = data.get("player_name") or ""
    if pname and not data.get("af_player_id"):
        try:
            # Tenta primeiro filtrando pela Saudi Pro League (temporadas recentes)
            for _season in ("2025", "2024"):
                r = await client.get(f"{AF}/players",
                    params={"search": pname, "league": "307", "season": _season},
                    headers=hdrs, timeout=8.0)
                results = r.json().get("response") or []
                if results:
                    break
            if not results:
                # Busca ampla sem filtro de liga
                r = await client.get(f"{AF}/players",
                    params={"search": pname, "season": "2024"},
                    headers=hdrs, timeout=8.0)
                results = r.json().get("response") or []
            if results:
                pid = str((results[0].get("player") or {}).get("id") or "")
                if pid:
                    data["af_player_id"] = pid
                    print(f"   📸 AF player: '{pname}' → id {pid}")
        except Exception as e:
            print(f"   ⚠️  AF player search error for '{pname}': {type(e).__name__}")

    # ── Clube de origem (qualquer país) ──────────────────────────────────
    cfrom = data.get("club_from") or ""
    if cfrom and not data.get("af_team_from_id"):
        try:
            r = await client.get(f"{AF}/teams",
                params={"search": cfrom}, headers=hdrs, timeout=7.0)
            results = r.json().get("response") or []
            if results:
                # Prefere correspondência exata de nome
                cfrom_low = cfrom.lower().strip()
                chosen = None
                for t in results[:5]:
                    if (t.get("team") or {}).get("name", "").lower().strip() == cfrom_low:
                        chosen = t; break
                if not chosen:
                    chosen = results[0]
                tid = str((chosen.get("team") or {}).get("id") or "")
                if tid:
                    data["af_team_from_id"] = tid
                    print(f"   🔵 AF team_from: '{cfrom}' → id {tid}")
        except Exception as e:
            print(f"   ⚠️  AF team_from search error for '{cfrom}': {type(e).__name__}")

    # ── Clube de destino (prefere Arábia Saudita) ────────────────────────
    cto = data.get("club_to") or ""
    if cto and not data.get("af_team_to_id"):
        try:
            r = await client.get(f"{AF}/teams",
                params={"search": cto}, headers=hdrs, timeout=7.0)
            results = r.json().get("response") or []
            if results:
                # Prefere times sauditas no destino (contexto Saudi Pro League)
                saudi = [t for t in results if (t.get("team") or {}).get("country") == "Saudi Arabia"]
                # Também verifica correspondência exata
                cto_low = cto.lower().strip()
                exact = [t for t in results if (t.get("team") or {}).get("name", "").lower().strip() == cto_low]
                chosen = (exact[0] if exact else (saudi[0] if saudi else results[0]))
                tid = str((chosen.get("team") or {}).get("id") or "")
                if tid:
                    data["af_team_to_id"] = tid
                    print(f"   🔴 AF team_to: '{cto}' → id {tid}")
        except Exception as e:
            print(f"   ⚠️  AF team_to search error for '{cto}': {type(e).__name__}")

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

        # Enriquece com IDs da api-football para logos e fotos diretas
        data = await enrich_with_af_ids(data, client)

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
