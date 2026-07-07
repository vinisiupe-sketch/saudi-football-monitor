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

    to_translate = [a for a in articles if not a.get("title_pt") and a.get("relevance_score", 0) >= 0.34]
    if not to_translate:
        print(f"   🌐 Todos os artigos já têm tradução")
        return articles
    print(f"   🌐 Traduzindo {len(to_translate)} artigos...")

    system = (
        "Você é um redator esportivo brasileiro especializado na Saudi Pro League. "
        "Adapte o texto para o português brasileiro com o estilo natural de sites como ge.globo.com ou ESPN Brasil — fluido, direto, jornalístico. "
        "NÃO faça tradução literal: reescreva as frases para soar natural em português. "
        "Use termos corretos do futebol: 'meio-campista', 'zagueiro', 'lateral', 'atacante', 'volante', 'emprestar', 'janela de transferências'. "
        "Se o texto já estiver em português, melhore o estilo apenas se necessário — mas NUNCA altere a direção factual da notícia. "
        "PONTO DE VISTA — FUTEBOL SAUDITA: quando a notícia envolver um clube saudita e um europeu, "
        "o título e o corpo devem ter o clube saudita como sujeito principal da ação "
        "(ex: 'Al Ittihad se movimenta por Konaté', não 'Konaté deixa o Liverpool'). "
        "Contexto europeu vai no corpo, não no título. "
        # Nomes: estendido para cobrir técnicos e qualquer pessoa (antes só dizia 'jogadores')
        "REGRA CRÍTICA PARA NOMES: JAMAIS invente ou deduza nomes de jogadores, técnicos, dirigentes ou qualquer pessoa mencionada. "
        "Se o texto usa uma abreviação ou apelido (ex: 'إنج', 'Lucho', 'Motta'), mantenha exatamente essa forma no title_pt e no body_pt — "
        "NÃO complete para o nome completo a menos que o original o escreva por extenso. "
        "Para nomes em árabe que você não conhece com certeza, aplique transliteração direta letra por letra. "
        "Nunca substitua um nome árabe por um nome latino inventado que soe parecido. "
        # Fatos: impede inventar 'comunicado oficial', 'em entrevista', framing jornalístico ausente no original
        "REGRA CRÍTICA PARA FATOS: Não adicione informações ausentes no original. "
        "JAMAIS escreva as seguintes expressões a menos que o texto original as diga explicitamente: "
        "'em comunicado oficial', 'segundo o clube', 'o clube informou', 'em entrevista', "
        "'em entrevista exclusiva', 'ao desembarcar', 'em coletiva'. "
        "Se a notícia vem de uma fonte jornalística ('segundo X', 'sources claim', 'مصادر'), "
        "preserve esse caráter no português ('segundo fontes', 'de acordo com X') — "
        "nunca eleve para declaração oficial do clube. "
        # Transferências: impede inverter quem compra e quem vende
        "REGRA CRÍTICA PARA TRANSFERÊNCIAS: Preserve rigorosamente a direção da negociação. "
        "'proposta ao Clube X' = proposta enviada AO clube X (X é o vendedor/destino). "
        "'proposta do Clube X' = proposta feita PELO clube X (X é o comprador). "
        "JAMAIS inverta sujeito e objeto de uma transferência. Em caso de ambiguidade, use a formulação mais literal possível. "
        "Responda APENAS com JSON válido, sem markdown.\n"
        + GLOSSARY_PROMPT
    )

    BATCH = 3
    async with httpx.AsyncClient() as client:
        for i in range(0, len(to_translate), BATCH):
            batch = to_translate[i:i + BATCH]
            items_text = ""
            for idx, art in enumerate(batch):
                body_orig_text = art.get('body_orig', '')
                brevity_note = (
                    "\n[TEXTO MUITO CURTO — NÃO expanda. body_pt deve ser fiel ao original; "
                    "no máximo 1 frase de contexto se absolutamente necessária. "
                    "Não invente detalhes ausentes.]"
                    if len(body_orig_text.strip()) < 120 else ""
                )
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {art.get('title_orig', '')}\nTexto: {body_orig_text[:1200]}{brevity_note}\n---"

            prompt = f"""Adapte os artigos abaixo para português brasileiro com estilo jornalístico esportivo.
Classifique cada artigo em UMA categoria: transferencia, patrocinio, planejamento, entrevista, resultado, competicao, treino, financeiro, lesao, sondagem, geral.
- transferencia: confirmação de compra/venda/empréstimo de jogador
- sondagem: interesse, negociação em andamento, rumor de transferência
- patrocinio: acordos comerciais, patrocinadores, naming rights
- planejamento: decisões sobre elenco, renovações, dispensas, estratégia
- entrevista: declarações de jogadores, técnicos ou dirigentes
- resultado: placar de jogos, desempenho em partidas
- competicao: Copa, torneio, classificação, chaveamento
- treino: sessões de treino, preparação física
- financeiro: salários, receitas, fair play financeiro
- lesao: machucados, recuperação, ausências médicas
- geral: qualquer outro assunto
Responda SOMENTE com este JSON (sem texto extra):
{{"translations": [{{"title_pt": "...", "body_pt": "...", "category": "..."}}]}}

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
                        art["category"] = translations[idx].get("category", "geral")
                    else:
                        art["title_pt"] = art["title_orig"]
                        art["body_pt"] = art["body_orig"]
                        art["category"] = "geral"
                print(f"   ✅ Lote {i//BATCH+1}/{(len(to_translate)-1)//BATCH+1} traduzido")
            except Exception as e:
                print(f"   ⚠️  Erro no lote {i//BATCH+1}: {type(e).__name__}: {e} — tentando artigo a artigo")
                # Um artigo problemático (aspas/hashtags em árabe que quebram o JSON,
                # texto curto demais, etc.) não pode derrubar a tradução dos outros
                # 2 do lote — re-tenta cada um isoladamente antes de desistir.
                for art in batch:
                    try:
                        solo_prompt = f"""Adapte o artigo abaixo para português brasileiro com estilo jornalístico esportivo.
Classifique em UMA categoria: transferencia, patrocinio, planejamento, entrevista, resultado, competicao, treino, financeiro, lesao, sondagem, geral.
Responda SOMENTE com este JSON (sem texto extra):
{{"title_pt": "...", "body_pt": "...", "category": "..."}}

Título: {art.get('title_orig', '')}
Texto: {art.get('body_orig', '')[:1200]}"""
                        solo_raw = await call_claude(solo_prompt, system, client, max_tokens=1000)
                        solo_raw = solo_raw.strip()
                        if solo_raw.startswith("```"):
                            solo_raw = solo_raw.split("```")[1]
                            if solo_raw.startswith("json"):
                                solo_raw = solo_raw[4:]
                        solo_data = json.loads(solo_raw.strip())
                        art["title_pt"] = apply_glossary(solo_data.get("title_pt") or art["title_orig"])
                        art["body_pt"] = apply_glossary(solo_data.get("body_pt") or art["body_orig"])
                        art["category"] = solo_data.get("category", "geral")
                    except Exception as e2:
                        print(f"   ⚠️  Falha isolada também em '{art.get('title_orig','')[:50]}': {type(e2).__name__}: {e2}")
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
    new_saved, dup_count = [], 0
    for art in articles:
        if save_article(art):
            new_saved.append(art)
        else:
            dup_count += 1
    new_count = len(new_saved)
    print(f"   💾 {new_count} novos, {dup_count} já existiam\n")

    # Extrai lesões dos artigos novos com category='lesao'
    lesao_arts = [a for a in new_saved if a.get("category") == "lesao"]
    if lesao_arts:
        from injury_processor import process_injury_article
        await asyncio.gather(*[process_injury_article(a) for a in lesao_arts])

    return {"articles_new": new_count, "articles_dup": dup_count}
