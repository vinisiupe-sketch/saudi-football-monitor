"""
Processador — traduz artigos usando Claude API.
"""
import os
import re
import json
import asyncio
import httpx
from difflib import SequenceMatcher
from database import save_article

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-5"
SIMILARITY_THRESHOLD = 0.82


def _sem_sufixo_do_veiculo(t: str) -> str:
    """Tira o " - Nome do Veículo" que o Google News cola no fim do título.

    Sem isso a comparação afunda: a mesma matéria como "محزري يرفض عرض القادسية" e
    como "محزري يرفض عرض القادسية - صحيفة الرياضية" dava 0.73 de similaridade, abaixo
    do limiar de 0.82, e a duplicata passava. Só o texto usado na COMPARAÇÃO muda —
    o title_orig guardado e exibido continua exatamente como veio da fonte.

    Corta pelo ÚLTIMO separador, não pelo primeiro: o veículo vem no fim, e há título
    que usa hífen no meio ("Al Hilal: o plano - parte 1"). E ignora sufixo longo, que
    quase certamente é parte da manchete e não nome de jornal."""
    seps = list(re.finditer(r"\s+[-–—]\s+", t))
    if not seps:
        return t
    ultimo = seps[-1]
    sufixo = t[ultimo.end():].strip()
    if not sufixo or len(sufixo) > 40:
        return t
    return t[:ultimo.start()].strip() or t


def titles_are_similar(t1: str, t2: str) -> bool:
    t1, t2 = t1.lower().strip(), t2.lower().strip()
    if SequenceMatcher(None, t1, t2).ratio() >= SIMILARITY_THRESHOLD:
        return True
    a, b = _sem_sufixo_do_veiculo(t1), _sem_sufixo_do_veiculo(t2)
    if (a != t1 or b != t2) and a and b:
        return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD
    return False


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


CLAUDE_MODEL_TRIAGEM = "claude-haiku-4-5-20251001"


async def call_claude(
    prompt: str,
    system: str,
    client: httpx.AsyncClient,
    max_tokens: int = 1000,
    cache_system: bool = False,
    model: str = None,
) -> str:
    """model=None usa o modelo padrão (Sonnet). Passe outro pra tarefas baratas,
    como a triagem de categoria, que não precisa da qualidade de tradução."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não configurada.")

    # Prompt caching: se cache_system=True, marca o system prompt para cache.
    # Cache reads custam 10% do preço normal — economiza ~15-20% no input total.
    if cache_system:
        system_payload = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    else:
        system_payload = system

    payload = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_payload,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "Content-Type": "application/json",
    }
    resp = await client.post(CLAUDE_API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


TRIAGEM_SYSTEM = (
    "Você classifica notícias de futebol saudita em UMA categoria. "
    "Responda SOMENTE com JSON, sem texto extra.\n"
    "Categorias:\n"
    "- mercado: transferências, sondagens, rumores, negociações, renovações, contratações, saídas, salários de contrato\n"
    "- lesao: machucados, cirurgias, recuperação, desfalques por questão médica\n"
    "- competicao: resultados, placares, tabela, jogos, sorteios, arbitragem\n"
    "- entrevista: declarações de jogador, técnico ou dirigente\n"
    "- treino: pré-temporada, amistosos, sessões de treino\n"
    "- financas: dívidas, receitas, patrocínio, fair play financeiro, gestão do clube\n"
    "- geral: qualquer outro assunto\n"
    "Na dúvida entre mercado e outra categoria, escolha mercado. "
    "Na dúvida entre lesao e outra categoria, escolha lesao."
)

# 600 caracteres de contexto, não menos: medido com 100 artigos reais, cair pra 300
# derruba o acerto de "não perder mercado/lesão" de 95,5% pra 85,7%. O ganho de
# economia por encurtar é irrisório perto do risco de deixar furo passar.
TRIAGEM_CHARS = 600
TRIAGEM_LOTE = 20


async def triar_categorias(articles: list[dict], client: httpx.AsyncClient) -> None:
    """Preenche art['categoria_triagem'] usando um modelo barato.

    Existe porque a categoria só era conhecida DEPOIS da tradução — vinha no mesmo
    JSON. Ou seja, pra descobrir que uma notícia era de 'competicao' já se tinha
    pago pra traduzi-la. Aqui a decisão vem antes, por ~1/40 do preço."""
    if not articles:
        return
    for i in range(0, len(articles), TRIAGEM_LOTE):
        lote = articles[i:i + TRIAGEM_LOTE]
        itens = ""
        for idx, a in enumerate(lote):
            itens += f'\n{idx+1}) {(a.get("title_orig") or "")[:150]}\n{(a.get("body_orig") or "")[:TRIAGEM_CHARS]}\n'
        prompt = (
            'Classifique cada item. Responda: {"cats": ["categoria1", "categoria2", ...]} '
            f'com exatamente {len(lote)} itens, na ordem.\n{itens}'
        )
        try:
            raw = (await call_claude(prompt, TRIAGEM_SYSTEM, client,
                                     max_tokens=500, model=CLAUDE_MODEL_TRIAGEM)).strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            cats = json.loads(raw.strip()).get("cats", [])
            for idx, a in enumerate(lote):
                if idx < len(cats):
                    a["categoria_triagem"] = str(cats[idx]).strip().lower()
        except Exception as e:
            # Falha na triagem NÃO pode virar notícia perdida: sem categoria definida,
            # o artigo segue para tradução normalmente.
            print(f"   ⚠️  Triagem falhou no lote {i//TRIAGEM_LOTE+1}: {type(e).__name__}: {e} — lote segue para tradução")


async def translate_articles(articles: list[dict]) -> list[dict]:
    from glossary import GLOSSARY_PROMPT, apply_glossary

    to_translate = [a for a in articles if not a.get("title_pt") and a.get("relevance_score", 0) >= 0.34]
    if not to_translate:
        print(f"   🌐 Todos os artigos já têm tradução")
        return articles
    print(f"   🌐 Traduzindo {len(to_translate)} artigos...")

    system = (
        "Você é um tradutor especializado em futebol para o português brasileiro. "
        "MISSÃO: traduzir fielmente o que está escrito, com gramática correta, fluência natural e terminologia adequada ao futebol brasileiro. "
        "Use os termos certos do futebol: 'meio-campista', 'zagueiro', 'lateral', 'atacante', 'volante', 'emprestar', 'janela de transferências', 'elenco', 'contratação', 'rescisão'. "
        "Adapte expressões idiomáticas para soar natural em português — mas NUNCA adicione informações ausentes no original. "
        "Se o original tem 1 frase, body_pt tem 1 frase. Se tem 3 linhas, body_pt tem 3 linhas. Não transforme tweets em artigos. "
        # O card do site exibe SOMENTE o body_pt — o title_pt nunca é mostrado ao lado dele.
        # Sem esta regra o modelo move a primeira frase pro título e não a repete no corpo,
        # e o lead da notícia desaparece da tela (ex: um tweet que abria com
        # "EXCLUSIVE: Al Hilal open talks to sign Iliman Ndiaye" virou um corpo que só
        # começava em "As negociações estão em estágio inicial...", sem dizer o principal).
        "REGRA CRÍTICA — body_pt É AUTOSSUFICIENTE: o body_pt é exibido SOZINHO, sem o título ao lado. "
        "Portanto body_pt deve ser a tradução COMPLETA do texto original, do começo ao fim, incluindo a primeira frase. "
        "JAMAIS omita a abertura do texto sob o argumento de que ela já foi usada no title_pt. "
        "O title_pt é um rótulo interno e NÃO subtrai conteúdo do corpo — quem lê só o body_pt "
        "precisa entender a notícia inteira, incluindo quem é o clube, quem é o jogador e qual é o fato principal. "
        "Se o texto já estiver em português, ajuste gramática e terminologia técnica apenas — NUNCA altere os fatos. "
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

    BATCH = 5
    async with httpx.AsyncClient() as client:
        for i in range(0, len(to_translate), BATCH):
            batch = to_translate[i:i + BATCH]
            items_text = ""
            for idx, art in enumerate(batch):
                body_orig_text = art.get('body_orig', '')
                brevity_note = (
                    "\n[TWEET/POST CURTÍSSIMO — REGRAS ABSOLUTAS: "
                    "(1) Traduza SOMENTE o que está escrito. Zero invenção, zero contexto adicional, zero padding. "
                    "(2) Se o original tem 1 frase, body_pt tem 1 frase. Se tem 3 linhas, body_pt tem 3 linhas. "
                    "(3) NÃO escreva quem publicou, quando publicou, nem adicione frases de encerramento sobre o clube. "
                    "(4) NÃO interprete intenções — traduza literalmente. "
                    "(5) Emojis e hashtags podem ser mantidos ou omitidos, mas NUNCA substituídos por texto inventado.]"
                    if len(body_orig_text.strip()) < 280 else ""
                )
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {art.get('title_orig', '')}\nTexto: {body_orig_text[:1200]}{brevity_note}\n---"

            prompt = f"""Adapte os artigos abaixo para português brasileiro com estilo jornalístico esportivo.
Classifique cada artigo em UMA categoria: mercado, financas, competicao, entrevista, lesao, treino, geral.
- mercado: transferências confirmadas, sondagens, rumores, renovações e planejamento de elenco
- financas: salários, receitas, patrocínios, acordos comerciais, fair play financeiro
- competicao: resultados de jogos, placares, classificações, copas e torneios
- entrevista: declarações de jogadores, técnicos ou dirigentes
- lesao: machucados, recuperação, ausências médicas
- treino: sessões de treino, preparação física
- geral: qualquer outro assunto
Responda SOMENTE com este JSON (sem texto extra):
{{"translations": [{{"title_pt": "...", "body_pt": "...", "category": "..."}}]}}

{items_text}"""
            try:
                raw = await call_claude(prompt, system, client, max_tokens=2000, cache_system=True)
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
Classifique em UMA categoria: mercado, financas, competicao, entrevista, lesao, treino, geral.
Responda SOMENTE com este JSON (sem texto extra):
{{"title_pt": "...", "body_pt": "...", "category": "..."}}

Título: {art.get('title_orig', '')}
Texto: {art.get('body_orig', '')[:1200]}"""
                        solo_raw = await call_claude(solo_prompt, system, client, max_tokens=1000, cache_system=True)
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


def _confirma_pendentes(articles: list[dict]) -> list[dict]:
    """Decide a relevância dos artigos que o coletor não teve como julgar pela manchete.

    Feeds do Google News só entregam o título, então uma notícia legítima cujo único
    sinal saudita é uma variante ambígua (ex: "الخليج" = Al Khaleej, mas também "o
    Golfo") era descartada antes de alguém ler o texto. Esses casos chegam aqui
    marcados como pending_relevance, já com o corpo baixado — agora dá pra decidir
    do jeito certo, com a notícia inteira em mãos."""
    from collector import is_relevant, compute_relevance

    mantidos = []
    for a in articles:
        if not a.pop("pending_relevance", False):
            mantidos.append(a)
            continue
        full = f"{a.get('title_orig', '')} {a.get('body_orig', '')}"
        if is_relevant(full, min_hits=2, strict_ambiguous=True):
            a["relevance_score"] = compute_relevance(full, a.get("source_tier", "C"))
            mantidos.append(a)
    return mantidos


async def process_and_save(raw_articles: list[dict]) -> dict:
    from scraper import enrich_with_article
    from database import filtrar_artigos_ja_salvos
    print(f"\n⚙️  Processando {len(raw_articles)} artigos...")
    articles = deduplicate(raw_articles)

    # Descarta o que já está no banco ANTES de raspar e traduzir. A pipeline roda a
    # cada 30 min com janela de horas, então o mesmo tweet reaparece várias vezes;
    # antes o descarte só acontecia no save_article, depois de já ter pago a tradução.
    # Medido em 20 execuções reais: 19 artigos novos contra 186 duplicados — ~91% do
    # gasto de tradução ia pro lixo.
    articles, ja_existiam = filtrar_artigos_ja_salvos(articles)
    if ja_existiam:
        print(f"   ⏭️  {ja_existiam} já estavam no banco — pulados antes de traduzir")
    if not articles:
        print("   💾 nada novo pra processar\n")
        return {"articles_new": 0, "articles_dup": ja_existiam}

    print(f"   🔗 Buscando artigos completos...")
    async with httpx.AsyncClient() as client:
        articles = list(await asyncio.gather(*[enrich_with_article(a, client) for a in articles]))
    antes = len(articles)
    articles = _confirma_pendentes(articles)
    if len(articles) != antes:
        print(f"   🔎 {antes - len(articles)} descartados na reavaliação pós-scraping")

    # Triagem barata antes da tradução cara. Só roda se houver filtro de categoria
    # ativo — com todas as categorias ligadas, não gasta nada.
    from database import get_categorias_ativas
    ativas = set(get_categorias_ativas())
    fora_do_filtro = []
    if ativas:
        async with httpx.AsyncClient() as client:
            await triar_categorias(articles, client)
        selecionados = []
        for a in articles:
            cat = a.get("categoria_triagem")
            # Sem categoria (triagem falhou) segue para tradução: perder notícia é
            # pior que traduzir a mais.
            if cat is None or cat in ativas:
                selecionados.append(a)
            else:
                a["category"] = cat
                fora_do_filtro.append(a)
        if fora_do_filtro:
            print(f"   🗂️  {len(fora_do_filtro)} fora das categorias ativas — guardados sem traduzir")
        articles = selecionados

    articles = await translate_articles(articles)
    new_saved, dup_count = [], 0
    for art in articles:
        if save_article(art):
            new_saved.append(art)
        else:
            dup_count += 1

    # Os que ficaram fora do filtro são guardados com o texto original e a categoria,
    # sem title_pt/body_pt. Não aparecem na tela (a consulta exige tradução), mas o
    # histórico fica — se você reabrir a categoria depois, o material está lá.
    guardados = 0
    for art in fora_do_filtro:
        art["title_pt"] = None
        art["body_pt"] = None
        if save_article(art):
            guardados += 1
    if guardados:
        print(f"   📦 {guardados} guardados sem tradução")

    new_count = len(new_saved)
    # dup_count aqui deve ficar em ~0: o descarte real acontece antes de traduzir.
    # Se voltar a subir, é sinal de que o pré-filtro parou de funcionar.
    dup_count += ja_existiam
    print(f"   💾 {new_count} novos, {dup_count} já existiam\n")

    # Extrai lesões dos artigos novos com category='lesao'
    lesao_arts = [a for a in new_saved if a.get("category") == "lesao"]
    if lesao_arts:
        from injury_processor import process_injury_article
        await asyncio.gather(*[process_injury_article(a) for a in lesao_arts])


    return {"articles_new": new_count, "articles_dup": dup_count}
