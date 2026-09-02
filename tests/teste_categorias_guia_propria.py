"""
Mercado e Aspas não dependem do botão ⚙️ Coleta da guia de Notícias.

O QUE ACONTECEU (01/09/26)
    O botão diz "categorias que são traduzidas". Quem o usa está olhando a
    guia de Notícias e lê outra coisa: "o que aparece AQUI". Foi exatamente
    assim que mercado e entrevista foram desmarcadas — para tirá-las da guia
    de Notícias, onde elas já nem apareciam (a guia exclui as duas desde que
    cada uma ganhou tela própria).

    O efeito real foi outro: pararam de ser TRADUZIDAS. E como as guias
    exigem title_pt, Mercado e Aspas ficaram vazias por dias, sem erro
    nenhum em lugar nenhum — a coleta continuava entrando (439 artigos num
    único dia), a tela continuava dizendo "0 notícias · 48h", e o diagnóstico
    inteiro coube em três hipóteses indistinguíveis pela tela.

O QUE ESTE ARQUIVO VIGIA
    Que a separação continue existindo. Um refactor que volte a ler
    `get_categorias_ativas` direto na triagem (em vez de
    `categorias_que_traduzem`) reintroduz o defeito inteiro, e o sintoma
    demora dias para aparecer — é o tipo de coisa que só um teste pega a
    tempo.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    talo = types.ModuleType("psycopg2")
    talo.extras = types.ModuleType("psycopg2.extras")
    talo.extras.RealDictCursor = object
    talo.Error = Exception
    sys.modules["psycopg2"] = talo
    sys.modules["psycopg2.extras"] = talo.extras

import database

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


class _EstadoFalso:
    """Guarda o app_state em memória, para exercitar get/set de verdade."""

    def __init__(self):
        self.valores = {}

    def get(self, chave):
        return self.valores.get(chave)

    def set(self, chave, valor):
        self.valores[chave] = valor


def com_estado(estado, fn, *a, **k):
    g, s = database.get_state, database.set_state
    database.get_state, database.set_state = estado.get, estado.set
    try:
        return fn(*a, **k)
    finally:
        database.get_state, database.set_state = g, s


def testar():
    falhas.clear()

    # ── 1. as duas guias próprias estão declaradas, e fora da lista do botão ──
    conferir("as categorias de guia própria",
             tuple(database.CATEGORIAS_COM_GUIA_PROPRIA), ("mercado", "entrevista"))
    for c in database.CATEGORIAS_COM_GUIA_PROPRIA:
        ok(c not in database.CATEGORIAS_DA_GUIA_NOTICIAS,
           f"'{c}' voltou para a lista do botão ⚙️ Coleta — desmarcar ali "
           "derruba a guia própria dela de novo")
    ok(set(database.CATEGORIAS_DA_GUIA_NOTICIAS)
       | set(database.CATEGORIAS_COM_GUIA_PROPRIA) == set(database.TODAS_CATEGORIAS),
       "juntas, as duas listas deixaram de cobrir TODAS_CATEGORIAS — alguma "
       "categoria ficou sem dono")

    # ── 2. o caso real: desmarcar tudo menos competição ─────────────────────
    estado = _EstadoFalso()
    salvas = com_estado(estado, database.set_categorias_ativas, ["competicao"])
    conferir("guarda só o que é da guia de Notícias", salvas, ["competicao"])

    traduzem = com_estado(estado, database.categorias_que_traduzem)
    ok("mercado" in traduzem,
       "mercado parou de traduzir com o filtro ligado — é EXATAMENTE o "
       "defeito de 01/09/26 de volta")
    ok("entrevista" in traduzem,
       "entrevista parou de traduzir com o filtro ligado — Aspas seca de novo")
    ok("competicao" in traduzem, "o que foi marcado no botão parou de valer")
    ok("geral" not in traduzem,
       "o filtro da guia de Notícias parou de filtrar — o botão virou enfeite")

    # ── 3. tentar desmarcar mercado/entrevista pelo botão não tem efeito ────
    estado2 = _EstadoFalso()
    com_estado(estado2, database.set_categorias_ativas,
               ["competicao", "mercado", "entrevista"])
    guardado = com_estado(estado2, database.get_categorias_ativas)
    ok("mercado" not in guardado and "entrevista" not in guardado,
       "o botão voltou a guardar mercado/entrevista — de onde alguém pode "
       "desmarcá-las depois, que é como o problema nasceu")
    ok("mercado" in com_estado(estado2, database.categorias_que_traduzem),
       "mercado deixou de traduzir depois de passar pelo botão")

    # ── 4. filtro desligado continua significando "tudo traduz" ─────────────
    vazio = _EstadoFalso()
    conferir("sem nada gravado, o filtro está desligado",
             com_estado(vazio, database.categorias_que_traduzem), set())
    todas_marcadas = _EstadoFalso()
    com_estado(todas_marcadas, database.set_categorias_ativas,
               list(database.CATEGORIAS_DA_GUIA_NOTICIAS))
    conferir("marcar todas as da guia = filtro desligado (sem custo de triagem)",
             com_estado(todas_marcadas, database.categorias_que_traduzem), set())

    # ── 5. a triagem usa a função certa ────────────────────────────────────
    fonte_proc = open(os.path.join(RAIZ, "processor.py"), encoding="utf-8").read()
    ok("categorias_que_traduzem()" in fonte_proc,
       "processor.py parou de usar categorias_que_traduzem")
    ok("ativas = set(get_categorias_ativas())" not in fonte_proc,
       "processor.py voltou a ler get_categorias_ativas direto — é assim que "
       "mercado e entrevista voltam a depender do botão da guia de Notícias")

    # ── 6. o painel não oferece mais as duas ───────────────────────────────
    fonte_main = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    i = fonte_main.find("const CAT_ROTULOS=")
    linha_rotulos = fonte_main[i:fonte_main.find("\n", i)] if i >= 0 else ""
    ok(linha_rotulos, "sumiu o CAT_ROTULOS do painel de coleta")
    ok("mercado:" not in linha_rotulos,
       "Mercado voltou a aparecer no painel ⚙️ Coleta — dá para desmarcar de "
       "novo, e a guia de Mercado seca junto")
    ok("entrevista:" not in linha_rotulos,
       "Entrevista voltou a aparecer no painel ⚙️ Coleta — Aspas seca junto")

    # E a rota que alimenta o painel também não pode voltar a oferecê-las.
    import ast

    def _corpo(nome):
        for n in ast.walk(ast.parse(fonte_main)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
                return "\n".join(fonte_main.split("\n")[n.lineno - 1:n.end_lineno])
        return ""

    rota = _corpo("api_get_categorias_ativas")
    ok("CATEGORIAS_DA_GUIA_NOTICIAS" in rota,
       "a rota do painel voltou a oferecer TODAS_CATEGORIAS")
    ok("sempre" in rota,
       "a rota parou de dizer quais categorias traduzem sempre — a tela fica "
       "sem como explicar por que Mercado e Aspas não estão na lista")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ Mercado e Aspas traduzem sozinhas, sem depender do botão da "
          "guia de Notícias")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
