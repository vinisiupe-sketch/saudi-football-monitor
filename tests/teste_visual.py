"""
A paleta e as guias.

O que é do topo, da barra de baixo e do menu mora em teste_navegacao.py —
separei quando aquilo virou assunto grande o bastante para ter arquivo próprio.
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

ns = {}
quero = {"_NAV_BOTTOM", "_NAV_MAIS", "_THEME_VARS_CSS", "PALETA"}
corpo = [n for n in mod.body if isinstance(n, ast.Assign)
         and isinstance(n.targets[0], ast.Name)
         and (n.targets[0].id.startswith("_ICO_") or n.targets[0].id in quero)]
exec(compile(ast.Module(body=corpo, type_ignores=[]), "main.py", "exec"), ns)

textos = {}
for n in mod.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        try:
            textos[n.targets[0].id] = ast.literal_eval(n.value)
        except Exception:
            pass

# ── a paleta ───────────────────────────────────────────────────────────────
css = ns["_THEME_VARS_CSS"]
for cor, papel in (("#08080E", "fundo"), ("#B6FF00", "acento"),
                   ("#FFBE5D", "alerta"), ("#FD5D5D", "negativo")):
    ok(cor in css, f"{papel} ({cor}) não está nas variáveis")
ok("--c-acento:" in css and "--c-acento-texto:" in css,
   "o acento precisa vir com a cor de texto que fica legível em cima dele")
ok(css.count(":root") == 2, "deveria haver tema claro e escuro")
print("  paleta: 4 cores, claro e escuro, acento com cor de texto própria")

antigas = ["#22c55e", "#16a34a", "#ef4444", "#fb7185", "#eab308",
           "#f59e0b", "#0ea5e9", "#3b82f6", "#edeae4", "#16161a"]
sobrou = [c for c in antigas if re.search(c, src, re.I)]
ok(not sobrou, f"cor da paleta antiga ainda no arquivo: {sobrou}")

# O azul do X é marca, não tema: ele diz para onde o post vai.
ok(re.search("#1d9bf0", src, re.I), "o azul do X sumiu")
print("  cores antigas: nenhuma | azul do X preservado de propósito")

# nenhuma página pode ter acento próprio brigando com o do tema
locais = re.findall(r"--accent:\s*(#[0-9a-fA-F]{3,8})", src)
ok(not locais, f"página com acento próprio: {locais}")
print("  nenhuma página com acento próprio")

# ── as guias ───────────────────────────────────────────────────────────────
# Notícias, Mercado e Aspas existem — mas moraram para o painel suspenso
# quando a barra de baixo virou cinco paradas fixas. Só Notícias do Mercado
# (a lista crua, e não o guia de negociações) ficou na barra.
for rota, rotulo in (("/noticias", "Notícias"), ("/mercado", "Mercado"),
                     ("/aspas", "Aspas")):
    ok(any(p[0] == rota for p in ns["_NAV_MAIS"]), f"{rotulo} não está no painel")
    ok(not any(p[0] == rota for p in ns["_NAV_BOTTOM"]),
       f"{rotulo} está na barra de baixo — a barra é só as cinco paradas fixas")
    ok(f'@app.get("{rota}"' in src, f"a rota {rota} não existe")
ok(src.count("async def _pagina_de_noticias") == 1, "a página de notícias duplicou")
print("  guias: Notícias, Mercado e Aspas no painel suspenso")

# A barra é sempre cinco: Início no meio, dois de cada lado. Ela não rola
# mais — se crescer, a lógica do Início centralizado (a lacuna, o
# position:absolute) deixa de fazer sentido, e é hora de repensar o desenho,
# não só de tirar este teste do caminho.
ok(len(ns["_NAV_BOTTOM"]) == 5,
   f"{len(ns['_NAV_BOTTOM'])} itens na barra — o desenho de pílula com "
   "Início elevado no meio pressupõe exatamente cinco")
print(f"  {len(ns['_NAV_BOTTOM'])} na barra, {len(ns['_NAV_MAIS'])} no painel suspenso")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
