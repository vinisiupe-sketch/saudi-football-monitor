"""
Roda as conferências todas de uma vez.

    py -3 tests/conferir.py

POR QUE ISTO EXISTE
    Eu vinha escrevendo os testes numa pasta temporária, e duas vezes eles
    sumiram quando a sessão reiniciou. Teste que some não é teste — é uma
    conferência que eu fiz uma vez e não consigo repetir. Daqui em diante eles
    ficam aqui, dentro do projeto, versionados junto com o código que testam.
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

# ── O CONSOLE DO WINDOWS NÃO FALA UTF-8 POR PADRÃO ──────────────────────────
#
# Em 14/09/26 o gancho de envio barrou o push do Vini com quase tudo
# "FALHOU" — e não havia teste quebrado nenhum. O console do Git Bash abre em
# cp1252, os testes imprimem "✓", "─" e acentos, e o Python estoura com
# UnicodeEncodeError. O processo morre com código diferente de zero, e quem
# está de fora lê isso como teste vermelho.
#
# É o pior tipo de falso alarme: ele acusa o código honesto e esconde o
# problema real, que é a saída do terminal. Pior ainda num gancho que BLOQUEIA
# o envio — vira um obstáculo sem explicação, que é exatamente o que eu disse
# que não queria quando escrevi a rede de proteção.
#
# Duas frentes, porque o estrago tem dois lugares:
#   1. a minha própria saída, abaixo;
#   2. a de cada teste, que roda num processo filho e não herda isto — por
#      isso o PYTHONIOENCODING vai no ambiente que eu passo a eles.
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Python antigo ou fluxo redirecionado: sigo em frente. Não conseguir
        # melhorar a saída não é motivo para não rodar os testes.
        pass

AMBIENTE = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


import re

# ── "NÃO DEU PARA CONFERIR" NÃO É "ESTÁ QUEBRADO" ───────────────────────────
#
# A máquina do Vini não tem pdfplumber, PIL nem lxml — elas vivem no servidor,
# e ele nunca precisou delas no computador dele. Sem lxml, por exemplo, o
# leitor do Transfermarkt devolve zero lesões e o teste morre com um KeyError
# que não tem nada a ver com o assunto.
#
# Chamar isso de "FALHOU" é mentira em duas direções: acusa um código que está
# certo e esconde o motivo verdadeiro. E num gancho que BLOQUEIA o envio, é a
# segunda vez que eu prendo o Vini por um defeito do meu próprio aparato.
#
# Então isto vira PULADO: contado à parte, dito em voz alta com o nome da
# biblioteca que falta, e sem barrar nada. Pulado não é escondido — é a
# diferença entre "conferi e está bom" e "não consegui conferir", e a segunda
# frase tem que aparecer na tela.
_FALTA_BIBLIOTECA = re.compile(
    r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]"
    r"|ImportError: cannot import name .* from ['\"]?([\w.]+)"
    # O bs4 não diz ModuleNotFoundError quando falta o parser: ele diz isto.
    r"|FeatureNotFound: Couldn't find a tree builder with the features you "
    r"requested: (\w+)")


# Nome que se importa -> nome que se instala. São diferentes com frequência
# suficiente para valer a tabela, e um `pip install PIL` erra sem dizer por quê.
PARA_INSTALAR = {"PIL": "pillow", "bs4": "beautifulsoup4", "yaml": "pyyaml",
                 "docx": "python-docx", "dotenv": "python-dotenv",
                 "cv2": "opencv-python", "fitz": "pymupdf",
                 "psycopg2": "psycopg2-binary"}


def _bibliotecas_declaradas() -> set:
    """As bibliotecas de fora que este projeto assume ter, pelo requirements.

    A LISTA VEM DO PROJETO, e não de um palpite meu, e é por isso que ela é
    confiável: no dia em que alguém acrescentar uma dependência nova, ela entra
    aqui sozinha. Uma lista escrita à mão aqui envelheceria calada.
    """
    nomes = set()
    for arquivo in ("requirements.txt", "requirements.mediahub.txt"):
        caminho = os.path.join(RAIZ, arquivo)
        if not os.path.exists(caminho):
            continue
        for linha in open(caminho, encoding="utf-8", errors="replace"):
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            pacote = re.split(r"[<>=!\[;]", linha)[0].strip().lower()
            if pacote:
                nomes.add(pacote)
                # O nome que se instala e o que se importa divergem o
                # suficiente para eu ter de aceitar os dois lados.
                nomes.add(pacote.replace("-", "_"))
    for instalar, importar in (("pillow", "PIL"), ("beautifulsoup4", "bs4"),
                               ("python-dotenv", "dotenv"),
                               ("psycopg2-binary", "psycopg2"),
                               ("python-docx", "docx"), ("pyyaml", "yaml")):
        if instalar in nomes:
            nomes.add(importar.lower())
    # Estas não estão no requirements do servidor porque só a arte precisa
    # delas, e a arte roda em outro lugar. Continuam sendo de fora.
    nomes.update({"pil", "pillow", "reportlab", "pypdf", "numpy", "docx",
                  "yaml", "pytest", "requests"})
    return nomes


_DECLARADAS = _bibliotecas_declaradas()


def _biblioteca_que_falta(saida: str) -> str:
    """O nome da biblioteca ausente, ou "" se o problema for outro.

    SÓ VALE PARA BIBLIOTECA DE FORA, e a fronteira é a lista do requirements.
    Se o que sumiu foi um arquivo do próprio projeto — glossario.py, elos.py —
    isso é defeito de verdade e tem que barrar.

    A primeira versão decidia isso perguntando se o arquivo existe no projeto.
    Não funciona, e eu só descobri porque testei: quando alguém APAGA
    glossario.py, o arquivo não existe — então ele parecia biblioteca de fora e
    virava "pulado". Ou seja, o único caso que essa regra tinha que pegar era
    exatamente o que ela deixava passar.

    Na dúvida eu BARRO. Módulo que ninguém declarou e ninguém reconhece é
    motivo para alguém olhar, não para seguir em frente.
    """
    m = _FALTA_BIBLIOTECA.search(saida or "")
    if not m:
        return ""
    raiz = next((g for g in m.groups() if g), "").split(".")[0]
    if not raiz:
        return ""
    return raiz if raiz.lower() in _DECLARADAS else ""


def main() -> int:
    testes = sorted(a for a in os.listdir(AQUI)
                    if a.startswith("teste_") and a.endswith(".py"))
    if not testes:
        print("nenhum teste encontrado")
        return 1
    largura = max(len(t) for t in testes)
    ruins, pulados = [], []
    for t in testes:
        r = subprocess.run([sys.executable, os.path.join(AQUI, t)],
                           cwd=RAIZ, capture_output=True, text=True,
                           env=AMBIENTE, encoding="utf-8", errors="replace")
        saida = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            marca = "ok"
        else:
            falta = _biblioteca_que_falta(saida)
            if falta:
                marca = f"PULADO (falta {falta})"
                pulados.append((t, falta))
            else:
                marca = "FALHOU"
                ruins.append((t, saida))
        print(f"  {t:{largura}}  {marca}")
    print()
    for t, saida in ruins:
        print(f"-- {t} " + "-" * 50)
        print(saida.strip()[-1500:])
        print()
    passaram = len(testes) - len(ruins) - len(pulados)
    print(f"{passaram} de {len(testes)} passaram")
    if pulados:
        faltando = sorted({b for _, b in pulados})
        print(f"{len(pulados)} pulado(s): falta(m) {', '.join(faltando)} nesta "
              "maquina. Nao e defeito do codigo.")
        # O nome para INSTALAR nem sempre é o nome para importar: quem escreve
        # `import PIL` instala `pillow`. Mandar `pip install PIL` daria um erro
        # sem explicação, e o recado viraria uma pista falsa.
        print(f"  Para conferir tudo: pip install "
              f"{' '.join(PARA_INSTALAR.get(b, b) for b in faltando)}")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
