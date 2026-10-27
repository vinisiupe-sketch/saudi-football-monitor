"""A agenda do dia: a arte dele reproduzida, e o botão até o post na home.

O QUE ELE PEDIU (26/10/26)
    "Conseguiríamos reproduzir isso aqui? Cria um botão de gerar agenda do
     dia?" — com a arte de 23/10 que ele fez no Canva.

AS MEDIDAS ABAIXO SÃO DA ARTE DELE
    Tiradas pixel a pixel da agenda de 23/10 (Faisaly x Nassr, Ittihad x
    Diriyah, Ahli x Khaleej, Qadsiah x Hilal). A arte gerada com os mesmos
    jogos tem de cair nelas — com folga de poucos pixels, porque a dele foi
    exportada pelo Canva e a nossa pelo Pillow.
"""
import asyncio
import io
import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

from PIL import Image                                       # noqa: E402

import agenda_arte as ag                                    # noqa: E402

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def _escudo(cor):
    im = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    for x in range(20, 100):
        for y in range(20, 100):
            im.putpixel((x, y), cor)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


ESC = _escudo((200, 40, 40, 255))
JOGOS_23_10 = [
    {"competicao": 307, "casa": "FAISALY", "fora": "NASSR", "escudo_casa": ESC,
     "escudo_fora": ESC, "hora": "10:30", "canais": ["CANAL GOAT", "XSPORTS"]},
    {"competicao": 307, "casa": "ITTIHAD", "fora": "DIRIYAH", "escudo_casa": ESC,
     "escudo_fora": ESC, "hora": "12:30", "canais": ["CANAL GOAT"]},
    {"competicao": 307, "casa": "AHLI", "fora": "KHALEEJ", "escudo_casa": ESC,
     "escudo_fora": ESC, "hora": "15:00", "canais": []},
    {"competicao": 307, "casa": "QADSIAH", "fora": "HILAL", "escudo_casa": ESC,
     "escudo_fora": ESC, "hora": "15:00", "canais": ["CANAL GOAT", "XSPORTS"]},
]
arte = Image.open(io.BytesIO(ag.montar({"data": "23/10 - SEXTA",
                                         "jogos": JOGOS_23_10}))).convert("RGB")
px = arte.load()
ok(arte.size == (1080, 1350), f"a agenda saiu {arte.size}, e não 1080x1350")


def _tinta(x0, x1, y0, y1, e_tinta):
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if e_tinta(px[x, y]):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


preto = lambda c: sum(c) < 60                                           # noqa: E731
apagado = lambda c: all(abs(v - 125) < 25 for v in c)                    # noqa: E731
branco = lambda c: min(c) > 225                                         # noqa: E731


def perto(a, b, folga):
    return a is not None and abs(a - b) <= folga


# ── AS CAIXAS: cor e lugar ──────────────────────────────────────────────
for topo, cor, nome in ((789, (1, 244, 104), "Faisaly x Nassr"),
                        (901, (1, 244, 104), "Ittihad x Diriyah"),
                        (1013, (48, 48, 48), "Ahli x Khaleej, sem transmissão"),
                        (1125, (1, 244, 104), "Qadsiah x Hilal")):
    for x in (50, 190, 380, 905, 1030):
        ok(px[x, topo + 3][:3] == cor,
           f"a caixa de {nome} em x={x} não tem a cor {cor}: {px[x, topo + 3]}")
    for x in (180, 372, 897):
        ok(px[x, topo + 3][:3] != cor,
           f"o intervalo entre as caixas de {nome} em x={x} foi pintado")
ok(px[400, 895][:3] != (1, 244, 104),
   "o intervalo de 12 px entre a 1ª e a 2ª linha sumiu")

# ── O TEXTO, contra a tinta da arte dele ────────────────────────────────
conf = _tinta(378, 893, 789, 889, preto)
ok(conf and perto(conf[1], 817, 2) and perto(conf[3], 863, 2),
   f"a tinta do confronto e dos canais da 1ª linha vai de y={conf and conf[1]} a "
   f"{conf and conf[3]}; na arte dele, de 817 a 863")
linha_conf = _tinta(378, 893, 789, 843, preto)
ok(linha_conf and perto(linha_conf[0], 483, 5) and perto(linha_conf[2], 799, 5),
   f"'FAISALY X NASSR' ocupa x={linha_conf and linha_conf[0]}–{linha_conf and linha_conf[2]}; "
   "na arte dele, 483–799")
linha_can = _tinta(378, 893, 845, 889, preto)
ok(linha_can and perto(linha_can[0], 527, 6) and perto(linha_can[2], 753, 6),
   f"'CANAL GOAT E XSPORTS' ocupa x={linha_can and linha_can[0]}–{linha_can and linha_can[2]}; "
   "na arte dele, 527–753")
hora = _tinta(903, 1033, 789, 889, preto)
ok(hora and perto(hora[0], 919, 4) and perto(hora[2], 1016, 4)
   and perto(hora[1], 831, 2) and perto(hora[3], 851, 2),
   f"o '10:30' ocupa {hora}; na arte dele, x 919–1016, y 831–851")
logo = _tinta(47, 177, 789, 889, preto)
ok(logo and perto(logo[0], 72, 4) and perto(logo[2], 152, 4)
   and perto(logo[1], 802, 4) and perto(logo[3], 874, 4),
   f"o logo do RSL ocupa {logo}; na arte dele, x 72–152, y 802–874, em PRETO")

# A linha sem transmissão: tudo apagado, e o logo também.
cinza_txt = _tinta(378, 893, 1013, 1113, apagado)
ok(cinza_txt and perto(cinza_txt[1], 1040, 3),
   f"o texto apagado da linha sem transmissão começa em y={cinza_txt and cinza_txt[1]}; "
   "na arte dele, 1040")
ok(_tinta(47, 177, 1013, 1113, preto) is None and _tinta(47, 177, 1013, 1113, apagado),
   "o logo da linha sem transmissão saiu preto; na arte dele ele é apagado")

data = _tinta(60, 700, 255, 305, branco)
ok(data and perto(data[0], 74, 3) and perto(data[1], 269, 3) and perto(data[2], 267, 6),
   f"a data ocupa {data}; na arte dele, x 74–267, y 269–291")

# ── O ESCURECIDO DE BAIXO ───────────────────────────────────────────────
claro = Image.new("RGB", (1080, 1350), (230, 230, 230))
cb = io.BytesIO()
claro.save(cb, "PNG")
sobre_claro = Image.open(io.BytesIO(ag.montar({"data": "", "foto": cb.getvalue(),
                                               "jogos": []}))).convert("L")
topo_brilho = sobre_claro.getpixel((1060, 500))
fundo_brilho = sobre_claro.getpixel((1060, 1240))
ok(topo_brilho > 200 and fundo_brilho < 40,
   f"o escurecido não está como na arte dele: brilho {topo_brilho} em y=500 e "
   f"{fundo_brilho} em y=1240 (na dele, ~88 e ~13 sobre a foto)")

# ── A CAMADA DE CIMA DELE ENTRA POR CIMA DE TUDO ────────────────────────
ok(sobre_claro.getpixel((150, 175)) > 240,
   "o título AGENDA da camada de cima não apareceu")

# ── QUANTOS JOGOS CABEM ─────────────────────────────────────────────────
ok(ag.topos_das_linhas(4) == [789, 901, 1013, 1125],
   f"com 4 jogos as linhas não caíram onde caem na arte dele: {ag.topos_das_linhas(4)}")
ok(ag.topos_das_linhas(1) == [1125], "um jogo só não ficou no lugar da última linha")
ok(ag.topos_das_linhas(3) == [901, 1013, 1125],
   "com 3 jogos as linhas não caíram onde caem na arte de 19/10")
ok(ag.topos_das_linhas(0) == [], "sem jogo nenhum, linhas apareceram")
ok(ag.escala_do_bloco(8) == 1.0, "com 8 jogos os quadros já saíram menores que os dele")

# MAIS DE 8 JOGOS (27/10/26: saíram 11, e os quadros se encavalaram). O
# bloco diminui por igual: cada quadro continua separado do seguinte, e
# nenhum sobe por cima da data.
onze = [dict(JOGOS_23_10[i % 4]) for i in range(11)]
im11 = Image.open(io.BytesIO(ag.montar({"data": "27/10 - TERÇA", "jogos": onze}))).convert("RGB")
quadros, dentro, y0 = [], False, 0
e11 = ag.escala_do_bloco(11)
x11 = round((1080 - 1080 * e11) / 2 + 386 * e11)   # junto à borda esquerda da caixa do meio
for y in range(250, 1350):
    c = im11.getpixel((x11, y))
    e_quadro = ((c[1] > 200 and c[0] < 60) or all(40 <= v <= 56 for v in c[:3]))
    if e_quadro and not dentro:
        dentro, y0 = True, y
    elif not e_quadro and dentro:
        dentro = False
        quadros.append((y0, y - 1))
ok(len(quadros) == 11,
   f"com 11 jogos a coluna do confronto tem {len(quadros)} quadros separados, e não 11: "
   f"{quadros} — os quadros se encavalaram")
ok(quadros and quadros[0][0] >= 300,
   f"com 11 jogos o primeiro quadro subiu até y={quadros and quadros[0][0]}, por cima da data")
ok(quadros and len({b - a for a, b in quadros}) <= 2,
   f"com 11 jogos os quadros saíram de alturas diferentes: {quadros}")

# ── O ESTADO DA TRANSMISSÃO ─────────────────────────────────────────────
uma = lambda canais: Image.open(io.BytesIO(ag.montar({"data": "X", "jogos": [  # noqa: E731
    dict(JOGOS_23_10[0], canais=canais)]}))).convert("RGB")
ok(uma([]).getpixel((400, 1128))[:3] == (48, 48, 48),
   "o jogo marcado SEM transmissão não saiu cinza")
ok(uma(None).getpixel((400, 1128))[:3] == (48, 48, 48),
   "jogo sem canal nenhum saiu verde; na arte dele é cinza, SEM TRANSMISSÃO")
ok(uma(["CANAL GOAT"]).getpixel((400, 1128))[:3] == (1, 244, 104),
   "jogo com canal não saiu verde")
ok(ag.nome_de_canal("Canal GOAT 🐐") == "CANAL GOAT" and ag.nome_de_canal("XSports") == "XSPORTS",
   "o nome do canal não saiu como na arte: em maiúsculas e sem emoji")
ok([t for t, _ in ag._linha_de_canais(["CANAL GOAT", "XSPORTS", "BAND"])]
   == ["CANAL GOAT", ", ", "XSPORTS", " E ", "BAND"],
   "três canais não saíram como 'A, B E C'")
ok(dict(ag._linha_de_canais(["CANAL GOAT", "XSPORTS"]))["CANAL GOAT"] is True
   and dict(ag._linha_de_canais(["CANAL GOAT", "XSPORTS"]))["XSPORTS"] is False,
   "o canal dele deixou de ir em negrito, ou os outros passaram a ir")

# Nome comprido (adversário da AFC) não estoura a caixa.
longo = Image.open(io.BytesIO(ag.montar({"data": "X", "jogos": [dict(
    JOGOS_23_10[0], casa="SHANGHAI PORT", fora="BURIRAM UNITED")]}))).convert("RGB")
px = longo.load()
t_longo = _tinta(378, 893, 1125, 1173, preto)
ok(t_longo and t_longo[0] >= 384 and t_longo[2] <= 887,
   f"'SHANGHAI PORT X BURIRAM UNITED' passou da caixa do confronto: {t_longo}")

# Sem foto, sem escudo, competição sem logo: a arte sai do mesmo jeito.
try:
    ag.montar({"data": "01/11 - SÁBADO", "jogos": [
        {"competicao": 9999, "casa": "A", "fora": "B", "hora": "09:00", "canais": None}]})
except Exception as e:
    falhas.append(f"a arte caiu com dados faltando: {e}")

for comp in (307, 504, 826, 17, 18):
    ok(ag.logo_da_competicao(comp) is not None,
       f"a competição {comp} do Bola Rolando ficou sem logo na agenda")


# ── O SERVIDOR: dos jogos da API-Football ao post na home ───────────────
def _importar_main():
    for nome in ("fastapi", "fastapi.responses", "fastapi.staticfiles",
                 "fastapi.middleware", "fastapi.middleware.cors",
                 "fastapi.templating", "httpx", "feedparser", "bs4", "dotenv",
                 "psycopg2", "psycopg2.extras", "psycopg2.extensions",
                 "apscheduler", "apscheduler.schedulers",
                 "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                 "apscheduler.triggers.cron", "apscheduler.triggers.interval",
                 "apscheduler.jobstores", "apscheduler.executors",
                 "apscheduler.schedulers.background", "starlette",
                 "starlette.middleware", "starlette.middleware.base",
                 "starlette.responses", "starlette.requests", "lxml"):
        sys.modules.setdefault(nome, MagicMock(name=nome))
    app = sys.modules["fastapi"].FastAPI.return_value
    for metodo in ("get", "post", "put", "patch", "delete", "middleware",
                   "on_event", "exception_handler", "websocket"):
        getattr(app, metodo).side_effect = lambda *a, **k: (lambda f: f)
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


main = _importar_main()
import database                                             # noqa: E402


AF_ID = {"Al-Nassr": 2939, "Al-Hilal Saudi FC": 2932}


def _fx(fid, quando, casa, fora, status="NS"):
    return {"fixture": {"id": fid, "date": quando, "status": {"short": status}},
            "teams": {"home": {"id": AF_ID.get(casa), "name": casa,
                               "logo": f"https://af/{casa}.png"},
                      "away": {"id": AF_ID.get(fora), "name": fora,
                               "logo": f"https://af/{fora}.png"}}}


RESPOSTAS = {
    307: [_fx(1, "2026-10-23T15:00:00-03:00", "Al-Qadisiyah FC", "Al-Hilal Saudi FC"),
          _fx(2, "2026-10-23T10:30:00-03:00", "Al-Faisaly FC", "Al-Nassr"),
          _fx(3, "2026-10-23T15:00:00-03:00", "Al-Ahli Jeddah", "Al Khaleej Saihat"),
          _fx(4, "2026-10-23T12:30:00-03:00", "Al-Ittihad FC", "Al Diriyah"),
          _fx(5, "2026-10-23T13:00:00-03:00", "Al-Hazm", "Abha", status="PST"),
          _fx(6, "2026-10-24T00:30:00-03:00", "NEOM", "Al Riyadh")],
    17: [_fx(7, "2026-10-23T14:00:00-03:00", "Al-Hilal Saudi FC", "Shanghai Port")],
}
RESPOSTAS[17].append(_fx(8, "2026-10-23T07:00:00-03:00", "Kyoto Sanga", "Newcastle Jets"))
RESPOSTAS[307].append(_fx(9, "2026-10-23T16:00:00-03:00", "Al-Okhdood", "Al-Fateh"))
RESPOSTAS[307].append(_fx(10, "2026-10-23T17:00:00-03:00", "Al-Taawoun", "Al-Ettifaq"))
# O estado de cada Bola Rolando na guia Agendamentos. Kyoto x Newcastle não
# tem post (é o jogo da AFC sem clube saudita que entrou em 27/10); Okhdood
# x Fateh está pendente; Taawoun x Ettifaq foi cancelado.
ESTADOS = {"bola_rolando:1": "aprovado", "bola_rolando:2": "publicado",
           "bola_rolando:3": "aprovado", "bola_rolando:4": "aprovado",
           "bola_rolando:7": "aprovado", "bola_rolando:9": "pendente",
           "bola_rolando:10": "cancelado"}
# Ittihad x Diriyah (4) foi aprovado sem canal marcado: sem transmissão.
CANAIS = {1: ["Canal GOAT 🐐", "XSports"], 2: ["Canal GOAT 🐐", "XSports"],
          3: [], 7: ["Canal GOAT 🐐"]}


async def _af(path, params, ttl=None):
    return {"response": RESPOSTAS.get(params.get("league"), [])}, None


async def _season(liga, inicio):
    return inicio


async def _times(**k):
    # O id da lista do campinho é o do Transfermarkt. O Nassr está com um
    # nome que NÃO casa por texto: só o glossário (af 2939 → tm 18544) o acha.
    return {"times": [{"id": 1114, "nome": "Al Hilal", "escudo": "https://spl/hilal.webp"},
                      {"id": 18544, "nome": "Clube 18544", "escudo": "https://spl/nassr.webp"}]}


import glossario                                            # noqa: E402


def _clube_no_glossario(af_id=None, tm_id=None, spl_id=None, nome=""):
    if af_id == 2939:
        return {"tm_id": 18544, "nome_curto": "Nassr", "escudo": "https://af/2939.png"}
    return {}


pedidos = []


async def _baixar(cli, url):
    pedidos.append(url or "")
    return ESC if url else None


FILA, ARTES, TEXTOS = {}, {}, {}


def _enfileirar(tipo, chave, texto, imagens=None, agendado_para=None):
    FILA[chave] = {"id": 50, "tipo": tipo, "chave_unica": chave, "texto": texto,
                   "imagens": list(imagens or []), "agendado_para": agendado_para,
                   "status": "pendente"}
    return "novo"


guard = (main._af_get, main._season_da_liga, main.api_elencos_times, main._baixar,
         main.transmissoes, main.enfileirar_post, main.listar_posts,
         main.atualizar_texto_post, database.salvar_post_arte, database.obter_post_arte,
         main.JSONResponse, glossario.clube, main.status_das_chaves)


class _Resp:
    def __init__(self, c=None, status_code=200, **k):
        self.dados, self.status_code = c, status_code


class _Form(dict):
    pass


class _Arquivo:
    def __init__(self, dados):
        self._d = dados

    async def read(self):
        return self._d


class _Pedido:
    def __init__(self, campos):
        self._f = _Form(campos)

    async def form(self):
        return self._f


try:
    main._af_get, main._season_da_liga = _af, _season
    main.api_elencos_times, main._baixar = _times, _baixar
    main.transmissoes = lambda ids: {i: CANAIS[i] for i in ids if i in CANAIS}
    main.enfileirar_post = _enfileirar
    main.listar_posts = lambda limite=500, **k: list(FILA.values())
    main.atualizar_texto_post = lambda pid, texto: TEXTOS.update({pid: texto}) or True
    database.salvar_post_arte = lambda chave, png, dados: ARTES.update({chave: png}) or True
    database.obter_post_arte = lambda chave: ({"png": ARTES[chave], "dados": {}}
                                              if chave in ARTES else None)
    main.JSONResponse = _Resp
    glossario.clube = _clube_no_glossario
    main.status_das_chaves = lambda chaves: {c: ESTADOS[c] for c in chaves if c in ESTADOS}
    LINHAS = []
    _montar_de_verdade = ag.montar
    ag.montar = lambda dados: LINHAS.append(dados["jogos"]) or _montar_de_verdade(dados)

    r = asyncio.run(main._montar_agenda(date(2026, 10, 23)))
    texto = r["texto"]
    linhas = LINHAS[-1] if LINHAS else []
    confrontos = [f"{l['casa']} x {l['fora']}" for l in linhas]
    ok(confrontos == ["Faisaly x Nassr", "Ittihad x Diriyah", "Hilal x Shanghai Port",
                      "Qadsiah x Hilal", "Ahli x Khaleej"],
       f"a arte de 23/10 saiu com {confrontos}; eram os 5 aprovados ou publicados na "
       "guia Agendamentos, em ordem de horário — sem o pendente, o cancelado, o "
       "da AFC sem post (Kyoto x Newcastle), o adiado e o de 00:30 do dia 24")
    ok(not any("Kyoto" in c for c in confrontos),
       "jogo da AFC sem clube saudita, sem post na guia, entrou na agenda")
    por_conf = dict(zip(confrontos, linhas))
    ok((por_conf.get("Ittihad x Diriyah") or {}).get("canais") == [],
       "jogo aprovado sem canal marcado não saiu como SEM TRANSMISSÃO (cinza)")
    ok((por_conf.get("Faisaly x Nassr") or {}).get("canais") == ["CANAL GOAT", "XSPORTS"],
       "os canais marcados não chegaram à arte")
    ok(texto == "🗓️🇸🇦 AGENDA DO DIA - Jogos da Saudi Pro League e da Champions Asiática do dia",
       f"a legenda não é o texto padrão dele: {texto!r}")
    ok(main._legenda_da_agenda([{"liga": 307, "competicao": "Liga Saudita"}] * 3)
       == "🗓️🇸🇦 AGENDA DO DIA - Jogos da Saudi Pro League do dia",
       "dia só de liga não saiu 'Jogos da Saudi Pro League do dia'")
    ok("https://spl/hilal.webp" in pedidos and "https://af/Al-Faisaly FC.png" in pedidos,
       "os escudos não vieram da lista do campinho, com a API-Football de reserva")
    ok("https://spl/nassr.webp" in pedidos,
       "o Nassr não foi achado pelo glossário (id da API-Football → id do "
       "Transfermarkt, que é o id da lista do campinho)")
    ok(r["primeiro"].startswith("2026-10-23T13:30"),
       f"o post não ficou marcado para o primeiro jogo (10h30 em Brasília): {r['primeiro']}")

    # ── O BOTÃO ─────────────────────────────────────────────────────────
    foto = io.BytesIO()
    Image.new("RGB", (3000, 2000), (10, 120, 200)).save(foto, "JPEG")
    resp = asyncio.run(main.api_agenda_gerar(_Pedido({
        "data": "2026-10-23", "foto": _Arquivo(foto.getvalue())})))
    ok(isinstance(resp, dict) and resp.get("ok") and resp.get("post") == "novo",
       f"o botão não gerou a agenda: {getattr(resp, 'dados', resp)}")
    post = FILA.get("agenda:2026-10-23") or {}
    ok(post.get("tipo") == "agenda" and post.get("imagens") == ["arte:agenda:2026-10-23"],
       f"a agenda não entrou na fila da home com a arte: {post}")
    ok("agenda-foto:2026-10-23" in ARTES
       and len(ARTES["agenda-foto:2026-10-23"]) < len(foto.getvalue()),
       "a foto enviada não foi guardada já no tamanho da arte")

    # REFAZER NO MESMO DIA: mantém a foto, troca a arte e o texto.
    arte_antes = ARTES.get("agenda:2026-10-23")
    CANAIS[3] = ["Band"]
    resp2 = asyncio.run(main.api_agenda_gerar(_Pedido({"data": "2026-10-23"})))
    ok(resp2.get("post") == "atualizado" and TEXTOS.get(50)
       and ARTES.get("agenda:2026-10-23") != arte_antes,
       "refazer a agenda depois de marcar um canal não atualizou o post")
    ok("agenda-foto:2026-10-23" in ARTES,
       "refazer sem foto apagou a foto que ele tinha enviado")

    vazio = asyncio.run(main.api_agenda_gerar(_Pedido({"data": "2026-12-25"})))
    ok(getattr(vazio, "status_code", 200) == 404, "dia sem jogo devolveu uma agenda vazia")
    ESTADOS.clear()
    nada = asyncio.run(main.api_agenda_gerar(_Pedido({"data": "2026-10-23"})))
    ok(getattr(nada, "status_code", 200) == 404
       and "Agendamentos" in str((getattr(nada, "dados", None) or {}).get("erro")),
       "dia sem jogo aprovado na guia gerou agenda, ou o erro não diz o que fazer")
    ruim = asyncio.run(main.api_agenda_gerar(_Pedido({"data": "ontem"})))
    ok(getattr(ruim, "status_code", 200) == 400, "data inválida foi aceita")
finally:
    (main._af_get, main._season_da_liga, main.api_elencos_times, main._baixar,
     main.transmissoes, main.enfileirar_post, main.listar_posts,
     main.atualizar_texto_post, database.salvar_post_arte, database.obter_post_arte,
     main.JSONResponse, glossario.clube, main.status_das_chaves) = guard
    ag.montar = _montar_de_verdade

# ── A HOME ──────────────────────────────────────────────────────────────
FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ok('id="agendaBotao"' in FONTE and "/api/agenda/gerar" in FONTE,
   "o botão de gerar agenda sumiu da home")
ok('item.get("tipo") in ("escalacao", "agenda")' in FONTE,
   "o ✓ da agenda deixou de publicar na hora")
ok("i.tipo_post === 'agenda'" in FONTE,
   "a home não mostra a arte do post da agenda")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ agenda do dia: a arte dele reproduzida, do botão ao post na home")
