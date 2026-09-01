"""
A navegação: o topo, a barra de baixo e o painel que sobe dela.

O DESENHO QUE ISTO VIGIA
    Você pediu sete paradas na barra — Agendamentos, Clipes, Fim de jogo à
    esquerda; Início no centro e elevado; Notícias do Mercado e Lesões à
    direita; e o botão de menu como sétima, à direita de Lesões. As "três
    barrinhas" que abriam o painel moravam no cabeçalho na primeira versão
    deste desenho — você pediu que elas se mudassem para a própria barra.

    O painel que esse botão abre também mudou de lado: não desce mais do
    topo, sobe da barra — um "bottom sheet" ancorado no mesmo fundo que a
    pílula, e não mais suspenso perto do cabeçalho.

Estes testes existem porque duas coisas já quebraram de verdade, antes desta
mudança, e continuam valendo:

  1. A pílula de baixo virava "uma bolha esquisita" nas telas de Posts e
     Elencos. Causa: eu chamei a barra de ".barra", e essas páginas já tinham
     uma ".barra" delas. O CSS da página carrega depois do do cabeçalho e
     vencia. Tudo do cabeçalho leva prefixo "iar-", e este teste garante que
     nenhuma classe minha colide com classe de página.

  2. O painel "não funcionava". Funcionava: ele abria e ficava recortado,
     porque um ancestral tinha overflow — overflow cria contexto de recorte.
     O Início elevado tem o mesmo risco: ele mora por fora do MIOLO que rola
     (.iar-linha), e não dentro dele, senão o recorte cortaria o círculo que
     sobe acima da pílula.
"""
import ast
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(RAIZ)
falhas = []


def ok(c, m):
    if not c:
        falhas.append(m)


src = open("main.py", encoding="utf-8").read()
mod = ast.parse(src)

# Monto o cabeçalho de verdade, com os ícones e as listas reais.
ns = {}
quero = {"_NAV_BOTTOM", "_NAV_MAIS", "_HEADER_CSS", "_THEME_VARS_CSS"}
corpo = [n for n in mod.body
         if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
             and (n.targets[0].id.startswith("_ICO_") or n.targets[0].id in quero))
         or (isinstance(n, ast.FunctionDef) and n.name == "_header")]
# O cabeçalho pergunta se há login ligado; aqui digo que sim, para o botão de
# sair entrar na conta dos testes.
ns["_login_ligado"] = lambda: True
exec(compile(ast.Module(body=corpo, type_ignores=[]), "main.py", "exec"), ns)
html = ns["_header"]("/noticias")
css = ns["_HEADER_CSS"]

# ── 1. nenhuma classe minha pode colidir com classe de página ──────────────
minhas = set(re.findall(r"\.(iar-[a-z-]+)", css))
ok(minhas, "não achei classe nenhuma com prefixo — o prefixo sumiu?")
# O _HEADER_CSS é uma soma de literais, então o texto avaliado não aparece
# inteiro no fonte — apagá-lo por substituição não funciona. Uso as linhas.
_linhas = src.splitlines()
_faixa = set()
for n in mod.body:
    if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id in ("_HEADER_CSS", "_THEME_VARS_CSS")):
        _faixa |= set(range(n.lineno - 1, n.end_lineno))
sem_cabecalho = "\n".join(l for i, l in enumerate(_linhas) if i not in _faixa)
colisoes = [c for c in minhas if re.search(r"\." + re.escape(c) + r"\s*[,{ ]", sem_cabecalho)]
ok(not colisoes, f"classe do cabeçalho colide com CSS de página: {colisoes}")
print(f"  {len(minhas)} classes prefixadas, nenhuma colidindo")

# as que causaram o defeito não podem voltar sem prefixo
for perigosa in (".barra", ".topo", ".marca"):
    ok(f'class="{perigosa[1:]}"' not in html,
       f"o cabeçalho voltou a usar {perigosa}, que as páginas já usam")
print("  .barra, .topo e .marca continuam sendo só das páginas")

# ── 2. o botão de menu mora NA BARRA, não mais no cabeçalho ────────────────
pos_nav = html.find('class="iar-nav"')
pos_fim_nav = html.find("</nav>", pos_nav)
pos_btn = html.find('id="btnMenu"')
ok(pos_nav < pos_btn < pos_fim_nav,
   "o botão de menu saiu da barra de baixo — você pediu que ele se mudasse "
   "para lá, junto dos outros seis ícones")
_qtd_btn_menu = html.count('id="btnMenu"')
ok(_qtd_btn_menu == 1, f"{_qtd_btn_menu} botões de menu no HTML — deveria haver um só")
print("  botão de menu: dentro da barra, uma cópia só")

# ── 3. o painel não pode ficar dentro de quem rola, e sobe — não desce ─────
pos_painel = html.find('id="iarPainel"')
ok(pos_painel > pos_fim_nav,
   "o painel está dentro da barra de baixo — um overflow ali pode voltar a "
   "recortá-lo")
ok(".iar-painel { position: fixed" in css,
   "painel deixou de ser fixed — volta a poder ser recortado por qualquer "
   "ancestral com overflow")
ok(".iar-painel-fundo { position: fixed" in css,
   "sumiu o fundo escurecido atrás do painel")
# "Emerge de baixo pra cima": ancorado por bottom, e não por top — e com uma
# transição, senão ele só pisca em vez de subir.
_bloco_painel = re.search(r"\.iar-painel \{(.*?)\.iar-painel a \{", css, re.S)
ok(_bloco_painel is not None, "não achei o bloco de regras do .iar-painel")
if _bloco_painel:
    regra = _bloco_painel.group(1)
    ok("bottom:" in regra, "o painel voltou a subir por 'top' — você pediu que ele "
       "emergisse da barra de baixo para cima")
    ok("top:" not in regra.replace("top: 0", ""),
       "sobrou uma âncora de topo no painel, e ele deveria vir só de baixo")
    ok("transition:" in regra, "o painel perdeu a transição — sem ela não dá pra "
       "ver ele emergindo, só pisca")
print("  painel fora da barra, fixo, ancorado embaixo e com transição de subida")

# ── 4. a marca voltou a ser o nome ─────────────────────────────────────────
ok(">IARABÃO<" in html, "a marca não voltou a ser o nome inteiro")
ok("iar-marca" in html, "a marca perdeu a classe prefixada")
print("  marca: IARABÃO")

# ── 5. o voltar só fora da tela inicial ─────────────────────────────────────
ok("history.back()" not in ns["_header"]("/"), "voltar aparece na tela inicial")
ok("history.back()" in ns["_header"]("/mercado"), "voltar sumiu das outras telas")
print("  voltar: fora da home, presente nas demais")

# ── 6. a barra tem seis rotas fixas, Início no meio, na ordem pedida ───────
# esquerda: Agendamentos, Clipes, Fim de jogo — centro: Início — direita:
# Notícias do Mercado, Lesões. O menu (sétimo ícone) não está em _NAV_BOTTOM
# porque não é uma rota — é montado à parte, mas sempre depois das seis.
ok(len(ns["_NAV_BOTTOM"]) == 6,
   f"a barra tem {len(ns['_NAV_BOTTOM'])} rotas, e são seis mais o menu")
rotas_barra = [p[0] for p in ns["_NAV_BOTTOM"]]
ok(rotas_barra == ["/posts", "/clipes", "/fim-de-jogo", "/",
                    "/mercado/noticias", "/lesoes"],
   f"a ordem da barra mudou: {rotas_barra}")
ok(rotas_barra[3] == "/", "o Início saiu do centro da barra")
print("  barra: 6 rotas na ordem pedida, Início no meio")

# ── 7. o Início é o item especial — maior, sempre com a cor de marca ───────
ok(re.search(r'class="iar-icon[^"]*iar-home', html),
   "o Início perdeu a classe que o deixa maior e elevado sobre a barra")
ok(html.count('<div class="iar-lacuna">') == 1,
   "sumiu (ou dobrou) a lacuna que reserva o espaço do Início na barra")
print("  Início: classe especial e lacuna reservando o espaço dele")

# ── 8. o espaço ao redor do Início é maior que o dos outros ícones ────────
# Você pediu para espaçar mais os botões ao lado do centro — a lacuna
# reservada para o Início precisa ficar mais larga que um ícone comum,
# senão os vizinhos encostam no círculo elevado.
_m_icone = re.search(r"\.iar-icon \{ width: (\d+)px", css)
_m_lacuna = re.search(r"\.iar-lacuna \{ width: (\d+)px", css)
ok(_m_icone and _m_lacuna, "não achei a largura do ícone comum ou da lacuna")
if _m_icone and _m_lacuna:
    ok(int(_m_lacuna.group(1)) > int(_m_icone.group(1)),
       "a lacuna do Início não é mais larga que um ícone comum — sem folga "
       "extra dos dois lados do botão central")
print("  lacuna do Início mais larga que um ícone comum — mais respiro ao redor dele")

# ── 9. Lesões saiu do painel e entrou na barra; não fica duplicada ────────
rotas_painel = [p[0] for p in ns["_NAV_MAIS"]]
ok("/lesoes" not in rotas_painel,
   "Lesões continua no painel — deveria ter entrado na barra")
ok(not (set(rotas_painel) & set(rotas_barra)),
   f"rota duplicada entre barra e painel: {set(rotas_painel) & set(rotas_barra)}")
for rota in ("/noticias", "/mercado", "/aspas", "/janela", "/elencos",
             "/arbitragem", "/previa", "/numeros", "/descartadas", "/lixeira",
             "/analise", "/fontes"):
    ok(rota in rotas_painel, f"{rota} sumiu do painel — e não está na barra")
print(f"  painel: {len(rotas_painel)} rotas, Lesões migrou para a barra")

# ── 10. o ativo é único — na barra OU no painel, nunca nos dois ───────────
for rota in ("/", "/clipes", "/posts", "/fim-de-jogo", "/mercado/noticias", "/lesoes"):
    h = ns["_header"](rota)
    ativos_barra = len(re.findall(r'class="iar-icon[^"]*\bativo\b', h))
    ok(ativos_barra == 1, f"{rota}: {ativos_barra} ícones ativos na barra")

for rota in ("/noticias", "/mercado", "/aspas", "/janela"):
    h = ns["_header"](rota)
    ok(h.count('aria-current="page"') == 1,
       f"{rota}: deveria marcar exatamente uma opção do painel como atual")
    ok(re.search(r'class="iar-icon ativo" id="btnMenu"', h),
       f"{rota}: o botão de menu deveria acender — a tela aberta está "
       "escondida no painel")
print("  exatamente um destino marcado como atual em cada tela")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
