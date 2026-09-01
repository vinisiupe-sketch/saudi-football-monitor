"""
A ordem das notícias nas guias, o horário mostrado, e o limite que corta.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    Você perguntou por que /mercado/noticias não vinha em ordem cronológica.
    A consulta ao banco já vem certa — `ORDER BY published_at DESC` — mas
    logo depois, em Python, a lista era reordenada por `collected_at` (quando
    O NOSSO coletor passou pela notícia), desfazendo a ordem por
    published_at (quando a notícia SAIU). Duas notícias publicadas na mesma
    hora podiam trocar de lugar dependendo da ordem em que o coletor visitou
    as fontes naquele ciclo — e uma notícia recuperada tarde (retentativa,
    backfill) pulava pro topo mesmo sendo velha.

    Enquanto investigava isso, apareceu um segundo defeito, mais sério: o
    `limit=80` da consulta é sobre TODAS as categorias juntas, não só
    Mercado. Num dia de muito volume — dia de fechamento de janela, 231
    artigos coletados até o meio da tarde num caso real — os 80 mais
    recentes do SITE INTEIRO podem ser todos de outra categoria, e uma
    notícia de mercado real, dentro das 48h, nunca chega a ser vista pelo
    filtro de categoria: ela é cortada ANTES disso, pelo limite. Foi
    exatamente esse tipo de dia (deadline day) que expôs o problema — um
    tweet do Fabrizio Romano sobre o Al Ittihad, publicado havia menos de
    duas horas, não apareceu na guia.

    De quebra, o pedido de trocar o fuso para horário do Brasil: os cards
    mostravam hora saudita (UTC+3). Você narra do Brasil.

Estes testes leem o CÓDIGO-FONTE (via AST), não executam o servidor — as
funções vivem dentro de um main.py de milhares de linhas com import pesado
(FastAPI, psycopg2, httpx). É o mesmo padrão de teste_guias.py.
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

    # ── 1. a ordem é por published_at, não por collected_at ────────────────
    # As duas guias que mostram artigo por artigo (a de notícias e a de
    # seleção) usam o mesmo padrão: buscam do banco (já ordenado) e depois
    # reordenam em Python. O reordenar tem que respeitar a mesma coluna.
    for nome_fn, rotulo in (("_pagina_de_noticias", "guias de notícia"),
                            ("selecao_page", "guia de seleção")):
        corpo = _corpo(nome_fn)
        ok(corpo, f"não achei {nome_fn}")
        if not corpo:
            continue
        m = re.search(r"articles\.sort\(key=lambda a: (.+?), reverse=True\)", corpo)
        ok(m is not None, f"{rotulo}: não achei o sort() de artigos")
        if m:
            chave = m.group(1)
            ok('a.get("published_at")' in chave,
               f"{rotulo}: o sort não olha mais published_at — volta a ordenar "
               "pela hora em que O COLETOR passou, não pela hora em que a "
               "notícia SAIU")
            # collected_at como desempate é aceitável (só entra quando
            # published_at falta); como critério PRINCIPAL não é.
            ok(re.match(r'^a\.get\("published_at"\)\s+or\b', chave),
               f"{rotulo}: published_at deveria vir primeiro na prioridade "
               f"do sort — ficou {chave!r}")
    print("  ordem: por published_at nas duas guias que reordenam em Python")

    # ── 2. o limite não pode cortar antes do filtro de categoria ───────────
    # /mercado/noticias, /aspas e /noticias saem da mesma busca. Um limite
    # baixo é seguro quando a busca já filtra por categoria — aqui ela NÃO
    # filtra (get_recent_articles não recebe categoria), e um dia de muito
    # volume em QUALQUER categoria pode expulsar uma notícia de mercado real
    # antes mesmo do filtro de categoria rodar.
    corpo_guias = _corpo("_pagina_de_noticias")
    m_limit = re.search(r"get_recent_articles\(hours=HORAS_DE_NOTICIA, limit=(\d+)\)", corpo_guias)
    ok(m_limit is not None, "não achei a chamada a get_recent_articles nas guias de notícia")
    if m_limit:
        limite = int(m_limit.group(1))
        ok(limite >= 300,
           f"limit={limite} nas guias de notícia — um dia de deadline (231 "
           "artigos até o meio da tarde, caso real) enche isso com outras "
           "categorias antes do filtro de Mercado/Aspas ver qualquer coisa. "
           "Precisa de folga bem acima do volume normal de um dia cheio.")
    print(f"  limite: {m_limit.group(1) if m_limit else '?'} artigos antes do "
          "filtro de categoria — folga para um dia de volume alto")

    # ── 3. o horário mostrado é o do Brasil, não o da Arábia Saudita ───────
    # Quatro cards diferentes (notícias/aspas/mercado, seleção, lixeira,
    # análise) fazem a mesma conta: converter published_at (UTC) para local.
    # As quatro têm que concordar — duas telas mostrando a mesma notícia com
    # horas diferentes é pior do que mostrar hora nenhuma.
    ocorrencias = re.findall(
        r"dt\.astimezone\(timezone\(timedelta\(hours=(-?\d+)\)\)\)", FONTE)
    ok(len(ocorrencias) == 4,
       f"esperava 4 lugares convertendo published_at para hora local, achei "
       f"{len(ocorrencias)} — se um card novo apareceu, ele também precisa "
       "entrar nesta conta")
    ok(all(h == "-3" for h in ocorrencias),
       f"nem todo card mostra horário do Brasil (UTC-3): {ocorrencias} — "
       "Brasília não tem horário de verão desde 2019, então -3 fixo não erra")
    # Nota: _dia_de_brasilia() (guia de Arbitragem) também usa "hours=3", só
    # que subtraindo em vez de somar deslocamento negativo — outra forma de
    # dizer a mesma conta (UTC-3), por isso não entra nesta contagem de 4.
    print("  horário: Brasília (UTC-3) nos 4 lugares que mostram data de artigo")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ cronologia: ordem por published_at, limite com folga, horário do Brasil")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
