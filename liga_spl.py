"""
O que a Saudi Pro League publica na própria API.

POR QUE ESTE MÓDULO EXISTE SEPARADO
    A guia de Arbitragem já falava com esta API para pegar a grafia dos nomes.
    A prévia de jogo precisa da mesma API para tabela, forma e confronto
    direto. Duas cópias do mesmo cliente é como se começa a ter dois
    comportamentos diferentes para a mesma pergunta — e a segunda cópia é
    sempre a que ninguém lembra de corrigir.

O QUE ELA TEM, E O QUE NÃO TEM
    Tem: tabela completa, forma dos últimos jogos, confronto direto, últimos
    encontros, escalação OFICIAL com formação e posição em campo, arbitragem
    com os seis papéis, e 245 estatísticas por partida.

    Não tem: escalação provável. O endpoint responde antes do jogo, mas vem
    com `fielded` vazio e formação em branco. Isso é uma qualidade, não um
    defeito: quando a liga diz quem joga, é porque já é oficial.

    Não cobre: Copa do Rei, Supercopa, AFC. Só a Roshn Saudi League. Para o
    resto o app depende do SAFF, e sem estatística nenhuma.

NADA DE ID CHUMBADO
    Competição, temporada e jogo são descobertos em cadeia a cada chamada. Id
    de catálogo vira de temporada em temporada; um id fixo aqui pararia de
    funcionar em julho, calado, no meio das férias.
"""
import re
import time
from urllib.parse import quote

API = "https://api-sdp.spl.com.sa/v1/spl/football"
TEMPO_LIMITE = 25.0
UA = "Mozilla/5.0 (compatible; IARABAO/1.0)"

# A temporada muda uma vez por ano; a tabela, algumas vezes por semana. Guardo
# na memória do processo com prazos diferentes para não repetir a cadeia de
# descoberta a cada jogo de uma mesma leva.
_CACHE: dict[str, tuple[float, object]] = {}
PRAZOS = {"temporada": 6 * 3600, "jogos": 900, "tabela": 900,
          "previa": 900, "escala": 300, "arbitros": 300}


def _guardado(chave: str, prazo: float):
    achado = _CACHE.get(chave)
    if achado and time.time() - achado[0] < prazo:
        return achado[1]
    return None


def _guardar(chave: str, valor):
    _CACHE[chave] = (time.time(), valor)
    return valor


def buscar_json(caminho: str, cliente):
    """GET no caminho, já com o locale. Levanta se der ruim — quem chama decide."""
    r = cliente.get(f"{API}/{caminho}", timeout=TEMPO_LIMITE,
                    follow_redirects=True,
                    headers={"Accept": "application/json", "User-Agent": UA})
    r.raise_for_status()
    return r.json()


def _id(bruto) -> str:
    """Os ids vêm no formato spl::Football_Match::abc e vão na URL codificados."""
    return quote(str(bruto or ""), safe="")


# ── Cruzar um jogo entre fontes diferentes ──────────────────────────────────
def confronto(casa: str, fora: str) -> frozenset:
    """A identidade de um jogo, para casar o que veio de fontes diferentes.

    Sem ordem: uma fonte pode chamar de mandante quem a outra chama de
    visitante, e o jogo continua sendo o mesmo. Passa pelo glossário de clubes
    porque 'Al Diraiyah' (SAFF), 'Diriyah' (liga) e 'Al-Diriyah' (API-Football)
    são o mesmo clube escrito por três pessoas diferentes.
    """
    import glossary
    lados = []
    for n in (casa, fora):
        limpo = re.sub(r"\s*-\s*[A-Z]{3}$", "", " ".join((n or "").split()))
        lados.append((glossary.padronizar_clube(limpo) or limpo).lower())
    return frozenset(lados)


# ── A cadeia de descoberta ──────────────────────────────────────────────────
def temporada(dia: str, cliente) -> str:
    """A temporada que CONTÉM este dia, e não 'a primeira da lista'.

    A diferença aparece em julho, quando duas temporadas convivem na resposta
    e pegar a primeira traz a que acabou.
    """
    guardado = _guardado(f"temporada:{dia}", PRAZOS["temporada"])
    if guardado is not None:
        return guardado
    comps = buscar_json("competitions?locale=en-GB", cliente).get("competitions") or []
    if not comps:
        return _guardar(f"temporada:{dia}", "")
    cid = _id(comps[0].get("competitionId"))
    temporadas = buscar_json(f"competitions/{cid}/seasons?locale=en-GB",
                             cliente).get("seasons") or []
    for t in temporadas:
        ini, fim = (t.get("startDateUtc") or "")[:10], (t.get("endDateUtc") or "")[:10]
        if ini and fim and ini <= dia <= fim:
            return _guardar(f"temporada:{dia}", t.get("seasonId") or "")
    return _guardar(f"temporada:{dia}", "")


def jogos_da_temporada(sid: str, cliente) -> list[dict]:
    """Os 306 jogos do ano numa tacada. Uma chamada, cache de 15 minutos."""
    guardado = _guardado(f"jogos:{sid}", PRAZOS["jogos"])
    if guardado is not None:
        return guardado
    dados = buscar_json(f"seasons/{_id(sid)}/matches?locale=en-GB", cliente)
    return _guardar(f"jogos:{sid}", dados.get("matches") or [])


def jogos_do_dia(sid: str, dia: str, cliente) -> list[dict]:
    """Uso matchDateLocal, que é a hora da Arábia.

    Um jogo das 21h locais é 18h UTC — mesmo dia. Mas um das 23h viraria o dia
    seguinte em UTC e sumiria da data certa sem deixar rastro.
    """
    return [j for j in jogos_da_temporada(sid, cliente)
            if (j.get("matchDateLocal") or j.get("matchDateUtc") or "")[:10] == dia]


def jogos_ate(sid: str, dia: str, cliente) -> list[dict]:
    """Os jogos já disputados até (sem incluir) esta data, do mais novo ao mais
    velho. É a matéria-prima da escalação provável."""
    passados = [j for j in jogos_da_temporada(sid, cliente)
                if (j.get("matchDateLocal") or "")[:10] < dia
                and (j.get("status") or "").upper() in ("FINISHED", "PLAYED")]
    passados.sort(key=lambda j: j.get("matchDateLocal") or "", reverse=True)
    return passados


# ── Os dados de um jogo ─────────────────────────────────────────────────────
def _do_jogo(sid: str, mid: str, recurso: str, segmento: str, prazo: float, cliente):
    chave = f"{recurso}:{mid}"
    guardado = _guardado(chave, prazo)
    if guardado is not None:
        return guardado
    dados = buscar_json(
        f"seasons/{_id(sid)}/{segmento}/{_id(mid)}/{recurso}?locale=en-GB", cliente)
    return _guardar(chave, dados)


def previa_do_jogo(sid: str, mid: str, cliente) -> dict:
    """Forma recente, confronto direto e últimos encontros. Existe ANTES do jogo."""
    return _do_jogo(sid, mid, "matchPreview", "match", PRAZOS["previa"], cliente)


def escala_do_jogo(sid: str, mid: str, cliente) -> dict:
    """A escalação OFICIAL. Antes de sair, vem com as listas vazias — e é assim
    que se sabe que ainda não saiu."""
    return _do_jogo(sid, mid, "lineups", "matches", PRAZOS["escala"], cliente)


def arbitros_do_jogo(sid: str, mid: str, cliente) -> dict:
    return _do_jogo(sid, mid, "matchfacts", "match", PRAZOS["arbitros"], cliente)


def tem_escalacao(escala: dict) -> bool:
    """Só é escalação quando tem gente dentro."""
    for lado in ("home", "away"):
        if len((escala.get(lado) or {}).get("fielded") or []) >= 11:
            return True
    return False


# ── A tabela ────────────────────────────────────────────────────────────────
def tabela(sid: str, cliente) -> list[dict]:
    """Uma linha por clube, com os números já achatados.

    A API devolve cada número como um objeto {statsId, statsLabel, statsValue}.
    Achato aqui para quem consome não precisar saber disso — e para que uma
    mudança no formato deles quebre em UM lugar, não em cinco telas.
    """
    guardado = _guardado(f"tabela:{sid}", PRAZOS["tabela"])
    if guardado is not None:
        return guardado
    dados = buscar_json(f"seasons/{_id(sid)}/standings/overall?locale=en-GB", cliente)
    grupos = dados.get("standings") or []
    linhas = []
    for t in (grupos[0].get("teams") if grupos else []) or []:
        linha = {"clube": t.get("shortName") or t.get("officialName") or "",
                 "time_id": t.get("teamId") or ""}
        for s in (t.get("stats") or []):
            chave = s.get("statsId")
            valor = s.get("statsValue")
            if chave == "form" and isinstance(valor, list):
                linha["forma"] = [f.get("formType") for f in valor if f.get("formType")]
            elif isinstance(valor, (int, float, str)):
                linha[chave] = valor
        linhas.append(linha)
    return _guardar(f"tabela:{sid}", linhas)


def linha_da_tabela(linhas: list[dict], clube: str) -> dict:
    """A linha do clube, cruzando pelo glossário. {} se não achar — nunca a
    linha errada, que passaria despercebida por parecer plausível."""
    import glossary
    alvo = (glossary.padronizar_clube(clube) or clube).lower()
    for l in linhas:
        c = l.get("clube") or ""
        if (glossary.padronizar_clube(c) or c).lower() == alvo:
            return l
    return {}
