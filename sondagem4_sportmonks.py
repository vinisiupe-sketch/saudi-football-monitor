"""
Sondagem 4 — as quatro checagens que faltam.

    A) ASSISTÊNCIA numa partida da PRO LEAGUE (não de copa). A hipótese é que
       a Copa do Rei tenha cobertura rasa e a liga venha completa.
    B) LIVESCORE com jogo rolando: duas fotos com 70s de intervalo.
    C) ELENCO CORRETO — o caso Bahebri. Procuro jogador repetido em mais de um
       clube e olho onde cada "Bahebri" está.
    D) TRANSFERÊNCIAS x a sua guia Janela (dados do Transfermarkt).
       Precisa da URL do app: crie um arquivo  app_url.txt  nesta pasta com
       o endereço do Railway (ex: https://seu-app.up.railway.app).
       Sem esse arquivo, a seção D é pulada.

Dois cliques em sondagem4_sportmonks.bat
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.sportmonks.com/v3/football"
PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem4_RELATORIO.txt")
BRUTO = os.path.join(PASTA, "sondagem4_BRUTO.json")
LIGA_PRO = 944
PAUSA = 0.3

linhas: list[str] = []
amostras: dict = {}


def diz(t: str = "") -> None:
    print(t)
    linhas.append(t)


def arquivo(nome: str) -> str:
    c = os.path.join(PASTA, nome)
    return open(c, encoding="utf-8").read().strip() if os.path.exists(c) else ""


TOKEN = os.environ.get("SPORTMONKS_TOKEN", "").strip() or arquivo("sportmonks_token.txt")
if not TOKEN:
    print("Não achei sportmonks_token.txt")
    sys.exit(1)
APP_URL = arquivo("app_url.txt").rstrip("/")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def http(url: str, seguro: str = ""):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode())
        time.sleep(PAUSA)
        return d, None
    except urllib.error.HTTPError as e:
        c = ""
        try:
            c = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"HTTP {e.code} :: {c}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def pega(caminho: str, **params):
    params["api_token"] = TOKEN
    url = f"{BASE}/{caminho}?" + urllib.parse.urlencode(params)
    return http(url, url.replace(TOKEN, "<TOKEN>"))


def simples(s: str) -> str:
    """Normaliza nome árabe transliterado para comparar TM x Sportmonks.

    Sem isso, "Al-Khaibari" e "Alkhaibari" pareceriam pessoas diferentes e eu
    inflaria a divergência entre as duas fontes — justamente o erro que esta
    sondagem existe para medir. Testei os pares reais antes de usar.
    """
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z ]", " ", s)
    partes = []
    for p in s.split():
        if p in ("al", "el", "bin", "ibn", "abu", "abd"):
            continue
        # prefixo colado: alkhaibari -> khaibari, eldawsari -> dawsari
        p = re.sub(r"^(al|el)(?=[a-z]{4,})", "", p)
        # transliterações que variam entre as fontes
        p = p.replace("ay", "ai").replace("ey", "ei").replace("ou", "u")
        p = p.replace("kh", "k").replace("dh", "d").replace("gh", "g")
        p = re.sub(r"(.)\1+", r"\1", p)          # duplicadas: hh -> h
        partes.append(p)
    return " ".join(partes)


def sobrenome(s: str) -> str:
    p = simples(s).split()
    return p[-1] if p else ""


def parecido(a: str, b: str) -> bool:
    """Casa por sobrenome ou por semelhança alta. A comparação exata sozinha
    não serve: 'Bulaihi' e 'Bulayhi' são a mesma pessoa em fontes diferentes."""
    if not a or not b:
        return False
    if a == b:
        return True
    sa, sb = sobrenome(a), sobrenome(b)
    if sa and sa == sb:
        return True
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.86


diz("=" * 78)
diz("SONDAGEM 4 — " + datetime.now().strftime("%d/%m/%Y %H:%M"))
diz("=" * 78)

# ══ A) Assistências numa partida da PRO LEAGUE ═══════════════════════════
diz()
diz("A) ASSISTÊNCIAS EM PARTIDAS DA PRO LEAGUE (e não de copa)")
diz("-" * 78)
hoje = datetime.now(timezone.utc).date()
jogos_pro = []
for i in range(0, 16):
    dia = (hoje - timedelta(days=i)).isoformat()
    d, e = pega(f"fixtures/date/{dia}", include="participants;league", per_page="100")
    for f in (d or {}).get("data", []) or []:
        if f.get("league_id") == LIGA_PRO:
            jogos_pro.append(f)
    if len(jogos_pro) >= 5:
        break
diz(f"    {len(jogos_pro)} partida(s) da Pro League nos últimos dias")

tot_gols = tot_assist = 0
for f in jogos_pro[:5]:
    nomes = " x ".join(p.get("name", "") for p in (f.get("participants") or []))
    d, e = pega(f"fixtures/{f.get('id')}",
                include="events.type;events.player;events.relatedPlayer;state")
    if e:
        diz(f"    [{f.get('id')}] {nomes}: FALHOU {e[:50]}")
        continue
    ff = d.get("data") or {}
    estado = (ff.get("state") or {}).get("name")
    ev = ff.get("events") or []
    gols = [x for x in ev if "goal" in ((x.get("type") or {}).get("name") or "").lower()
            and "own" not in ((x.get("type") or {}).get("name") or "").lower()]
    com_a = [g for g in gols if g.get("related_player_name")
             or (g.get("relatedplayer") or {}).get("display_name")]
    tot_gols += len(gols)
    tot_assist += len(com_a)
    tipos = sorted({(x.get("type") or {}).get("name") for x in ev})
    diz(f"    [{f.get('id')}] {nomes[:38]:38} {estado[:12]:12} "
        f"{len(ev):>3} eventos, {len(gols)} gols, {len(com_a)} com assistência")
    diz(f"        tipos de evento: {', '.join(t for t in tipos if t)[:100]}")
    for g in gols:
        a = g.get("related_player_name") or (g.get("relatedplayer") or {}).get("display_name")
        diz(f"          {str(g.get('minute')):>3}' {str(g.get('player_name'))[:26]:26} assist={a or '—'}")
    amostras.setdefault("jogos_pro", []).append({"id": f.get("id"), "nomes": nomes,
                                                 "eventos": len(ev), "gols": len(gols),
                                                 "assist": len(com_a)})
diz()
diz(f"    TOTAL: {tot_assist} assistências em {tot_gols} gols da Pro League")
if tot_gols:
    diz(f"    ({100*tot_assist//tot_gols}% dos gols têm assistência identificada)")

# ══ C) Elenco correto — o caso Bahebri ═══════════════════════════════════
diz()
diz("C) ELENCO CORRETO — jogador no clube certo? (o caso Bahebri)")
diz("-" * 78)
d, e = pega("leagues/944", include="currentSeason")
season = ((d or {}).get("data") or {})
sid = (season.get("currentseason") or season.get("currentSeason") or {}).get("id")
d, e = pega(f"teams/seasons/{sid}", per_page="100")
times = (d or {}).get("data", []) or []

onde: dict[int, list] = {}
nomes_por_id: dict[int, str] = {}
for t in times:
    d, e = pega(f"squads/teams/{t.get('id')}", include="player")
    for x in (d or {}).get("data", []) or []:
        p = x.get("player") or {}
        pid = p.get("id")
        if not pid:
            continue
        onde.setdefault(pid, []).append(t.get("name"))
        nomes_por_id[pid] = p.get("display_name") or p.get("name") or "?"

diz(f"    {len(onde)} jogadores distintos em {len(times)} elencos")
repetidos = {k: v for k, v in onde.items() if len(v) > 1}
diz(f"    jogadores em MAIS DE UM elenco: {len(repetidos)}")
for pid, clubes in list(repetidos.items())[:15]:
    diz(f"      {nomes_por_id[pid][:30]:30} -> {', '.join(clubes)}")
if not repetidos:
    diz("      nenhum. (na API-Football isso acontecia e bagunçava o campinho)")

diz()
diz("    Procurando 'Bahebri':")
achou = [(pid, nomes_por_id[pid], onde[pid]) for pid in onde
         if "bahebri" in simples(nomes_por_id[pid])]
if achou:
    for pid, nome, clubes in achou:
        diz(f"      [{pid}] {nome} -> {', '.join(clubes)}")
else:
    diz("      não achei ninguém com 'Bahebri' nos elencos da liga.")
    d, e = pega("players/search/Bahebri", include="teams.team")
    for p in (d or {}).get("data", []) or []:
        eq = [(x.get("team") or {}).get("name") for x in (p.get("teams") or [])]
        diz(f"      busca direta: [{p.get('id')}] {p.get('display_name')} -> {eq}")
amostras["repetidos"] = {str(k): v for k, v in list(repetidos.items())[:30]}

# ══ D) Transferências x guia Janela (Transfermarkt) ══════════════════════
diz()
diz("D) TRANSFERÊNCIAS: SPORTMONKS x A SUA GUIA JANELA (Transfermarkt)")
diz("-" * 78)

# Casar clube pela última palavra não funciona: "Al-Ahli Jeddah" viraria
# "jeddah" e "NEOM SC" viraria "sc". Uso a lista fechada dos 18 clubes da liga
# com as variantes que cada fonte usa, e procuro qual delas aparece no nome.
CLUBES = {
    "hilal":   ["hilal"],
    "nassr":   ["nassr", "nasr"],
    "ahli":    ["ahli"],
    "ittihad": ["ittihad", "itihad"],
    "shabab":  ["shabab"],
    "fateh":   ["fateh"],
    "taawoun": ["taawoun", "taawon", "tawun", "tawon"],
    "khaleej": ["khaleej", "kalej", "khalij"],
    "kholood": ["kholood", "kolud", "khulood"],
    "hazm":    ["hazm", "hazem"],
    "fayha":   ["fayha", "faiha"],
    "faisaly": ["faisaly", "faisali", "faysaly"],
    "riyadh":  ["riyadh", "riad"],
    "qadsiah": ["qadsiah", "qadisiyah", "qadisiya"],
    "abha":    ["abha"],
    "neom":    ["neom"],
    "ettifaq": ["ettifaq", "etifaq"],
    "diriyah": ["diriyah", "draih", "diraiyah", "draiyah"],
}
_VARIANTES = [(v, k) for k, vs in CLUBES.items() for v in vs]


def clube_chave(nome: str) -> str:
    """Devolve o clube canônico, ou '' se for time de fora da liga."""
    s = simples(nome).replace(" ", "")
    for variante, canonico in _VARIANTES:
        if simples(variante).replace(" ", "") in s:
            return canonico
    return ""


if not APP_URL:
    diz("    PULADO — crie app_url.txt nesta pasta com a URL do seu app.")
else:
    d, e = http(f"{APP_URL}/api/af-window-transfers")
    tm = []
    if isinstance(d, dict):
        tm = d.get("transfers") or d.get("data") or d.get("rows") or []
    elif isinstance(d, list):
        tm = d
    if e or not tm:
        diz(f"    não consegui ler a janela do app: {e or 'resposta vazia'}")
        if isinstance(d, dict):
            diz(f"    (chaves recebidas: {list(d)[:8]})")
    else:
        diz(f"    guia Janela (TM): {len(tm)} movimentações")
        diz(f"    campos: {sorted(tm[0])[:12]}")

        # ── Sportmonks: movimentações dos últimos 90 dias, por clube ──────
        d90 = (hoje - timedelta(days=90)).isoformat()
        sm_por_clube: dict[str, list] = {}
        for t in times:
            dd, ee = pega(f"transfers/teams/{t.get('id')}", include="player",
                          per_page="100")
            recentes = [x for x in ((dd or {}).get("data") or [])
                        if (x.get("date") or "") >= d90]
            sm_por_clube[clube_chave(t.get("name") or "")] = recentes

        # ── TM: movimentações por clube ──────────────────────────────────
        tm_por_clube: dict[str, list] = {}
        for r in tm:
            for campo in ("team_in_name", "team_out_name"):
                nome = r.get(campo)
                if not nome and isinstance(r.get(campo.replace("_name", "")), dict):
                    nome = r[campo.replace("_name", "")].get("name")
                k = clube_chave(nome) if nome else ""
                if k:
                    tm_por_clube.setdefault(k, []).append(r)

        # ── Tabela comparativa ───────────────────────────────────────────
        diz()
        diz("    MOVIMENTAÇÕES POR CLUBE (é a comparação que não depende de nome)")
        diz(f"    {'clube':22} {'TM':>5} {'SM':>5} {'dif':>6}")
        diz("    " + "-" * 42)
        chaves = sorted(set(sm_por_clube) | (set(tm_por_clube) & set(sm_por_clube)))
        somaT = somaS = 0
        for k in chaves:
            nt, ns = len(tm_por_clube.get(k, [])), len(sm_por_clube.get(k, []))
            somaT += nt
            somaS += ns
            sinal = "" if nt == ns else ("+" if ns > nt else "")
            diz(f"    {k[:22]:22} {nt:>5} {ns:>5} {sinal}{ns-nt:>5}")
        diz("    " + "-" * 42)
        diz(f"    {'TOTAL':22} {somaT:>5} {somaS:>5} {somaS-somaT:>+6}")

        orfas = sorted(set(tm_por_clube) - set(sm_por_clube))
        if orfas:
            diz()
            diz(f"    clubes do TM que não casaram com nenhum da Sportmonks: {orfas}")
            diz("    (pode ser clube de fora da liga, que aparece como origem/destino)")

        # ── Cruzamento por nome de jogador ───────────────────────────────
        sm_todos = [x for v in sm_por_clube.values() for x in v]
        nomes_tm = sorted({simples(r.get("player_name") or "") for r in tm} - {""})
        nomes_sm = sorted({simples((x.get("player") or {}).get("display_name") or "")
                           for x in sm_todos} - {""})
        so_tm = [a for a in nomes_tm if not any(parecido(a, b) for b in nomes_sm)]
        so_sm = [b for b in nomes_sm if not any(parecido(a, b) for a in nomes_tm)]
        nos_dois = [a for a in nomes_tm if any(parecido(a, b) for b in nomes_sm)]
        diz()
        diz("    CRUZAMENTO POR JOGADOR")
        diz(f"      nos dois:         {len(nos_dois)}")
        diz(f"      só no TM:         {len(so_tm)}")
        diz(f"      só na Sportmonks: {len(so_sm)}")
        if nomes_tm:
            diz(f"      cobertura do TM pela Sportmonks: {100*len(nos_dois)//len(nomes_tm)}%")
        diz()
        diz("    SÓ NO TM (o que você perderia):")
        for n in so_tm[:30]:
            diz(f"      {n}")
        diz()
        diz("    SÓ NA SPORTMONKS (o que o TM não pegou):")
        for n in so_sm[:30]:
            diz(f"      {n}")
        amostras["cruzamento"] = {
            "tm_total": len(tm), "sm_total": len(sm_todos),
            "so_tm": so_tm[:80], "so_sm": so_sm[:80], "nos_dois": len(nos_dois),
            "por_clube": {k: [len(tm_por_clube.get(k, [])), len(sm_por_clube.get(k, []))]
                          for k in chaves}}

# ══ B) Livescore ═════════════════════════════════════════════════════════
diz()
diz("B) LIVESCORE — com jogo rolando")
diz("-" * 78)
d, e = pega("livescores/inplay", include="participants;scores;periods;state")
ao_vivo = (d or {}).get("data", []) or []
if not ao_vivo:
    diz(f"    nenhum jogo ao vivo agora{'  (' + e[:40] + ')' if e else ''}")
    diz("    rode de novo durante uma partida para medir isto")
else:
    def foto(lst):
        r = {}
        for f in lst:
            per = [p for p in (f.get("periods") or []) if p.get("ticking")]
            r[f.get("id")] = {
                "n": " x ".join(p.get("name", "") for p in (f.get("participants") or [])),
                "min": per[0].get("minutes") if per else None,
                "seg": per[0].get("seconds") if per else None,
                "g": [(s.get("score") or {}).get("goals") for s in (f.get("scores") or [])
                      if s.get("description") == "CURRENT"],
                "e": (f.get("state") or {}).get("name")}
        return r
    a = foto(ao_vivo)
    for k, v in a.items():
        diz(f"      [{k}] {v['n']}  {v['e']}  {v['min']}'{v['seg'] or 0:02}s  gols={v['g']}")
    diz("    esperando 70s...")
    time.sleep(70)
    d2, _ = pega("livescores/inplay", include="participants;scores;periods;state")
    b = foto((d2 or {}).get("data", []) or [])
    diz()
    for k, v in a.items():
        w = b.get(k)
        if not w:
            diz(f"      [{k}] {v['n']}: saiu da lista")
            continue
        andou = (v["min"], v["seg"]) != (w["min"], w["seg"])
        diz(f"      [{k}] {v['n'][:32]:32} {v['min']}'{v['seg'] or 0:02} -> "
            f"{w['min']}'{w['seg'] or 0:02}  {'ANDOU' if andou else 'PARADO'}"
            f"{'  PLACAR MUDOU' if v['g'] != w['g'] else ''}")
    amostras["livescore"] = {"antes": a, "depois": b}

diz()
diz("=" * 78)
with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
with open(BRUTO, "w", encoding="utf-8") as f:
    json.dump(amostras, f, ensure_ascii=False, indent=2)
print()
print(f"Relatório: {RELATORIO}")
input("Enter para fechar...")
