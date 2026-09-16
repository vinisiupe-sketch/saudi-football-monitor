"""
A guia de Configurações, organizada em seções.

O PEDIDO (16/09/26)
    "Também quero que organize a guia de configurações, tá uma zona. Gosto do
    layout de configurações daqui do aplicativo do Claude, se puder replicar,
    agradeço."

    Estava mesmo: vinte e quatro ajustes de oito grupos, mais jogadores,
    convites e contas, empilhados numa coluna só. Quem ia lá mudar UMA coisa
    rolava a página inteira.

O QUE ESTE ARQUIVO VIGIA — e a ordem importa
    1. QUE NENHUM AJUSTE SUMIU. É o risco real de reorganizar: um ajuste fora
       de toda seção continua existindo, o app continua obedecendo a ele, e
       ninguém mais consegue mexer. Por isso grupo sem seção cai em "Outros"
       em vez de desaparecer, e por isso este é o primeiro teste do arquivo.
    2. Que a página se monta a partir do `ajustes.py`, sem uma segunda lista
       noutro arquivo para apodrecer.
    3. Que as gavetas que já existiam — Jogadores, Convites, Contas — não
       ficaram órfãs no caminho.
    4. Que o JavaScript é JavaScript válido. Ele mora dentro de uma string de
       Python num arquivo de vinte mil linhas, e uma chave a menos derruba a
       página inteira sem o py_compile perceber.
"""
import os
import subprocess
import sys
import tempfile
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    _t = types.ModuleType("psycopg2")
    _t.extras = types.ModuleType("psycopg2.extras")
    _t.extras.RealDictCursor = object
    _t.Error = Exception
    sys.modules["psycopg2"] = _t
    sys.modules["psycopg2.extras"] = _t.extras

import ajustes                                          # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def bloco(qual):
    """O conteúdo de um dos três blocos da página, recortado com precisão.

    Cada um tem o seu terminador porque eles NÃO são iguais: o HTML acaba em
    `</html>\"\"\"`, sem quebra de linha antes das aspas. Recortar os três com a
    mesma regra foi como eu apaguei o `_CONFIG_HTML` inteiro sem perceber —
    o py_compile passou, e só o teste de nomes indefinidos pegaria.
    """
    marcas = {"css": ('_CONFIG_CSS = """', '\n"""'),
              "html": ('_CONFIG_HTML = """<!DOCTYPE html>', '</html>"""'),
              "js": ('_CONFIG_JS = r"""', '\n"""')}
    ini, fim = marcas[qual]
    assert FONTE.count(ini) == 1, f"o marcador de {qual} não é único"
    i = FONTE.index(ini) + len(ini)
    return FONTE[i:FONTE.index(fim, i)]


CSS, HTML, JS = bloco("css"), bloco("html"), bloco("js")


# ─────────────────────────────────────────────────────────────────────────
# 1. NENHUM AJUSTE PODE TER SUMIDO
# ─────────────────────────────────────────────────────────────────────────
grupos = ajustes.grupos()
secoes = ajustes.secoes()
cobertos = [g for s in secoes for g in s["grupos"]]

for g in grupos:
    ok(g in cobertos,
       f"o grupo '{g}' não aparece em seção nenhuma. Os ajustes dele "
       f"continuam existindo e o app continua obedecendo — só ninguém mais "
       f"consegue mexer neles")
ok(len(cobertos) == len(set(cobertos)),
   "algum grupo está em duas seções; os ajustes dele apareceriam duplicados")

# E O ÓRFÃO TEM DE APARECER. Aqui está o teste que importa: eu invento um
# grupo que ninguém mapeou e confiro que ele NÃO some.
_guardado = list(ajustes.AJUSTES)
try:
    ajustes.AJUSTES.append({"chave": "_teste_orfao", "grupo": "Grupo Inventado",
                            "rotulo": "x", "tipo": "int", "min": 1, "max": 2,
                            "padrao": 1, "ajuda": "x"})
    com_orfao = ajustes.secoes()
    onde = [s for s in com_orfao if "Grupo Inventado" in s["grupos"]]
    ok(len(onde) == 1,
       "um grupo que ninguém mapeou sumiu da tela em vez de cair em 'Outros'. "
       "É o pior desfecho possível: o ajuste existe, o app obedece, e não há "
       "onde mexer")
    if onde:
        ok(onde[0]["chave"] == "outros",
           f"o grupo órfão foi parar em '{onde[0]['chave']}' em vez de 'Outros'")
        ok(com_orfao[-1]["chave"] in ("saude",),
           "a seção 'Outros' entrou depois das seções de tela própria; ela "
           "tem de ficar junto das de ajustes")
finally:
    ajustes.AJUSTES[:] = _guardado

# Sem órfão, "Outros" não existe — seção vazia é ruído.
ok(not any(s["chave"] == "outros" for s in ajustes.secoes()),
   "a seção 'Outros' aparece mesmo sem nenhum grupo órfão")


# ─────────────────────────────────────────────────────────────────────────
# 2. A PÁGINA SE MONTA A PARTIR DO ajustes.py
# ─────────────────────────────────────────────────────────────────────────
ok('"secoes": ajustes.secoes()' in FONTE,
   "a rota /api/ajustes parou de mandar as seções; a página não tem como se "
   "montar")
ok("d.secoes" in JS,
   "o JavaScript parou de ler as seções que o servidor manda")

# NENHUM NOME DE SEÇÃO ESCRITO NA PÁGINA. Se estiver, é uma segunda lista, e
# segunda lista apodrece — foi a regra que o próprio ajustes.py estabeleceu
# quando os grupos nasceram.
for s in ajustes.SECOES:
    ok(s["nome"] not in JS and s["nome"] not in HTML,
       f"o nome da seção '{s['nome']}' está escrito na página. Ele tem de vir "
       f"do ajustes.py, senão são duas listas para manter")


# ─────────────────────────────────────────────────────────────────────────
# 3. O QUE JÁ EXISTIA NÃO PODE TER FICADO ÓRFÃO
# ─────────────────────────────────────────────────────────────────────────
for funcao, gaveta in (("carregarElenco", "elenco"),
                       ("carregarConvites", "convites"),
                       ("carregarContas", "contas"),
                       ("carregarSaude", "saude")):
    ok(f"function {funcao}(" in JS,
       f"sumiu a função {funcao} da página de configurações")
    ok(f"gaveta('{gaveta}'" in JS,
       f"a gaveta '{gaveta}' não é criada em lugar nenhum — a função "
       f"{funcao} escreveria num elemento que não existe")
    ok(f"{funcao}()" in JS,
       f"{funcao} nunca é chamada")

# CARREGA SÓ QUANDO ABRE. Antes a página disparava quatro consultas ao abrir,
# inclusive quando ele só queria mudar um número. A da saúde é a mais cara:
# ela conversa com quatro fontes externas, incluindo o Transfermarkt.
ok(JS.count("carregarSaude()") == 2,
   "a saúde do sistema deixou de ser carregada sob demanda — ou nunca é "
   "carregada, ou voltou a rodar na abertura da página")
i_abre = JS.index("function abrirSecao(")
ok(JS.index("carregarSaude()", i_abre) > i_abre,
   "a saúde não é mais carregada ao abrir a seção")

_inicio = JS[JS.index("carregar();\n", JS.index("async function salvar(")):]
ok("carregarContas();" not in _inicio.split("async function")[0],
   "a página voltou a carregar contas na abertura, antes de alguém pedir")


# ─────────────────────────────────────────────────────────────────────────
# 4. O DESENHO QUE ELE PEDIU
# ─────────────────────────────────────────────────────────────────────────
ok('id="menu"' in HTML and 'id="secoes"' in HTML,
   "a página perdeu o menu ou o lugar das seções")
ok(".painel{display:grid" in CSS and "grid-template-columns:232px 1fr" in CSS,
   "sumiu a grade de duas colunas — é o menu à esquerda e a seção à direita, "
   "que é o molde que ele pediu")
ok("@media (max-width:820px)" in CSS and "flex-direction:row" in CSS,
   "sumiu o arranjo de celular. Sem ele o menu de 232px come metade da tela "
   "num telefone, e ele usa isto no telefone")
ok(".item{" in CSS and "display:flex" in CSS.split(".item{")[1][:120],
   "a linha deixou de ser texto à esquerda e controle à direita")

# O botão de voltar ao padrão só onde há o que desfazer.
_cartao = JS[JS.index("function cartao(a) {"):JS.index("async function salvar(")]
ok(_cartao.count("if (!a.no_padrao)") == 2,
   "o botão de voltar ao padrão voltou a aparecer em toda linha — numa tela "
   "de vinte e quatro linhas são vinte e quatro botões que não fazem nada")

# A seção aberta fica guardada: mudar um ajuste e recarregar não pode jogar
# de volta na primeira seção.
ok("localStorage.setItem('config_secao'" in JS
   and "localStorage.getItem('config_secao'" in JS,
   "a página parou de lembrar em que seção ele estava")
# AS DUAS PONTAS, e não só a leitura: plantei o defeito que tira o try da
# ESCRITA e o teste passou, porque eu só olhava a linha da leitura. Em aba
# anônima ou com cookies bloqueados, qualquer uma das duas levanta — e a
# página inteira deixaria de montar por causa de uma conveniência.
for _uso in ("localStorage.setItem('config_secao'",
             "localStorage.getItem('config_secao'"):
    _i = JS.index(_uso)
    _antes = JS[max(0, _i - 140):_i]
    ok("try" in _antes,
       f"{_uso[:24]}... está fora de um try. Em aba anônima o localStorage "
       f"levanta, e a guia de configurações inteira pararia de abrir")


# ─────────────────────────────────────────────────────────────────────────
# 5. O JAVASCRIPT PRECISA SER JAVASCRIPT
# ─────────────────────────────────────────────────────────────────────────
try:
    _tem_node = subprocess.run(["node", "--version"],
                               capture_output=True).returncode == 0
except (FileNotFoundError, OSError):
    _tem_node = False
if _tem_node:
    _arq = os.path.join(tempfile.gettempdir(), "_conf_config.js")
    try:
        with open(_arq, "w", encoding="utf-8") as f:
            f.write(JS)
        _r = subprocess.run(["node", "--check", _arq], capture_output=True,
                            text=True)
        ok(_r.returncode == 0,
           f"o JavaScript das configurações não compila: {_r.stderr[:200]}")
    except (FileNotFoundError, OSError) as e:
        print(f"  (não consegui rodar o node: {type(e).__name__})")
else:
    print("  (node ausente — não conferi o JS)")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print(f"✅ configurações: {len(grupos)} grupos em {len(secoes)} seções, "
      f"nenhum ajuste perdido")
