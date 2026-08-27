"""
A tela inicial de aprovação.

O que mais me importa aqui: que os números não mintam e que os botões não
sejam decorativos. Número inventado faz você confiar numa tela que não sabe
do que fala, e botão que não faz nada é pior que botão ausente.
"""
import ast
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(RAIZ)
falhas = []


def ok(c, m):
    if not c:
        falhas.append(m)


src = open("main.py", encoding="utf-8").read()
mod = ast.parse(src)
textos = {}
for n in mod.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        try:
            textos[n.targets[0].id] = ast.literal_eval(n.value)
        except Exception:
            pass

# ── as contagens ───────────────────────────────────────────────────────────
# A home só conta o que VOCÊ separou na guia (arrastar para a direita / ✓).
# Aqui: dois de mercado, mas só um separado; um de aspas separado; e um de
# mercado separado porém sem tradução, que não pode entrar.
SEPARADA = "publicado"
from datetime import datetime, timezone, timedelta
_agora = datetime.now(timezone.utc)
def _em(horas):
    return (_agora + timedelta(hours=horas)).isoformat()

# Cinco posts: dois pendentes no futuro, um pendente que já perdeu a hora, um
# publicado e um cancelado. Só os dois primeiros ainda pedem algo de você.
POSTS = [
    {"id": 1, "status": "pendente",  "agendado_para": _em(3),  "texto": "hoje mais tarde"},
    {"id": 2, "status": "pendente",  "agendado_para": _em(27), "texto": "amanha"},
    {"id": 3, "status": "pendente",  "agendado_para": _em(-2), "texto": "ja comecou"},
    {"id": 4, "status": "publicado", "agendado_para": _em(-30), "texto": "ja saiu"},
    {"id": 5, "status": "cancelado", "agendado_para": _em(5),  "texto": "cancelado"},
    {"id": 6, "status": "aprovado",  "agendado_para": _em(6),  "texto": "aprovado, sai sozinho"},
]
ns = {"listar_posts": lambda **k: POSTS,
      "clipes_recentes": lambda h: [{"estado": "pronto"}, {"estado": "erro"}],
      "MARCA_SEPARADA": SEPARADA,
      "get_all_flags": lambda: {"m1": SEPARADA, "e1": SEPARADA,
                                "m3": SEPARADA, "g1": SEPARADA},
      "get_recent_articles": lambda **k: [
          {"id": "m1", "category": "mercado", "title_pt": "a"},
          {"id": "m2", "category": "mercado", "title_pt": "nao separada"},
          {"id": "e1", "category": "entrevista", "title_pt": "b"},
          {"id": "e2", "category": "entrevista", "title_pt": "nao separada"},
          {"id": "g1", "category": "geral", "title_pt": "c"},
          {"id": "m3", "category": "mercado", "title_pt": None}]}
# _contar_para_aprovar e _log_de_entrada dependem de _posts_do_futuro, então
# as três vão juntas — testar a de cima sem a de baixo testaria outra coisa.
def pegar(*nomes):
    return [n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name in nomes]

FUTURO = pegar("_posts_do_futuro")
f = pegar("_contar_para_aprovar")[0]
ESTADOS = next(n for n in mod.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "ESTADOS_ABERTOS")
def rodar(corpo, espaco):
    exec(compile(ast.Module(body=[ESTADOS] + FUTURO + corpo, type_ignores=[]),
                 "main.py", "exec"), espaco)

rodar([f], ns)
n = ns["_contar_para_aprovar"]()
ok(n["posts"] == 2, f"posts pendentes e no futuro deveriam ser 2: {n['posts']}")

# O que a peneira tem que tirar, um por um — cada linha aqui é um jeito de o
# log voltar a encher com coisa resolvida.
rodar([], ns)
futuro = ns["_posts_do_futuro"]()
ids = sorted(p["id"] for p in futuro)
ok(ids == [1, 2, 6], f"deveriam sobrar os abertos e futuros, sobraram {ids}")
ok(all(p["status"] != "publicado" for p in futuro), "post publicado ficou na fila")
ok(all(p["status"] != "cancelado" for p in futuro), "post cancelado ficou na fila")
ok(all(p["id"] != 3 for p in futuro), "post cujo jogo já começou ficou na fila")
# Post sem horário não pode sumir: não sei quando é, mas alguém precisa ver.
ns_sem_data = dict(ns)
ns_sem_data["listar_posts"] = lambda **k: [
    {"id": 7, "status": "pendente", "agendado_para": None, "texto": "sem data"},
    {"id": 8, "status": "pendente", "agendado_para": "data torta", "texto": "torta"}]
rodar([], ns_sem_data)
ok(len(ns_sem_data["_posts_do_futuro"]()) == 2,
   "post com data ausente ou ilegível sumiu — melhor aparecer a mais")
ok(n["clipes"] == 1, f"clipes deveria contar só os prontos: {n['clipes']}")
ok(n["mercado"] == 1, f"mercado: separadas e traduzidas, deu {n['mercado']}")
ok(n["aspas"] == 1, f"aspas: {n['aspas']}")
print(f"  contagens: {n}")

# Sem NENHUMA separada, a home mostra zero — e zero aqui é verdade, não falha.
ns_vazio = dict(ns); ns_vazio["get_all_flags"] = lambda: {}
rodar([f], ns_vazio)
nv = ns_vazio["_contar_para_aprovar"]()
ok(nv["mercado"] == 0 and nv["aspas"] == 0,
   f"sem separar nada deveria dar zero: {nv}")

# Mas se a LEITURA das marcas falhar, tem que virar traço. Zero diria "você
# não separou nada", quando a verdade é "eu não consegui olhar".
def explode_flags():
    raise RuntimeError("banco fora")
ns_falha = dict(ns); ns_falha["get_all_flags"] = explode_flags
rodar([f], ns_falha)
nf = ns_falha["_contar_para_aprovar"]()
ok(nf["mercado"] is None and nf["aspas"] is None,
   f"falha ao ler as marcas virou número: {nf}")

# banco fora do ar não pode virar zero — zero faz você achar que não tem nada
def explode(*a, **k):
    raise RuntimeError("banco fora")
ns2 = dict(ns)
ns2.update({"listar_posts": explode, "clipes_recentes": explode,
            "get_recent_articles": explode})
rodar([f], ns2)
n2 = ns2["_contar_para_aprovar"]()
ok(all(v is None for v in n2.values()),
   f"falha virou número em vez de traço: {n2}")
print("  banco fora do ar: devolve traço, não zero")

# ── o log ──────────────────────────────────────────────────────────────────
g = next(x for x in mod.body if isinstance(x, ast.FunctionDef)
         and x.name == "_log_de_entrada")
ns3 = {"listar_posts": lambda **k: [
           {"id": 1, "texto": "post que ainda vem", "status": "pendente",
            "criado_em": "2026-08-01T10:00:00", "agendado_para": _em(2)},
           {"id": 4, "texto": "post ja publicado", "status": "publicado",
            "criado_em": "2026-08-26T23:00:00", "agendado_para": _em(-1)}],
       "clipes_recentes": lambda h: [
           {"id": 9, "texto": "gol", "atualizado_em": "2026-08-26T10:00:00",
            "estado": "pronto"}],
       "MARCA_SEPARADA": SEPARADA,
       "get_all_flags": lambda: {"x": SEPARADA, "y": SEPARADA},
       "arbitragem_do_dia": lambda d: [],
       "_dia_de_brasilia": lambda n=0: "2026-08-27",
       "get_recent_articles": lambda **k: [
           {"id": "x", "title_pt": "noticia nova", "category": "mercado",
            "collected_at": "2026-08-26T12:00:00"},
           {"id": "y", "title_pt": None, "category": "geral",
            "collected_at": "2026-08-26T13:00:00"},
           {"id": "z", "title_pt": "essa eu nao separei", "category": "mercado",
            "collected_at": "2026-08-26T23:00:00"}]}
rodar([g], ns3)
log = ns3["_log_de_entrada"]()
ok([i["tipo"] for i in log] == ["posts", "mercado", "clipes"],
   f"o log não está do mais novo para o mais velho: {[i['tipo'] for i in log]}")
ok(not any("publicado" in i["titulo"] for i in log),
   "post já publicado apareceu no log de aprovações")
ok(all(i.get("onde") for i in log), "item sem para onde ir ao tocar")
ok(not any(i["titulo"] == "None" for i in log), "artigo sem tradução entrou no log")
# A notícia mais NOVA das três é a que ele não separou. Se ela aparecer, é
# porque o filtro caiu — e o sintoma seria a home voltando a encher sozinha.
ok(not any("nao separei" in i["titulo"] for i in log),
   "notícia não separada entrou no log da home")
print(f"  log: {len(log)} itens, do mais novo para o mais velho")

# ── a decisão ──────────────────────────────────────────────────────────────
ok('if tipo != "posts":' in src,
   "a rota finge que aprova tipos que ela não sabe aprovar")
ok('"ainda não sei aprovar' in src, "não explica por que recusou")
ok('decisao not in ("sim", "nao")' in src, "aceita qualquer decisão")
js = textos["_HOME_JS"]
ok("i.tipo === 'posts' && i.estado === 'pendente'" in js,
   "mostra ✓ e ✗ em item que não tem decisão por trás")
print("  decisão: só onde existe de verdade, e diz quando não sabe")

# ── a tela ─────────────────────────────────────────────────────────────────
# node --check nao le de stdin; grava num arquivo.
import tempfile
_t = os.path.join(tempfile.gettempdir(), "_home_check.js")
with open(_t, "w", encoding="utf-8") as _f:
    _f.write(js.replace("__ICONES_JSON__", "{}"))
r = subprocess.run(["node", "--check", _t], capture_output=True, text=True)
ok(r.returncode == 0, "JS da home quebrou: " + r.stderr[:300])
ok("Salamaleikum" in textos["_HOME_HTML"], "faltou a saudação")
ok("__ICONES_JSON__" in js and '"__ICONES_JSON__"' in src,
   "os ícones não são injetados")
ok("'bloco ' + (v ? c.cor : 'quieto')" in js,
   "bloco sem nada esperando continua colorido — cor forte o tempo todo cega")
ok("grid-template-columns:repeat(2,1fr)" in textos["_HOME_CSS"],
   "no celular os quatro blocos vão espremer numa linha")
print("  tela: JS válido, saudação, blocos em 2 colunas no celular")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
