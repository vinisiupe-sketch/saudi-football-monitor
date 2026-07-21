"""
Extrai dados estruturados de lesão de artigos com category='lesao'.
Chamado pelo pipeline de processamento e pelo endpoint de rebuild retroativo.
"""
import json
import asyncio
import httpx
from processor import call_claude

INJURY_SYSTEM = (
    "Você é um analista esportivo especializado na Saudi Pro League. "
    "Extraia dados de lesão de jogador a partir de uma notícia esportiva. "
    "Responda APENAS com JSON válido, sem markdown."
)


async def extract_injury_data(article: dict, client: httpx.AsyncClient) -> dict | None:
    """Extrai dados estruturados de lesão. Retorna None se artigo não reportar lesão clara."""
    title = article.get("title_pt") or article.get("title_orig", "")
    body = article.get("body_pt") or article.get("body_orig", "")
    source = article.get("source_name", "")
    published = (article.get("published_at") or "")[:10]

    prompt = f"""Analise o artigo abaixo e extraia dados de lesão de jogador da Saudi Pro League.

Título: {title}
Texto: {body[:800]}
Fonte: {source}
Data publicação: {published}

Responda com este JSON exato (sem texto extra):
{{
  "is_injury": true,
  "player_name": "nome do jogador em português ou transliteração latina",
  "player_name_orig": "nome exatamente como aparece no texto",
  "club": "nome do clube saudita (Al Hilal, Al Nassr, Al Ittihad, Al Ahli, etc.)",
  "injury_date": "YYYY-MM-DD estimado em que ocorreu a lesão, ou null",
  "injury_type": "muscular|ligamento|fratura|cirurgia|doença|contusão|fadiga|outro",
  "body_part": "parte do corpo em português (ex: joelho, tornozelo, coxa, panturrilha, ombro) ou null",
  "expected_return": "tempo estimado de retorno (ex: '3 semanas', '6 semanas', '2 meses', 'indefinido') ou null",
  "status": "lesionado|em_recuperacao|retornando|recuperado",
  "notes": "contexto em 1 frase curta ou null"
}}

Se o artigo NÃO reportar lesão específica de um jogador da Saudi Pro League, responda apenas: {{"is_injury": false}}

Regras:
- status='lesionado' quando recém lesionado ou prazo indefinido
- status='em_recuperacao' quando em tratamento com prazo conhecido
- status='retornando' quando está próximo de voltar / voltou a treinar
- status='recuperado' quando explicitamente declarado apto/recuperado"""

    try:
        raw = await call_claude(prompt, INJURY_SYSTEM, client, max_tokens=400, cache_system=True)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        if not data.get("is_injury"):
            return None
        if not data.get("player_name") or not data.get("club"):
            return None
        return data
    except Exception as e:
        print(f"   ⚠️  Erro ao extrair lesão de '{title[:50]}': {e}")
        return None


async def process_injury_article(article: dict):
    """Extrai dados de lesão de um artigo e faz upsert na tabela injuries.
    Chamado após save_article() quando category == 'lesao'."""
    from database import upsert_injury

    async with httpx.AsyncClient() as client:
        data = await extract_injury_data(article, client)

    if not data:
        return

    source_info = {
        "source_name": article.get("source_name", ""),
        "url": article.get("url", ""),
        "published_at": (article.get("published_at") or "")[:10],
        "title": (article.get("title_pt") or article.get("title_orig", ""))[:120],
    }

    result = upsert_injury({
        "player_name":     data.get("player_name", ""),
        "player_name_orig": data.get("player_name_orig"),
        "club":            data.get("club", ""),
        "injury_date":     data.get("injury_date"),
        "injury_type":     data.get("injury_type"),
        "body_part":       data.get("body_part"),
        "expected_return": data.get("expected_return"),
        "status":          data.get("status", "lesionado"),
        "source_info":     source_info,
        "notes":           data.get("notes"),
    })
    print(f"   🏥 Lesão {result}: {data.get('player_name')} ({data.get('club')})")


async def rebuild_injuries_from_history():
    """Reprocessa TODOS os artigos históricos com category='lesao'.
    Chamado via POST /api/injuries/rebuild."""
    from database import get_lesao_articles

    articles = get_lesao_articles()
    print(f"🏥 Rebuild: {len(articles)} artigos de lesão para processar...")

    BATCH = 5  # processa em paralelo em lotes pequenos para não sobrecarregar API
    created = updated = skipped = 0

    async with httpx.AsyncClient() as client:
        for i in range(0, len(articles), BATCH):
            batch = articles[i:i + BATCH]
            results = await asyncio.gather(
                *[extract_injury_data(a, client) for a in batch],
                return_exceptions=True
            )
            for art, data in zip(batch, results):
                if isinstance(data, Exception) or not data:
                    skipped += 1
                    continue
                from database import upsert_injury
                source_info = {
                    "source_name": art.get("source_name", ""),
                    "url": art.get("url", ""),
                    "published_at": (art.get("published_at") or "")[:10],
                    "title": (art.get("title_pt") or art.get("title_orig", ""))[:120],
                }
                r = upsert_injury({
                    "player_name":     data.get("player_name", ""),
                    "player_name_orig": data.get("player_name_orig"),
                    "club":            data.get("club", ""),
                    "injury_date":     data.get("injury_date"),
                    "injury_type":     data.get("injury_type"),
                    "body_part":       data.get("body_part"),
                    "expected_return": data.get("expected_return"),
                    "status":          data.get("status", "lesionado"),
                    "source_info":     source_info,
                    "notes":           data.get("notes"),
                })
                if r == "created":
                    created += 1
                elif r == "updated":
                    updated += 1
                else:
                    skipped += 1
            print(f"   Lote {i//BATCH+1}: {created} ok, {skipped} ignorados")
            await asyncio.sleep(0.5)

    print(f"Rebuild concluido: {created} criados, {skipped} ignorados de {len(articles)}")
    return {"classified": created, "skipped": skipped, "total": len(articles)}
