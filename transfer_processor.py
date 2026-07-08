"""
Extrai metadados estruturados de transferência de artigos com category em ('transferencia','sondagem').
Chamado pelo pipeline de processamento e pelo endpoint de rebuild retroativo.
"""
import json
import asyncio
import httpx
from processor import call_claude

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
        return data
    except Exception as e:
        print(f"   ⚠️  Erro ao extrair transferência de '{title[:50]}': {e}")
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
    print(f"   🔄 Transferência: {data.get('player_name')} ({data.get('nego_type')}) — {data.get('club_from')} → {data.get('club_to')}")


async def rebuild_transfers_from_history():
    """Reprocessa TODOS os artigos históricos com category em ('transferencia','sondagem').
    Chamado via POST /api/transfers/rebuild."""
    from database import get_transfer_articles_raw, upsert_transfer_meta

    articles = get_transfer_articles_raw()
    print(f"🔄 Rebuild transferências: {len(articles)} artigos para processar...")

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
            print(f"   🔄 Lote {i//BATCH+1}/{(len(articles)-1)//BATCH+1 if articles else 1}: {created} classificados, {skipped} ignorados")

    print(f"🔄 Rebuild concluído: {created} classificados, {skipped} ignorados de {len(articles)} artigos")
    return {"classified": created, "skipped": skipped, "total": len(articles)}
