"""
Sondagem do LIVESCORE — precisa de jogo rolando.

Tira 8 amostras de 20 em 20 segundos (pouco menos de 3 minutos) e mostra:
  - se o relógio da partida anda, e se anda no ritmo certo
  - se o placar muda
  - quanto tempo o dado leva para mudar entre uma amostra e outra

Não toca em nada do app.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://api.sportmonks.com/v3/football"
PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem_livescore_RELATORIO.txt")
AMOSTRAS = 8
INTERVALO = 20

linhas = []


def diz(t=""):
    print(t, flush=True)
    linhas.append(t)


c = os.path.join(PASTA, "sportmonks_token.txt")
TOKEN = os.environ.get("SPORTMONKS_TOKEN", "").strip() or (
    open(c, encoding="utf-8").read().strip() if os.path.exists(c) else "")
if not TOKEN:
    print("Não achei sportmonks_token.txt")
    sys.exit(1)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def pega(caminho, **params):
    params["api_token"] = TOKEN
    url = f"{BASE}/{caminho}?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": UA})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
        return d, None, time.time() - t0
    except urllib.error.HTTPError as e:
        corpo = ""
        try:
            corpo = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"HTTP {e.code} :: {corpo}", 0
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", 0


def ler(f):
    per = [p for p in (f.get("periods") or []) if p.get("ticking")]
    gols = {}
    for s in (f.get("scores") or []):
        if s.get("description") == "CURRENT":
            sc = s.get("score") or {}
            gols[sc.get("participant")] = sc.get("goals")
    return {
        "nomes": " x ".join(p.get("name", "") for p in (f.get("participants") or [])),
        "min": per[0].get("minutes") if per else None,
        "seg": per[0].get("seconds") if per else None,
        "estado": (f.get("state") or {}).get("short_name")
                  or (f.get("state") or {}).get("name"),
        "gols": gols,
        "eventos": len(f.get("events") or []),
    }


diz("=" * 76)
diz("SONDAGEM LIVESCORE — " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
diz("=" * 76)

INC = "participants;scores;periods;state;events"
d, e, _ = pega("livescores/inplay", include=INC)
jogos = (d or {}).get("data", []) or []
if not jogos:
    diz(f"    nenhum jogo ao vivo agora{'  (' + str(e) + ')' if e else ''}")
    diz("    (a assinatura só cobre as 5 ligas sauditas/AFC)")
else:
    diz(f"    {len(jogos)} jogo(s) ao vivo:")
    for f in jogos:
        v = ler(f)
        diz(f"      [{f.get('id')}] {v['nomes']}  {v['estado']}  {v['min']}'  {v['gols']}")

    diz()
    diz(f"    {AMOSTRAS} amostras de {INTERVALO} em {INTERVALO}s "
        f"(~{AMOSTRAS*INTERVALO//60}min{AMOSTRAS*INTERVALO%60:02d}s)")
    diz()
    hist = {}
    for i in range(AMOSTRAS):
        d, e, lat = pega("livescores/inplay", include=INC)
        agora = datetime.now().strftime("%H:%M:%S")
        if e:
            diz(f"    [{agora}] FALHOU: {e[:60]}")
        else:
            for f in (d or {}).get("data", []) or []:
                v = ler(f)
                v["quando"] = agora
                v["lat"] = lat
                hist.setdefault(f.get("id"), []).append(v)
                diz(f"    [{agora}] {v['nomes'][:30]:30} {str(v['estado'])[:6]:6} "
                    f"{str(v['min']):>3}'{(v['seg'] or 0):02}s  gols={v['gols']}  "
                    f"ev={v['eventos']}  resposta={lat:.2f}s")
        if i < AMOSTRAS - 1:
            time.sleep(INTERVALO)

    diz()
    diz("    ANÁLISE")
    diz("    " + "-" * 68)
    for fid, série in hist.items():
        diz(f"    [{fid}] {série[0]['nomes']}")
        # o relógio andou o quanto deveria?
        mudancas = 0
        segundos_reportados = []
        for a, b in zip(série, série[1:]):
            if (a["min"], a["seg"]) != (b["min"], b["seg"]):
                mudancas += 1
            if a["min"] is not None and b["min"] is not None:
                dm = (b["min"] - a["min"]) * 60 + ((b["seg"] or 0) - (a["seg"] or 0))
                segundos_reportados.append(dm)
        diz(f"      o relógio mudou em {mudancas} de {len(série)-1} intervalos")
        if segundos_reportados:
            media = sum(segundos_reportados) / len(segundos_reportados)
            diz(f"      avanço médio por intervalo: {media:.0f}s "
                f"(o real foi {INTERVALO}s)")
            diz(f"      avanços observados: {segundos_reportados}")
            if abs(media - INTERVALO) <= 6:
                diz("      -> relógio no ritmo certo")
            elif media == 0:
                diz("      -> relógio PARADO (dado congelado)")
            else:
                diz("      -> relógio fora de ritmo (pode ser intervalo/parada)")
        tem_seg = sum(1 for v in série if v["seg"] is not None)
        diz(f"      precisão de segundos: {tem_seg}/{len(série)} amostras")
        gols = [v["gols"] for v in série]
        diz(f"      placar mudou durante a medição: "
            f"{'SIM' if any(a != b for a, b in zip(gols, gols[1:])) else 'não'}")
        evs = [v["eventos"] for v in série]
        diz(f"      eventos: {evs[0]} -> {evs[-1]}")
        lats = [v["lat"] for v in série]
        diz(f"      tempo de resposta da API: min {min(lats):.2f}s "
            f"média {sum(lats)/len(lats):.2f}s máx {max(lats):.2f}s")

diz()
diz("=" * 76)
with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
print()
print(f"Relatório: {RELATORIO}")
input("Enter para fechar...")
