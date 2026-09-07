"""
Módulo usado sem import é NameError esperando um jogo acontecer.

O QUE ACONTECEU (07/09/26)
    O Al Hilal fez dois gols contra o NEOM e nenhum virou clipe automático.
    A causa: eu escrevi `liga_spl.mesmo_jogo(...)` no código do clipe
    automático, e `liga_spl` não estava importado ali — o resto do arquivo o
    importa DENTRO de cada função que usa, e eu não percebi.

    Cada gol levantava NameError. O erro subia até o except do agendador,
    virava uma linha de log que ninguém lê, e o clipe simplesmente não
    nascia. Nenhuma tela mostrou nada. O `python -m py_compile` passava — para
    ele, nome não resolvido em tempo de execução não é erro de sintaxe. E os
    meus testes olhavam o TEXTO do código com AST, então também passavam: o
    texto estava certo, o import é que faltava.

    A mesma falha derrubou o /api/diag/clipe-auto, que era justamente o
    instrumento que eu tinha feito para diagnosticar isso.

O QUE ESTE ARQUIVO FAZ
    Varre cada função dos módulos do projeto e confere que todo nome de
    MÓDULO usado ali (liga_spl.x, reels.x, arbitragem.x...) esteja importado
    — no topo do arquivo ou dentro da própria função. É a checagem que um
    pyflakes faria, mas ele não está disponível neste ambiente.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []

# Os módulos do próprio projeto: são estes que aparecem como `nome.funcao()`
# e que, faltando import, quebram só quando aquela linha roda.
MODULOS = {a[:-3] for a in os.listdir(RAIZ)
           if a.endswith(".py") and not a.startswith(("teste_", "sondagem"))}

ARQUIVOS = ["main.py", "database.py", "processor.py", "collector.py",
            "scheduler.py", "liga_spl.py", "reels.py", "matchsheet.py",
            "arbitragem.py", "previa.py", "mercado.py", "elos.py"]


def _proprios(no):
    """Os nós de dentro deste, SEM entrar em funções aninhadas.

    A distinção importa: uma função de dentro tem escopo próprio, e o que ela
    usa não é problema de quem a contém. O contrário também vale — o que ela
    importa não vale para fora dela.
    """
    for campo in ast.iter_child_nodes(no):
        if isinstance(campo, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            continue
        yield campo
        for neto in ast.walk(campo):
            if neto is not campo:
                yield neto


def _importados(no) -> set:
    """Os nomes que ESTE nó (módulo ou função) traz para o escopo."""
    nomes = set()
    for filho in _proprios(no):
        if isinstance(filho, ast.Import):
            for a in filho.names:
                nomes.add((a.asname or a.name).split(".")[0])
        elif isinstance(filho, ast.ImportFrom):
            for a in filho.names:
                nomes.add(a.asname or a.name)
        # Um parâmetro ou variável com o mesmo nome também "define" — não é
        # o caso comum, mas evita falso alarme.
        elif isinstance(filho, ast.arg):
            nomes.add(filho.arg)
        elif isinstance(filho, ast.Name) and isinstance(filho.ctx, ast.Store):
            nomes.add(filho.id)
    return nomes


def _usados_como_modulo(no) -> set:
    """Nomes usados na forma `nome.alguma_coisa`, sem contar os aninhados."""
    usados = set()
    for filho in _proprios(no):
        if (isinstance(filho, ast.Attribute)
                and isinstance(filho.value, ast.Name)
                and filho.value.id in MODULOS):
            usados.add(filho.value.id)
    return usados


def testar():
    falhas.clear()
    olhados = 0
    for arquivo in ARQUIVOS:
        caminho = os.path.join(RAIZ, arquivo)
        if not os.path.exists(caminho):
            continue
        arvore = ast.parse(open(caminho, encoding="utf-8").read())

        # O que o módulo inteiro importa no topo (fora de funções).
        topo = set()
        for no in arvore.body:
            if isinstance(no, ast.Import):
                for a in no.names:
                    topo.add((a.asname or a.name).split(".")[0])
            elif isinstance(no, ast.ImportFrom):
                for a in no.names:
                    topo.add(a.asname or a.name)

        # Desço carregando o escopo: uma função aninhada enxerga o que a de
        # fora importou. Ignorar isso me deu um falso positivo em `_rosto`,
        # que usa `elos` importado pela função que a contém — e teste que
        # grita à toa é teste que ninguém lê depois.
        def descer(no, herdado, nome_pai=""):
            nonlocal olhados
            escopo = herdado | _importados(no)
            rotulo = getattr(no, "name", nome_pai)
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                olhados += 1
                for nome in _usados_como_modulo(no) - escopo:
                    if nome == arquivo[:-3]:
                        continue      # o próprio arquivo não se importa
                    falhas.append(
                        f"{arquivo}: {rotulo}() usa '{nome}.' e '{nome}' não "
                        "está importado nem no topo do arquivo, nem nesta "
                        "função, nem em nenhuma que a contenha — isso é "
                        "NameError na hora em que aquela linha rodar")
            for filho in ast.iter_child_nodes(no):
                if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef)):
                    descer(filho, escopo, rotulo)

        descer(arvore, topo)

    ok = olhados > 50
    if not ok:
        falhas.append(f"olhei só {olhados} funções — a varredura está "
                      "pegando pouca coisa e passaria verde à toa")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          f"  ✓ nomes de módulo: {olhados} funções, todas com import no escopo")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
