"""
Toda função chamada numa página tem que existir NAQUELA página.

O QUE ACONTECEU (15/09/26)
    A ficha do jogador abriu com o cabeçalho desenhado e, no lugar dos
    números:

        Não consegui buscar os números: esc is not defined

    Eu escrevi `esc(...)` ao montar a ficha. Essa função existe na guia de
    Mercado e no campinho — não na guia de Elencos. O JavaScript só descobre
    isso ao EXECUTAR a linha, então o teste que compila os scripts passa: o
    código é sintaticamente perfeito, só chama alguém que não está lá.

    O estrago tem um formato enganoso: o cabeçalho já tinha sido desenhado, o
    erro apareceu dentro do `catch` da busca, e a mensagem final foi "não
    consegui buscar os números" — que parece problema de rede, servidor ou
    banco. O Vini gastou um print e uma pergunta com o que era uma função
    faltando.

O QUE ESTE ARQUIVO FAZ
    Percorre cada página, junta o que ela DEFINE e o que ela CHAMA, e cobra a
    diferença. É estático de propósito: para pegar isto executando, seria
    preciso clicar em cada caminho de cada tela.
"""
import ast
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


# O que o navegador já oferece, e o que cada página recebe de fora. Chamar
# qualquer um destes é legítimo, e listá-los aqui é o que separa "faltou
# definir" de "vem do ambiente".
DO_NAVEGADOR = {
    "alert", "confirm", "prompt", "fetch", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "parseInt", "parseFloat", "isNaN",
    "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
    "String", "Number", "Boolean", "Array", "Object", "Date", "Math", "JSON",
    "Promise", "Error", "RegExp", "Set", "Map", "require", "escape",
    "unescape", "structuredClone", "queueMicrotask", "reportError", "btoa",
    "atob", "print", "open", "close", "focus", "blur", "scrollTo", "matchMedia",
    "requestAnimationFrame", "getComputedStyle", "Intl", "FormData", "Blob",
    "URL", "URLSearchParams", "Image", "AbortController", "CustomEvent",
    "Event", "IntersectionObserver", "MutationObserver", "ResizeObserver",
    "localStorage", "sessionStorage", "navigator", "location", "history",
    "Symbol", "BigInt", "WeakMap", "WeakSet", "Proxy", "Reflect",
    "TextEncoder", "TextDecoder", "Function", "eval", "isFinite",
    "File", "FileReader", "Option", "Audio", "Notification", "WebSocket",
    "async",
    # Bibliotecas carregadas por <script src>. Elas existem no navegador, e
    # este teste só lê os scripts EMBUTIDOS — então precisam ser nomeadas
    # aqui, senão viram acusação permanente e o teste deixa de ser lido.
    "html2canvas",
    # O atalho de seleção da guia do glossário, definido lá dentro.
    "$",
}


def _constantes() -> dict:
    """Todo bloco de texto longo do main.py, nas DUAS formas de aspas triplas.

    O `_FIMJOGO_JS` usa aspas SIMPLES triplas, porque o JavaScript dele tem
    aspas duplas no meio. Eu procurava só as duplas, então aquele bloco não
    existia para o teste — e `carregarJogosDoDia`, que mora nele, aparecia
    como "não existe nesta página".

    Um teste que acusa o que está certo é pior que um teste que não existe:
    ele treina quem lê a ignorá-lo, e aí a acusação verdadeira passa junto.
    """
    saida = {}
    for aspas in ('"' * 3, "'" * 3):
        padrao = r"^(_\w+) = (?:r?f?|f?r?)" + re.escape(aspas)
        for m in re.finditer(padrao, FONTE, re.M):
            i = m.end()
            j = FONTE.find("\n" + aspas, i)
            if j > i:
                saida[m.group(1)] = FONTE[i:j]
    return saida


def _marcadores() -> dict:
    """{__MARCADOR__: _CONSTANTE} — como as rotas montam cada página.

    A PÁGINA TEM DE SER MONTADA COMO O SERVIDOR A MONTA. Sem isto o teste lia
    só o HTML e acusava `carregarJogosDoDia` como inexistente na guia de Fim de
    Jogo — mas ela mora em `_FIMJOGO_JS`, que a rota injeta no lugar de
    `__FJ_JS__`. Falso positivo, e do tipo caro: um teste que acusa o que está
    certo é um teste que se aprende a ignorar.
    """
    return {m.group(1): m.group(2)
            for m in re.finditer(r'\.replace\("(__\w+__)",\s*(_\w+)\)', FONTE)}


def _paginas():
    """(nome, html) de cada página servida pelo main.py e pelo public/.

    Já com os marcadores resolvidos — é o texto que chega ao navegador.
    """
    consts, marcas = _constantes(), _marcadores()

    def montar(html: str) -> str:
        for marca, const in marcas.items():
            if marca in html and const in consts:
                html = html.replace(marca, consts[const])
        return html

    for nome, corpo in consts.items():
        if nome.endswith("_HTML"):
            yield nome, montar(corpo)
    publico = os.path.join(RAIZ, "public")
    if os.path.isdir(publico):
        for arq in sorted(os.listdir(publico)):
            if arq.endswith(".html"):
                yield arq, montar(open(os.path.join(publico, arq),
                                       encoding="utf-8").read())


def _scripts(html: str) -> str:
    """Todo o JavaScript da página, junto — é assim que o navegador o vê."""
    return "\n".join(m.group(1) for m in
                     re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S)
                     if "src=" not in m.group(0).split(">")[0])


def _sem_comentarios_nem_texto(js: str) -> str:
    """O código sem comentários, sem o conteúdo das aspas e sem regex.

    Sem isto, o verificador lê os COMENTÁRIOS — e este projeto comenta muito.
    "o setor (G/D/M/A)" virava uma chamada a `setor`.

    A EXPRESSÃO REGULAR PRECISOU DE TRATAMENTO PRÓPRIO, e ela foi o defeito
    que me pegou: o código tem `.replace(/"/g, '&quot;')`, e a aspa DENTRO da
    regex foi lida como início de texto. O limpador engoliu daí até a próxima
    aspa — dois mil caracteres de código viraram branco, e com eles a chamada
    `esc(...)` que este teste existia para achar.

    O teste passou com o defeito plantado, e passou em silêncio. É o pior
    resultado possível para uma ferramenta de verificação: ela não estava
    errando, estava CEGA, e uma ferramenta cega dá a mesma resposta de uma que
    funciona.

    Distinguir `/` de divisão para `/` de regex é ambíguo em JavaScript. Uso a
    regra usual: depois de operador, abre-parêntese, vírgula ou `return`, uma
    barra começa regex; depois de um valor, é divisão. Erra em casos raros — e
    por isso a varredura confere, no fim, quanto do código sobrou.
    """
    fora, i, n = [], 0, len(js)
    anterior = ""
    while i < n:
        c = js[i]
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            j = js.find("\n", i)
            j = n if j < 0 else j
            fora.append(" " * (j - i)); i = j
        elif c == "/" and i + 1 < n and js[i + 1] == "*":
            j = js.find("*/", i + 2)
            j = n if j < 0 else j + 2
            fora.append(" " * (j - i)); i = j
        elif c == "/" and anterior in "(,=:[!&|?{};+-*%<>~^" + "\n" or (
                c == "/" and js[max(0, i - 6):i].strip().endswith("return")):
            # Expressão regular: vai até a barra de fecho, pulando escapes e
            # o que estiver dentro de [ ].
            j, classe = i + 1, False
            while j < n:
                if js[j] == "\\":
                    j += 2; continue
                if js[j] == "[":
                    classe = True
                elif js[j] == "]":
                    classe = False
                elif js[j] == "/" and not classe:
                    break
                elif js[j] == "\n":
                    break
                j += 1
            j = min(j + 1, n)
            fora.append(" " * (j - i)); i = j
        elif c in "\"'`":
            j, aspas = i + 1, c
            while j < n and js[j] != aspas:
                j += 2 if js[j] == "\\" else 1
            j = min(j + 1, n)
            fora.append(" " * (j - i)); i = j
        else:
            fora.append(c); i += 1
            if not c.isspace():
                anterior = c
    return "".join(fora)

def _definidas(js: str) -> set:
    nomes = set(re.findall(r"function\s+(\w+)\s*\(", js))
    # `const f = function(){}` e `const f = (x) => ...` também definem.
    nomes |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?"
                            r"(?:function|\()", js))
    # E qualquer variável declarada pode ser um objeto que se chama.
    nomes |= set(re.findall(r"(?:const|let|var)\s+(\w+)", js))
    # `pct=n=>...` e `a=(x,y)=>...`, inclusive dentro de uma declaração com
    # vírgulas: `let total=0,pct=n=>...`. É como o código minificado da guia
    # do glossário declara, e sem isto ele virava acusação permanente.
    nomes |= set(re.findall(r"(\w+)\s*=\s*(?:async\s*)?(?:\w+|\([^)]*\))\s*=>", js))
    # E métodos de objeto: `{ pct(n){...} }` ou `{ pct: function(){} }`.
    nomes |= set(re.findall(r"(\w+)\s*:\s*(?:async\s*)?function", js))
    # OS PARÂMETROS TAMBÉM CONTAM COMO DEFINIDOS.
    #
    # `function botao(icone, rotulo, dica, aoClicar)` recebe uma função e a
    # chama: `aoClicar(b)`. Ela existe — veio de quem chamou. Cobrá-la como
    # "não definida" seria acusar o padrão mais comum de JavaScript, e o teste
    # viraria ruído.
    for m in re.finditer(r"function\s*\w*\s*\(([^)]*)\)", js):
        for arg in m.group(1).split(","):
            arg = arg.strip().split("=")[0].strip()
            if re.fullmatch(r"\w+", arg):
                nomes.add(arg)
    # O mesmo para as flechas: `(a, b) => ...` e `x => ...`.
    for m in re.finditer(r"\(([^)]*)\)\s*=>", js):
        for arg in m.group(1).split(","):
            arg = arg.strip().split("=")[0].strip()
            if re.fullmatch(r"\w+", arg):
                nomes.add(arg)
    nomes |= set(re.findall(r"(\w+)\s*=>", js))
    return nomes


def _chamadas(js: str) -> set:
    """Nomes chamados como função, fora de `algo.metodo()`.

    A exclusão do ponto é o que separa `esc(x)` de `d.json()`: método de
    objeto não é uma função da página, e cobrá-lo daria um teste que acusa
    tudo e por isso não é lido.
    """
    achadas = set()
    for m in re.finditer(r"(^|[^.\w$])([a-zA-Z_$][\w$]*)\s*\(", js, re.M):
        nome = m.group(2)
        if nome in ("function", "if", "for", "while", "switch", "catch",
                    "return", "typeof", "new", "delete", "void", "in", "of",
                    "else", "do", "try", "await", "case", "instanceof"):
            continue
        achadas.add(nome)
    return achadas


def testar():
    falhas.clear()
    total = 0
    for nome, html in _paginas():
        js = _scripts(html)
        if not js.strip():
            continue
        # Os marcadores que o Python troca na hora de servir viram valores;
        # sem trocá-los, `__FORMACOES__` pareceria uma chamada.
        js = re.sub(r"__\w+__", "0", js)
        total += 1
        # Os nomes definidos saem do código COM as aspas (uma função pode ser
        # definida dentro de uma string montada), mas as chamadas saem do
        # código limpo — senão a prosa dos comentários vira acusação.
        limpo = _sem_comentarios_nem_texto(js)
        faltando = sorted(_chamadas(limpo) - _definidas(js) - DO_NAVEGADOR)
        ok(not faltando,
           f"{nome} chama função que não existe nela: {', '.join(faltando)}. "
           "O JavaScript só descobre isso ao executar a linha — a página "
           "compila e quebra no uso, com uma mensagem que parece defeito de "
           "rede")

    print(f"  {total} páginas conferidas")
    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ funções do JavaScript: toda chamada tem dona na própria página")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
