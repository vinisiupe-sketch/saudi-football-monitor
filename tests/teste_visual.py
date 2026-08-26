import sys, ast, re
falhas=[]
def ok(c,m):
    if not c: falhas.append(m)
src = open("main.py", encoding="utf-8").read()
mod = ast.parse(src)

ns = {}
corpo = [n for n in mod.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
         and (n.targets[0].id.startswith("_ICO_") or n.targets[0].id in
              {"_NAV_PRINCIPAIS","_NAV_EXTRAS","_THEME_VARS_CSS","_HEADER_CSS","PALETA"})]
exec(compile(ast.Module(body=corpo, type_ignores=[]), "main.py","exec"), ns)

# ── a paleta ───────────────────────────────────────────────────────────────
css = ns["_THEME_VARS_CSS"]
for cor, onde in (("#08080E","fundo escuro"), ("#B6FF00","acento"),
                  ("#FFBE5D","alerta"), ("#FD5D5D","negativo")):
    ok(cor in css, f"{onde} ({cor}) nao esta nas variaveis")
ok("--c-acento:" in css and "--c-acento-texto:" in css, "faltou o par acento/texto")
ok(css.count(":root") == 2, "deveria haver claro e escuro")
print("   paleta: 4 cores, tema claro e escuro, acento com cor de texto propria")

# nenhuma cor da paleta antiga pode ter sobrado
antigas = ["#22c55e","#16a34a","#ef4444","#fb7185","#eab308","#f59e0b",
           "#0ea5e9","#3b82f6","#edeae4","#16161a"]
sobrou = [c for c in antigas if re.search(c, src, re.I)]
ok(not sobrou, f"cor antiga ainda no arquivo: {sobrou}")
ok(len(re.findall("#1d9bf0", src, re.I)) > 0, "o azul do X sumiu — ele e marca, nao tema")
print("   cores antigas: nenhuma | azul do X preservado")

# ── o topo ─────────────────────────────────────────────────────────────────
h = ns["_HEADER_CSS"]
ok(".topo {" in h, "faltou o estilo do topo")
ok(".marca {" in h, "faltou a marca")
ok(">IA<" in src, "a marca nao virou IA")
ok("IARABÃO</a>" not in src, "o nome inteiro ainda esta no cabecalho")
ok("_ICO_VOLTAR" in src, "faltou o icone de voltar")
ok('active == "/"' in src, "o voltar aparece na tela inicial, onde ele mente")
ok('href="/config"' in src and "topo-btn" in src, "config nao esta no topo")
print("   topo: IA no meio, voltar a esquerda (fora da home), config a direita")

# ── a barra de baixo ───────────────────────────────────────────────────────
ok(".barra { position: fixed" in h, "a barra nao e flutuante")
ok("bottom: max(12px, env(safe-area-inset-bottom))" in h,
   "sem safe-area o iPhone corta a barra na barrinha de gestos")
ok("overflow-x: auto" in h, "oito icones num celular estreito precisam rolar")
ok("padding-bottom: 84px" in h, "o ultimo item da pagina fica debaixo da barra")
ok(".nav-menu { position: absolute; bottom:" in h, "o menu abre para baixo, fora da tela")
ok("flex: 0 0 42px" in h, "os icones vao espremer em vez de rolar")
print("   barra: fixa embaixo, rola no estreito, respeita a area segura do iPhone")

# ── a navegacao ────────────────────────────────────────────────────────────
ok(not any(p[0] == "/config" for p in ns["_NAV_EXTRAS"]), "config duplicado no menu")
ok(len(ns["_NAV_PRINCIPAIS"]) == 8, f"{len(ns['_NAV_PRINCIPAIS'])} itens na barra")
ok("color-mix(in srgb,{c}" not in src and "color-mix(in srgb,{color}" not in src,
   "sobrou a cor POR GUIA do menu, que briga com a paleta")
print(f"   navegacao: {len(ns['_NAV_PRINCIPAIS'])} na barra, {len(ns['_NAV_EXTRAS'])} no menu")

print()
print("FALHAS:", len(falhas))
for f in falhas: print("  -", f)
sys.exit(1 if falhas else 0)
