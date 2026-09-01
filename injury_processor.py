"""
Extrai dados estruturados de lesão de artigos com category='lesao'.
Chamado pelo pipeline de processamento e pelo endpoint de rebuild retroativo.
"""
import json
import asyncio

# O `processor` (e o httpx, e o banco por tabela) só é importado DENTRO das
# funções que falam com o modelo. A peneira `fala_de_lesao` é a que mais
# precisa de teste, e não faz sentido exigir a pilha inteira de IA instalada
# para poder testá-la.

INJURY_SYSTEM = (
    "Você é um analista esportivo especializado na Saudi Pro League. "
    "Extraia dados de lesão de jogador a partir de uma notícia esportiva. "
    "Responda APENAS com JSON válido, sem markdown."
)


# Palavras que dizem PROBLEMA FÍSICO. Não são sinônimos de "está fora".
#
# Existem porque o pedido ao modelo, por mais claro que seja, é um pedido —
# ele pode responder is_injury=true para um desfalque tático, e respondia. A
# guia encheu de gente que só não tinha sido relacionada.
#
# Aqui a garantia não depende de ninguém se comportar: se o texto não tem
# NENHUMA dessas palavras, a resposta é descartada antes de virar linha no
# banco. É uma peneira grossa de propósito — ela não decide quem está
# lesionado, ela só barra o que nem fala de lesão.
_SINAIS_DE_LESAO = (
    # português
    "lesão", "lesao", "lesionad", "contusão", "contusao", "machucad",
    "cirurgia", "operad", "fratura", "ruptura", "estiramento", "distensão",
    "distensao", "ligamento", "menisco", "tendão", "tendao", "muscular",
    "fisioterapia", "tratamento médico", "tratamento medico", "exame médico",
    "exame medico", "departamento médico", "departamento medico",
    "recuperação", "recuperacao", "recupera-se", "dores", "dor no", "dor na",
    "desconforto", "entorse", "luxação", "luxacao", "sofreu no",
    # inglês
    "injury", "injured", "surgery", "fracture", "torn", "strain", "sprain",
    "hamstring", "acl", "ligament", "meniscus", "physio", "medical department",
    "recovery", "rehab", "knock", "muscle problem",
    # árabe
    "إصابة", "الإصابة", "مصاب", "يعاني", "العضلي", "عضلية", "جراحة",
    "كسر", "تمزق", "الرباط", "التأهيل", "العلاج", "الطبي", "الأشعة",
)


def fala_de_lesao(texto: str) -> bool:
    """O texto menciona problema físico, ou só diz que o jogador está fora?

    Nem toda ausência é lesão. Não relacionado, suspenso, poupado, negociando
    saída, motivo pessoal — tudo isso tira o jogador do jogo e nada disso é
    lesão. Sem uma palavra que fale de corpo, a notícia não entra.
    """
    t = (texto or "").lower()
    return any(p in t for p in _SINAIS_DE_LESAO)


async def extract_injury_data(article: dict, client) -> dict | None:
    """Extrai dados estruturados de lesão. Retorna None se artigo não reportar lesão clara."""
    title = article.get("title_pt") or article.get("title_orig", "")
    body = article.get("body_pt") or article.get("body_orig", "")
    source = article.get("source_name", "")
    published = (article.get("published_at") or "")[:10]

    # A peneira ANTES da chamada, e não depois: notícia que nem fala de lesão
    # não precisa ir ao modelo. Economiza a chamada e, mais importante, tira
    # do modelo a chance de inventar uma lesão a partir de um desfalque.
    #
    # Olho as duas escritas: o texto traduzido e o original. Uma notícia árabe
    # que chegou sem tradução ainda diz 'إصابة'.
    tudo = " ".join(str(x or "") for x in (
        title, body, article.get("title_orig"), article.get("body_orig")))
    if not fala_de_lesao(tudo):
        return None

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

AUSÊNCIA NÃO É LESÃO. Esta é a regra mais importante daqui.
O texto precisa dizer, explicitamente, que existe um problema FÍSICO: lesão,
contusão, dor, cirurgia, tratamento, fisioterapia, exame médico, departamento
médico, recuperação de lesão, ou o nome de uma parte do corpo machucada.

Responda {{"is_injury": false}} quando o motivo for outro, mesmo que o jogador
esteja fora do jogo:
- não foi relacionado, ficou fora da lista, não viajou com a delegação
- suspensão, cartões, punição, decisão técnica, opção do treinador
- ficou no banco, não entrou, foi poupado sem menção a problema físico
- negociação, transferência, empréstimo, saída, atraso na renovação
- motivo pessoal, familiar, luto, visto, documentação, seleção
- desfalque sem motivo dito no texto

E também {{"is_injury": false}} quando:
- o texto fala de lesão de forma genérica, sem dizer QUEM se lesionou
- lista vários desfalques sem separar quem está machucado de quem não está
- é especulação sobre uma lesão que ainda não aconteceu

Na dúvida entre "está lesionado" e "está fora por outro motivo", responda
false. Um jogador que falta na guia é um incômodo pequeno; um jogador
marcado como lesionado sem estar é uma informação errada indo ao ar.

Regras de status (só valem quando is_injury=true):
- status='lesionado' quando recém lesionado ou prazo indefinido
- status='em_recuperacao' quando em tratamento com prazo conhecido
- status='retornando' quando está próximo de voltar / voltou a treinar
- status='recuperado' quando explicitamente declarado apto/recuperado"""

    from processor import call_claude
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
    import httpx
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
        "status": data.get("status", "lesionado"),
        "expected_return": data.get("expected_return"),
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
    import httpx
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
                    "status": data.get("status", "lesionado"),
                    "expected_return": data.get("expected_return"),
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
