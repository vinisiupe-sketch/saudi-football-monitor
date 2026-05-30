"""
Processador — usa Claude API para traduzir e resumir notícias.
"""
import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from difflib import SequenceMatcher
from database import save_article, get_recent_articles, save_summary

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
SIMILARITY_THRESHOLD = 0.82


def titles_are_similar(t1: str, t2: str) -> bool:
    t1, t2 = t1.lower().strip(), t2.lower().strip()
    return SequenceMatcher(None, t1, t2).ratio() >= SIMILARITY_THRESHOLD


def deduplicate(articles: list[dict]) -> list[dict]:
    sorted_arts = sorted(articles, key=lambda x: -x.get("relevance_score", 0))
    kept = []
    for art in sorted_arts:
        if not any(titles_are_similar(art.get("title_orig") or "", e.get("title_orig") or "") for e in kept):
            kept.append(art)
    removed = len(articles) - len(kept)
    if removed:
        print(f"   🔁 {removed} duplicatas semânticas removidas")
    return kept


async def call_claude(prompt: str, system: str, client: httpx.AsyncClient, max_tokens: int = 1000) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não configurada.")
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = await client.post(
        CLAUDE_API_URL,
        json=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


async def translate_articles(articles: list[dict]) -> list[dict]:
    # Traduz tudo que ainda não tem title_pt — independente do idioma detectado
    # (a detecção automática pode errar, especialmente em textos curtos ou mistos)
    to_translate = [a for a in articles if not a.get("title_pt")]
    if not to_translate:
        print(f"   🌐 Todos os artigos já têm tradução")
        return articles
    print(f"   🌐 Traduzindo {len(to_translate)} artigos...")
    BATCH = 5
    async with httpx.AsyncClient() as client:
        for i in range(0, len(to_translate), BATCH):
            batch = to_translate[i:i + BATCH]
            items_text = ""
            for idx, art in enumerate(batch):
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {art.get('title_orig', '')}\nTexto: {art.get('body_orig', '')[:2000]}\n---"
            from glossary import GLOSSARY_PROMPT, apply_glossary
            system = (
                "Você é um redator esportivo brasileiro especializado em futebol saudita. "
                "Sua tarefa é adaptar textos para o português brasileiro com o estilo natural de sites como ge.globo.com ou ESPN Brasil — fluido, direto, jornalístico. "
                "NÃO faça tradução literal: reescreva as frases para soar natural em português. "
                "Use termos corretos do futebol: 'meio-campista' (não 'meia'), 'zagueiro', 'lateral', 'atacante', 'volante', 'emprestar' (não 'ceder'), 'janela de transferências'. "
                "Se o texto já estiver em português, reescreva-o apenas para melhorar o estilo se necessário. "
                "Preserve nomes próprios de jogadores e técnicos exatamente como estão no original (transliteração do árabe). "
                "Responda APENAS com JSON válido, sem markdown.\n"
                + GLOSSARY_PROMPT
            )
            prompt = f"""Adapte os artigos abaixo para português brasileiro com estilo jornalístico esportivo.
Responda SOMENTE com este JSON (sem texto extra):
{{"translations": [{{"title_pt": "...", "body_pt": "..."}}]}}

{items_text}"""
            try:
                raw = await call_claude(prompt, system, client, max_tokens=4000)
                # Limpa possível markdown ao redor do JSON
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                translations = json.loads(raw).get("translations", [])
                if len(translations) != len(batch):
                    print(f"   ⚠️  Lote {i//BATCH+1}: esperava {len(batch)} traduções, recebeu {len(translations)}")
                for idx, art in enumerate(batch):
                    if idx < len(translations):
                        art["title_pt"] = apply_glossary(translations[idx].get("title_pt") or art["title_orig"])
                        art["body_pt"] = apply_glossary(translations[idx].get("body_pt") or art["body_orig"])
                    else:
                        art["title_pt"] = art["title_orig"]
                        art["body_pt"] = art["body_orig"]
                print(f"   ✅ Lote {i//BATCH+1}/{(len(to_translate)-1)//BATCH+1} traduzido")
            except json.JSONDecodeError as e:
                print(f"   ⚠️  Erro de JSON no lote {i//BATCH+1}: {e} | raw={raw[:200]}")
                for art in batch:
                    art["title_pt"] = art.get("title_orig", "")
                    art["body_pt"] = art.get("body_orig", "")
            except Exception as e:
                print(f"   ⚠️  Erro na tradução lote {i//BATCH+1}: {type(e).__name__}: {e}")
                for art in batch:
                    art["title_pt"] = art.get("title_orig", "")
                    art["body_pt"] = art.get("body_orig", "")
    return articles


async def generate_summary(articles: list[dict], hours: int = 24) -> str:
    if not articles:
        return "Nenhuma notícia relevante encontrada no período."
    top = sorted(articles, key=lambda x: -x.get("relevance_score", 0))[:20]
    news_block = ""
    for i, art in enumerate(top, 1):
        title = art.get("title_pt") or art.get("title_orig") or "Sem título"
        body = art.get("body_pt") or art.get("body_orig") or ""
        news_block += f"{i}. [{art.get('source_tier','?')}] {art.get('source_name','')} — {title}\n{body[:200]}\n\n"
    system = "Você é um analista especializado em futebol saudita. Escreve resumos claros em português brasileiro."
    prompt = f"""Com base nas {len(top)} notícias abaixo das últimas {hours}h, gere um resumo executivo com:
1. **📰 Destaques do dia** (3-5 pontos)
2. **🔄 Mercado de transferências**
3. **⚽ Resultados e jogos**
4. **👁️ Fique de olho**
Máximo 400 palavras.

NOTÍCIAS:
{news_block}"""
    try:
        async with httpx.AsyncClient() as client:
            return await call_claude(prompt, system, client, max_tokens=600)
    except Exception as e:
        return f"Erro ao gerar resumo: {e}"


async def process_and_save(raw_articles: list[dict]) -> dict:
    import httpx
    from scraper import enrich_with_article
    print(f"\n⚙️  Processando {len(raw_articles)} artigos...")
    articles = deduplicate(raw_articles)
    # Enriquece com conteúdo completo dos artigos linkados
    print(f"   🔗 Buscando artigos completos...")
    async with httpx.AsyncClient() as client:
        import asyncio
        articles = list(await asyncio.gather(*[enrich_with_article(a, client) for a in articles]))
    articles = await translate_articles(articles)
    new_count = sum(1 for art in articles if save_article(art))
    dup_count = len(articles) - new_count
    print(f"   💾 {new_count} novos, {dup_count} já existiam")
    cycle_hours = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 120)) // 60 or 2
    recent = get_recent_articles(hours=cycle_hours)
    summary_text = await generate_summary(recent, hours=cycle_hours)
    now = datetime.now(timezone.utc).isoformat()
    save_summary({
        "generated_at": now,
        "period_start": recent[-1]["collected_at"] if recent else now,
        "period_end": now,
        "summary_pt": summary_text,
        "article_ids": [a["id"] for a in recent],
    })
    print(f"   📝 Resumo gerado com {len(recent)} artigos das últimas {cycle_hours}h\n")
    return {"articles_new": new_count, "articles_dup": dup_count, "summary": summary_text}
