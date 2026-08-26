"""
As conferências que valem para o app inteiro, independentes de tela.

Cada uma nasceu de um defeito real deste projeto:

  1. nome usado antes de existir  — um `import` esquecido derrubou o app
     inteiro no deploy, e o py_compile passou porque decorador só é avaliado
     na importação.
  2. import de main que não existe — o agendador importava uma constante que
     eu tinha apagado; import preguiçoso não quebra a compilação e a falha ia
     aparecer de madrugada, num print vermelho que ninguém lê.
  3. JS das páginas — um bloco de script quebrado deixa a tela em branco sem
     erro nenhum no servidor.
  4. marcadores de substituição — um __MARCADOR__ que ninguém troca vai para
     o navegador como texto literal.
"""
import ast
import builtins
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _nomes_do_modulo(mod):
    nomes = set()
    for n in mod.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            nomes.add(n.targets[0].id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            nomes.add(n.target.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nomes.add(n.name)
    return nomes


def conferir_ordem(caminho):
    """Nenhum nome de módulo pode ser usado antes de existir."""
    mod = ast.parse(open(caminho, encoding="utf-8").read())
    definidos = set(dir(builtins)) | {"__name__", "__file__", "__doc__"}
    problemas = []

    class Usa(ast.NodeVisitor):
        def __init__(self):
            self.nomes = []

        def visit_Name(self, n):
            if isinstance(n.ctx, ast.Load):
                self.nomes.append(n.id)

        def visit_Lambda(self, n):
            for a in n.args.args + n.args.kwonlyargs:
                definidos.add(a.arg)
            self.generic_visit(n)

        def _compreensao(self, n):
            for g in n.generators:
                for nn in ast.walk(g.target):
                    if isinstance(nn, ast.Name):
                        definidos.add(nn.id)
            self.generic_visit(n)

        visit_ListComp = visit_SetComp = _compreensao
        visit_GeneratorExp = visit_DictComp = _compreensao

    for n in mod.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                definidos.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                u = Usa()
                u.visit(d)
                problemas += [f"decorador de {n.name}: {x}"
                              for x in u.nomes if x not in definidos]
            definidos.add(n.name)
        elif isinstance(n, ast.Assign):
            u = Usa()
            u.visit(n.value)
            problemas += [f"{ast.unparse(n.targets[0])[:30]}: {x}"
                          for x in u.nomes if x not in definidos]
            for t in n.targets:
                for nn in ast.walk(t):
                    if isinstance(nn, ast.Name):
                        definidos.add(nn.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            definidos.add(n.target.id)
    return problemas


os.chdir(RAIZ)
ARQUIVOS = ["main.py", "database.py", "scheduler.py", "gravador.py",
            "ajustes.py", "glossary.py", "fim_sportmonks.py", "x_client.py"]

# ── 1. tudo compila ────────────────────────────────────────────────────────
for a in ARQUIVOS:
    r = subprocess.run([sys.executable, "-m", "py_compile", a],
                       capture_output=True, text=True)
    ok(r.returncode == 0, f"{a} não compila: {r.stderr[:200]}")
print(f"  {len(ARQUIVOS)} arquivos compilam")

# ── 2. ordem dos nomes ─────────────────────────────────────────────────────
for a in ("main.py", "database.py", "gravador.py"):
    p = conferir_ordem(a)
    ok(not p, f"{a}: nome usado antes de existir: {p[:4]}")
print("  nenhum nome usado antes de existir")

# ── 3. o que os outros importam de main tem que existir ────────────────────
principal = _nomes_do_modulo(ast.parse(open("main.py", encoding="utf-8").read()))
fantasmas = []
for arq in ("scheduler.py", "injury_processor.py", "processor.py", "collector.py"):
    if not os.path.exists(arq):
        continue
    for n in ast.walk(ast.parse(open(arq, encoding="utf-8").read())):
        if isinstance(n, ast.ImportFrom) and n.module == "main":
            fantasmas += [f"{arq}: {a.name}" for a in n.names
                          if a.name not in principal]
ok(not fantasmas, f"importam de main o que main não tem: {fantasmas}")
print("  imports de main: todos existem")

# ── 4. o JS de cada página ─────────────────────────────────────────────────
mod = ast.parse(open("main.py", encoding="utf-8").read())
textos = {}
for n in mod.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        try:
            textos[n.targets[0].id] = ast.literal_eval(n.value)
        except Exception:
            pass
blocos = [k for k in textos if k.endswith("_JS")]
tem_node = subprocess.run(["node", "--version"], capture_output=True).returncode == 0
if tem_node:
    for nome in blocos:
        js = textos[nome].replace("__PASSO_AJUSTE__", "8")
        with open("/tmp/_conf.js", "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run(["node", "--check", "/tmp/_conf.js"],
                           capture_output=True, text=True)
        ok(r.returncode == 0, f"{nome} não é JS válido: {r.stderr[:200]}")
    print(f"  {len(blocos)} blocos de JS válidos")
else:
    print("  (node ausente — não conferi o JS)")

# ── 5. nenhum marcador sem troca ───────────────────────────────────────────
fonte = open("main.py", encoding="utf-8").read()
import re
marcadores = set(re.findall(r"__[A-Z_]{3,}__", fonte))
sem_troca = [m for m in marcadores
             if fonte.count(m) < 2 or f'"{m}"' not in fonte]
ok(not sem_troca, f"marcador que ninguém troca: {sem_troca}")
print(f"  {len(marcadores)} marcadores, todos com troca")

# ── 6. rotas ───────────────────────────────────────────────────────────────
rotas = sum(1 for n in ast.walk(mod)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            for d in n.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name) and d.func.value.id == "app")
ok(rotas > 100, f"só {rotas} rotas — algo sumiu")
print(f"  {rotas} rotas registradas")

# ── 7. a versão do gravador tem que bater com a que o app espera ───────────
v_grav = re.search(r'^VERSAO = "(.+?)"', open("gravador.py", encoding="utf-8").read(),
                   re.M)
v_app = re.search(r'VERSAO_GRAVADOR = "(.+?)"', fonte)
ok(v_grav and v_app and v_grav.group(1) == v_app.group(1),
   f"versão do gravador ({v_grav and v_grav.group(1)}) != esperada pelo app "
   f"({v_app and v_app.group(1)}) — a tela vai acusar desatualizado para sempre")
print(f"  versão do gravador: {v_grav.group(1)} dos dois lados")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
