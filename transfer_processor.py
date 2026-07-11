"""
Extrai metadados estruturados de transferência via Claude Opus.
Fase 1: interpretação pura por IA — sem chamadas a APIs externas.
"""
import json
import asyncio
import httpx
from processor import call_claude

TRANSFER_SYSTEM = (
    "Você é um analista de mercado de transferências especializado na Saudi Pro League. "
    "Leia a notícia com atenção e extraia os metadados estruturados com máxima precisão. "
    "Use o contexto completo do texto para inferir informações não explícitas. "
    "Responda APENAS com JSON válido, sem markdown, sem texto extra."
)

# Mapa completo de status → exibição
# Chave = valor exato retornado pelo Opus (lowercase sem acento para o DB)
NEGO_TYPES = {
    # ── Confirmados / assinados ────────────────────────────────────────────
    "oficial":    {"label": "Oficial",    "icon": "✅", "color": "#4ade80", "bg": "#14532d"},
    "anunciado":  {"label": "Anunciado",  "icon": "📢", "color": "#4ade80", "bg": "#14532d"},
    "assinou":    {"label": "Assinou",    "icon": "✍️", "color": "#4ade80", "bg": "#14532d"},
    "acordo":     {"label": "Acordo",     "icon": "🤜",  "color": "#86efac", "bg": "#14532d"},
    "acerto":     {"label": "Acerto",     "icon": "🎯", "color": "#86efac", "bg": "#14532d"},
    "exames":     {"label": "Exames",     "icon": "🏥", "color": "#86efac", "bg": "#14532d"},
    # ── Avançado / encaminhado ─────────────────────────────────────────────
    "avancado":   {"label": "Avançado",   "icon": "⚡", "color": "#93c5fd", "bg": "#1e3a5f"},
    "encaminhado":{"label": "Encaminhado","icon": "🔜", "color": "#93c5fd", "bg": "#1e3a5f"},
    "apalavrado": {"label": "Apalavrado", "icon": "🤝", "color": "#93c5fd", "bg": "#1e3a5f"},
    # ── Em negociação ─────────────────────────────────────────────────────
    "negociacao": {"label": "Negociação", "icon": "💬", "color": "#fcd34d", "bg": "#451a03"},
    "conversas":  {"label": "Conversas",  "icon": "🗣️", "color": "#fcd34d", "bg": "#451a03"},
    "proposta":   {"label": "Proposta",   "icon": "📋", "color": "#fb923c", "bg": "#431407"},
    "contato":    {"label": "Contato",    "icon": "📞", "color": "#fcd34d", "bg": "#451a03"},
    # ── Estágios iniciais ─────────────────────────────────────────────────
    "interesse":  {"label": "Interesse",  "icon": "👁️", "color": "#d1d5db", "bg": "#1f2937"},
    "sondagem":   {"label": "Sondagem",   "icon": "🔍", "color": "#9ca3af", "bg": "#1f2937"},
    "consulta":   {"label": "Consulta",   "icon": "❓", "color": "#9ca3af", "bg": "#1f2937"},
    "opcao":      {"label": "Opção",      "icon": "🔖", "color": "#9ca3af", "bg": "#1f2937"},
    "espera":     {"label": "Espera",     "icon": "⏳", "color": "#9ca3af", "bg": "#374151"},
    # ── Negativos / especiais ─────────────────────────────────────────────
    "melou":      {"label": "Melou",      "icon": "❌", "color": "#f87171", "bg": "#3b0000"},
    "travado":    {"label": "Travado",    "icon": "🔒", "color": "#f87171", "bg": "#3b0000"},
    "de_saida":   {"label": "De Saída",   "icon": "🚪", "color": "#fca5a5", "bg": "#3b0000"},
    "rescisao":   {"label": "Rescisão",   "icon": "📝", "color": "#fca5a5", "bg": "#3b0000"},
    # ── Tipos especiais ───────────────────────────────────────────────────
    "emprestimo": {"label": "Empréstimo", "icon": "🔄", "color": "#67e8f9", "bg": "#164e63"},
    "troca":      {"label": "Troca",      "icon": "↔️", "color": "#67e8f9", "bg": "#164e63"},
    "renovacao":  {"label": "Renovação",  "icon": "🔃", "color": "#c4b5fd", "bg": "#2e1065"},
}

# Lista de status aceitos (em português, como enviado ao Opus)
_STATUS_LIST = (
    "Acerto, Acordo, Anunciado, Assinou, Apalavrado, Avançado, Consulta, Contato, "
    "Conversas, De Saída, Empréstimo, Encaminhado, Espera, Exames, Interesse, "
    "Melou, Negociação, Oficial, Opção, Proposta, Rescisão, Renovação, Sondagem, "
    "Travado, Troca"
)

# Mapa do texto do Opus → chave interna do DB
_STATUS_NORM = {
    "acerto": "acerto", "acordo": "acordo", "anunciado": "anunciado",
    "assinou": "assinou", "apalavrado": "apalavrado", "avançado": "avancado",
    "avancado": "avancado", "consulta": "consulta", "contato": "contato",
    "conversas": "conversas", "de saída": "de_saida", "de saida": "de_saida",
    "empréstimo": "emprestimo", "emprestimo": "emprestimo",
    "encaminhado": "encaminhado", "espera": "espera", "exames": "exames",
    "interesse": "interesse", "melou": "melou", "negociação": "negociacao",
    "negociacao": "negociacao", "oficial": "oficial", "opção": "opcao",
    "opcao": "opcao", "proposta": "proposta", "rescisão": "rescisao",
    "rescisao": "rescisao", "renovação": "renovacao", "renovacao": "renovacao",
    "sondagem": "sondagem", "travado": "travado", "troca": "troca",
}


def _norm_status(raw: str) -> str:
    """Normaliza o status retornado pelo Opus para a chave interna."""
    key = (raw or "").strip().lower()
    return _STATUS_NORM.get(key, "sondagem")


async def extract_transfer_meta(article: dict, client: httpx.AsyncClient) -> dict | None:
    """Extrai metadados de negociação via Opus. Retorna None se não for transferência."""
    title = article.get("title_pt") or article.get("title_orig", "")
    body  = article.get("body_pt")  or article.get("body_orig", "")
    source    = article.get("source_name", "")
    published = (article.get("published_at") or "")[:10]

    prompt = f"""Analise a notícia esportiva abaixo e extraia os dados de transferência.

Título: {title}
Fonte: {source} | Data: {published}
Texto: {body[:2000]}

Responda com este JSON exato (sem texto extra, sem inventar informações ausentes):
{{
  "is_transfer": true ou false,
  "nego_status": "um de: {_STATUS_LIST}",
  "player_name": "nome EXATAMENTE como escrito no texto",
  "player_position": "posição em português (Atacante, Meia, Zagueiro, Lateral Direito, Lateral Esquerdo, Volante, Goleiro) ou null",
  "player_nationality": "gentílico ou país em português (ex: brasileiro, português) ou null",
  "player_age": número ou null,
  "club_from": "clube de origem EXATAMENTE como no texto, ou null",
  "country_from": "país do clube de origem — infira pelo clube se necessário (ex: Portugal, Espanha, Brasil) ou null",
  "league_from": "liga do clube de origem — infira pelo clube+país (ex: Primeira Liga, La Liga, Premier League) ou null",
  "club_to": "clube de destino EXATAMENTE como no texto, ou null",
  "fee": "valor da transferência se mencionado (ex: €50M, free, empréstimo) ou null"
}}

Instruções:
- is_transfer: true apenas se a notícia envolver negociação de um jogador identificável
- nego_status: escolha O MAIS PRECISO da lista — reflita o estágio real descrito no texto
- club_from/club_to: copie o nome EXATAMENTE como aparece no texto — não traduza nem normalize
- country_from e league_from: use seu conhecimento para inferir pelo clube (ex: "Sporting CP" → Portugal, Primeira Liga)
- player_nationality: quando não explícito, infira pela nacionalidade comum do nome ou pelo clube
- Se não for transferência de jogador identificável: {{"is_transfer": false}}"""

    try:
        raw = await call_claude(prompt, TRANSFER_SYSTEM, client, max_tokens=350)
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        if not data.get("is_transfer"):
            return None
        if not data.get("player_name"):
            return None

        # Normaliza status para chave interna
        data["nego_type"] = _norm_status(data.get("nego_status", ""))
        # Renomeia para colunas do DB
        data["context_country"] = data.get("country_from")
        data["context_league"]  = data.get("league_from")

        return data

    except Exception as e:
        title_short = title[:60]
        print(f"   ⚠️  Erro ao extrair transferência de '{title_short}': {e}")
        return None


async def process_transfer_article(article: dict):
    """Extrai e salva metadados de transferência. Chamado pelo pipeline."""
    from database import upsert_transfer_meta

    async with httpx.AsyncClient() as client:
        data = await extract_transfer_meta(article, client)

    if not data:
        return

    upsert_transfer_meta(article["id"], {
        "player_name":        data.get("player_name"),
        "player_position":    data.get("player_position"),
        "player_nationality": data.get("player_nationality"),
        "player_age":         data.get("player_age"),
        "club_from":          data.get("club_from"),
        "club_to":            data.get("club_to"),
        "context_country":    data.get("context_country"),
        "context_league":     data.get("context_league"),
        "fee":                data.get("fee"),
        "nego_type":          data.get("nego_type"),
    })


async def rebuild_transfers_from_history():
    """Reprocessa TODOS os artigos históricos com category em ('transferencia','sondagem').
    Chamado via POST /api/transfers/rebuild."""
    from database import get_transfer_articles_raw, upsert_transfer_meta

    articles = get_transfer_articles_raw()
    print(f"🔄 Rebuild transferências: {len(articles)} artigos para processar...")

    BATCH = 4  # conservador para não sobrecarregar rate limit do Opus
    created = skipped = 0

    async with httpx.AsyncClient() as client:
        for i in range(0, len(articles), BATCH):
            batch   = articles[i:i + BATCH]
            results = await asyncio.gather(
                *[extract_transfer_meta(a, client) for a in batch],
                return_exceptions=True,
            )
            for art, data in zip(batch, results):
                if isinstance(data, Exception) or not data:
                    skipped += 1
                    continue
                upsert_transfer_meta(art["id"], {
                    "player_name":        data.get("player_name"),
                    "player_position":    data.get("player_position"),
                    "player_nationality": data.get("player_nationality"),
                    "player_age":         data.get("player_age"),
                    "club_from":          data.get("club_from"),
                    "club_to":            data.get("club_to"),
                    "context_country":    data.get("context_country"),
                    "context_league":     data.get("context_league"),
                    "fee":                data.get("fee"),
                    "nego_type":          data.get("nego_type"),
                })
                created += 1
            print(f"   Lote {i//BATCH+1}: {created} ok, {skipped} ignorados")
            await asyncio.sleep(0.5)  # respeita rate limit

    print(f"✅ Rebuild concluído: {created} classificados, {skipped} ignorados de {len(articles)} artigos")
    return {"classified": created, "skipped": skipped, "total": len(articles)}
