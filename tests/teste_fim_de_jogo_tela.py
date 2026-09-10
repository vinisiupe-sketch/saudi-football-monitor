"""
A guia Fim de Jogo depois da faxina de 09/09/26.

O QUE ESTAVA ERRADO
    Três reclamações do Vini que pareciam três coisas e eram uma só:

        "o texto não cabe no card"
        "a fonte é diferente do resto do app"
        "tem sub-aba que não serve mais"

    Esta tela foi copiada da guia Posts, e veio com o HTML de lá — mas não com
    o CSS. As classes `.duas`, `.fonte` e `.fonte pre` são declaradas dentro do
    `_POSTS_HTML`; aqui elas simplesmente não existiam. Um `<pre>` sem estilo
    cai no padrão do navegador: monoespaçada e `white-space: pre`, que NÃO
    quebra linha. Daí o texto em outra fonte, escapando do card.

    As sub-abas "Alertas" e "Escalações" nasceram para comparar duas fontes de
    dados (API-Football e Sportmonks). Sobrou uma. Comparação com uma fonte só
    não é comparação — e as duas telas já eram feitas melhor em outro lugar: o
    alerta de gol virou o clipe automático, e a escalação virou a guia
    Escalações, com o matchsheet oficial.

    E o texto copiável começava com "⏱️ FIM DE JOGO (parcial)" enquanto o jogo
    rolava. Isso ia junto no ctrl+C e podia parar num post publicado.

COMO FICOU
    Uma tela só. O texto vai direto num `<pre class="fj-texto">`, que É
    declarado no CSS desta página, com `pre-wrap` e `overflow-wrap`. O estado
    do jogo virou etiqueta — "Encerrado" e "Em andamento" — e saiu do texto.

O QUE ESTE ARQUIVO VIGIA
    Que toda classe usada no HTML e no JS desta página exista no CSS DESTA
    página (a regra que, se estivesse valendo antes, teria pego o defeito
    original); que as sub-abas não voltem; que "(parcial)" não volte ao texto;
    e que a tipografia continue igual à do resto do app.
"""
import os
import re
import sys
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _importar_main():
    for nome in ("fastapi", "fastapi.responses", "fastapi.staticfiles",
                 "fastapi.middleware", "fastapi.middleware.cors",
                 "fastapi.templating", "httpx", "feedparser", "bs4", "dotenv",
                 "psycopg2", "psycopg2.extras", "psycopg2.extensions",
                 "apscheduler", "apscheduler.schedulers",
                 "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                 "apscheduler.triggers.cron", "apscheduler.triggers.interval",
                 "apscheduler.jobstores", "apscheduler.executors",
                 "apscheduler.schedulers.background", "starlette",
                 "starlette.middleware", "starlette.middleware.base",
                 "starlette.responses", "starlette.requests", "lxml"):
        sys.modules.setdefault(nome, MagicMock(name=nome))
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


def _pagina(main):
    """A página como a rota /fim-de-jogo a monta — e não como eu imagino."""
    return (main._FIMJOGO_HTML
            .replace("__HEADER_CSS__", main._HEADER_CSS)
            .replace("__THEME__", main._HEAD_COMUM)
            .replace("__FJ_CSS__", main._FIMJOGO_CSS)
            .replace("__FJ_JS__", main._FIMJOGO_JS)
            .replace("__HDR__", ""))


# Classes que vêm do cabeçalho comum ou são usadas só como gancho de
# JavaScript, sem estilo próprio. Ficam de fora da varredura.
DO_CABECALHO = {
    "iar-marca", "iar-linha", "iar-item", "iar-pilula", "iar-menu",
    "iar-inicio", "iar-lacuna", "iar-ativo", "iar-ico", "iar-rot",
    "ativa", "on", "copied", "aberto",
}


def testar():
    falhas.clear()
    main = _importar_main()
    pagina = _pagina(main)
    css = "\n".join(re.findall(r"<style>(.*?)</style>", pagina, re.S))

    # ── 1. a regra que teria pego o defeito original ─────────────────────
    # Toda classe escrita no HTML ou montada no JS desta página tem que estar
    # declarada no CSS DESTA página. Era exatamente isto que falhava: `.duas`,
    # `.fonte` e `.fonte pre` só existiam no CSS da guia Posts.
    usadas = set()
    for m in re.finditer(r'class="([^"{}]+)"', pagina):
        usadas.update(m.group(1).split())
    for m in re.finditer(r"className = '([^'{}+]+)'", pagina):
        usadas.update(m.group(1).split())
    declaradas = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    orfas = sorted(c for c in usadas - declaradas - DO_CABECALHO
                   if not c.startswith("iar-"))
    ok(not orfas,
       f"classe usada na página e sem estilo nenhum aqui: {orfas}. Foi assim "
       "que o texto do fim de jogo saiu em monoespaçada sem quebrar linha — "
       "o HTML veio da guia Posts e o CSS ficou lá")

    # ── 2. as sub-abas não voltam ────────────────────────────────────────
    for sumiu in ("mostrarAba", "painel-gols", "painel-esc", "abaGolsN",
                  "abaEscN", "carregarGols", "carregarEscalacoes",
                  "cartaoEscalacao", "cicloEscalacoes", "caixaFonte"):
        ok(sumiu not in main._FIMJOGO_JS and sumiu not in main._FIMJOGO_HTML
           or sumiu in main._FIMJOGO_JS.split("saíram junto")[-1][:600],
           f"'{sumiu}' voltou à guia Fim de Jogo")

    # As rotas que elas consumiam CONTINUAM de pé: quem carimba o gol para o
    # clipe automático é /api/gols/ao-vivo. Apagar a rota junto com a tela
    # derrubaria o corte automático numa mudança de layout.
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    for rota in ('@app.get("/api/gols/ao-vivo")', '@app.get("/api/escalacoes")'):
        ok(rota in fonte,
           f"a rota {rota} foi apagada junto com a sub-aba. Ela alimenta o "
           "clipe automático, que não tem nada a ver com esta tela")

    # ── 3. nenhuma menção à Sportmonks na tela ───────────────────────────
    # Só no HTML e no JS: os comentários do Python explicam por que ela saiu,
    # e um teste que proíbe a palavra no arquivo inteiro proíbe a explicação.
    visivel = main._FIMJOGO_HTML + re.sub(r"//[^\n]*", "", main._FIMJOGO_JS)
    ok("ortmonks" not in visivel.lower(),
       "a Sportmonks voltou a aparecer na tela do Fim de Jogo")
    ok("API-Football" not in visivel,
       "o selo da API-Football voltou. Com uma fonte só, carimbar de onde vem "
       "o dado em 100% dos cards não informa nada — só encolhe o texto")

    # ── 4. o estado do jogo é etiqueta, não texto copiável ───────────────
    # Olho as LINHAS DE CÓDIGO, sem os comentários: a primeira versão deste
    # teste procurava "(parcial)" no arquivo inteiro e falhava por causa do
    # comentário que explica por que a palavra saiu. Teste que acusa a própria
    # documentação é teste que alguém apaga.
    # Tiro o comentário de Python (#) e a linha inteira quando ela é comentário
    # de JavaScript — o JS mora dentro de uma string do Python, então o `#` não
    # dá conta dele. Corto o `//` só quando a linha COMEÇA com ele, para não
    # decepar um "https://" no meio do código.
    codigo = "\n".join("" if l.lstrip().startswith("//") else l.split("#")[0]
                       for l in fonte.split("\n"))
    ok("(parcial)" not in codigo,
       '"(parcial)" voltou ao cabeçalho do texto. Aquilo entra no ctrl+C e '
       'já podia sair num post publicado')
    ok('"⏱️ FIM DE JOGO"' in fonte,
       "sumiu o cabeçalho do texto de fim de jogo")
    ok("Em andamento" in main._FIMJOGO_JS,
       "sumiu a etiqueta 'Em andamento'")
    ok("fj-selo fj-vivo\">Em andamento" in main._FIMJOGO_JS,
       "a etiqueta 'Em andamento' perdeu a classe fj-vivo, que é o que a "
       "deixa verde no padrão do 'Encerrado'")
    ok('fj-selo fj-fim">Encerrado' in main._FIMJOGO_JS,
       "a etiqueta 'Encerrado' mudou de forma — as duas seguem o mesmo padrão")
    ok(".fj-selo.fj-vivo" in main._FIMJOGO_CSS
       and "#B6FF00" in main._FIMJOGO_CSS.split(".fj-selo.fj-vivo")[1][:80],
       "a etiqueta de jogo em andamento deixou de ser verde")

    # ── 5. o texto quebra linha e cabe no card ───────────────────────────
    regra = main._FIMJOGO_CSS[main._FIMJOGO_CSS.find(".fj-texto"):]
    regra = regra[:regra.find("}")]
    ok("pre-wrap" in regra,
       ".fj-texto perdeu o white-space:pre-wrap — sem ele as quebras que o "
       "texto já traz somem e ele vira um parágrafo só")
    ok("overflow-wrap:anywhere" in regra.replace(" ", ""),
       ".fj-texto perdeu o overflow-wrap — uma palavra comprida (nome de "
       "clube, URL) estica o card e o celular ganha rolagem lateral")
    ok("font-family:inherit" in regra.replace(" ", ""),
       ".fj-texto perdeu o font-family:inherit e o <pre> volta para a "
       "monoespaçada padrão do navegador")

    # ── 6. tipografia igual à do resto do app ────────────────────────────
    corpo = main._FIMJOGO_HTML[main._FIMJOGO_HTML.find("body{"):]
    corpo = corpo[:corpo.find("}")]
    ok("'Inter'" in corpo,
       "a página voltou a ter uma pilha de fontes só dela. O resto do app "
       "usa 'Inter',system-ui,-apple-system,'Segoe UI',sans-serif")
    titulo = main._FIMJOGO_HTML[main._FIMJOGO_HTML.find("h1{"):]
    titulo = titulo[:titulo.find("}")]
    ok("Bebas Neue" in titulo,
       "o h1 desta guia não está em Bebas Neue, e todas as outras estão")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ Fim de Jogo: uma tela só, texto que quebra linha, etiqueta no "
          "lugar do '(parcial)' e tipografia do app")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
