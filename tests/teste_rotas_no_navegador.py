"""
Rota que eu peço para o Vini "rodar" tem que abrir no navegador.

O QUE ACONTECEU (10/09/26)
    Eu escrevi na resposta: "rode POST /api/pendurados/atualizar?refazer=1".
    Ele fez a única coisa que dá para fazer com um endereço — colou na barra
    do navegador — e recebeu:

        {"detail":"Method Not Allowed"}

    A barra de endereço só sabe GET. A rota só aceitava POST. Nada rodou.

    O detalhe que torna isso pior que um erro comum: a tela devolveu um JSON
    de aparência técnica, sem nada dizendo "isto não fez nada". Ele veio
    perguntar se tinha funcionado — e podia perfeitamente ter suposto que sim,
    e seguido achando que os cartões perdidos tinham voltado.

    A culpa não é do navegador. É de eu ter entregado um endereço sabendo que
    o único jeito de abrir um endereço é com GET.

A REGRA QUE FICA
    Se uma ação precisa ser disparável colando o endereço, ela tem que
    responder no GET. O app já fazia isso em /api/admin/fix-article, com o
    comentário explicando exatamente este motivo — eu não segui o padrão que
    já estava no projeto.

    GET que muda estado não é bonito, e não vale para tudo: publicar, apagar e
    aprovar continuam só no POST, porque ali um clique errado (ou um prefetch
    do navegador) custa caro. Vale para as ações de MANUTENÇÃO, que só
    reprocessam dado e no pior caso gastam chamada de API.

O QUE ESTE ARQUIVO VIGIA
    Que as rotas de manutenção que eu costumo mandar por endereço tenham o
    par GET, e que as rotas destrutivas NÃO tenham.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _rotas():
    """{caminho: {métodos}} lido dos decoradores do main.py."""
    mapa = {}
    for n in ast.walk(ast.parse(FONTE)):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in n.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not (isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name) and f.value.id == "app"):
                continue
            if f.attr not in ("get", "post", "put", "delete", "patch"):
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)):
                continue
            mapa.setdefault(dec.args[0].value, set()).add(f.attr)
    return mapa


# Manutenção: reprocessa dado, no pior caso gasta chamada de API. Precisa
# abrir no navegador, porque é assim que eu a entrego ao Vini.
PRECISA_DE_GET = [
    "/api/pendurados/atualizar",
]

# Destrutivas ou públicas: um clique errado custa caro, e prefetch de
# navegador existe. Continuam só no POST.
SO_POST = [
    "/api/aprovacao/{tipo}/{item_id}",
    "/api/posts/{post_id}/publicar",
]


def testar():
    falhas.clear()
    rotas = _rotas()

    for caminho in PRECISA_DE_GET:
        metodos = rotas.get(caminho)
        ok(metodos is not None, f"a rota {caminho} sumiu do app")
        if metodos:
            ok("get" in metodos,
               f"{caminho} não responde a GET. Se eu mandar este endereço "
               "para o Vini, ele vai colar na barra do navegador e receber "
               '"Method Not Allowed" — e nada vai rodar, com cara de que '
               "rodou")
            ok("post" in metodos,
               f"{caminho} perdeu o POST, que é como a própria tela chama")

    for caminho in SO_POST:
        metodos = rotas.get(caminho)
        if metodos:
            ok("get" not in metodos,
               f"{caminho} ganhou um GET. Esta ação muda o que vai ao ar: "
               "um prefetch do navegador, um link tocado sem querer ou um "
               "histórico recarregado bastam para dispará-la")

    # E o motivo tem que estar escrito no código, senão o próximo a passar
    # aqui 'limpa' o GET duplicado por achar que é sobra.
    ok("Method Not Allowed" in FONTE,
       "sumiu a explicação de por que existe o par GET/POST. Sem ela, o par "
       "parece duplicação e alguém apaga — e o erro volta inteiro")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ rotas de manutenção abrem colando o endereço; as destrutivas "
          "continuam só no POST")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
