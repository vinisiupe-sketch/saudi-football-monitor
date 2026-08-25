"""
Motor da Sportmonks para FIM DE JOGO e alerta de GOL.

Existe em paralelo ao motor da API-Football, não no lugar dele: a ideia é ver
os dois lado a lado com a mesma partida e decidir com base no que aparece na
tela, não em documentação.

O texto sai no MESMO formato dos posts, para a comparação ser justa.
"""
import os
import time
import json
import urllib.parse

import httpx

import glossary

BASE = "https://api.sportmonks.com/v3/football"

# A Sportmonks fica atrás do Cloudflare, que barra cliente sem User-Agent de
# navegador com "Error 1010". Descobri isso na sondagem: com o UA padrão do
# httpx a chamada volta 403 mesmo com token válido.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Ids das nossas 5 competições no catálogo deles (conferidos na sondagem).
LIGAS = {944: "Liga Saudita", 950: "Copa do Rei", 1557: "Supercopa Saudita",
         1085: "AFC Champions League Elite", 1088: "AFC Champions League Two"}

# type_id 14 = Goal, 16 = Penalty, 15 = Own Goal (confirmados em /core/types
# durante a sondagem; guardo aqui para não gastar chamada a cada consulta).
TIPO_GOL = 14
TIPO_PENALTI = 16
TIPO_GOL_CONTRA = 15
TIPOS_DE_GOL = {TIPO_GOL, TIPO_PENALTI, TIPO_GOL_CONTRA}

_CACHE: dict[str, tuple[float, dict]] = {}
TTL_AO_VIVO = 15          # segundos; jogo ao vivo muda rápido
TTL_PARADO = 600


def configurado() -> bool:
    return bool(os.environ.get("SPORTMONKS_TOKEN", "").strip())


async def _get(caminho: str, ttl: int = TTL_AO_VIVO, **params):
    """Devolve (dado, erro). Nunca levanta, nunca devolve o token no erro."""
    token = os.environ.get("SPORTMONKS_TOKEN", "").strip()
    if not token:
        return None, "SPORTMONKS_TOKEN não configurada no servidor."
    params["api_token"] = token
    chave = caminho + "?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if k != "api_token"})
    agora = time.time()
    if chave in _CACHE and agora - _CACHE[chave][0] < ttl:
        return _CACHE[chave][1], None
    url = f"{BASE}/{caminho}?" + urllib.parse.urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=25.0) as c:
            r = await c.get(url, headers={"Accept": "application/json",
                                          "User-Agent": UA})
        if r.status_code >= 300:
            return None, f"HTTP {r.status_code}: {r.text[:160]}"
        dados = r.json()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    _CACHE[chave] = (agora, dados)
    return dados, None


def _nome_curto(nome: str) -> str:
    """Mesma regra do resto do app: tira o 'Al-' e o sufixo do clube."""
    n = (nome or "").strip()
    for prefixo in ("Al-", "Al "):
        if n.startswith(prefixo):
            n = n[len(prefixo):]
    for sufixo in (" Saudi FC", " FC", " SC", " Jeddah", " Saihat", " Club"):
        if n.endswith(sufixo):
            n = n[: -len(sufixo)]
    return n.strip()


def _nome_card(nome: str) -> str:
    """Nome como você escreve no card de gol: "AL HILAL", "AL FAISALY".

    Diferente do FIM DE JOGO, que usa o nome curto sem o "Al" ("Hilal 2x1
    Nassr"). Conferi nos seus posts: no card de gol o "AL" fica.

    A grafia vem da tabela do glossário, não do que a API mandou. As duas
    fontes escrevem diferente ("Al-Qadisiyah FC" numa, "Al Qadsiah" na outra)
    e o post não pode depender de qual delas carimbou o gol primeiro.
    """
    return glossary.nome_para_card(nome)


def _placar_atual(f: dict) -> tuple[int, int]:
    casa = fora = 0
    for s in (f.get("scores") or []):
        if s.get("description") != "CURRENT":
            continue
        sc = s.get("score") or {}
        if sc.get("participant") == "home":
            casa = sc.get("goals") or 0
        elif sc.get("participant") == "away":
            fora = sc.get("goals") or 0
    return casa, fora


def _lados(f: dict) -> tuple[dict, dict]:
    """Devolve (time da casa, visitante) lendo o meta location de cada um."""
    casa = fora = {}
    for p in (f.get("participants") or []):
        if ((p.get("meta") or {}).get("location")) == "home":
            casa = p
        else:
            fora = p
    return casa, fora


def _autor(ev: dict) -> str:
    return (ev.get("player") or {}).get("display_name") or ev.get("player_name") or "?"


def _assistente(ev: dict) -> str:
    return ((ev.get("relatedplayer") or {}).get("display_name")
            or ev.get("related_player_name") or "")


def chave_do_gol(ev: dict) -> str:
    """Identidade estável de um gol, para saber se já vimos este.

    Não uso o id do evento: as duas fontes têm ids próprios, e a comparação
    precisa casar o MESMO gol entre elas. Minuto + autor + placar resultante
    identifica o lance nas duas.
    """
    return f"{ev.get('minute')}|{_autor(ev)}|{ev.get('result') or ''}"


def gols_da_partida(f: dict) -> list[dict]:
    """Só os eventos que são gol de verdade, em ordem de minuto."""
    saida = []
    for ev in (f.get("events") or []):
        tid = ev.get("type_id")
        nome_tipo = ((ev.get("type") or {}).get("name") or "").lower()
        if tid not in TIPOS_DE_GOL and "goal" not in nome_tipo:
            continue
        if "missed" in nome_tipo or "cancel" in nome_tipo:
            continue
        saida.append(ev)
    saida.sort(key=lambda e: (e.get("minute") or 0, e.get("extra_minute") or 0))
    return saida


def texto_do_gol(f: dict, ev: dict, cores: dict, narrativa: str = "") -> str:
    """Card de GOL no formato que você usa no X.

        🔵⚪️ 𝑮𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑶𝑳

        ⏰ 28' AL HILAL 3 x 0 AL FAISALY
        ⚽ Ruben Neves (p)
        🅰️ Fulano

        [narrativa]
    """
    casa, fora = _lados(f)
    nc, nf = _nome_card(casa.get("name")), _nome_card(fora.get("name"))
    gc, gf = _placar_atual(f)
    # O placar CURRENT é o de agora; num gol antigo o certo é o resultante
    # daquele lance, que a Sportmonks devolve no campo 'result' ("2-0").
    res = (ev.get("result") or "").split("-")
    if len(res) == 2 and res[0].strip().isdigit() and res[1].strip().isdigit():
        gc, gf = int(res[0]), int(res[1])

    # A cor é a do time que MARCOU. Em gol contra, quem pontua é o outro.
    dono = ev.get("participant_id")
    marcou_casa = dono == casa.get("id")
    if ev.get("type_id") == TIPO_GOL_CONTRA:
        marcou_casa = not marcou_casa
    time_gol = casa if marcou_casa else fora
    cor = cores.get(time_gol.get("id")) or ""

    autor = _autor(ev)
    marca = ""
    if ev.get("type_id") == TIPO_PENALTI:
        marca = " (p)"
    elif ev.get("type_id") == TIPO_GOL_CONTRA:
        marca = " (gc)"

    partes = [f"{cor} {glossary.GRITO_DE_GOL}".strip(), ""]
    minuto = ev.get("minute")
    extra = ev.get("extra_minute")
    rot_min = f"{minuto}+{extra}" if extra else f"{minuto}"
    partes.append(f"⏰ {rot_min}' {nc} {gc} x {gf} {nf}")
    partes.append(f"⚽ {autor}{marca}")
    assist = _assistente(ev)
    if assist:
        partes.append(f"🅰️ {assist}")
    if narrativa:
        partes += ["", narrativa]
    return "\n".join(partes)


def texto_fim_de_jogo(f: dict, cores: dict, narrativa: str = "") -> dict:
    """Mesmo formato do motor da API-Football, para dar para comparar."""
    casa, fora = _lados(f)
    nc, nf = _nome_curto(casa.get("name")), _nome_curto(fora.get("name"))
    gc, gf = _placar_atual(f)
    estado = ((f.get("state") or {}).get("short_name")
              or (f.get("state") or {}).get("name") or "")
    encerrado = estado.upper() in ("FT", "AET", "FT_PEN", "PEN", "FULL TIME",
                                   "FINISHED", "AFTER_EXTRA_TIME")

    gols = gols_da_partida(f)
    linhas_casa, linhas_fora = [], []
    for ev in gols:
        autor = _autor(ev)
        marca = ""
        if ev.get("type_id") == TIPO_PENALTI:
            marca = " (p)"
        elif ev.get("type_id") == TIPO_GOL_CONTRA:
            marca = " (gc)"
        assist = _assistente(ev)
        linha = f"⚽ {autor}{marca}"
        if assist and not marca:
            linha = f"⚽ {autor} ({assist})"
        dono = ev.get("participant_id")
        marcou_casa = dono == casa.get("id")
        if ev.get("type_id") == TIPO_GOL_CONTRA:
            marcou_casa = not marcou_casa
        (linhas_casa if marcou_casa else linhas_fora).append(linha)

    # Mesma guarda do outro motor: só considero completo quando a contagem de
    # linhas bate com o placar. Texto incompleto virando post é o pior defeito.
    completo = (len(linhas_casa) == gc and len(linhas_fora) == gf)

    cabecalho = "⏱️ FIM DE JOGO" if encerrado else "⏱️ FIM DE JOGO (parcial)"
    partes = [cabecalho, ""]
    if narrativa:
        partes += [narrativa, ""]
    cc = cores.get(casa.get("id")) or ""
    cf = cores.get(fora.get("id")) or ""
    partes.append(f"{cc} {nc} {gc}x{gf} {nf} {cf}".replace("  ", " ").strip())
    if linhas_casa:
        partes += [""] + linhas_casa
    if linhas_fora:
        partes += [""] + linhas_fora

    return {
        "fonte": "sportmonks",
        "fixture": f.get("id"),
        "casa": nc, "fora": nf, "placar": f"{gc}x{gf}",
        "estado": estado, "encerrado": encerrado, "completo": completo,
        "texto": "\n".join(partes),
        "gols": [{"chave": chave_do_gol(e), "minuto": e.get("minute"),
                  "autor": _autor(e), "assistente": _assistente(e),
                  "tipo": (e.get("type") or {}).get("name"),
                  "resultado": e.get("result")} for e in gols],
        "aviso": None if completo else
                 f"a Sportmonks ainda não publicou todos os gols "
                 f"({len(linhas_casa)+len(linhas_fora)} de {gc+gf})",
    }


INCLUDE_PARTIDA = ("participants;scores;state;periods;"
                   "events.type;events.player;events.relatedPlayer")


async def partida(fixture_id: int, ttl: int = TTL_AO_VIVO):
    d, e = await _get(f"fixtures/{fixture_id}", ttl=ttl, include=INCLUDE_PARTIDA)
    if e:
        return None, e
    return (d or {}).get("data"), None


async def ao_vivo():
    """Partidas rolando agora — e as que acabaram de encerrar.

    O /livescores/inplay tira a partida da lista no apito final. Se eu olhasse
    só ele, o último gol do jogo poderia nunca ser carimbado: basta a partida
    encerrar entre duas passagens do coletor. Por isso somo os jogos de hoje.
    """
    vistos, saida = set(), []
    d, e = await _get("livescores/inplay", ttl=10, include=INCLUDE_PARTIDA)
    for f in ((d or {}).get("data") or []):
        if f.get("league_id") in LIGAS:
            vistos.add(f.get("id"))
            saida.append(f)

    from datetime import datetime, timezone
    hoje = datetime.now(timezone.utc).date().isoformat()
    d2, e2 = await _get(f"fixtures/date/{hoje}", ttl=45,
                        include=INCLUDE_PARTIDA, per_page="100")
    for f in ((d2 or {}).get("data") or []):
        if f.get("league_id") not in LIGAS or f.get("id") in vistos:
            continue
        # só o que já começou; jogo futuro não tem gol para carimbar
        if f.get("events") or _placar_atual(f) != (0, 0):
            saida.append(f)
    return saida, (e or e2)


async def do_dia(data_iso: str):
    d, e = await _get(f"fixtures/date/{data_iso}", ttl=120,
                      include=INCLUDE_PARTIDA, per_page="100")
    if e:
        return [], e
    return [f for f in ((d or {}).get("data") or [])
            if f.get("league_id") in LIGAS], None


# ══════════════════════════════════════════════════════════════════════════
# ESCALAÇÕES
#
# A pergunta aqui é a mesma do alerta de gol: qual fonte publica primeiro.
# Para isso, o que importa é DETECTAR que a escalação existe — a lista de
# nomes é para a tela, o carimbo é para a medição.
# ══════════════════════════════════════════════════════════════════════════

INCLUDE_ESCALACAO = ("participants;state;lineups.player;lineups.type;"
                     "metadata.type")

# A Sportmonks publica uma escalação PROVÁVEL antes da oficial — montada com
# histórico, lesões e suspensões — e depois troca pela de verdade, tipicamente
# uma hora antes do apito. É por isso que a escalação dela chega cedo e vem
# errada: nesse momento ela ainda é um palpite, e está dito na documentação
# deles.
#
# Quem separa uma da outra é a marca lineup_confirmed, que vem no metadata da
# partida. Não fixo o id do tipo: procuro pelo NOME, porque id de catálogo
# muda e eu não tenho como conferir o valor daqui.
_MARCA_CONFIRMADA = ("lineup_confirmed", "lineupconfirmed",
                     "lineup confirmed", "lineups_confirmed")


def _verdadeiro(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def escalacao_confirmada(f: dict) -> bool | None:
    """A escalação desta partida já é a oficial?

    Devolve True, False, ou None quando a marca não veio — e None é uma
    resposta, não um erro. Tratar "não sei" como "não confirmada" carimbaria
    tudo de provável para sempre, e a comparação entre as fontes viraria
    ficção. Quando é None, a tela diz que não sabe.
    """
    for m in (f.get("metadata") or []):
        nome = ((m.get("type") or {}).get("name")
                or (m.get("type") or {}).get("code")
                or (m.get("type") or {}).get("developer_name") or "")
        if str(nome).strip().lower().replace("-", "_") in _MARCA_CONFIRMADA:
            return _verdadeiro(m.get("value"))
    return None

# type_id 11 = titular, 12 = banco, segundo o catálogo deles. NÃO confio só
# nisso: se o id mudar ou vier ausente, o formation_field decide — quem tem
# posição em campo é titular, quem não tem está no banco. Errar essa divisão
# estragaria a tela, mas não a medição, que é o que interessa aqui.
TIPO_TITULAR = 11
TIPO_BANCO = 12


def _e_titular(j: dict) -> bool:
    tid = j.get("type_id")
    if tid in (TIPO_TITULAR, TIPO_BANCO):
        return tid == TIPO_TITULAR
    nome = ((j.get("type") or {}).get("name") or "").lower()
    if "bench" in nome or "substitut" in nome:
        return False
    if "lineup" in nome or "start" in nome:
        return True
    return bool(j.get("formation_field"))


def escalacao_da_partida(f: dict) -> dict:
    """Titulares e banco por time. Vazio quando ainda não saiu.

    Devolve {} — e não uma estrutura com listas vazias — quando não há nada,
    porque quem chama usa isso para decidir se já dá para carimbar. Estrutura
    vazia mas presente faria o carimbo sair antes da escalação existir.
    """
    linhas = f.get("lineups") or []
    if not linhas:
        return {}
    casa, fora = _lados(f)
    times = {casa.get("id"): {"nome": _nome_card(casa.get("name")),
                             "titulares": [], "banco": []},
             fora.get("id"): {"nome": _nome_card(fora.get("name")),
                              "titulares": [], "banco": []}}
    for j in linhas:
        alvo = times.get(j.get("team_id"))
        if alvo is None:
            continue
        nome = ((j.get("player") or {}).get("display_name")
                or j.get("player_name") or "?")
        item = {"nome": nome, "camisa": j.get("jersey_number")}
        (alvo["titulares"] if _e_titular(j) else alvo["banco"]).append(item)
    # Sem nenhum titular, a escalação não saiu de verdade: às vezes vem só o
    # banco ou uma lista parcial, e carimbar isso mediria a coisa errada.
    if not any(t["titulares"] for t in times.values()):
        return {}
    return {"times": [t for t in times.values() if t["titulares"] or t["banco"]],
            "quantos": len(linhas)}


async def com_escalacao(data_iso: str):
    """Partidas do dia com o include de escalação."""
    d, e = await _get(f"fixtures/date/{data_iso}", ttl=45,
                      include=INCLUDE_ESCALACAO, per_page="100")
    if e:
        return [], e
    return [f for f in ((d or {}).get("data") or [])
            if f.get("league_id") in LIGAS], None
