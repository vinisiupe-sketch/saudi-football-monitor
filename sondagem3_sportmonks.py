"""
Sondagem 3 — fecha as duas pontas soltas.

    A) O Al-Diriyah existe na Sportmonks? Desta vez SEM busca por nome:
       listo todos os times da temporada corrente da Pro League. Se ele subiu
       para a elite em 2026/27, tem que estar aí. Se não estiver, é buraco de
       cobertura — e aí é grave.

    B) Transferências: na sondagem 2 eu errei o caminho do endpoint de
       intervalo de datas (422) e concluí meio no escuro. Aqui testo várias
       formas antes de dar veredito.

    C) De brinde: taxa de foto/altura/camisa em TODOS os clubes da liga, não
       só em dois. É o número que vale para decidir sobre o campinho.

Dois cliques em sondagem3_sportmonks.bat
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.sportmonks.com/v3/football"
PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem3_RELATORIO.txt")
BRUTO = os.path.join(PASTA, "sondagem3_BRUTO.json")
PAUSA = 0.3

linhas: list[str] = []
amostras: dict = {}


def diz(t: str = "") -> None:
    print(t)
    linhas.append(t)


def token() -> str:
    t = os.environ.get("SPORTMONKS_TOKEN", "").strip()
    if t:
        return t
    c = os.path.join(PASTA, "sportmonks_token.txt")
    if os.path.exists(c):
        return open(c, encoding="utf-8").read().strip()
    print("Não achei sportmonks_token.txt")
    sys.exit(1)


TOKEN = token()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def pega(caminho: str, **params):
    params["api_token"] = TOKEN
    url = f"{BASE}/{caminho}?" + urllib.parse.urlencode(params)
    seguro = url.replace(TOKEN, "<TOKEN>")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        time.sleep(PAUSA)
        return d, None
    except urllib.error.HTTPError as e:
        c = ""
        try:
            c = e.read().decode()[:220]
        except Exception:
            pass
        return None, f"HTTP {e.code} :: {c}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def util(v) -> bool:
    if v in (None, "", 0, "None", [], " "):
        return False
    return not (isinstance(v, str) and "placeholder" in v.lower())


diz("=" * 78)
diz("SONDAGEM 3 — " + datetime.now().strftime("%d/%m/%Y %H:%M"))
diz("=" * 78)

# ══ A) Todos os times da Pro League, sem depender de nome ════════════════
diz()
diz("A) TIMES DA PRO LEAGUE NA TEMPORADA CORRENTE (busca por ID, não por nome)")
diz("-" * 78)
d, e = pega("leagues/944", include="currentSeason")
temp = ((d or {}).get("data") or {})
season = temp.get("currentseason") or temp.get("currentSeason") or {}
sid = season.get("id")
diz(f"    liga 944 = {temp.get('name')}   temporada corrente = {sid} ({season.get('name')})")
if e:
    diz(f"    FALHOU: {e}")

times = []
if sid:
    d, e = pega(f"teams/seasons/{sid}", per_page="100")
    times = (d or {}).get("data", []) or []
    diz(f"    {len(times)} times na temporada")
    diz()
    for t in sorted(times, key=lambda x: x.get("name") or ""):
        diz(f"      [{t.get('id'):>7}] {t.get('name')}")
    amostras["times_pro_league"] = [{"id": t.get("id"), "name": t.get("name")} for t in times]

    diz()
    achou_dir = [t for t in times
                 if "dir" in (t.get("name") or "").lower()
                 or "dar" in (t.get("name") or "").lower()]
    if achou_dir:
        diz(f"    AL-DIRIYAH: encontrado -> {[(t.get('id'), t.get('name')) for t in achou_dir]}")
    else:
        diz("    AL-DIRIYAH: NÃO está entre os times da temporada corrente.")
        diz("    Como você confirmou que ele subiu para a elite em 2026/27,")
        diz("    isso é buraco de cobertura da Sportmonks, não erro de grafia.")
else:
    diz("    não consegui a temporada corrente")

# ══ C) Taxa de preenchimento em TODOS os clubes ══════════════════════════
diz()
diz("C) ELENCO — TAXA DE PREENCHIMENTO EM TODOS OS CLUBES DA LIGA")
diz("-" * 78)
diz(f"    {'clube':26} {'jog':>4} {'foto':>7} {'altura':>7} {'camisa':>7}")
diz("    " + "-" * 60)
tot_j = tot_f = tot_a = tot_c = 0
por_clube = []
for t in sorted(times, key=lambda x: x.get("name") or ""):
    d, e = pega(f"squads/teams/{t.get('id')}", include="player")
    el = (d or {}).get("data", []) or []
    if not el:
        diz(f"    {str(t.get('name'))[:26]:26} {'—':>4}  (sem elenco{': ' + e[:30] if e else ''})")
        continue
    jog = [x.get("player") or {} for x in el]
    nf = sum(1 for j in jog if util(j.get("image_path")))
    na = sum(1 for j in jog if util(j.get("height")))
    nc = sum(1 for x in el if util(x.get("jersey_number")))
    n = len(el)
    tot_j += n; tot_f += nf; tot_a += na; tot_c += nc
    por_clube.append({"clube": t.get("name"), "n": n, "foto": nf, "altura": na, "camisa": nc})
    diz(f"    {str(t.get('name'))[:26]:26} {n:>4} {100*nf//n:>6}% {100*na//n:>6}% {100*nc//n:>6}%")

if tot_j:
    diz("    " + "-" * 60)
    diz(f"    {'TOTAL DA LIGA':26} {tot_j:>4} {100*tot_f//tot_j:>6}% "
        f"{100*tot_a//tot_j:>6}% {100*tot_c//tot_j:>6}%")
amostras["por_clube"] = por_clube

# ══ B) Transferências: testar de verdade ═════════════════════════════════
diz()
diz("B) TRANSFERÊNCIAS — testando as formas possíveis")
diz("-" * 78)
hoje = datetime.now(timezone.utc).date()
d30 = (hoje - timedelta(days=30)).isoformat()
d90 = (hoje - timedelta(days=90)).isoformat()

tentativas = [
    ("intervalo 90d, sem include", f"transfers/between/{d90}/{hoje}", {}),
    ("intervalo 30d, sem include", f"transfers/between/{d30}/{hoje}", {}),
    ("intervalo 90d, com include", f"transfers/between/{d90}/{hoje}",
     {"include": "player;fromteam;toteam;type"}),
    ("por data (outro formato)", f"transfers/between/{d90.replace('-','')}/{hoje.isoformat().replace('-','')}", {}),
]
achou_intervalo = None
for rot, caminho, extra in tentativas:
    d, e = pega(caminho, per_page="100", **extra)
    n = len((d or {}).get("data") or [])
    diz(f"    {rot:30} -> {'OK, ' + str(n) + ' registros' if not e else e[:70]}")
    if not e and n:
        achou_intervalo = (caminho, d)
        break

# por time: é assim que a guia Janela seria montada
diz()
diz("    POR TIME (é assim que a guia Janela seria montada):")
tr_liga = []
for t in sorted(times, key=lambda x: x.get("name") or "")[:6]:
    d, e = pega(f"transfers/teams/{t.get('id')}",
                include="player;type", per_page="100")
    tr = (d or {}).get("data", []) or []
    recentes = [x for x in tr if (x.get("date") or "") >= d90]
    com_valor = sum(1 for x in recentes if util(x.get("amount")))
    diz(f"      {str(t.get('name'))[:24]:24} {len(tr):>3} no total, "
        f"{len(recentes):>2} nos últimos 90d, {com_valor} com valor"
        + (f"   ({e[:40]})" if e else ""))
    tr_liga.extend(recentes)

diz()
if tr_liga:
    diz(f"    {len(tr_liga)} transferências recentes nesses clubes. Exemplos:")
    for x in tr_liga[:10]:
        p = (x.get("player") or {}).get("display_name") or x.get("player_id")
        tp = (x.get("type") or {}).get("name") or x.get("type_id")
        diz(f"      {str(x.get('date')):12} {str(p)[:26]:26} {str(tp)[:14]:14} "
            f"valor={x.get('amount')}")
    com_valor = sum(1 for x in tr_liga if util(x.get("amount")))
    diz()
    diz(f"    COM VALOR DA NEGOCIAÇÃO: {com_valor} de {len(tr_liga)}")
else:
    diz("    nenhuma transferência recente encontrada por time")
amostras["transferencias_liga"] = tr_liga[:30]

diz()
diz("=" * 78)
with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
with open(BRUTO, "w", encoding="utf-8") as f:
    json.dump(amostras, f, ensure_ascii=False, indent=2)
print()
print(f"Relatório: {RELATORIO}")
input("Enter para fechar...")
