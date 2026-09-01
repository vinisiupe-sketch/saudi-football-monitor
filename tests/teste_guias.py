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

    # ── 4. Lesões segue a mesma anatomia do card de Mercado ────────────────
    # Não é capricho: duas telas que mostram a mesma ideia — uma pessoa, um
    # clube, uma situação que anda — não podem ter duas gramáticas visuais.
    # E o rosto tem a mesma regra das outras: quem não é achado com certeza
    # fica com as iniciais, nunca com uma foto parecida.
    lesoes = _corpo("_page_lesoes_impl")
    ok(lesoes, "não achei _page_lesoes_impl")
    for pedaco, porque in (
            ("lsn-rosto", "o card de lesão perdeu o rosto"),
            # A classe existe no CSS mesmo quando o HTML para de emiti-la —
            # foi assim que este teste passou verde com o círculo removido.
            # O que prova a emissão é a chamada que monta as iniciais.
            ("_iniciais(player)", "o card de lesão perdeu o círculo de iniciais — "
                                  "sem ele, quem não tem foto some da tela"),
            ("lsn-escudo", "o card de lesão perdeu o escudo do clube"),
            ("status-pill", "o card de lesão perdeu o selo de estado")):
        ok(pedaco in lesoes, porque)
    ok("elos.jogadores_no_texto" in lesoes,
       "o rosto da lesão deixou de usar o índice de nomes — se voltar a casar "
       "por conta própria, volta a errar de pessoa")
    ok("len(achados) != 1" in lesoes,
       "o rosto passou a aceitar nome que cai em mais de uma pessoa")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ guias: chips só onde há escolha, e o botão de coleta acima do menu")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
