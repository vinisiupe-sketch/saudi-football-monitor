"""
A navegação: o topo, a barra de baixo e o menu de reticências.

Estes testes existem porque duas coisas quebraram de verdade:

  1. A pílula de baixo virava "uma bolha esquisita" nas telas de Posts e
     Elencos. Causa: eu chamei a barra de ".barra", e essas páginas já tinham
     uma ".barra" delas. O CSS da página carrega depois do do cabeçalho e
     vencia. Agora tudo do cabeçalho leva prefixo "iar-", e este teste garante
     que nenhuma classe minha colida com classe de página.

  2. O botão de reticências "não funcionava". Funcionava: o menu abria e
     ficava recortado, porque o pai tinha overflow para rolar os ícones —
     overflow cria contexto de recorte. O menu saiu de dentro da barra.
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
quero = {"_NAV_PRINCIPAIS", "_NAV_EXTRAS", "_HEADER_CSS", "_THEME_VARS_CSS"}
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
_bloco = next(n for n in mod.body if isinstance(n, ast.Assign)
              and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id in ("_HEADER_CSS", "_THEME_VARS_CSS"))
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

# ── 2. o menu não pode ficar dentro de quem rola ───────────────────────────
pos_nav = html.find('class="iar-nav"')
pos_fim_nav = html.find("</nav>", pos_nav)
pos_menu = html.find('id="navMenu"')
ok(pos_menu > pos_fim_nav,
   "o menu está dentro da barra — o overflow da rolagem vai recortá-lo, "
   "e o botão vai parecer quebrado")
ok('class="iar-rolo"' in html, "a rolagem não está num miolo próprio")
ok("overflow-x: auto" in css, "os ícones não rolam — vão espremer no celular")
ok(".iar-menu { position: fixed" in css,
   "menu absoluto volta a poder ser recortado por qualquer ancestral")
print("  menu fora da área de rolagem e em posição fixa")

# ── 3. o botão existe e o script encontra os dois lados ────────────────────
ok('id="btnMais"' in html, "sem botão de reticências")
ok('id="navMenu"' in html, "sem menu")
ok("getElementById('btnMais')" in html and "getElementById('navMenu')" in html,
   "o script não acha o botão ou o menu")
print("  botão e menu presentes, e o script encontra os dois")

# ── 4. a marca voltou a ser o nome ─────────────────────────────────────────
ok(">IARABÃO<" in html, "a marca não voltou a ser o nome inteiro")
ok("iar-marca" in html, "a marca perdeu a classe prefixada")
print("  marca: IARABÃO")

# ── 5. o voltar só fora da tela inicial ────────────────────────────────────
ok("history.back()" not in ns["_header"]("/"), "voltar aparece na tela inicial")
ok("history.back()" in ns["_header"]("/mercado"), "voltar sumiu das outras telas")
print("  voltar: fora da home, presente nas demais")

# ── 6. o ativo é único ─────────────────────────────────────────────────────
for rota in ("/noticias", "/mercado", "/aspas", "/clipes"):
    h = ns["_header"](rota)
    ok(h.count("iar-icon ativo") == 1,
       f"{rota}: {h.count('iar-icon ativo')} ícones marcados como ativos")
print("  exatamente um ícone ativo em cada tela")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
