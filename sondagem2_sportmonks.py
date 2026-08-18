"""
Sondagem 2 da Sportmonks — as quatro perguntas que sobraram.

    A) Al-Diriyah e Al-Kholood: o elenco vem tão preenchido quanto o do Hilal?
       (foram justamente os dois que deram trabalho nas outras fontes)
    B) Transferências DESTA JANELA: dá para montar a guia Janela como hoje,
       ou só dá para consultar jogador por jogador?
    C) FIM DE JOGO do Qadsiah x Taee de hoje: a API-Football ficou devendo os
       gols e as assistências. A Sportmonks traz?
    D) Livescore: o quanto ele está atualizado de verdade.

Mesma receita da sondagem 1: só biblioteca padrão, token lido de arquivo,
token nunca impresso, nada do app é tocado.

    Dois cliques em  sondagem2_sportmonks.bat
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
BASE_CORE = "https://api.sportmonks.com/v3/core"
PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem2_RELATORIO.txt")
BRUTO = os.path.join(PASTA, "sondagem2_BRUTO.json")
PAUSA = 0.35

linhas: list[str] = []
amostras: dict = {}


def diz(txt: str = "") -> None:
    print(txt)
    linhas.append(txt)


def token() -> str:
    t = os.environ.get("SPORTMONKS_TOKEN", "").strip()
    if t:
        return t
    caminho = os.path.join(PASTA, "sportmonks_token.txt")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return f.read().strip()
    print("Não achei o token (sportmonks_token.txt).")
    sys.exit(1)


TOKEN = token()
AGENTES = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "curl/8.5.0",
]
_agente_bom = None


def pega(caminho: str, base: str = "", **params):
    global _agente_bom
    params["api_token"] = TOKEN
    url = f"{base or BASE}/{caminho}?" + urllib.parse.urlencode(params)
    seguro = url.replace(TOKEN, "<TOKEN>")
    for ua in ([_agente_bom] if _agente_bom else AGENTES):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json", "User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = json.loads(r.read().decode())
            _agente_bom = ua
            time.sleep(PAUSA)
            return dados, None
        except urllib.error.HTTPError as e:
            corpo = ""
            try:
                corpo = e.read().decode()[:250]
            except Exception:
                pass
            if e.code == 403 and "1010" in corpo:
                continue
            return None, f"HTTP {e.code} :: {corpo}"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
    return None, "bloqueado pelo Cloudflare em todos os agentes"


def util(v) -> bool:
    """Valor que serve. placeholder.png NÃO serve (erro que cometi na 1a rodada)."""
    if v in (None, "", 0, "None", [], " "):
        return False
    return not (isinstance(v, str) and "placeholder" in v.lower())


def taxa(campo: str, itens: list, rotulo: str = "") -> None:
    tem = sum(1 for i in itens if isinstance(i, dict) and util(i.get(campo)))
    total = len(itens)
    pct = (100 * tem // total) if total else 0
    diz(f"    {(rotulo or campo):22} {tem:3}/{total:<3} {pct:3}%  "
        + "#" * (pct // 5) + "." * (20 - pct // 5))


def primeiro_que_responde(candidatos: list[tuple[str, dict]]):
    """Tenta caminhos alternativos e devolve (caminho, dado). A documentação
    deles não mostra a URL literal de vários endpoints, então descobrir vale
    mais do que chutar um e concluir errado que 'não existe'."""
    for caminho, params in candidatos:
        d, e = pega(caminho, **params)
        if not e and d.get("data"):
            return caminho, d
        diz(f"      (nada em /{caminho}{'  → ' + e[:60] if e else ''})")
    return None, None


diz("=" * 74)
diz("SONDAGEM 2 SPORTMONKS — " + datetime.now().strftime("%d/%m/%Y %H:%M"))
diz("=" * 74)

# ══ A) Al-Diriyah e Al-Kholood ═══════════════════════════════════════════
diz()
diz("A) ELENCO DE AL-DIRIYAH E AL-KHOLOOD")
diz("-" * 74)
for alvo in ("Diriyah", "Kholood"):
    diz()
    diz(f"  >>> {alvo}")
    d, e = pega(f"teams/search/{alvo}")
    achados = (d or {}).get("data", []) or []
    if not achados:
        diz(f"    time não encontrado na busca{'  ' + e if e else ''}")
        continue
    for t in achados[:5]:
        diz(f"      [{t.get('id')}] {t.get('name')}  escudo="
            f"{'sim' if util(t.get('image_path')) else 'NÃO'}")
    tid = achados[0].get("id")
    d, e = pega(f"squads/teams/{tid}", include="player;position;detailedPosition")
    elenco = (d or {}).get("data", []) or []
    if not elenco:
        diz(f"    SEM ELENCO{'  ' + e if e else ''}")
        continue
    jog = [x.get("player") or {} for x in elenco]
    diz(f"    {len(elenco)} jogadores")
    taxa("image_path", jog, "foto do rosto")
    taxa("height", jog, "altura")
    taxa("date_of_birth", jog, "nascimento")
    taxa("nationality_id", jog, "nacionalidade")
    taxa("jersey_number", elenco, "camisa")
    taxa("position_id", elenco, "posição")
    # pé preferido numa amostra de 5
    com_pe = 0
    olhados = 0
    for x in sorted(elenco, key=lambda z: (z.get("jersey_number") or 99))[:5]:
        pid = (x.get("player") or {}).get("id")
        if not pid:
            continue
        olhados += 1
        dd, ee = pega(f"players/{pid}", include="metadata")
        for m in ((dd or {}).get("data") or {}).get("metadata", []) or []:
            v = m.get("values", m.get("value"))
            if isinstance(v, str) and v.strip():
                com_pe += 1
                break
    diz(f"    pé preferido           {com_pe}/{olhados} da amostra")
    amostras.setdefault("elencos", {})[alvo] = {"time_id": tid, "n": len(elenco)}

# ══ B) Transferências desta janela ═══════════════════════════════════════
diz()
diz("B) TRANSFERÊNCIAS DESTA JANELA (dá para montar a guia Janela?)")
diz("-" * 74)
hoje = datetime.now(timezone.utc).date()
ini = (hoje - timedelta(days=75)).isoformat()
fim = hoje.isoformat()
diz(f"    período testado: {ini} a {fim}")
caminho, d = primeiro_que_responde([
    (f"transfers/between/{ini}/{fim}", {"include": "player;fromTeam;toTeam;type",
                                        "per_page": "100"}),
    (f"transfers/latest", {"include": "player;fromTeam;toTeam;type", "per_page": "100"}),
    (f"transfers", {"include": "player;fromTeam;toTeam;type", "per_page": "100"}),
])
if not caminho:
    diz("    NENHUM endpoint de transferências em lote respondeu.")
    diz("    Isso significaria montar a Janela jogador a jogador — inviável.")
else:
    tr = d.get("data", [])
    diz(f"    endpoint: /{caminho}  →  {len(tr)} transferência(s)")
    pag = d.get("pagination") or {}
    diz(f"    paginação: total={pag.get('total')} por_página={pag.get('per_page')} "
        f"tem_mais={pag.get('has_more')}")
    diz()
    diz("    primeiras 12:")
    for t in tr[:12]:
        p = (t.get("player") or {}).get("display_name") or t.get("player_id")
        de = (t.get("fromTeam") or {}).get("name") or "?"
        para = (t.get("toTeam") or {}).get("name") or "?"
        tipo = (t.get("type") or {}).get("name") or t.get("type_id")
        diz(f"      {str(t.get('date')):12} {str(p)[:22]:22} {str(de)[:16]:16} -> "
            f"{str(para)[:16]:16} {str(tipo)[:12]:12} valor={t.get('amount')}")
    diz()
    diz(f"    campos de uma transferência: {sorted(tr[0].keys()) if tr else '-'}")
    com_valor = sum(1 for t in tr if util(t.get("amount")))
    diz(f"    com valor da negociação: {com_valor}/{len(tr)}")
    amostras["transferencias"] = tr[:20]

# ══ C) FIM DE JOGO: Qadsiah x Taee ═══════════════════════════════════════
diz()
diz("C) FIM DE JOGO — QADSIAH x TAEE (gols e assistências)")
diz("-" * 74)
alvo_fix = None
for dia in (hoje.isoformat(), (hoje - timedelta(days=1)).isoformat()):
    d, e = pega(f"fixtures/date/{dia}", include="participants", per_page="100")
    jogos = (d or {}).get("data", []) or []
    diz(f"    {dia}: {len(jogos)} jogo(s) na sua assinatura")
    for f in jogos:
        nomes = [p.get("name", "") for p in (f.get("participants") or [])]
        junto = " ".join(nomes).lower()
        if "qadsiah" in junto or ("taee" in junto or "ta'ee" in junto):
            diz(f"      ACHEI: [{f.get('id')}] {' x '.join(nomes)}  ({f.get('starting_at')})")
            alvo_fix = f.get("id")
    if alvo_fix:
        break

if not alvo_fix:
    diz("    não achei o jogo. Listando os jogos de hoje para conferência:")
    d, e = pega(f"fixtures/date/{hoje.isoformat()}", include="participants", per_page="100")
    for f in ((d or {}).get("data") or [])[:20]:
        nomes = [p.get("name", "") for p in (f.get("participants") or [])]
        diz(f"      [{f.get('id')}] {' x '.join(nomes)}")
else:
    d, e = pega(f"fixtures/{alvo_fix}",
                include="participants;scores;events.type;events.player;"
                        "events.relatedPlayer;statistics.type;state")
    if e:
        diz(f"    FALHOU: {e}")
    else:
        f = d.get("data") or {}
        estado = (f.get("state") or {}).get("name")
        diz(f"    estado: {estado}")
        placares = [(s.get("description"), (s.get("score") or {}).get("participant"),
                     (s.get("score") or {}).get("goals")) for s in (f.get("scores") or [])]
        diz(f"    placares: {placares}")
        ev = f.get("events") or []
        diz(f"    {len(ev)} evento(s) no total")
        gols = [x for x in ev if "goal" in ((x.get("type") or {}).get("name") or "").lower()]
        diz(f"    {len(gols)} evento(s) de gol:")
        com_assist = 0
        for g in gols:
            autor = (g.get("player") or {}).get("display_name") or g.get("player_name")
            assist = (g.get("relatedPlayer") or {}).get("display_name") or g.get("related_player_name")
            tipo = (g.get("type") or {}).get("name")
            if assist:
                com_assist += 1
            diz(f"      {str(g.get('minute')):>3}'  {str(autor)[:26]:26} "
                f"assist={assist or '—'}   [{tipo}]")
        diz()
        diz(f"    GOLS COM ASSISTÊNCIA IDENTIFICADA: {com_assist} de {len(gols)}")
        diz("    (era exatamente isso que a API-Football ficou devendo)")
        amostras["fim_de_jogo"] = {"fixture": alvo_fix, "eventos": ev[:30]}

# ══ D) Livescore: está atualizado? ═══════════════════════════════════════
diz()
diz("D) LIVESCORE — o quanto está atualizado")
diz("-" * 74)
caminho, d = primeiro_que_responde([
    ("livescores/inplay", {"include": "participants;scores;periods;state"}),
    ("livescores", {"include": "participants;scores;periods;state"}),
])
if not caminho:
    diz("    Nenhum jogo ao vivo agora (ou o endpoint não respondeu).")
    diz("    Para medir de verdade, rode este script COM UM JOGO ROLANDO.")
else:
    ao_vivo = d.get("data", [])
    diz(f"    endpoint: /{caminho}  →  {len(ao_vivo)} jogo(s) ao vivo")

    def foto(lista):
        r = {}
        for f in lista:
            per = [p for p in (f.get("periods") or []) if p.get("ticking")]
            minuto = per[0].get("minutes") if per else None
            segundos = per[0].get("seconds") if per else None
            gols = [(s.get("score") or {}).get("goals") for s in (f.get("scores") or [])
                    if s.get("description") == "CURRENT"]
            r[f.get("id")] = {
                "nomes": " x ".join(p.get("name", "") for p in (f.get("participants") or [])),
                "minuto": minuto, "segundos": segundos,
                "gols": gols, "estado": (f.get("state") or {}).get("name"),
            }
        return r

    a = foto(ao_vivo)
    for fid, v in a.items():
        diz(f"      [{fid}] {v['nomes']}  {v['estado']}  "
            f"min={v['minuto']} seg={v['segundos']} gols={v['gols']}")
    diz()
    diz("    esperando 70s para ver se o relógio anda...")
    time.sleep(70)
    d2, e2 = pega(caminho, include="participants;scores;periods;state")
    b = foto((d2 or {}).get("data", []) or [])
    diz()
    diz("    COMPARAÇÃO (o relógio andou?):")
    for fid, v in a.items():
        w = b.get(fid)
        if not w:
            diz(f"      [{fid}] {v['nomes']}: sumiu da lista (jogo acabou?)")
            continue
        andou = (v["minuto"] != w["minuto"]) or (v["segundos"] != w["segundos"])
        mudou_gol = v["gols"] != w["gols"]
        diz(f"      [{fid}] {v['nomes'][:34]:34} "
            f"{v['minuto']}'{v['segundos'] or 0:02}s -> {w['minuto']}'{w['segundos'] or 0:02}s  "
            f"{'ANDOU' if andou else 'PARADO'}"
            f"{'  GOL NOVO' if mudou_gol else ''}")
    amostras["livescore"] = {"antes": a, "depois": b}

diz()
diz("=" * 74)
with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
with open(BRUTO, "w", encoding="utf-8") as f:
    json.dump(amostras, f, ensure_ascii=False, indent=2)
print()
print(f"Relatório: {RELATORIO}")
input("Pressione Enter para fechar...")
