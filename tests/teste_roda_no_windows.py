"""
A suíte tem que rodar na máquina do Vini, e não só na minha.

POR QUE ESTE ARQUIVO EXISTE (14/09/26)
    Quatro vezes seguidas o gancho de envio barrou o Vini, e nenhuma delas era
    defeito do código dele:

        1. o console do Windows não imprimia "✓" e acentos;
        2. o arquivo do gancho vinha com fim de linha do Windows e o shell
           não o executava;
        3. bibliotecas que só existem no servidor (lxml, PIL, pdfplumber);
        4. um teste escrevendo em "/tmp/_conf.js", que no Windows não existe.

    A causa é sempre a mesma: eu escrevo e rodo tudo em Linux, e o gancho roda
    no Windows dele. Cada diferença entre os dois só aparecia na TELA DELE, uma
    por vez, e cada uma custava uma ida e volta.

    "Qual a dificuldade? Quarta vez que mando algo" — e ele tem razão.

O QUE ESTE ARQUIVO FAZ
    Procura, aqui no Linux, os hábitos que só funcionam aqui. Não substitui
    rodar no Windows de verdade; pega a classe inteira de erro que me escapou
    quatro vezes, antes de custar mais uma ida e volta.
"""
import ast
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTES = os.path.join(RAIZ, "tests")
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _arquivos_de_teste():
    for nome in sorted(os.listdir(TESTES)):
        if nome.startswith("teste_") and nome.endswith(".py"):
            yield nome, open(os.path.join(TESTES, nome),
                             encoding="utf-8").read()


# Pastas que só existem em Unix. Escritas fora de um comentário, elas viram
# FileNotFoundError no Windows — e o erro não menciona o sistema operacional,
# então quem lê acha que o teste quebrou.
_PASTA_UNIX = re.compile(r"""['"](/tmp|/usr|/home|/var|/etc|/opt)(/|['"])""")


def _sem_comentarios(texto: str) -> str:
    """O código sem comentários nem docstrings.

    Os comentários deste projeto citam caminhos a torto e a direito ("o mesmo
    truque do /tmp/subir.py"), e acusá-los seria transformar a documentação
    num obstáculo — exatamente o oposto do que ela é aqui.
    """
    linhas = []
    for linha in texto.split("\n"):
        sem = re.sub(r"#.*$", "", linha)
        linhas.append(sem)
    limpo = "\n".join(linhas)
    # Docstrings e blocos de texto longo saem por aspas triplas.
    limpo = re.sub(r'"""(?:.|\n)*?"""', '""', limpo)
    limpo = re.sub(r"'''(?:.|\n)*?'''", "''", limpo)
    return limpo


def testar():
    falhas.clear()

    # ── 1. NADA DE PASTA DO LINUX ESCRITA À MÃO ──────────────────────────
    # Foi o defeito de hoje: "/tmp/_conf.js" no teste_estrutura.py. O jeito
    # certo é tempfile.gettempdir(), que responde certo nos dois sistemas.
    for nome, texto in _arquivos_de_teste():
        achados = _PASTA_UNIX.findall(_sem_comentarios(texto))
        ok(not achados,
           f"{nome} escreve um caminho que só existe no Linux "
           f"({', '.join(sorted({a[0] for a in achados}))}). No Windows isso "
           "vira FileNotFoundError, e o erro não fala em sistema operacional — "
           "parece teste quebrado. Use tempfile.gettempdir()")

    # ── 2. CHAMAR PROGRAMA DE FORA TEM QUE SER PROTEGIDO ─────────────────
    # No Linux, `subprocess.run` de um programa ausente devolve código de erro.
    # No Windows, LEVANTA FileNotFoundError. Sem proteção, "node não instalado"
    # vira "o JS da página está quebrado" — acusa o código errado.
    externos = ("node", "nodejs", "ffmpeg", "ffprobe", "git", "sh", "bash")
    for nome, texto in _arquivos_de_teste():
        try:
            arvore = ast.parse(texto)
        except SyntaxError:
            continue
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call)
                    and isinstance(no.func, ast.Attribute)
                    and no.func.attr == "run"
                    and isinstance(no.func.value, ast.Name)
                    and no.func.value.id == "subprocess"):
                continue
            if not no.args or not isinstance(no.args[0], ast.List):
                continue
            primeiro = no.args[0].elts[0] if no.args[0].elts else None
            programa = ""
            if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
                programa = primeiro.value
            elif isinstance(primeiro, ast.Name):
                # Variável: quem a preencheu já conferiu se o programa existe.
                continue
            if os.path.basename(programa) not in externos:
                continue
            # Está dentro de um try QUE PEGA a exceção?
            #
            # A primeira versão aceitava qualquer `ast.Try`, e isso deixou
            # passar um `try/finally` sem `except` — que não pega nada, só
            # garante a limpeza. Foi exatamente o caso do
            # teste_gravar_jogo_do_canal.py, e o defeito só apareceu quando
            # simulei a máquina sem Node. O verificador tinha o mesmo tipo de
            # furo que ele fora escrito para achar.
            protegido = False
            for pai in ast.walk(arvore):
                if not isinstance(pai, ast.Try) or not pai.handlers:
                    continue
                if any(no is n for n in ast.walk(pai)):
                    protegido = True
                    break
            ok(protegido,
               f"{nome} chama '{programa}' sem try/except. No Windows, "
               "programa ausente LEVANTA em vez de devolver erro — e aí a "
               "falta de uma ferramenta vira acusação contra o código")

    # ── 3. O GANCHO DE ENVIO TEM QUE SER LEGÍVEL PELO SHELL ──────────────
    # Fim de linha do Windows (CR+LF) num script de shell faz o interpretador
    # procurar um comando com um caractere invisível grudado. O erro diz "not
    # found" numa linha visivelmente correta.
    gancho = os.path.join(RAIZ, "ganchos", "pre-push")
    if os.path.exists(gancho):
        bruto = open(gancho, "rb").read()
        ok(b"\r\n" not in bruto,
           "ganchos/pre-push está com fim de linha do Windows. O shell não "
           "executa: ele procura um comando com um CR grudado e diz 'not "
           "found' numa linha que na tela está certa")
        ok(bruto.startswith(b"#!"),
           "ganchos/pre-push perdeu a primeira linha que diz qual "
           "interpretador usar")
        atributos = os.path.join(RAIZ, ".gitattributes")
        ok(os.path.exists(atributos)
           and "ganchos" in open(atributos, encoding="utf-8").read(),
           "sumiu a regra do .gitattributes que trava o fim de linha dos "
           "ganchos. Sem ela o Windows reconverte no próximo clone")

    # ── 4. A SAÍDA TEM QUE SOBREVIVER A UM CONSOLE ANTIGO ────────────────
    # O Git Bash no Windows abre em cp1252 e não escreve "✓" nem acento. Sem
    # forçar UTF-8, todo teste morre ao imprimir — e vira "FALHOU".
    conf = open(os.path.join(TESTES, "conferir.py"), encoding="utf-8").read()
    ok("PYTHONIOENCODING" in conf,
       "conferir.py parou de forçar UTF-8 no ambiente dos testes. No console "
       "do Windows eles morrem ao imprimir '✓' e o placar vira uma mentira")
    ok('reconfigure(encoding="utf-8"' in conf,
       "conferir.py parou de forçar UTF-8 na própria saída")
    ok('encoding="utf-8", errors="replace"' in conf,
       "conferir.py voltou a ler a saída dos testes no formato do sistema — "
       "um acento no meio derruba a leitura inteira")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ roda no Windows: sem caminho do Linux, sem programa desprotegido")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
