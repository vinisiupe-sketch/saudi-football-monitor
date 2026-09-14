"""
O glossário oficial decide quem é quem — e vem ANTES da transliteração.

A INVERSÃO (14/09/26)
    Durante meses este app respondeu "quem é este nome?" por dedução: índice
    de nomes, semelhança de texto a 0,75, busca escopada ao clube. Cada regra
    nasceu de um erro real — Rajkovic e Bergwijn separados, três Roger
    Fernandes, dois Kalidou Koulibaly, o Hamdallah que a canetinha não
    consertava — e cada conserto foi uma camada de palpite sobre a anterior.

    O Vini montou o glossário: 601 jogadores ancorados na SPL, 595 cruzados na
    API-Football, 595 no Transfermarkt, auditados à mão. A pergunta deixou de
    ser deduzida e passou a ser consultada.

    "Ele é anterior à transliteração" — palavras dele. É a parte que mais
    importa: antes, a IA transliterava e o app tentava reconhecer o resultado.
    Criar um erro para corrigir depois, e as correções nunca pegam todas.

O QUE ESTE ARQUIVO VIGIA
    Que o glossário GANHA, que ele PARA a dedução dentro da liga, e que ele
    NÃO adivinha. As três coisas são testadas executando o código com um
    glossário de mentira injetado — não procurando texto no arquivo. Procurar
    texto provaria que eu escrevi a linha, não que ela decide.
"""
import os
import sys
import types
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    _talo = types.ModuleType("psycopg2")
    _talo.extras = types.ModuleType("psycopg2.extras")
    _talo.extras.RealDictCursor = object
    _talo.Error = Exception
    sys.modules["psycopg2"] = _talo
    sys.modules["psycopg2.extras"] = _talo.extras

import glossario

falhas = []


def _importar_main():
    """O mesmo talo dos outros testes: o main puxa FastAPI e meio mundo, e
    nada disso tem a ver com a pergunta daqui."""
    for nome in ("fastapi", "fastapi.responses", "fastapi.staticfiles",
                 "fastapi.middleware", "fastapi.middleware.cors",
                 "fastapi.templating", "httpx", "feedparser", "bs4", "dotenv",
                 "psycopg2", "psycopg2.extras", "psycopg2.extensions",
                 "apscheduler", "apscheduler.schedulers",
                 "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                 "apscheduler.triggers.cron", "apscheduler.triggers.interval",
                 "apscheduler.jobstores", "apscheduler.executors",
                 "apscheduler.schedulers.background", "starlette",
                 "starlette.middleware", "starlette.middleware.base",
                 "starlette.responses", "starlette.requests", "lxml"):
        sys.modules.setdefault(nome, MagicMock(name=nome))
    import main
    return main


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


# Um glossário pequeno e REAL no formato: as fichas como o banco devolve e as
# grafias como o laboratório grava. Inclui de propósito os casos que doeram.
FICHAS = [
    {"id": 1, "spl_id": "s1", "af_id": 101, "tm_id": "201",
     "nome_principal": "Abderrazak Hamdallah", "nome_curto": "Hamdallah",
     "nome_ar": "عبد الرزاق حمد الله", "clube": "Al Ittihad",
     "posicao": "Atacante", "nacionalidade": "Marrocos", "foto": "spl/ham.png",
     "af_foto": "af/ham.png", "af_nacionalidade": "Morocco",
     "tm_foto": "tm/ham.png", "tm_posicao": "Centre-Forward",
     "tm_nacionalidade": "Morocco"},
    {"id": 2, "spl_id": "s2", "af_id": 102, "tm_id": "202",
     "nome_principal": "Roger Fernandes", "nome_curto": "Roger",
     "nome_ar": "روجر فرنانديز", "clube": "Al Ahli",
     "posicao": "Meia", "nacionalidade": "Portugal", "foto": "",
     "af_foto": "af/roger.png", "af_nacionalidade": "Portugal",
     "tm_foto": "tm/roger.png", "tm_posicao": "Left Winger",
     "tm_nacionalidade": "Portugal"},
    # Dois homônimos exatos, em clubes diferentes. Existe nesta liga.
    {"id": 3, "spl_id": "s3", "af_id": 103, "tm_id": "203",
     "nome_principal": "Mohammed Al Otaibi", "clube": "Al Hilal",
     "posicao": "Zagueiro", "nacionalidade": "Arábia Saudita", "foto": "a.png"},
    {"id": 4, "spl_id": "s4", "af_id": 104, "tm_id": "204",
     "nome_principal": "Mohammed Al Otaibi", "clube": "Al Nassr",
     "posicao": "Lateral", "nacionalidade": "Arábia Saudita", "foto": "b.png"},
]

GRAFIAS = [
    {"jogador_id": 1, "fonte": "noticia", "idioma": "ar", "tipo": "variacao",
     "nome": "حمد الله", "nome_normalizado": "", "confirmado": True},
    {"jogador_id": 1, "fonte": "pdf", "idioma": "lat", "tipo": "nome",
     "nome": "A. Hamdallah", "nome_normalizado": "", "confirmado": True},
    # As três grafias tortas que a IA produziu para a MESMA pessoa.
    {"jogador_id": 2, "fonte": "noticia", "idioma": "lat", "tipo": "variacao",
     "nome": "Rúger Fernández", "nome_normalizado": "", "confirmado": True},
    {"jogador_id": 2, "fonte": "noticia", "idioma": "lat", "tipo": "variacao",
     "nome": "Rojer", "nome_normalizado": "", "confirmado": True},
]


def _plantar():
    """Põe o glossário de mentira no lugar do banco e derruba o cache."""
    for g in GRAFIAS:
        if not g["nome_normalizado"]:
            g["nome_normalizado"] = glossario._chave(g["nome"])
    import database
    database.glossario_completo = lambda: ([dict(f) for f in FICHAS],
                                           [dict(g) for g in GRAFIAS])
    glossario.recarregar()


def _ajuste_fixo(valores: dict):
    import database
    database.valor_de_ajuste = lambda chave: valores.get(chave, "melhor disponível")


def testar():
    falhas.clear()
    _plantar()
    _ajuste_fixo({})

    # ── 1. ELE RESPONDE, E RESPONDE PELA GRAFIA TORTA ────────────────────
    # É o teste que resume tudo: "Rúger Fernández" e "Rojer" não se parecem
    # com "Roger Fernandes" — nenhuma comparação de string diria que são a
    # mesma pessoa. O glossário diz, porque o Vini disse.
    conferir("nome principal", glossario.identidade("Roger Fernandes").get("id"), 2)
    conferir("grafia torta da IA", glossario.identidade("Rúger Fernández").get("id"), 2)
    conferir("apelido solto", glossario.identidade("Rojer").get("id"), 2)
    conferir("sobrenome que o índice antigo recusava",
             glossario.identidade("Hamdallah").get("id"), 1)
    conferir("abreviação do PDF", glossario.identidade("A. Hamdallah").get("id"), 1)
    conferir("grafia árabe", glossario.identidade("عبد الرزاق حمد الله").get("id"), 1)
    conferir("árabe abreviado da notícia",
             glossario.identidade("حمد الله").get("id"), 1)

    # ── 2. ELE NÃO ADIVINHA ──────────────────────────────────────────────
    # Um glossário que chuta é uma heurística com nome melhor, e foi de
    # heurística que a gente saiu. Nome parecido NÃO é resposta.
    conferir("nome parecido não vale", glossario.identidade("Roger Fernande"), {})
    conferir("nome que não está", glossario.identidade("Cristiano Ronaldo"), {})
    conferir("vazio", glossario.identidade(""), {})
    conferir("prefixo não vale", glossario.identidade("Ham"), {})

    # ── 3. HOMÔNIMO: DESEMPATAR É DIFERENTE DE PROCURAR ──────────────────
    # Com dois "Mohammed Al Otaibi", o clube desempata. Sem clube, ou com um
    # clube que não é de nenhum dos dois, a resposta é "não sei" — e não "vou
    # de um dos dois".
    conferir("homônimo sem clube", glossario.identidade("Mohammed Al Otaibi"), {})
    conferir("homônimo com clube",
             glossario.identidade("Mohammed Al Otaibi", "Al Nassr").get("id"), 4)
    conferir("homônimo com o outro clube",
             glossario.identidade("Mohammed Al Otaibi", "Al Hilal").get("id"), 3)
    conferir("homônimo com clube de terceiro",
             glossario.identidade("Mohammed Al Otaibi", "Al Ittihad"), {})
    # E o clube NÃO pode virar busca: quem não é homônimo continua achado
    # mesmo com o clube errado, porque a chave já era única.
    conferir("clube errado não apaga quem é único",
             glossario.identidade("Hamdallah", "Al Hilal").get("id"), 1)

    # ── 4. PELOS IDENTIFICADORES ─────────────────────────────────────────
    conferir("por af_id", glossario.por_af_id(102).get("id"), 2)
    conferir("por af_id em texto", glossario.por_af_id("102").get("id"), 2)
    conferir("por tm_id", glossario.por_tm_id("201").get("id"), 1)
    conferir("por spl_id", glossario.por_spl_id("s3").get("id"), 3)
    conferir("af_id que não existe", glossario.por_af_id(999), {})
    conferir("af_id lixo", glossario.por_af_id("abc"), {})

    # ── 5. O GLOSSÁRIO COMO PROFESSOR DA IA ──────────────────────────────
    # Varre o texto ÁRABE BRUTO antes de a IA ver, e devolve o de-para. É a
    # inversão que o Vini pediu: o glossário é anterior à transliteração.
    texto_ar = "أكد نادي الاتحاد أن حمد الله سيغيب عن المباراة المقبلة"
    achados = [j["id"] for j in glossario.jogadores_no_texto(texto_ar)]
    ok(1 in achados,
       f"o glossário não achou o jogador no texto árabe: {achados}. É aqui "
       "que a IA deixa de ter o que adivinhar")
    licao = glossario.licao_para_a_ia(texto_ar)
    ok("Abderrazak Hamdallah" in licao,
       "a lição não traz a grafia em português que a IA deve usar")
    ok("حمد الله" in licao,
       "a lição não diz QUAL nome árabe corresponde — sem o de-para a IA não "
       "tem como ligar uma coisa à outra")
    ok("NÃO translitere" in licao or "não translitere" in licao,
       "a lição deixou de ORDENAR que a IA não transliterasse. Sem a ordem "
       "ela translitera assim mesmo, e a lista vira decoração")
    conferir("texto sem ninguém conhecido não inventa lição",
             glossario.licao_para_a_ia("الفريق يستعد للمباراة"), "")
    conferir("texto vazio", glossario.licao_para_a_ia(""), "")
    # Homônimo NÃO entra na lição: aqui não há clube para desempatar, e citar
    # o jogador errado num post é pior do que não citar nenhum.
    ok(not any(j["id"] in (3, 4)
               for j in glossario.jogadores_no_texto("Mohammed Al Otaibi marcou")),
       "um homônimo entrou na lição da IA. Sem clube não dá para saber qual "
       "dos dois é, e o post sairia com o jogador errado")

    # ── 6. A FONTE DE CADA CAMPO É ESCOLHA DO VINI ───────────────────────
    # Vale para as 601 fichas de uma vez, na guia de Ajustes.
    ham = glossario.carregar()["por_id"][1]
    _ajuste_fixo({"glossario_fonte_foto": "transfermarkt",
                  "glossario_fonte_posicao": "transfermarkt",
                  "glossario_fonte_nacionalidade": "spl"})
    f = glossario.ficha(ham)
    conferir("foto da fonte escolhida", f["foto"], "tm/ham.png")
    conferir("posição detalhada do TM", f["posicao"], "Centre-Forward")
    conferir("nacionalidade da SPL", f["nacionalidade"], "Marrocos")

    _ajuste_fixo({"glossario_fonte_foto": "spl"})
    conferir("foto da SPL", glossario.ficha(ham)["foto"], "spl/ham.png")

    # FONTE ESTRITA QUE NÃO TEM O DADO DEIXA VAZIO, e isso é de propósito:
    # preencher com outra tabela seria mentira calada, que é justamente o que
    # a gente passou semanas caçando.
    roger = glossario.carregar()["por_id"][2]
    _ajuste_fixo({"glossario_fonte_foto": "spl"})
    conferir("fonte estrita sem o dado fica vazia",
             glossario.ficha(roger)["foto"], "")
    # A API-Football não guarda posição no nosso cadastro. Escolhê-la deixa o
    # campo vazio em vez de cair para outra.
    _ajuste_fixo({"glossario_fonte_posicao": "api_football"})
    conferir("api_football não tem posição", glossario.ficha(ham)["posicao"], "")

    # "melhor disponível" percorre SPL → API-Football → Transfermarkt.
    _ajuste_fixo({})
    conferir("melhor disponível pega a primeira que tem",
             glossario.ficha(roger)["foto"], "af/roger.png")
    conferir("melhor disponível prefere a SPL quando ela tem",
             glossario.ficha(ham)["foto"], "spl/ham.png")

    # ── 7. SEM GLOSSÁRIO, NINGUÉM INVENTA UM ─────────────────────────────
    # Banco fora do ar não pode virar respostas erradas com ar de autoridade.
    # Vazio faz cada tela cair no caminho antigo, que é pior e conhecido.
    import database
    guardado = database.glossario_completo
    database.glossario_completo = lambda: (_ for _ in ()).throw(RuntimeError("caiu"))
    glossario.recarregar()
    try:
        conferir("banco fora do ar não responde nada",
                 glossario.identidade("Roger Fernandes"), {})
        conferir("e avisa que não está carregado",
                 glossario.esta_carregado(), False)
    finally:
        database.glossario_completo = guardado
        glossario.recarregar()

    # ── 8. A CORREÇÃO DO VINI VALE NO CLIQUE SEGUINTE ────────────────────
    # O cache dura dois minutos. Sem derrubá-lo na escrita, ele corrigiria um
    # nome, conferiria, veria o erro antigo e concluiria — com razão — que a
    # correção não pegou. Já aconteceu com a canetinha.
    conferir("antes de cadastrar", glossario.identidade("Zezinho da Silva"), {})
    GRAFIAS.append({"jogador_id": 2, "fonte": "manual", "idioma": "lat",
                    "tipo": "variacao", "nome": "Zezinho da Silva",
                    "nome_normalizado": glossario._chave("Zezinho da Silva"),
                    "confirmado": True})
    glossario.recarregar()
    conferir("depois de cadastrar e recarregar",
             glossario.identidade("Zezinho da Silva").get("id"), 2)
    GRAFIAS.pop()

    banco = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    for fn in ("adicionar_nome_glossario_lab", "vincular_fonte_glossario_lab",
               "desvincular_fonte_glossario_lab", "remover_nome_glossario_lab",
               "revisar_jogador_glossario_lab", "sincronizar_glossario_lab"):
        import ast
        corpo = next((ast.get_source_segment(banco, n) for n in ast.walk(ast.parse(banco))
                      if isinstance(n, ast.FunctionDef) and n.name == fn), "")
        ok("_glossario_mudou()" in corpo,
           f"{fn} escreve no glossário sem derrubar o cache do leitor. A "
           "correção do Vini só valeria dois minutos depois")

    # ── 9. A INVERSÃO DENTRO DO APP ──────────────────────────────────────
    # Até aqui testei o glossário sozinho. Isto testa a REGRA ÚNICA de
    # identidade do app — a mesma que Lesões, conferência de retorno e a
    # lista do Transfermarkt usam — de verdade, com a heurística viva ao lado.
    #
    # É o teste que importa, porque o defeito que eu mais temo não é o
    # glossário errar: é ele acertar e alguém depois "melhorar" a resposta.
    _plantar()
    _ajuste_fixo({})
    main = _importar_main()

    # O elenco congelado diz uma coisa; o glossário diz outra. O glossário
    # ganha — e o elenco continua sendo de onde os campos saem.
    elenco = [
        {"spl_id": "s1", "nome": "Hamdallah A.", "clube": "Al Ittihad",
         "foto": "elenco/ham.png", "af_id": 101},
        {"spl_id": "s9", "nome": "Outro Jogador", "clube": "Al Ittihad",
         "foto": "", "af_id": 109},
    ]
    ctx = {"gente": elenco, "por_id": {j["spl_id"]: j for j in elenco},
           "indice": {"chave": {}}, "apelidos": {},
           "por_clube": {"al ittihad": elenco}}

    achado = main._identificar_jogador("Rúger Fernández", "Al Ahli", ctx)
    conferir("o glossário responde por uma grafia que o elenco não tem",
             achado.get("spl_id"), "s2")
    achado = main._identificar_jogador("Hamdallah", "Al Ittihad", ctx)
    conferir("quando o glossário resolve, os campos vêm do elenco",
             achado.get("foto"), "elenco/ham.png")

    # A PARADA. Nome desconhecido, clube DA LIGA: a resposta é {} e a
    # heurística não roda. Planto um índice que casaria por semelhança para
    # provar que ele não é consultado — se fosse, viria "s9".
    ctx_armadilha = dict(ctx, apelidos={main and "": ""})
    ctx_armadilha["por_clube"] = {"al ittihad": elenco}
    conferir("dentro da liga, o que o glossário não sabe fica sem resposta",
             main._identificar_jogador("Outro Jogador", "Al Ittihad",
                                       ctx_armadilha), {})

    # A FRONTEIRA. Clube de fora da liga: o caminho antigo continua, senão a
    # guia de Mercado pararia de reconhecer qualquer estrangeiro. Foi a
    # decisão do Vini quando perguntei.
    fora = [{"spl_id": "x1", "nome": "Mohamed Salah", "clube": "Liverpool"}]
    ctx_fora = {"gente": fora, "por_id": {"x1": fora[0]},
                "indice": {"chave": {}}, "apelidos": {},
                "por_clube": {"liverpool": fora}}
    conferir("fora da liga a heurística continua valendo",
             main._identificar_jogador("Salah", "Liverpool", ctx_fora).get("spl_id"),
             "x1")

    # E o interruptor de emergência: desligado, volta tudo ao antigo.
    _ajuste_fixo({"glossario_manda": "desligado"})
    conferir("com o glossário desligado, a heurística volta a responder",
             main._identificar_jogador("Outro Jogador", "Al Ittihad",
                                       ctx).get("spl_id"), "s9")
    _ajuste_fixo({})

    # ── 10. O PROFESSOR CHEGA AO PROMPT ──────────────────────────────────
    # Não basta a lição existir: ela tem que entrar no texto que vai à IA.
    proc = open(os.path.join(RAIZ, "processor.py"), encoding="utf-8").read()
    ok("licao_para_a_ia" in proc,
       "o tradutor de notícias parou de consultar o glossário antes de "
       "traduzir. A IA volta a transliterar quem já está mapeado")
    ok("{licao}\\n---" in proc or "{licao}" in proc,
       "a lição é calculada e não entra no prompt")
    # No PROMPT e não no system: o system é cacheado e igual para todos; a
    # lição é deste artigo.
    sistema = proc[proc.find("system = ("):proc.find("+ GLOSSARY_PROMPT")]
    ok("licao" not in sistema,
       "a lição foi para o system prompt, que é cacheado e compartilhado — "
       "os jogadores de um artigo apareceriam no prompt de outro")
    lesao = open(os.path.join(RAIZ, "injury_processor.py"), encoding="utf-8").read()
    ok("licao_para_a_ia" in lesao and "{licao}" in lesao,
       "o extrator de lesões não recebe o de-para do glossário — é ele que "
       "decide em qual card a lesão cai")
    glo = open(os.path.join(RAIZ, "glossary.py"), encoding="utf-8").read()
    ok("JOGADORES JÁ IDENTIFICADOS" in glo,
       "o glossário base ainda manda transliterar sem falar da lista. Era a "
       "instrução antiga, de quando não existia glossário de jogadores")

    for f_ in falhas:
        print("  ✗", f_)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ glossário manda: identidade consultada, não deduzida")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
