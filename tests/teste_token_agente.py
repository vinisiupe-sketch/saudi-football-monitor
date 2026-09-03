"""
Senha errada tem que dar 403, e nunca 500.

O QUE ACONTECEU (02/09/26)
    A máquina de quem ia gravar ficou horas mostrando

        sem contato com o app: HTTP 500: Internal Server Error

    e nada mais. Fomos procurar defeito no servidor, no deploy, no Railway.
    Não era nada disso: a senha daquela máquina tinha vindo de um
    copiar-e-colar de aplicativo de mensagem e carregava um caractere fora
    do ASCII. O `secrets.compare_digest` LEVANTA TypeError nesse caso — não
    devolve False — e uma exceção não tratada dentro da rota vira 500.

    Ou seja: o app respondia "eu quebrei" quando a resposta certa era "essa
    senha não é a minha". As duas mandam procurar em lugares opostos, e foi
    por isso que custou tanto.

O QUE ESTE ARQUIVO VIGIA
    Que a comparação continue sendo feita em BYTES. É uma linha só, e é a
    linha que separa um diagnóstico de dez minutos de um de três horas.
"""
import os
import secrets
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _compara_como_a_rota(enviado: str, esperado: str):
    """A mesma comparação que _agente_autorizado faz, isolada.

    Copiar a linha aqui seria testar a minha cópia. Em vez disso eu leio a
    linha do main.py e rodo ELA — se alguém trocar o jeito de comparar lá,
    este teste passa a exercitar o jeito novo.
    """
    import ast
    for no in ast.walk(ast.parse(FONTE)):
        if isinstance(no, ast.FunctionDef) and no.name == "_agente_autorizado":
            corpo = "\n".join(FONTE.split("\n")[no.lineno - 1:no.end_lineno])
            break
    else:
        raise AssertionError("não achei _agente_autorizado no main.py")
    # A última expressão da função é o `return secrets.compare_digest(...)`.
    linha = corpo[corpo.rindex("return secrets.compare_digest"):]
    expressao = linha[len("return "):].strip()
    return eval(expressao, {"secrets": secrets},
                {"enviado": enviado, "esperado": esperado})


def testar():
    falhas.clear()

    ok("encode(" in FONTE[FONTE.find("def _agente_autorizado"):
                          FONTE.find("def _agente_autorizado") + 1800],
       "a comparação do token voltou a ser feita em texto — senha com "
       "caractere não-ASCII volta a derrubar a rota com 500")

    esperado = "abc123XYZ"

    conferir("senha certa passa",
             bool(_compara_como_a_rota(esperado, esperado)), True)
    conferir("senha errada, mesmo tamanho, é recusada",
             bool(_compara_como_a_rota("abc123XYW", esperado)), False)
    conferir("senha errada de outro tamanho é recusada",
             bool(_compara_como_a_rota(esperado * 2, esperado)), False)
    conferir("senha vazia é recusada",
             bool(_compara_como_a_rota("", esperado)), False)

    # O CASO REAL: caractere que veio junto no copiar-e-colar.
    for descricao, sujeira in (("acento", "abc123XYÇ"),
                               ("aspa curva", "abc123XY’"),
                               ("espaço não separável", "abc123XY "),
                               ("emoji", "abc123XY🙂")):
        try:
            r = _compara_como_a_rota(sujeira, esperado)
            conferir(f"senha com {descricao} é recusada sem quebrar",
                     bool(r), False)
        except Exception as e:
            falhas.append(
                f"senha com {descricao} LEVANTOU {type(e).__name__} — isso "
                "vira 500 na cara de quem está com a máquina, quando devia "
                "ser um 403 dizendo que a senha está errada")

    # E o gravador precisa avisar disso do lado dele, onde dá para consertar.
    grav = open(os.path.join(RAIZ, "gravador.py"), encoding="utf-8").read()
    ok("token.isascii()" in grav,
       "o gravador parou de conferir se a senha tem caractere estranho — "
       "quem está com a máquina volta a não ter como saber")
    ok("digite a senha à mão em vez de colar" in grav,
       "sumiu a instrução de digitar a senha em vez de colar, que é o "
       "conserto de verdade desse caso")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ senha errada dá 403 e diz o que é, mesmo vinda de copiar-e-colar")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
