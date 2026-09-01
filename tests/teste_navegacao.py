"""
A navegação: o topo, a barra de baixo e o painel suspenso.

O DESENHO QUE ISTO VIGIA
    Você pediu cinco paradas fixas embaixo — Notícias do Mercado, Fim de
    jogo, Início no centro e elevado, Agendamentos, Clipes — no estilo de
    pílula flutuante que você mandou em referência. Tudo o mais foi para um
    painel em grade suspenso no alto, aberto por um ícone de menu no
    cabeçalho: o "More" do Fotmob que você também mandou.

Estes testes existem porque duas coisas já quebraram de verdade, antes desta
mudança, e continuam valendo:

  1. A pílula de baixo virava "uma bolha esquisita" nas telas de Posts e
     Elencos. Causa: eu chamei a barra de ".barra", e essas páginas já tinham
     uma ".barra" delas. O CSS da página carrega depois do do cabeçalho e
     vencia. Tudo do cabeçalho leva prefixo "iar-", e este teste garante que
     nenhuma classe minha colide com classe de página.

  2. O botão que abre a lista de mais opções "não funcionava". Funcionava: o
     menu abria e ficava recortado, porque um ancestral tinha overflow —
     overflow cria contexto de recorte. Agora o painel é fixed (não more
     absolute) e vive fora de qualquer coisa que role, dentro ou fora da
     barra.
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

# ── 2. o painel não pode ficar dentro de quem rola ─────────────────────────
pos_nav = html.find('class="iar-nav"')
pos_fim_nav = html.find("</nav>", pos_nav)
pos_painel = html.find('id="iarPainel"')
ok(pos_painel > pos_fim_nav,
   "o painel está dentro da barra de baixo — um overflow ali pode voltar a "
   "recortá-lo")
ok(".iar-painel { position: fixed" in css,
   "painel deixou de ser fixed — volta a poder ser recortado por qualquer "
   "ancestral com overflow")
ok(".iar-painel-fundo { position: fixed" in css,
   "sumiu o fundo escurecido atrás do painel")
print("  painel fora da barra e em posição fixa, com fundo próprio")

# ── 3. o botão existe e o script encontra as três peças ────────────────────
ok('id="btnMenu"' in html, "sem botão de menu no cabeçalho")
ok('id="iarPainel"' in html, "sem painel")
ok('id="iarPainelFundo"' in html, "sem fundo do painel")
ok("getElementById('btnMenu')" in html and "getElementById('iarPainel')" in html
   and "getElementById('iarPainelFundo')" in html,
   "o script não acha o botão, o painel ou o fundo")
# O botão de menu mora no CABEÇALHO agora, e não mais dentro da pílula de
# baixo — a barra ficou só com as cinco paradas fixas. Conto as ocorrências:
# uma cópia extra dentro da barra passaria batido se eu olhasse só a
# primeira ocorrência, que continuaria sendo a do cabeçalho.
_qtd_btn_menu = html.count('id="btnMenu"')
ok(_qtd_btn_menu == 1,
   f"{_qtd_btn_menu} botões de menu no HTML — deveria haver um só")
ok(pos_fim_nav > 0 and html.find('id="btnMenu"') < pos_nav,
   "o botão de menu foi parar dentro da barra de baixo — deveria estar no "
   "cabeçalho, de onde o painel abre suspenso no alto")
print("  botão no cabeçalho, painel e fundo presentes, script encontra os três")

# ── 4. a marca voltou a ser o nome ─────────────────────────────────────────
ok(">IARABÃO<" in html, "a marca não voltou a ser o nome inteiro")
ok("iar-marca" in html, "a marca perdeu a classe prefixada")
print("  marca: IARABÃO")

# ── 5. o voltar só fora da tela inicial ─────────────────────────────────────
ok("history.back()" not in ns["_header"]("/"), "voltar aparece na tela inicial")
ok("history.back()" in ns["_header"]("/mercado"), "voltar sumiu das outras telas")
print("  voltar: fora da home, presente nas demais")

# ── 6. a barra de baixo tem exatamente cinco paradas, Início no meio ───────
# A ordem que você deu foi: Início, Notícias do Mercado, Fim de jogo,
# Agendamento e Clipes. Início no centro deixa dois de cada lado — os dois
# que vieram antes dele na sua frase à esquerda, os dois de depois à direita.
ok(len(ns["_NAV_BOTTOM"]) == 5,
   f"a barra tem {len(ns['_NAV_BOTTOM'])} paradas, e você pediu cinco")
rotas_barra = [p[0] for p in ns["_NAV_BOTTOM"]]
ok(rotas_barra == ["/mercado/noticias", "/fim-de-jogo", "/", "/posts", "/clipes"],
   f"a ordem da barra mudou: {rotas_barra}")
ok(rotas_barra[2] == "/", "o Início saiu do centro da barra")
print("  barra: 5 paradas, Início no meio")

# ── 7. o Início é o item especial — maior, sempre com a cor de marca ───────
ok('iar-icon iar-home' in html or 'iar-home iar-icon' in html
   or re.search(r'class="iar-icon[^"]*iar-home', html),
   "o Início perdeu a classe que o deixa maior e elevado sobre a barra")
ok(html.count('<div class="iar-lacuna">') == 1,
   "sumiu (ou dobrou) a lacuna que reserva o espaço do Início na barra")
print("  Início: classe especial e lacuna reservando o espaço dele")

# ── 8. cada rota do painel está lá, e nenhuma repete a da barra ───────────
rotas_painel = [p[0] for p in ns["_NAV_MAIS"]]
ok(not (set(rotas_painel) & set(rotas_barra)),
   f"rota duplicada entre barra e painel: {set(rotas_painel) & set(rotas_barra)}")
for rota in ("/noticias", "/mercado", "/aspas", "/lesoes", "/janela", "/elencos",
             "/arbitragem", "/previa", "/numeros", "/descartadas", "/lixeira",
             "/analise", "/fontes"):
    ok(rota in rotas_painel, f"{rota} sumiu do painel — e não está na barra")
print(f"  painel: {len(rotas_painel)} rotas, nenhuma repetida da barra")

# ── 9. o ativo é único — na barra OU no painel, nunca nos dois ────────────
for rota in ("/", "/clipes", "/posts", "/fim-de-jogo", "/mercado/noticias"):
    h = ns["_header"](rota)
    ativos_barra = len(re.findall(r'class="iar-icon[^"]*\bativo\b', h))
    ok(ativos_barra == 1, f"{rota}: {ativos_barra} ícones ativos na barra")

for rota in ("/noticias", "/mercado", "/aspas", "/lesoes"):
    h = ns["_header"](rota)
    ok(h.count('aria-current="page"') == 1,
       f"{rota}: deveria marcar exatamente uma opção do painel como atual")
    ok('class="iar-btn ativo" id="btnMenu"' in h,
       f"{rota}: o botão de menu deveria acender — a tela aberta está "
       "escondida no painel")
print("  exatamente um destino marcado como atual em cada tela")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
