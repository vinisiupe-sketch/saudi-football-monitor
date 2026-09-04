"""
O JavaScript embutido nas páginas precisa COMPILAR.

O QUE ACONTECEU (04/09/26)
    Eu montei um botão assim, dentro do HTML da guia de Escalação por PDF:

        onclick="copyText(this, document.getElementById('...').value)\\">

    A aspa que fecha o atributo vinha escapada — só que aquele HTML mora
    dentro de uma string do PYTHON. O Python comeu a barra, sobrou uma aspa
    solta, a string de JavaScript fechou cedo e o <script> INTEIRO virou erro
    de sintaxe. A página parou de responder — nem o envio do PDF funcionava
    mais — e nada apareceu na tela: erro de sintaxe não dá mensagem, dá
    silêncio. Só apareceu porque o Vini disse "não estou vendo nada".

    O Python compilando não pega isso: para ele, aquilo é texto. Os testes de
    estrutura também não: eles conferem se um pedaço de texto ESTÁ na página,
    e o pedaço estava lá — quebrado.

O QUE ESTE ARQUIVO FAZ
    Renderiza as páginas de verdade, arranca cada <script> e manda para o
    parser do Node. Se não compilar, quebra aqui — antes de virar uma tela
    muda no meio de um jogo.
"""
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _tem_node() -> bool:
    for nome in ("node", "nodejs"):
        try:
            r = subprocess.run([nome, "--version"], capture_output=True, timeout=20)
            if r.returncode == 0:
                return nome
        except Exception:
            continue
    return ""


def _blocos_de_script(html: str):
    """Cada <script> sem src, como texto."""
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html,
                         re.S | re.I):
        corpo = m.group(1).strip()
        if corpo:
            yield corpo


def _paginas():
    """O HTML como o NAVEGADOR recebe, e não como está escrito no arquivo.

    Esta distinção é o teste inteiro. Na primeira versão eu li o texto do
    main.py com expressão regular — e aí `\\"` no arquivo continua sendo duas
    letras, quando o que chega ao navegador é uma aspa só. Ou seja: eu estaria
    conferindo exatamente o texto que NÃO é o que quebra, e o defeito que me
    fez escrever este teste passaria batido por ele.

    Usando a árvore do Python, cada literal já vem decodificado: as barras
    foram comidas, as chaves dobradas das f-strings viraram chaves simples, e
    o que sobra é o JavaScript de verdade. Os buracos das f-strings viram "0"
    — o que interessa aqui é a estrutura (aspas, chaves, parênteses), não o
    valor que entra no lugar.
    """
    import ast
    arvore = ast.parse(FONTE)
    for no in ast.walk(arvore):
        if isinstance(no, ast.JoinedStr):
            pedacos = []
            for parte in no.values:
                if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                    pedacos.append(parte.value)
                else:
                    pedacos.append("0")
            texto = "".join(pedacos)
        elif isinstance(no, ast.Constant) and isinstance(no.value, str):
            texto = no.value
        else:
            continue
        if "<script" in texto:
            yield texto


def testar():
    node = _tem_node()
    if not node:
        print("  (sem node neste ambiente — pulando a checagem de sintaxe)")
        return 0

    blocos = 0
    for pagina in _paginas():
        for corpo in _blocos_de_script(pagina):
            limpo = corpo
            blocos += 1
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as f:
                f.write(limpo)
                caminho = f.name
            try:
                r = subprocess.run([node, "--check", caminho],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    erro = (r.stderr or "").strip().splitlines()
                    resumo = " | ".join(erro[:4])
                    trecho = limpo[:70].replace("\n", " ")
                    falhas.append(f"script que começa com '{trecho}...' não "
                                  f"compila: {resumo}")
            finally:
                try:
                    os.unlink(caminho)
                except Exception:
                    pass

    ok(blocos > 0, "não achei nenhum <script> nas páginas — o teste está "
                   "olhando para o lugar errado e passaria verde para sempre")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          f"  ✓ javascript das páginas: {blocos} bloco(s) compilam")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
