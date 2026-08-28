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
# As imagens vêm como caminho relativo; a base é outro domínio.
MEDIA = "https://media-sdp.spl.com.sa/"
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
def _do_jogo(sid: str, mid: str, recurso: str, segmento: str, prazo: float,
             cliente, locale: str = "en-GB"):
    # O idioma entra na CHAVE do cache. Sem isso, pedir a escalação em árabe
    # depois de já ter pedido em inglês devolveria a inglesa, e a varredura
    # gravaria o nome latino nas duas colunas sem reclamar de nada.
    chave = f"{recurso}:{locale}:{mid}"
    guardado = _guardado(chave, prazo)
    if guardado is not None:
        return guardado
    dados = buscar_json(
        f"seasons/{_id(sid)}/{segmento}/{_id(mid)}/{recurso}?locale={locale}", cliente)
    return _guardar(chave, dados)


def previa_do_jogo(sid: str, mid: str, cliente) -> dict:
    """Forma recente, confronto direto e últimos encontros. Existe ANTES do jogo."""
    return _do_jogo(sid, mid, "matchPreview", "match", PRAZOS["previa"], cliente)


def escala_do_jogo(sid: str, mid: str, cliente, locale: str = "en-GB") -> dict:
    """A escalação OFICIAL. Antes de sair, vem com as listas vazias — e é assim
    que se sabe que ainda não saiu."""
    return _do_jogo(sid, mid, "lineups", "matches", PRAZOS["escala"], cliente,
                    locale)


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


# ── Quem jogou ──────────────────────────────────────────────────────────────
#
# A mesma escalação, pedida em `en-GB` e em `ar-SA`, volta com o MESMO
# playerId e o nome nas duas escritas. É essa coincidência — que não é
# coincidência, é o id ser de verdade — que dispensa Wikidata, transliteração
# e casamento por string para montar a identidade dos jogadores.
IDIOMAS = ("en-GB", "ar-SA")


def _pessoa(j: dict, time: dict, quando: str, arabe: bool) -> dict:
    nome = " ".join(x for x in (j.get("mediaFirstName"),
                                j.get("mediaLastName")) if x).strip()
    imagens = j.get("imagery") or {}
    # Guardo o CAMINHO, não a URL montada: se eles trocarem o servidor de
    # imagem, é uma constante para mudar, não uma coluna para reescrever.
    foto = (imagens.get("playerImage_home_middle")
            or imagens.get("playerImage_home_left")
            or imagens.get("playerImage_home_celeb") or "")
    # Só o que NÃO muda com o idioma fica aqui.
    #
    # `nacionalidade` e `posicao` moravam neste bloco, e isso era um defeito
    # de verdade: a passada em árabe devolve 'السعودية' e 'مدافع' nesses mesmos
    # campos, roda DEPOIS da latina, e a gravação deixa o último valor não
    # vazio vencer. Resultado: a nacionalidade de quase todo mundo ficou em
    # árabe — e o cruzamento por data, que usa a nacionalidade para desempatar
    # dois nascidos no mesmo dia, comparava 'السعودية' com 'Saudi Arabia' e
    # nunca desempatava nada. O empate era recusado, calado, como se fosse
    # ambiguidade real.
    #
    # O clube escapou por sorte: ele só é atualizado quando a data do jogo é
    # mais nova, e as duas passadas têm a mesma data.
    base = {"spl_id": j.get("playerId") or "", "visto_em": quando,
            "clube": time.get("shortName") or time.get("officialName") or "",
            "camisa": j.get("bibNumber") or "",
            "foto": foto}
    if arabe:
        base["nome_ar"] = nome
    else:
        base["nome"] = nome
        base["nome_curto"] = j.get("shortName") or ""
        base["posicao"] = j.get("roleLabel") or ""
        base["nacionalidade"] = j.get("nationality") or ""
    return base


def jogadores_dos_jogos(sid: str, jogos: list[dict], cliente) -> list[dict]:
    """Todo mundo relacionado nestes jogos, nas duas escritas.

    Junta pelo playerId. Uma pessoa que aparece em cinco jogos vira uma linha
    só, com a data mais recente em que foi vista.
    """
    juntos: dict[str, dict] = {}
    for j in jogos:
        mid = j.get("matchId")
        quando = (j.get("matchDateLocal") or j.get("matchDateUtc") or "")[:10]
        if not mid:
            continue
        for idioma in IDIOMAS:
            chave = f"escala:{idioma}:{mid}"
            escala = _guardado(chave, PRAZOS["escala"])
            if escala is None:
                try:
                    escala = buscar_json(
                        f"seasons/{_id(sid)}/matches/{_id(mid)}/lineups"
                        f"?locale={idioma}", cliente)
                except Exception:
                    continue
                _guardar(chave, escala)
            arabe = idioma.startswith("ar")
            for lado in ("home", "away"):
                time = escala.get(lado) or {}
                for grupo in ("fielded", "benched"):
                    for p in (time.get(grupo) or []):
                        pid = p.get("playerId") or ""
                        if not pid:
                            continue
                        pessoa = _pessoa(p, time, quando, arabe)
                        antigo = juntos.setdefault(pid, {})
                        # A comparação tem que acontecer ANTES da junção.
                        # Como `_pessoa` já devolve visto_em preenchido, o
                        # laço abaixo sobrescrevia a data com a do jogo atual,
                        # e o teste seguinte comparava a data consigo mesma —
                        # sempre falso. Resultado: a pessoa ficava com o clube
                        # do jogo MAIS ANTIGO, e quem trocou de time no meio
                        # da temporada aparecia no clube errado, calado.
                        mais_novo = quando > (antigo.get("visto_em") or "")
                        for k, v in pessoa.items():
                            if k in ("visto_em", "clube"):
                                continue
                            # Campo vazio não apaga o que a outra passada
                            # trouxe. A passada em árabe não tem nome latino,
                            # e vice-versa.
                            if v or k not in antigo:
                                antigo[k] = v
                        # A data mais recente é a que vale: ela diz em que
                        # clube a pessoa estava por último.
                        if mais_novo:
                            antigo["visto_em"] = quando
                            antigo["clube"] = pessoa["clube"]
    return list(juntos.values())
