"""
Elencos da Saudi Pro League direto do Transfermarkt.

Motor exclusivo da guia /elencos. A API-Football não entra aqui: ela não tem pé
preferido nem posição detalhada, publica elenco desatualizado (o Al Kholood
seguia com Hattan Bahbri depois de ele sair) e simplesmente não publica elenco
de clube recém-promovido (Al Diriyah). O TM resolve os três casos na origem, o
que dispensa o cruzamento entre fontes que existia antes.

Segue usada nas outras telas — FIM DE JOGO, Números e Janela não mudam.
"""
import re
import time
import asyncio
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from janela_scraper import TM_BASE, TM_HEADERS, TM_SAISON

_CACHE: dict[str, tuple[float, object]] = {}
TTL_ELENCO = 6 * 3600      # elenco muda por transferência, não por hora
TTL_CALENDARIO = 1800      # placar e súmula do dia entram aqui
TTL_ESCALACAO = 6 * 3600   # jogo encerrado não muda mais


def _cache_get(chave: str, ttl: int):
    v = _CACHE.get(chave)
    if v and (time.time() - v[0]) < ttl:
        return v[1]
    return None


def _cache_set(chave: str, valor):
    _CACHE[chave] = (time.time(), valor)
    return valor


# O TM não tem API: é raspagem, e ele bloqueia quem chega rápido demais. Em
# 16/08/2026 uma rajada de validação (elenco + desempenho + calendário + súmula
# de vários clubes em poucos minutos) rendeu 403 em tudo. Daí as três defesas:
# uma requisição por vez, intervalo mínimo entre elas e nova tentativa com
# espera crescente.
_PORTAO = asyncio.Semaphore(1)
_INTERVALO = 1.5          # segundos entre requisições
_ultimo_acesso = 0.0


async def _sopa(caminho: str, tentativas: int = 3) -> BeautifulSoup:
    global _ultimo_acesso
    url = TM_BASE.rstrip("/") + "/" + caminho.lstrip("/")
    erro = None
    for tentativa in range(tentativas):
        async with _PORTAO:
            espera = _INTERVALO - (time.time() - _ultimo_acesso)
            if espera > 0:
                await asyncio.sleep(espera)
            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                             headers=TM_HEADERS) as c:
                    r = await c.get(url)
            finally:
                _ultimo_acesso = time.time()
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        erro = r.status_code
        if r.status_code in (403, 429, 503) and tentativa < tentativas - 1:
            await asyncio.sleep(2 ** tentativa * 3)     # 3s, depois 6s
            continue
        break
    raise RuntimeError(f"Transfermarkt HTTP {erro} em {caminho}")


async def _com_cache(chave: str, ttl: int, caminho: str, parser):
    """Busca, guarda e — se o TM bloquear — devolve o que já tinha.

    Servir dado velho com aviso é melhor que tela vazia: o elenco de ontem
    continua quase todo certo, e o bloqueio costuma passar sozinho."""
    v = _CACHE.get(chave)
    if v and (time.time() - v[0]) < ttl:
        return v[1], None
    try:
        return _cache_set(chave, parser(await _sopa(caminho))), None
    except Exception as e:
        if v:
            return v[1], f"o Transfermarkt recusou a consulta agora ({e}); mostrando dados de antes"
        raise


# ── helpers de leitura ───────────────────────────────────────────────────────

def _id_de(href: str, padrao: str) -> int | None:
    m = re.search(padrao, href or "")
    return int(m.group(1)) if m else None


def _n(txt: str | None) -> int | None:
    """'-' e vazio viram None; zero de verdade continua zero."""
    t = (txt or "").strip().replace(".", "").replace("'", "")
    if not t or t == "-":
        return None
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def _altura_cm(txt: str | None) -> int | None:
    m = re.search(r"(\d)[,.](\d{2})", txt or "")
    return int(m.group(1)) * 100 + int(m.group(2)) if m else None


def _nasc_idade(txt: str | None) -> tuple[str | None, int | None]:
    """'05/04/1991 (35)' -> ('1991-04-05', 35)."""
    t = txt or ""
    nasc = None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        nasc = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    mi = re.search(r"\((\d{1,2})\)", t)
    return nasc, (int(mi.group(1)) if mi else None)


# Grupo de campo a partir da posição detalhada em português do TM.
_GRUPOS = [
    ("G", ("goleiro",)),
    ("D", ("zagueiro", "lateral", "defesa", "defensor")),
    ("M", ("volante", "meio-campo", "meio campo", "meia", "midfielder")),
    ("A", ("ponta", "atacante", "centroavante", "extremo")),
]


def grupo_da_posicao(pos: str | None) -> str | None:
    p = (pos or "").lower()
    if not p:
        return None
    for g, chaves in _GRUPOS:
        if any(k in p for k in chaves):
            return g
    return None


# ── elenco (kader) ───────────────────────────────────────────────────────────

def _parse_elenco(soup: BeautifulSoup) -> list[dict]:
    tabela = soup.select_one("table.items")
    if not tabela:
        return []
    corpo = tabela.find("tbody")
    if not corpo:
        return []
    out = []
    for tr in corpo.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue
        link = tds[1].select_one("a[href*='/profil/spieler/']")
        if not link:
            continue
        pid = _id_de(link.get("href", ""), r"/spieler/(\d+)")
        nome = link.get_text(" ", strip=True)
        if not pid or not nome:
            continue
        # A posição fica na SEGUNDA linha da tabela interna da célula. Tentar
        # deduzi-la subtraindo o nome do texto não funciona: o TM quebra o nome
        # em vários nós e a subtração devolvia "A b d u l l a h ... P o n t a".
        posicao = None
        interna = tds[1].find("table")
        if interna:
            linhas_int = interna.find_all("tr")
            if len(linhas_int) > 1:
                posicao = re.sub(r"\s+", " ", linhas_int[-1].get_text(" ", strip=True)).strip() or None
        if not posicao:
            resto = tds[1].get_text("|", strip=True).split("|")
            resto = [x for x in resto if x and x != nome]
            posicao = resto[-1] if resto else None

        nacs = [i.get("title") or i.get("alt") for i in tds[3].select("img")
                if (i.get("title") or i.get("alt"))]
        nasc, idade = _nasc_idade(tds[2].get_text(" ", strip=True))
        out.append({
            "id": pid,
            "nome": nome,
            "numero": _n(tds[0].get_text(strip=True)),
            "posicao": posicao,
            "grupo": grupo_da_posicao(posicao),
            "nascimento": nasc,
            "idade": idade,
            "nacionalidades": nacs,
            "altura": _altura_cm(tds[4].get_text(strip=True)),
            "pe": (tds[5].get_text(strip=True) or None),
            "foto": f"https://img.a.transfermarkt.technology/portrait/medium/{pid}-1.jpg",
            "valor": (tds[9].get_text(" ", strip=True) or None) if len(tds) > 9 else None,
            "contrato": (tds[8].get_text(" ", strip=True) or None) if len(tds) > 8 else None,
        })
    return out


async def elenco(clube_id: int, season: int | None = None) -> tuple[list[dict], str | None]:
    season = season or TM_SAISON
    return await _com_cache(f"elenco:{clube_id}:{season}", TTL_ELENCO,
                            f"x/kader/verein/{clube_id}/saison_id/{season}/plus/1",
                            _parse_elenco)


# ── desempenho (leistungsdaten) ──────────────────────────────────────────────
# Colunas confirmadas em 16/08/2026 pela chave de ordenação do próprio TM
# (sort/tore, sort/vorlagen, sort/gelbe, sort/rote, sort/einsatzzeit) e
# conferidas contra fato conhecido: Rúben Neves marcou 2 na estreia e a coluna 6
# mostra 2. Índices fixos aqui só depois dessa dupla checagem.
_COL = {"jogos": 5, "gols": 6, "assistencias": 7, "amarelos": 8,
        "segundo_amarelo": 9, "vermelhos": 10, "entrou": 11, "saiu": 12,
        "minutos": 14}


def _parse_desempenho(soup: BeautifulSoup) -> dict[int, dict]:
    tabela = soup.select_one("table.items")
    if not tabela:
        return {}
    corpo = tabela.find("tbody")
    if not corpo:
        return {}
    fora: dict[int, dict] = {}
    for tr in corpo.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) <= _COL["minutos"]:
            continue
        link = tds[1].select_one("a[href*='/profil/spieler/']")
        pid = _id_de(link.get("href", ""), r"/spieler/(\d+)") if link else None
        if not pid:
            continue
        def val(k):
            return _n(tds[_COL[k]].get_text(" ", strip=True))
        # "Não esteve no plantel" cai na coluna de jogos como texto: vira None.
        fora[pid] = {k: val(k) for k in _COL}
    return fora


async def desempenho(clube_id: int, season: int | None = None) -> tuple[dict[int, dict], str | None]:
    season = season or TM_SAISON
    return await _com_cache(f"desemp:{clube_id}:{season}", TTL_ELENCO,
                            f"x/leistungsdaten/verein/{clube_id}/plus/1/saison_id/{season}",
                            _parse_desempenho)


# ── calendário e clubes ──────────────────────────────────────────────────────

def _parse_calendario(soup: BeautifulSoup) -> list[dict]:
    jogos = []
    ultima_data = None
    for tabela in soup.select("table"):
        cab = [th.get_text(strip=True) for th in tabela.select("thead th")]
        if "Resultado" not in cab:
            continue
        corpo = tabela.find("tbody")
        if not corpo:
            continue
        for tr in corpo.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 7:
                continue          # linhas de data/hora, sem jogo
            def clube(td):
                a = td.select_one("a[href*='/verein/']")
                if not a:
                    return None, None
                return (_id_de(a.get("href", ""), r"/verein/(\d+)"),
                        (a.get("title") or a.get_text(" ", strip=True) or None))
            cid, cnome = clube(tds[3])
            vid, vnome = clube(tds[6]) if len(tds) > 6 else (None, None)
            if not cid:
                cid, cnome = clube(tds[2])
            if not vid:
                vid, vnome = clube(tds[5])
            res = tds[4].select_one("a[href*='/spielbericht/']")
            sid = _id_de(res.get("href", ""), r"/spielbericht/(\d+)") if res else None
            placar = res.get_text(strip=True) if res else None
            dm = re.search(r"(\d{2})/(\d{2})/(\d{2})", tds[0].get_text(" ", strip=True))
            if dm:
                # A data só aparece na primeira linha de cada dia; as seguintes
                # herdam. Sem isso, quase todo jogo ficava sem data e o "último
                # jogo" era escolhido por desempate errado.
                ultima_data = f"20{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
            data = ultima_data
            if cid and vid:
                jogos.append({"data": data, "casa_id": cid, "casa": cnome,
                              "fora_id": vid, "fora": vnome,
                              "placar": placar, "sumula": sid})
    return jogos


async def calendario(season: int | None = None) -> tuple[list[dict], str | None]:
    season = season or TM_SAISON
    return await _com_cache(
        f"cal:{season}", TTL_CALENDARIO,
        f"saudi-professional-league/gesamtspielplan/wettbewerb/SA1/saison_id/{season}",
        _parse_calendario)


async def clubes(season: int | None = None) -> tuple[list[dict], str | None]:
    """Clubes da liga, deduzidos do calendário — uma requisição serve às duas coisas."""
    jogos, aviso = await calendario(season)
    vistos: dict[int, str] = {}
    for j in jogos:
        for i, n in ((j["casa_id"], j["casa"]), (j["fora_id"], j["fora"])):
            if i and n and i not in vistos:
                vistos[i] = n
    return sorted(({"id": i, "nome": n,
                    "escudo": f"https://tmssl.akamaized.net//images/wappen/head/{i}.png"}
                   for i, n in vistos.items()), key=lambda c: c["nome"].lower()), aviso


async def ultimo_jogo(clube_id: int, season: int | None = None) -> tuple[dict | None, str | None]:
    """Partida encerrada mais recente do clube (a que tem súmula e placar)."""
    hoje = date.today().isoformat()
    jogos, aviso = await calendario(season)
    disputados = [j for j in jogos
                  if clube_id in (j["casa_id"], j["fora_id"])
                  and j["sumula"] and j["placar"] and re.match(r"^\d+:\d+$", j["placar"] or "")
                  and (not j["data"] or j["data"] <= hoje)]
    if not disputados:
        return None, aviso
    return max(disputados, key=lambda j: j["data"] or ""), aviso


# ── escalação da súmula ──────────────────────────────────────────────────────

def _parse_escalacao(soup: BeautifulSoup) -> list[dict]:
    """Devolve [{formacao, titulares:[ids], banco:[ids]}] na ordem casa, fora."""
    # A formação precisa ficar amarrada à seção do time, não à ordem em que
    # aparece na página: pegar as duas soltas e distribuir por índice pode
    # trocar as escalações de lado sem ninguém perceber. Aqui cada time recebe
    # a última formação que aparece ANTES do seu primeiro titular no HTML.
    caixa = soup.select_one("[class*=aufstellung-box]") or soup
    html = str(caixa)
    marcas_form = [(m.start(), m.group(0))
                   for m in re.finditer(r"\b\d(?:-\d){1,3}\b", html)]

    def formacao_antes(pos_html: int) -> str | None:
        anteriores = [f for p, f in marcas_form if p < pos_html]
        return anteriores[-1] if anteriores else None

    # Percorre os jogadores em ordem de documento e quebra em blocos toda vez
    # que alterna entre titular e banco: sai casa-XI, casa-banco, fora-XI,
    # fora-banco. Dedupe por id porque o TM repete a lista (campo e versão
    # mobile) dentro da mesma seção.
    blocos: list[dict] = []
    for a in caixa.select("a[href*='/profil/spieler/']"):
        pid = _id_de(a.get("href", ""), r"/spieler/(\d+)")
        if not pid:
            continue
        pai = a.find_parent(class_=True)
        classes = " ".join(pai.get("class") or []) if pai else ""
        if "formation-number-name" in classes:
            tipo = "xi"
        elif "ersatzbank" in classes:
            tipo = "banco"
        else:
            continue
        if not blocos or blocos[-1]["tipo"] != tipo:
            pos = html.find(a.get("href", ""))
            blocos.append({"tipo": tipo, "ids": [], "pos": pos if pos >= 0 else 0})
        if pid not in blocos[-1]["ids"]:
            blocos[-1]["ids"].append(pid)

    times = []
    i = 0
    while i < len(blocos):
        if blocos[i]["tipo"] != "xi":
            i += 1
            continue
        banco = blocos[i + 1]["ids"] if i + 1 < len(blocos) and blocos[i + 1]["tipo"] == "banco" else []
        times.append({"formacao": formacao_antes(blocos[i]["pos"]),
                      "titulares": blocos[i]["ids"], "banco": banco})
        i += 2
    return times


async def escalacao(sumula_id: int) -> tuple[list[dict], str | None]:
    return await _com_cache(f"esc:{sumula_id}", TTL_ESCALACAO,
                            f"x/index/spielbericht/{sumula_id}", _parse_escalacao)


def posicoes_no_campo(formacao: str | None, quantidade: int = 11) -> list[tuple[float, float]]:
    """Coordenadas de cada casa, na ordem em que a súmula lista os titulares.

    A súmula do TM lista do goleiro para a frente, então a formação sozinha já
    diz quem fica onde — sem precisar da grade de coordenadas, que o TM só
    desenha em imagem."""
    linhas = [1]
    if formacao:
        try:
            linhas += [int(x) for x in formacao.split("-")]
        except ValueError:
            linhas = [1]
    if sum(linhas) != quantidade:
        linhas = [1, 4, 3, 3] if quantidade == 11 else [quantidade]
    coords = []
    total = len(linhas)
    for li, n in enumerate(linhas):
        y = 92.0 if total <= 1 else 92.0 - li * (76.0 / (total - 1))
        for c in range(n):
            coords.append((round(((c + 1) / (n + 1)) * 100, 1), round(y, 1)))
    return coords
