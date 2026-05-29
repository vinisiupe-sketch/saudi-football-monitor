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
CLAUDE_MODEL = "claude-sonnet-4-20250514"
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
    to_translate = [a for a in articles if a.get("language") != "pt" and not a.get("title_pt")]
    if not to_translate:
        return articles
    print(f"   🌐 Traduzindo {len(to_translate)} artigos...")
    BATCH = 5
    async with httpx.AsyncClient() as client:
        for i in range(0, len(to_translate), BATCH):
            batch = to_translate[i:i + BATCH]
            items_text = ""
            for idx, art in enumerate(batch):
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {art.get('title_orig', '')}\nTexto: {art.get('body_orig', '')[:500]}\n---"
            system = "Você é um tradutor especializado em futebol. Responda APENAS com JSON válido."
            prompt = f"""Traduza para pt-BR. Preserve nomes próprios.
Responda SOMENTE com: {{"translations": [{{"title_pt": "...", "body_pt": "..."}}]}}

{items_text}"""
            try:
                raw = await call_claude(prompt, system, client, max_tokens=2000)
                raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                translations = json.loads(raw).get("translations", [])
                for idx, art in enumerate(batch):
                    if idx < len(translations):
                        art["title_pt"] = translations[idx].get("title_pt", art["title_orig"])
                        art["body_pt"] = translations[idx].get("body_pt", art["body_orig"])
                    else:
                        art["title_pt"] = art["title_orig"]
                        art["body_pt"] = art["body_orig"]
            except Exception as e:
                print(f"   ⚠️  Erro na tradução: {e}")
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
    print(f"\n⚙️  Processando {len(raw_articles)} artigos...")
    articles = deduplicate(raw_articles)
    articles = await translate_articles(articles)
    new_count = sum(1 for art in articles if save_article(art))
    dup_count = len(articles) - new_count
    print(f"   💾 {new_count} novos, {dup_count} já existiam")
    recent = get_recent_articles(hours=24)
    summary_text = await generate_summary(recent, hours=24)
    now = datetime.now(timezone.utc).isoformat()
    save_summary({
        "generated_at": now,
        "period_start": recent[-1]["collected_at"] if recent else now,
        "period_end": now,
        "summary_pt": summary_text,
        "article_ids": [a["id"] for a in recent],
    })
    print(f"   📝 Resumo gerado com {len(recent)} artigos\n")
    return {"articles_new": new_count, "articles_dup": dup_count, "summary": summary_text}
