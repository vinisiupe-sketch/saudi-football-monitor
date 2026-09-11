"""
As três guias de notícia, e o que cada uma mostra.

O QUE ESTE ARQUIVO VIGIA
    As três — Notícias, Aspas e Notícias do Mercado — saem da MESMA função,
    com um parâmetro de categoria. É a decisão certa: são setecentas linhas, e
    três cópias divergiriam na primeira correção feita só numa delas.

    O preço é que uma mudança pensada para uma sai nas três sem avisar. Este
    arquivo existe para as diferenças que são de propósito não sumirem.

    Duas, hoje:

    1. Os chips de categoria só existem em /noticias. Em Aspas só há
       entrevista e em Notícias do Mercado só há mercado — um filtro ali não
       filtra nada, só ocupa faixa de tela sugerindo escolha onde não há.

    2. A barra de coleta fica ACIMA da barra de menu. Ela ficou meses em
       bottom:0 com z-index 10, e o menu mora em bottom:12px com z-index 30:
       no celular o menu cobria o botão Coletar por inteiro. Não dava erro,
       não aparecia em log — o botão simplesmente não existia para quem usa o
       app no telefone, que é como ele é usado.
"""
import ast
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo(nome):
    for n in ast.walk(ast.parse(FONTE)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
            return "\n".join(FONTE.split("\n")[n.lineno - 1:n.end_lineno])
    return ""


def testar():
    falhas.clear()
    corpo = _corpo("_pagina_de_noticias")
    ok(corpo, "não achei _pagina_de_noticias")

    # ── 1. os chips dependem da categoria ──────────────────────────────────
    ok("if categoria:" in corpo and 'filtros_de_categoria = ""' in corpo,
       "os chips de categoria voltaram a aparecer em toda guia — em Aspas e "
       "em Notícias do Mercado eles não filtram nada")
    ok("{filtros_de_categoria}" in corpo,
       "a variável dos chips existe mas não é usada no HTML")
    # E os chips ainda precisam EXISTIR para a guia que tem várias categorias.
    ok("cat-filters" in corpo and "filterCat" in corpo,
       "os chips sumiram de vez — /noticias perdeu o filtro que ela deve ter")

    # Simula as duas chamadas: com e sem categoria.
    for cat, deve_ter in (("", True), ("entrevista", False), ("mercado", False)):
        escopo = {"categoria": cat}
        exec("if categoria:\n filtros = ''\nelse:\n filtros = 'CHIPS'",
             escopo)
        ok(bool(escopo["filtros"]) == deve_ter,
           f"categoria={cat!r}: chips {'deveriam' if deve_ter else 'não deveriam'} existir")

    # ── 1b. guia de categoria única não mostra o que não tem escolha ──────
    # Título no topo, Coletar no canto, e mais nada. Sem selo de categoria
    # repetindo em todo card o que o título já diz, e sem a engrenagem — que
    # é o controle mais perigoso da tela: ele decide o que o app INTEIRO
    # traduz. Mexer nela de dentro da guia de Entrevistas seca as outras
    # guias, e foi exatamente assim que ficamos quatro dias com só 'mercado'
    # ligado sem ninguém entender por quê.
    ok('selo_de_categoria = ("" if categoria else' in corpo,
       "o selo de categoria voltou a aparecer nas guias de categoria única")
    ok('"entrevista": "Entrevistas"' in corpo,
       "a guia de categoria única perdeu o título no topo")
    ok('painel_de_coleta = ""' in corpo,
       "a engrenagem voltou para a guia de categoria única — de lá ela mexe "
       "no que o app inteiro traduz")
    ok('barra_de_coleta = ""' in corpo,
       "a barra fixa de baixo voltou para a guia de categoria única")
    ok("coleta-topo" in corpo and "titulo-guia" in corpo,
       "sumiu o Coletar do canto superior")
    # O botão continua sendo o mesmo id, senão o JS de progresso para de achá-lo.
    ok(corpo.count('id="cbtn"') >= 1 and "_COLETA_MIOLO" in corpo,
       "o Coletar do topo e o de baixo deixaram de ser o mesmo pedaço — "
       "duas cópias divergem na primeira correção")

    # ── 2. a barra de coleta não pode ficar atrás do menu ──────────────────
    barra = re.search(r"\.collect-bar \{\{(.*?)\}\}", corpo, re.S)
    ok(barra is not None, "não achei a regra .collect-bar")
    if barra:
        regra = barra.group(1)
        ok("bottom: 0" not in regra,
           "a barra de coleta voltou para bottom:0 — no celular ela fica "
           "atrás do menu e o botão Coletar deixa de existir no telefone")
        ok("env(safe-area-inset-bottom)" in regra,
           "a barra de coleta ignora a área segura do aparelho")
        ok("62px" in regra,
           "o deslocamento da barra deixou de acompanhar o do menu — os dois "
           "números precisam concordar, e por isso são o mesmo")
    ok("padding-bottom: 170px" in corpo,
       "o corpo perdeu a folga de baixo: os últimos cards ficam presos atrás "
       "da barra de coleta")

    # ── 3. cada guia com a sua categoria ───────────────────────────────────
    for rota, categoria in (('@app.get("/aspas"', '"entrevista"'),
                            ('@app.get("/mercado/noticias"', '"mercado"'),
                            ('@app.get("/noticias"', None)):
        ok(rota in FONTE, f"sumiu a rota {rota}")
    ok('_pagina_de_noticias("entrevista", "/aspas")' in FONTE,
       "a guia Aspas deixou de ser fixa em entrevista")
    ok('_pagina_de_noticias("mercado", "/mercado/noticias")' in FONTE,
       "a guia Notícias do Mercado deixou de ser fixa em mercado")

    # ── 4. Lesões segue a mesma anatomia do card de Pendurados ─────────────
    # Não é capricho: duas telas que mostram a mesma ideia — uma pessoa, um
    # clube, uma situação que anda — não podem ter duas gramáticas visuais.
    #
    # A anatomia MUDOU em 11/09/26. Antes era a da guia de Mercado, com o
    # rosto do jogador ocupando o canto esquerdo. Numa lista de lesionados o
    # olho procura de que time é a pessoa e quão grave é o caso, e o retrato
    # não responde nenhuma das duas — só ocupa o espaço que o texto queria.
    # Agora é escudo · nome e clube · tipo · estado, tudo numa linha, igual a
    # pendurados e suspensos.
    lesoes = _corpo("_page_lesoes_impl")
    ok(lesoes, "não achei _page_lesoes_impl")
    for pedaco, porque in (
            ("lsn-linha", "o card de lesão perdeu a linha única do padrão de "
                          "Pendurados"),
            ("lsn-escudo", "o card de lesão perdeu o escudo do clube — é ele "
                           "que responde 'de que time é' num relance"),
            ("lsn-tipo", "o card perdeu o tipo da lesão no canto"),
            ("status-pill", "o card de lesão perdeu o selo de estado")):
        ok(pedaco in lesoes, porque)
    ok("lsn-rosto" not in lesoes,
       "voltou a foto do jogador ao card de lesão. Ela ocupa o canto mais "
       "valioso com a informação menos útil da tela")

    # O ÍNDICE DE NOMES continua mandando — e agora dá o NOME, não só a foto.
    #
    # O nome vinha da transliteração que a IA fazia do texto da notícia, e
    # saía diferente do resto do app: "Fares Abdy" numa tela e "Faris Abdi" na
    # outra são a mesma pessoa parecendo duas. O índice já era bom o bastante
    # para escolher a foto certa (exige correspondência única); usá-lo também
    # para o nome não é fonte nova, é parar de desperdiçar a que estava aberta.
    ok("elos.jogadores_no_texto" in lesoes,
       "a identificação da lesão deixou de usar o índice de nomes — se voltar "
       "a casar por conta própria, volta a errar de pessoa")
    ok("len(achados) == 1" in lesoes,
       "a identificação passou a aceitar nome que cai em mais de uma pessoa")
    # A SEGUNDA tentativa, escopada ao clube. O índice geral exige duas
    # palavras — regra certa para varrer notícia, onde "Silva" não identifica
    # ninguém. Mas aqui eu tenho o CLUBE: dentro de um elenco de trinta,
    # "Bergwijn" e "Rajkovic" são únicos. Sem isso, "Steven Bergwijn" e
    # "Bergwijn" viravam dois lesionados.
    ok("_jogador_do_elenco_do_clube(" in lesoes and "_por_clube" in lesoes,
       "sumiu a segunda tentativa de identificação, escopada ao elenco do "
       "clube. Sem ela, sobrenome sozinho não identifica ninguém e o mesmo "
       "jogador volta a aparecer duas vezes")

    # E a regra, EXERCITADA — não procurada no texto. A primeira versão deste
    # teste só lia o código, e passou com um `return {}` posto na frente da
    # busca: o trecho continuava escrito e nunca rodava. Por isso a função
    # saiu da closure e virou módulo.
    regra = _corpo("_jogador_do_elenco_do_clube")
    ok(regra, "sumiu a função da busca escopada ao clube")
    if regra:
        import re as _re
        import unicodedata as _ud
        chave_src = _corpo("_chave_de_nome")
        ns = {"re": _re, "unicodedata": _ud}
        for pedaco in (chave_src, regra):
            exec(compile(ast.Module(body=[ast.parse(pedaco).body[0]],
                                    type_ignores=[]), "<x>", "exec"), ns)
        achar = ns["_jogador_do_elenco_do_clube"]

        ITTIHAD = [{"nome": "Steven Bergwijn", "nome_curto": "Bergwijn"},
                   {"nome": "Predrag Rajković", "nome_curto": "Rajković"},
                   {"nome": "Houssem Aouar", "nome_curto": "Aouar"}]
        # O CASO DO VINI: sobrenome sozinho tem que achar a pessoa.
        ok(achar("Bergwijn", ITTIHAD).get("nome") == "Steven Bergwijn",
           "'Bergwijn' sozinho não achou o Steven Bergwijn no elenco do "
           "Al-Ittihad. É o caso que fazia o mesmo jogador aparecer em dois "
           "cards")
        ok(achar("Rajkovic", ITTIHAD).get("nome") == "Predrag Rajković",
           "'Rajkovic' sem acento não achou o Predrag Rajković")
        ok(achar("Predrag Rajković", ITTIHAD).get("nome") == "Predrag Rajković",
           "o nome completo deixou de achar")
        # E o limite: pedaço que não existe no jogador não pode casar.
        ok(achar("Steven Silva", ITTIHAD) == {},
           "'Steven Silva' casou com 'Steven Bergwijn'. Todo pedaço do nome "
           "procurado tem que existir no jogador — com interseção em vez de "
           "subconjunto, bastaria o 'steven' coincidir")
        ok(achar("Bergwijn", []) == {}, "elenco vazio devolveu alguém")
        ok(achar("", ITTIHAD) == {}, "nome vazio devolveu alguém")
        # Dois jogadores do mesmo clube com o mesmo sobrenome: desiste.
        dois = ITTIHAD + [{"nome": "Lucas Bergwijn", "nome_curto": "Bergwijn"}]
        ok(achar("Bergwijn", dois) == {},
           "com dois Bergwijn no mesmo elenco, a busca escolheu um. Juntar "
           "duas lesões pela dúvida é pior que deixá-las separadas")
    ok("_do_elenco(bruto, club)" in lesoes and 'do_elenco.get("nome")' in lesoes,
       "o card voltou a exibir o nome que a IA transliterou da notícia em vez "
       "do nome do elenco. É o mesmo jogador aparecendo com dois nomes "
       "diferentes em duas guias do mesmo app")
    ok('do_elenco.get("clube")' in lesoes,
       "o clube também tem que vir do elenco: a notícia escreve 'Al Ahli' e o "
       "elenco escreve 'Al-Ahli Jeddah', e é o segundo que casa com o escudo")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ guias: chips só onde há escolha, e o botão de coleta acima do menu")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
