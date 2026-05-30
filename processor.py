"""
Processador — traduz artigos usando Claude API.
"""
import os
import json
import asyncio
import httpx
from difflib import SequenceMatcher
from database import save_article

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
    from glossary import GLOSSARY_PROMPT, apply_glossary

    to_translate = [a for a in articles if not a.get("title_pt")]
    if not to_translate:
        print(f"   🌐 Todos os artigos já têm tradução")
        return articles
    print(f"   🌐 Traduzindo {len(to_translate)} artigos...")

    system = (
        "Você é um redator esportivo brasileiro especializado em futebol saudita. "
        "Adapte o texto para o português brasileiro com o estilo natural de sites como ge.globo.com ou ESPN Brasil — fluido, direto, jornalístico. "
        "NÃO faça tradução literal: reescreva as frases para soar natural em português. "
        "Use termos corretos do futebol: 'meio-campista', 'zagueiro', 'lateral', 'atacante', 'volante', 'emprestar', 'janela de transferências'. "
        "Se o texto já estiver em português, melhore o estilo apenas se necessário. "
        "REGRA CRÍTICA PARA NOMES DE JOGADORES: JAMAIS invente ou deduza nomes de jogadores. "
        "Para nomes em árabe que você não conhece com certeza, aplique transliteração direta letra por letra (ex: م=M, ح=H, م=M, د=D → Mohammed). "
        "Nunca substitua um nome árabe por um nome latino inventado que soe parecido. "
        "Prefira uma transliteração simples e fiel ao original a qualquer suposição criativa. "
        "Responda APENAS com JSON válido, sem markdown.\n"
        + GLOSSARY_PROMPT
    )

    BATCH = 3
    async with httpx.AsyncClient() as client:
        for i in range(0, len(to_translate), BATCH):
            batch = to_translate[i:i + BATCH]
            items_text = ""
            for idx, art in enumerate(batch):
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {art.get('title_orig', '')}\nTexto: {art.get('body_orig', '')[:1200]}\n---"

            prompt = f"""Adapte os artigos abaixo para português brasileiro com estilo jornalístico esportivo.
Responda SOMENTE com este JSON (sem texto extra):
{{"translations": [{{"title_pt": "...", "body_pt": "..."}}]}}

{items_text}"""
            try:
                raw = await call_claude(prompt, system, client, max_tokens=2000)
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                translations = json.loads(raw).get("translations", [])
                for idx, art in enumerate(batch):
                    if idx < len(translations):
                        art["title_pt"] = apply_glossary(translations[idx].get("title_pt") or art["title_orig"])
                        art["body_pt"] = apply_glossary(translations[idx].get("body_pt") or art["body_orig"])
                    else:
                        art["title_pt"] = art["title_orig"]
                        art["body_pt"] = art["body_orig"]
                print(f"   ✅ Lote {i//BATCH+1}/{(len(to_translate)-1)//BATCH+1} traduzido")
            except Exception as e:
                print(f"   ⚠️  Erro no lote {i//BATCH+1}: {type(e).__name__}: {e}")
                for art in batch:
                    art["title_pt"] = art.get("title_orig", "")
                    art["body_pt"] = art.get("body_orig", "")
    return articles


async def process_and_save(raw_articles: list[dict]) -> dict:
    from scraper import enrich_with_article
    print(f"\n⚙️  Processando {len(raw_articles)} artigos...")
    articles = deduplicate(raw_articles)
    print(f"   🔗 Buscando artigos completos...")
    async with httpx.AsyncClient() as client:
        articles = list(await asyncio.gather(*[enrich_with_article(a, client) for a in articles]))
    articles = await translate_articles(articles)
    new_count = sum(1 for art in articles if save_article(art))
    dup_count = len(articles) - new_count
    print(f"   💾 {new_count} novos, {dup_count} já existiam\n")
    return {"articles_new": new_count, "articles_dup": dup_count}
