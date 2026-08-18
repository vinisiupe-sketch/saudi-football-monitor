"""
Diagnóstico: por que um gol não apareceu no alerta.

Olha os três lugares onde ele pode ter se perdido:
  1. a Sportmonks tem o gol?
  2. a API-Football tem o gol?
  3. o app carimbou? (bate no /api/gols/ao-vivo do Railway)

E mostra a CHAVE que cada lado gera, que é onde eu mais desconfio: se as duas
fontes geram chaves diferentes para o mesmo gol, ele aparece como "só uma
fonte"; se geram a MESMA chave para gols diferentes, o segundo é engolido pela
trava de duplicidade.

Dois cliques em diag_gols.bat
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
SAIDA = os.path.join(PASTA, "diag_gols_RELATORIO.txt")
LIGAS = {944: "Liga Saudita", 950: "Copa do Rei", 1557: "Supercopa",
         1085: "AFC Elite", 1088: "AFC Two"}
linhas = []


def diz(t=""):
    print(t, flush=True)
    linhas.append(t)


def arq(n):
    c = os.path.join(PASTA, n)
    return open(c, encoding="utf-8").read().strip() if os.path.exists(c) else ""


TOKEN = os.environ.get("SPORTMONKS_TOKEN", "").strip() or arq("sportmonks_token.txt")
APP = arq("app_url.txt").rstrip("/")
AF_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip() or arq("af_key.txt")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def http(url, headers=None):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        c = ""
        try:
            c = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"HTTP {e.code} :: {c}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def sm(caminho, **p):
    p["api_token"] = TOKEN
    return http(f"{BASE}/{caminho}?" + urllib.parse.urlencode(p))


diz("=" * 76)
diz("DIAGNÓSTICO DO ALERTA DE GOL — " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
diz("=" * 76)

# ── 1. Sportmonks: o que ela vê agora ────────────────────────────────────
diz()
diz("1) SPORTMONKS — jogos ao vivo e seus gols")
diz("-" * 76)
INC = ("participants;scores;state;periods;"
       "events.type;events.player;events.relatedPlayer")
d, e = sm("livescores/inplay", include=INC)
vivos = [f for f in ((d or {}).get("data") or []) if f.get("league_id") in LIGAS]
if e:
    diz(f"    FALHOU: {e}")
diz(f"    {len(vivos)} jogo(s) ao vivo nas nossas ligas")

chaves_sm = {}
for f in vivos:
    nomes = " x ".join(p.get("name", "") for p in (f.get("participants") or []))
    est = (f.get("state") or {}).get("short_name")
    gols = [ev for ev in (f.get("events") or [])
            if ev.get("type_id") in (14, 15, 16)]
    diz(f"    [{f.get('id')}] {nomes}  {est}  — {len(gols)} gol(s), "
        f"{len(f.get('events') or [])} eventos no total")
    for ev in sorted(gols, key=lambda x: (x.get("minute") or 0)):
        autor = ((ev.get("player") or {}).get("display_name")
                 or ev.get("player_name") or "?")
        ch = f"{ev.get('minute')}|{autor}|{ev.get('result') or ''}"
        chaves_sm[ch] = f.get("id")
        diz(f"        {str(ev.get('minute')):>3}' {autor[:24]:24} "
            f"tipo={ev.get('type_id')} result={ev.get('result')!r}")
        diz(f"             chave -> {ch!r}")
    # também procuro gol que a lista de eventos não traz mas o placar acusa
    gc = gf = 0
    for s in (f.get("scores") or []):
        if s.get("description") == "CURRENT":
            sc = s.get("score") or {}
            if sc.get("participant") == "home":
                gc = sc.get("goals") or 0
            else:
                gf = sc.get("goals") or 0
    if gc + gf != len(gols):
        diz(f"        >>> PLACAR DIZ {gc}x{gf} ({gc+gf} gols) MAS SÓ HÁ "
            f"{len(gols)} EVENTO(S) DE GOL")
        diz(f"        >>> o gol existe no placar e não na lista de eventos")

# ── 2. API-Football ──────────────────────────────────────────────────────
diz()
diz("2) API-FOOTBALL — os mesmos jogos")
diz("-" * 76)
if not AF_KEY:
    diz("    sem a chave da API-Football aqui (crie af_key.txt se quiser esta parte)")
else:
    hoje = datetime.now(timezone.utc).date().isoformat()
    for liga in (307, 504, 826, 17, 18):
        u = ("https://v3.football.api-sports.io/fixtures?"
             + urllib.parse.urlencode({"league": liga, "season": 2026, "date": hoje}))
        d, e = http(u, {"x-apisports-key": AF_KEY})
        for fx in ((d or {}).get("response") or []):
            st = ((fx.get("fixture") or {}).get("status") or {}).get("short")
            if st not in ("1H", "2H", "HT", "ET", "P", "BT", "FT"):
                continue
            fid = (fx.get("fixture") or {}).get("id")
            t = fx.get("teams") or {}
            nomes = f"{(t.get('home') or {}).get('name')} x {(t.get('away') or {}).get('name')}"
            g = fx.get("goals") or {}
            u2 = ("https://v3.football.api-sports.io/fixtures/events?"
                  + urllib.parse.urlencode({"fixture": fid, "type": "Goal"}))
            d2, e2 = http(u2, {"x-apisports-key": AF_KEY})
            evs = (d2 or {}).get("response") or []
            diz(f"    [{fid}] {nomes}  {st}  placar={g.get('home')}x{g.get('away')}  "
                f"{len(evs)} evento(s) de gol")
            gc = gf = 0
            for ev in evs:
                if (ev.get("detail") or "") == "Missed Penalty":
                    continue
                dono = (ev.get("team") or {}).get("id")
                casa = dono == (t.get("home") or {}).get("id")
                if (ev.get("detail") or "") == "Own Goal":
                    casa = not casa
                if casa:
                    gc += 1
                else:
                    gf += 1
                autor = (ev.get("player") or {}).get("name") or "?"
                minuto = (ev.get("time") or {}).get("elapsed")
                ch = f"{minuto}|{autor}|{gc}-{gf}"
                diz(f"        {str(minuto):>3}' {autor[:24]:24} "
                    f"detail={ev.get('detail')}")
                diz(f"             chave -> {ch!r}")
            if (g.get("home") or 0) + (g.get("away") or 0) != len([
                    x for x in evs if (x.get("detail") or "") != "Missed Penalty"]):
                diz(f"        >>> PLACAR E EVENTOS NÃO BATEM")

# ── 3. O que o app carimbou ──────────────────────────────────────────────
diz()
diz("3) O QUE O SEU APP JÁ CARIMBOU")
diz("-" * 76)
if not APP:
    diz("    sem app_url.txt")
else:
    d, e = http(f"{APP}/api/gols/ao-vivo?horas=8")
    if e:
        diz(f"    FALHOU: {e}")
    else:
        diz(f"    sportmonks_configurada: {d.get('sportmonks_configurada')}")
        gols = d.get("gols") or []
        diz(f"    {len(gols)} gol(s) carimbado(s)")
        for g in gols:
            a = "sim" if g.get("api_football") else "NÃO"
            s = "sim" if g.get("sportmonks") else "NÃO"
            diz(f"      {str(g.get('minuto')):>3}' {str(g.get('autor'))[:24]:24} "
                f"placar={g.get('placar')}  AF={a}  SM={s}  dif={g.get('diferenca_seg')}")

diz()
diz("=" * 76)
diz("ONDE OLHAR:")
diz("  - se o gol aparece na seção 1 ou 2 mas não na 3, o coletor não gravou")
diz("  - se as chaves dos dois lados são diferentes para o mesmo gol, ele")
diz("    aparece como 'só uma fonte' em vez de comparado")
diz("  - se o placar acusa mais gols que a lista de eventos, a fonte está")
diz("    devendo o evento e não há o que carimbar")
diz("=" * 76)

with open(SAIDA, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
print()
print(f"Relatório: {SAIDA}")
input("Enter para fechar...")
