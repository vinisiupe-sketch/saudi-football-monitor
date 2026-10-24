"""A arte de escalação ligada na guia: rota, botão e o capitão por padrão.

O QUE ELE PEDIU
    "Eu queria que as escalações saíssem automatizadas numa arte como essa."
    "O jogador da foto grande o ideal seria eu escolher na hora, mas ele
     vindo como padrão a do capitão."

A REGRA QUE ESTE ARQUIVO DEFENDE
    A arte é o MESMO texto que ele já copia, desenhado. Não é uma segunda
    montagem da escalação: se fossem dois caminhos, um dia a imagem sairia
    com um nome e o texto copiado com outro — que é exatamente o que o star
    schema existe para impedir.
"""
import asyncio
import os
import re
import sys
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


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
    fastapi = sys.modules["fastapi"]
    app = fastapi.FastAPI.return_value
    for metodo in ("get", "post", "put", "patch", "delete", "middleware",
                   "on_event", "exception_handler", "websocket"):
        getattr(app, metodo).side_effect = lambda *a, **k: (lambda f: f)
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


main = _importar_main()


# ── A LEITURA DO TEXTO DO MATCHSHEET ────────────────────────────────────
# Este é o formato REAL que `matchsheet.texto_titulares` produz e que ele
# copia hoje: emoji de bandeira, número com dois dígitos, nome.
TEXTO = ("\U0001F1F8\U0001F1F0 01 RODÁK\n"
         "\U0001F1EC\U0001F1E7 04 HENDRY\n"
         "\U0001F1E7\U0001F1F7 05 HENRIQUE\n"
         "70 KHATEEB\n"
         "\U0001F1E8\U0001F1EE 42 KANTÉ\n"
         "61 AL OTAIBI\n")

linhas = main._linhas_da_escalacao(TEXTO)
ok(len(linhas) == 6,
   f"li {len(linhas)} linhas de 6. Uma linha perdida é um jogador que some "
   "da arte sem erro nenhum na tela")
ok(linhas[0] == {"numero": "01", "nome": "RODÁK",
                 "bandeira": "\U0001F1F8\U0001F1F0"},
   f"a primeira linha saiu errada: {linhas[0]}")
ok(linhas[3]["bandeira"] == "" and linhas[3]["nome"] == "KHATEEB",
   "a linha SEM bandeira não foi lida. Jogador sem nacionalidade cruzada sai "
   "sem bandeira de propósito — e tem de sair na arte do mesmo jeito")
ok(linhas[5]["nome"] == "AL OTAIBI",
   "o nome com espaço no meio foi cortado; metade dos nomes desta liga tem")
ok(main._linhas_da_escalacao("") == []
   and main._linhas_da_escalacao("Técnico: Arthur Papas") == [],
   "uma linha que não é jogador entrou na lista")
ok(main._linhas_da_escalacao("1 DUDA")[0]["numero"] == "1",
   "o número veio alterado já na leitura; quem põe o zero à esquerda é a "
   "arte, e ter duas regras para isso é ter duas respostas")


# ── A ROTA ──────────────────────────────────────────────────────────────
class PedidoFalso:
    def __init__(self, corpo):
        self._corpo = corpo

    async def json(self):
        return self._corpo


class RespostaFalsa:
    """O FastAPI está mockado neste teste, então `Response` não guarda nada.

    Sem isto, `media_type` e os cabeçalhos voltam como MagicMock e TODA
    asserção passa — inclusive as que deveriam cair."""

    def __init__(self, conteudo=None, media_type=None, headers=None,
                 status_code=200, **resto):
        self.body = conteudo if isinstance(conteudo, (bytes, bytearray)) else b""
        self.dados = conteudo if isinstance(conteudo, dict) else None
        self.media_type = media_type
        self.headers = dict(headers or {})
        self.status_code = status_code


# O ELENCO DO CAMPINHO, como a guia de Elencos o entrega: nome já resolvido
# pelo glossário na fonte que ele escolheu, foto, bandeira em emoji e número.
ELENCO = {"jogadores": [
    {"numero": 1, "nome": "Marko Rodák", "foto": "https://spl/1.png",
     "pais_bandeira": "\U0001F1F8\U0001F1F0"},
    {"numero": 99, "nome": "Chancel Mbemba", "foto": "https://spl/99.png",
     "pais_bandeira": "\U0001F1E8\U0001F1E9"},
    {"numero": 42, "nome": "Kanté", "foto": "https://spl/42.png",
     "pais_bandeira": "\U0001F1E8\U0001F1EE"},
]}
# COMO A LISTA DE CLUBES DO CAMPINHO É DE VERDADE: a fonte é a SPL — nome
# curto da SPL, escudo da SPL (.webp) e id do TRANSFERMARKT.
#
# Esta lista já esteve escrita aqui com escudos e ids da API-Football. Era o
# formato que eu IMAGINEI, a partir de uma resposta que não conferi de onde
# vinha (24/10/26). O código foi feito para esse formato, o teste usava esse
# formato, tudo passava — e no ar nenhum técnico saiu com bandeira, porque o
# id da API-Football nunca estava lá. Dado de teste tem de ser cópia do real.
TIMES = {"fonte": "spl", "avisos": [], "times": [
    {"id": 7732, "nome": "Al Ettifaq", "sigla": "ETT",
     "escudo": "https://media-sdp.spl.com.sa/clubLogos/ab988d0ad28b419b96ab3cf2c49e0f6f.webp"},
    {"id": 8023, "nome": "Al Ittihad", "sigla": "ITT",
     "escudo": "https://media-sdp.spl.com.sa/clubLogos/5c55f144687d497da1249c312392bb47.webp"},
    {"id": 1114, "nome": "Al Hilal", "sigla": "HIL",
     "escudo": "https://media-sdp.spl.com.sa/clubLogos/ae14a651fb584440979f8c4d02b89428.webp"},
]}
# E a lista de clubes da liga NA API-FOOTBALL, com os nomes de lá — é dela que
# sai o id para perguntar pelo técnico.
TEAMS_AF = {"response": [
    {"team": {"id": 2934, "name": "Al-Ettifaq"}},
    {"team": {"id": 2938, "name": "Al-Ittihad FC"}},
    {"team": {"id": 2932, "name": "Al-Hilal Saudi FC"}},
    {"team": {"id": 2933, "name": "Al-Qadisiyah FC"}},
]}


def _com_times(responde_tecnico):
    """Stub da API-Football: a lista de clubes de verdade, e o técnico do teste."""
    async def af(path, params, ttl=None):
        if path == "teams":
            return TEAMS_AF, None
        return await responde_tecnico(path, params, ttl)
    return af


def _chamar(corpo, **stubs):
    """Roda a rota com as portas do campinho e o download de mentira."""
    guardados = {
        "_baixar": main._baixar, "_baixar_foto": main._baixar_foto,
        "Response": main.Response, "JSONResponse": main.JSONResponse,
        "jogadores": main.api_elencos_jogadores, "times": main.api_elencos_times,
        "af": main._af_get}
    main.Response = RespostaFalsa
    main.JSONResponse = RespostaFalsa

    async def baixar(cli, url):
        return b"PNG-FALSO" if url else None

    async def elenco(**k):
        return stubs.get("elenco", ELENCO)

    async def times(**k):
        return stubs.get("times", TIMES)

    main._baixar = stubs.get("_baixar", baixar)
    main._baixar_foto = stubs.get("_baixar_foto", baixar)
    main.api_elencos_jogadores = elenco
    main.api_elencos_times = times

    async def tecnico(path, params, ttl=None):
        resposta = stubs.get("af", (None, "sem chave no teste"))
        if callable(resposta):
            return await resposta(path, params, ttl)
        return resposta

    main._af_get = _com_times(tecnico)

    # O TRANSFERMARKT de mentira também: sem isto o teste tentava o TM de
    # verdade, esperava 3 s e 6 s entre as tentativas e levava meio minuto.
    import elenco_tm as _tm
    _tm_real = _tm.tecnico

    async def tm(clube_id):
        return stubs.get("tm", ({}, "sem Transfermarkt no teste"))
    _tm.tecnico = tm
    try:
        return asyncio.run(main.api_elencos_card(PedidoFalso(corpo)))
    finally:
        main._baixar, main._baixar_foto = guardados["_baixar"], guardados["_baixar_foto"]
        main.Response, main.JSONResponse = guardados["Response"], guardados["JSONResponse"]
        main.api_elencos_jogadores = guardados["jogadores"]
        main.api_elencos_times = guardados["times"]
        main._af_get = guardados["af"]
        _tm.tecnico = _tm_real


r = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "adversario": "Al-Ittihad",
             "tecnico": "ARTHUR PAPAS", "capitao": "KANTÉ"})
ok(getattr(r, "media_type", "") == "image/png",
   f"a rota não devolveu um PNG: {getattr(r, 'media_type', '?')}")
ok(len(getattr(r, "body", b"")) > 10000,
   "o PNG veio pequeno demais para ser a arte")
# "Kanté" e não "KANTÉ": o capitão foi escolhido pelo nome que a TELA mostra
# (o do texto), e depois ganhou a grafia do campinho. As duas coisas ao mesmo
# tempo são o ponto — a escolha dele continua valendo com o nome novo.
ok(r.headers.get("X-Destaque") == "Kanté",
   f"o destaque saiu '{r.headers.get('X-Destaque')}' e não o capitão. Ele "
   "pediu o capitão como padrão")

# A ESCOLHA DELE MANDA no capitão.
r2 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "capitao": "KANTÉ",
              "destaque": "HENRIQUE"})
ok(r2.headers.get("X-Destaque") == "HENRIQUE",
   "a escolha na tela foi ignorada e a arte saiu com o capitão. O seletor "
   "existe porque ele quer trocar na hora")

# Sem capitão e sem escolha, alguém tem de ser o destaque: arte sem foto é a
# arte pela metade.
r3 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq"})
ok(r3.headers.get("X-Destaque") == "Rodák",
   f"sem capitão a arte não escolheu ninguém ({r3.headers.get('X-Destaque')})")

# O QUE FALTOU TEM DE SER DITO. Foto e escudo somem calados na imagem.
async def _nada(cli, url):
    return None


r4 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq"},
             _baixar=_nada, _baixar_foto=_nada)
faltou = r4.headers.get("X-Faltou") or ""
ok("foto" in faltou and "escudo" in faltou,
   f"a arte saiu sem foto e sem escudo e o cabeçalho disse '{faltou}'. Ele "
   "publicaria a imagem furada sem perceber")
ok((_chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "adversario": "Al-Ittihad"})
    .headers.get("X-Faltou")) == "nada",
   "com tudo baixado o cabeçalho ainda acusa falta — aviso que sempre aparece "
   "é aviso que ele aprende a ignorar")
ok("escudo-adversario" in (_chamar({"texto": TEXTO, "clube": "Al-Ettifaq"})
                           .headers.get("X-Faltou") or ""),
   "sem o adversário o escudo do canto sai vazio e ninguém é avisado")

vazio = _chamar({"texto": "Técnico: ninguém", "clube": "X"})
ok(getattr(vazio, "status_code", 200) == 400,
   "texto sem jogador nenhum devolveu uma arte em vez de dizer o que houve")


# ── O IMPORT QUE JÁ ME PEGOU UMA VEZ ────────────────────────────────────
import ast                                                 # noqa: E402

arvore = ast.parse(FONTE)
# A ROTA só lê o pedido e devolve a imagem; quem monta a arte é
# `_montar_arte_escalacao`, que o post automático de escalação também usa
# (24/10/26). As conferências abaixo olham para ela — e a rota tem de passar
# por ela, senão a arte do botão e a do post divergem.
_rota_http = next(n for n in ast.walk(arvore)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "api_elencos_card")
ok("_montar_arte_escalacao" in {c.func.id for c in ast.walk(_rota_http)
                                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)},
   "a rota da arte deixou de usar a mesma montagem do post automático")
rota = next(n for n in ast.walk(arvore)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_montar_arte_escalacao")
importados = {a.name for n in ast.walk(rota) if isinstance(n, ast.Import)
              for a in n.names}
ok("escalacao_card" in importados,
   "a rota não importa o módulo da arte dentro dela")

# A rota NÃO PODE resolver por conta própria. Ela pergunta às mesmas portas
# que o campinho usa — foi isso que ele cortou em 23/10/26: "você tá
# complicando coisas que já temos (...) temos tudo lá". Um segundo caminho
# para a mesma pergunta um dia responde diferente, e aí a arte e o campinho
# mostram grafias distintas do mesmo jogador.
# Desde 24/10/26 quem resolve o time é `_lado_da_escalacao`, a função que a
# arte E a legenda usam. A rota tem de passar por ela, e ela pelas portas.
_lado_fn = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_lado_da_escalacao")
_chamadas_rota = {n.func.id for n in ast.walk(rota)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
ok("_lado_da_escalacao" in _chamadas_rota,
   "a rota da arte deixou de resolver o time pela função compartilhada; arte e "
   "legenda do mesmo jogo voltariam a poder discordar")
chamadas = {n.func.id for n in ast.walk(_lado_fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
ok("api_elencos_jogadores" in chamadas,
   "a rota deixou de pedir o elenco à guia de Elencos. Nome, foto e bandeira "
   "voltam a ser resolvidos por um caminho só dela")
ok("api_elencos_times" in chamadas,
   "a rota deixou de pedir os clubes à mesma lista que desenha os chips de "
   "filtro do campinho")
atributos = {n.func.attr for n in ast.walk(rota)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
ok("clube" not in atributos and "quem" not in atributos,
   "a rota voltou a consultar o glossário direto, em paralelo ao campinho")


# ── O CAPITÃO É GRAVADO ─────────────────────────────────────────────────
# NOS DOIS LADOS: conferir só `in FONTE` passava com o capitão apagado da
# casa, porque a linha do `fora` sozinha já satisfazia a busca.
_grava = FONTE.count('for k in ("time", "tecnico", "texto", "deduzidos", "capitao")')
ok(_grava == 2,
   f"o capitão é gravado em {_grava} dos 2 lados do jogo. A marca 'C' só "
   "existe no parse do PDF; sem gravar, o padrão da arte se perde — e some "
   "só para um dos times, que é o defeito mais difícil de enxergar")
ok('dados[lado]["capitao"]' in FONTE,
   "ninguém calcula o capitão a partir dos titulares")


# ── O NOME CURTO DO CLUBE (23/10/26) ────────────────────────────────────
#
#   "não saiu o nome reduzido do clube"
#
# O DIM_CLUBE estava vazio — a semeadura nunca rodou — e a arte saiu com
# "DIRIYAH CLUB" ocupando a largura toda. A curadoria dele continua mandando
# quando existe; isto aqui é a reserva para quando não existe.
for bruto, esperado in (("DIRIYAH CLUB", "DIRIYAH"), ("AL ITTIHAD", "ITTIHAD"),
                        ("Al-Ettifaq", "ETTIFAQ"), ("Al Ahli SFC", "AHLI"),
                        ("Al-Qadsiah FC", "QADSIAH"), ("NEOM", "NEOM")):
    got = main._nome_curto_de_clube(bruto)
    ok(got == esperado,
       f"'{bruto}' virou '{got}' e devia virar '{esperado}'")

ok(main._nome_curto_de_clube("AL") == "AL"
   and main._nome_curto_de_clube("") == "",
   "a regra esvaziou o nome do clube. Arte sem o nome do time não serve")

r5 = _chamar({"texto": TEXTO, "clube": "Diriyah Club", "adversario": "Al Ittihad"},
             times={"times": []})
ok(r5.headers.get("X-Clube") == "DIRIYAH",
   f"a arte saiu com '{r5.headers.get('X-Clube')}'. Era 'DIRIYAH CLUB' "
   "inteiro que ele viu na tela")


# ── O ESCUDO SAI DOS CHIPS DO CAMPINHO (23/10/26) ───────────────────────
#
#   "Na aba campinho temos os escudos que servem de filtro. Use aquela
#    origem."
#
r7 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "adversario": "Al Ittihad"})
ok((r7.headers.get("X-Faltou") or "") == "nada",
   f"os escudos não vieram da lista de clubes do campinho "
   f"('{r7.headers.get('X-Faltou')}') — é a mesma lista dos chips de filtro")

# A grafia do clube muda entre a folha oficial e a lista: "Al Ittihad" x
# "Al-Ittihad Club". Os dois lados passam pelo padronizador, como no resto
# do app; sem isso o escudo do adversário volta a faltar.
ok("escudo-adversario" not in (r7.headers.get("X-Faltou") or ""),
   "o escudo do adversário não casou porque o nome vem escrito diferente na "
   "folha oficial e na lista de clubes")

# E quando a lista não responder, o endereço que a tela já exibe assume.
r8 = _chamar({"texto": TEXTO, "clube": "X", "adversario": "Y",
              "escudo": "https://a.png", "escudo_adversario": "https://b.png"},
             times={"times": []})
ok((r8.headers.get("X-Faltou") or "") == "nada",
   "com a lista de clubes fora do ar os blocos do canto saíram vazios, "
   "mesmo a tela tendo mandado o escudo que ela já mostra no card")

ok("data-escudo=" in FONTE and "escudo: botao.dataset.escudo" in FONTE,
   "a tela parou de mandar o escudo de reserva")


# ── O NOME E A BANDEIRA VÊM DO CAMPINHO ─────────────────────────────────
#
#   "o nome usado no campinho é também a melhor fonte pra buscar nome dos
#    jogadores. Temos tudo lá."
#
r9 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "adversario": "Al Ittihad",
              "destaque": "KANTÉ"})
ok(r9.headers.get("X-Destaque") == "Kanté",
   f"o destaque saiu '{r9.headers.get('X-Destaque')}'. Quem casou pelo "
   "número tem de ganhar o nome do campinho — a grafia que ele escolheu em "
   "Ajustes, e não a que o PDF escreveu")
# Dois dos seis: o elenco de mentira só tem as camisas 1, 42 e 99, e a 99 não
# está nesta folha. O número existe para ele ver quando o elenco não carregou.
ok(r9.headers.get("X-Do-Campinho") == "2/6",
   f"o cruzamento com o elenco reconheceu {r9.headers.get('X-Do-Campinho')} "
   "e deviam ser 2 de 6")

# O QUE REALMENTE CHEGA NA ARTE. Os cabeçalhos contam o cruzamento, mas não
# provam que nome, bandeira e foto foram repassados — apagar a linha da
# bandeira passava calado neste teste até 23/10/26.
import escalacao_card as _ec                                # noqa: E402

_capturado = {}
_montar_real = _ec.montar
try:
    _ec.montar = lambda d: (_capturado.update(d), _montar_real(d))[1]
    _chamar({"texto": "01 RODAK DO PDF\n70 KHATEEB\n", "clube": "Al-Ettifaq"})
finally:
    _ec.montar = _montar_real

_lista = _capturado.get("jogadores") or []
ok(len(_lista) == 2, f"chegaram {len(_lista)} jogadores na arte, e eram 2")
if len(_lista) == 2:
    casou, nao_casou = _lista[0], _lista[1]
    ok(casou["nome"] == "Rodák",
       f"o nome que chegou à arte foi '{casou['nome']}'. A placa do campinho "
       "escreve a ÚLTIMA palavra do nome do elenco (nomeCurto em "
       "campinho.html) — mandar o nome inteiro fez a arte do Hilal sair "
       "'KALIDOU KOULIBA...' estourando a borda. E não o do PDF: o "
       "campinho tem a grafia que ele escolheu em Ajustes")
    ok(casou["bandeira"] is not None,
       "o jogador que casou com o elenco chegou à arte sem bandeira")
    ok(nao_casou["nome"] == "KHATEEB",
       "quem o elenco não reconheceu perdeu o nome do PDF e some da arte")

ok((_capturado.get("clube") or "") == "ETTIFAQ",
   f"o nome curto que chegou à arte foi '{_capturado.get('clube')}'")


# A PONTE É O NÚMERO: a folha escreve "01" e o elenco guarda 1.
r9b = _chamar({"texto": "01 QUALQUER\n", "clube": "Al-Ettifaq"})
ok(r9b.headers.get("X-Do-Campinho") == "1/1",
   "o zero à esquerda da folha oficial não casou com o número do elenco. "
   "São as duas pontas do mesmo jogador e nenhuma arte casaria")

# O CASO QUE ELE VIU: o PDF escreve a inicial, o campinho tem o nome inteiro.
r9c = _chamar({"texto": "99 C. MBEMBA\n", "clube": "Al-Ettifaq",
               "destaque": "C. MBEMBA"})
ok(r9c.headers.get("X-Destaque") == "Mbemba",
   f"'C. MBEMBA' do PDF saiu como '{r9c.headers.get('X-Destaque')}'. O "
   "campinho tem o nome inteiro, resolvido na fonte que ele escolheu — era "
   "essa a origem que ele mandou usar")

# Quem o elenco não conhece FICA com a linha do PDF. Some ninguém.
r10 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "destaque": "KHATEEB"})
ok(r10.headers.get("X-Destaque") == "KHATEEB",
   "o jogador que o elenco não reconheceu sumiu em vez de ficar com o nome "
   "do PDF. Linha a menos na arte é pior que grafia imperfeita")

r11 = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq"}, elenco={"jogadores": []})
ok(r11.headers.get("X-Do-Campinho") == "0/6"
   and len(getattr(r11, "body", b"")) > 10000,
   "com o elenco vazio a arte não saiu. Ela tem de sair com o que o PDF deu")


# ── A BANDEIRA DE EMOJI CHEGA AO MÓDULO ─────────────────────────────────
# A BANDEIRA: o emoji do CAMPINHO vira a sigla, e a sigla vira a imagem do
# país — como no campinho. Prova pelo endereço pedido: a linha "70 KHATEEB"
# do PDF não tem emoji nenhum, e mesmo assim a bandeira certa tem de ser
# pedida quando o elenco conhece a camisa.
pedidos = []


async def _anota(cli, url):
    pedidos.append(url or "")
    return b"PNG-FALSO" if url else None


_chamar({"texto": "70 KHATEEB\n", "clube": "Al-Ettifaq"},
        _baixar=_anota, _baixar_foto=_anota,
        elenco={"jogadores": [{"numero": 70, "nome": "Abdullah Khateeb",
                               "foto": "https://spl/70.png",
                               "pais_bandeira": "\U0001F1F8\U0001F1E6"}]})
ok(any(u.endswith("/sa.png") for u in pedidos),
   f"a bandeira do campinho não foi pedida (pedidos: {pedidos}). O emoji "
   "está no elenco e na linha do PDF; a arte tem de desenhar a imagem do "
   "país a partir dele, como o campinho")

# E NADA DE FONTE DE EMOJI NO BUILD: ela existiu por um commit e produziu a
# arte do Hilal com letras no lugar das bandeiras.
NIX = open(os.path.join(RAIZ, "nixpacks.toml"), encoding="utf-8").read()
_linha_apt = next((l for l in NIX.splitlines() if l.strip().startswith("aptPkgs")), "")
ok("ffmpeg" in _linha_apt,
   "o ffmpeg saiu da imagem — é ele que corta a fita dos clipes")
ok("emoji" not in _linha_apt,
   "a fonte de emoji voltou ao build. Desenhada pelo Pillow ela vira \"SA\", "
   "\"NL\" em letras — a bandeira certa é a imagem, como no campinho")


# ── O NOME DO CLUBE SAI DA FOLHA OFICIAL ────────────────────────────────
# Cada base escreve o clube do seu jeito ("Al-Hilal Saudi FC" na API-Football,
# "Al Hilal" na SPL). O nome da arte vem da folha, que é a grafia aprovada.
r12 = _chamar({"texto": TEXTO, "clube": "AL HILAL", "adversario": "AL ITTIHAD"})
ok(r12.headers.get("X-Clube") == "HILAL",
   f"o nome do clube saiu '{r12.headers.get('X-Clube')}'. A lista do campinho "
   "escreve o clube do seu jeito; o nome da arte vem da folha")
ok("escudo" not in (r12.headers.get("X-Faltou") or "").replace("escudo-adversario", ""),
   "o escudo do Hilal não casou com a lista de clubes do campinho")


# ── A BANDEIRA DO TÉCNICO (23/10/26) ────────────────────────────────────
#
#   "Não tá vindo o emoji do país do treinador."
#
COACHS = {"response": [
    {"name": "S. Inzaghi", "firstname": "Simone", "lastname": "Inzaghi",
     "nationality": "Italy",
     "career": [{"team": {"id": 2932}, "start": "2025-06-03", "end": None},
                {"team": {"id": 505}, "start": "2021-07-01", "end": "2025-06-02"}]},
    {"name": "J. Jesus", "firstname": "Jorge", "lastname": "Jesus",
     "nationality": "Portugal",
     "career": [{"team": {"id": 2932}, "start": "2023-07-01", "end": "2025-06-01"}]},
]}
pedidos_af = []


async def _baixa_anotando(cli, url):
    pedidos_af.append(url or "")
    return b"PNG-FALSO" if url else None


r13 = _chamar({"texto": TEXTO, "clube": "AL HILAL", "adversario": "AL ITTIHAD",
               "tecnico": "SIMONE INZAGHI"},
              af=(COACHS, None), _baixar=_baixa_anotando)
ok(any(u.endswith("/it.png") for u in pedidos_af),
   f"a bandeira da Itália não foi pedida para o Inzaghi (pedidos: "
   f"{[u for u in pedidos_af if 'flagcdn' in u]}). A nacionalidade vem da "
   "API-Football, pelo id do clube na lista de clubes DELA")
ok("bandeira-tecnico" not in (r13.headers.get("X-Faltou") or ""),
   "com a bandeira do técnico encontrada, o cabeçalho ainda acusou falta")

# QUEM MANDA É A FOLHA OFICIAL. A API-Football devolve todo mundo que já
# treinou o clube — aqui o Jorge Jesus, que passou pelo Hilal. O nome escrito
# na folha decide qual deles é: com "SIMONE INZAGHI" sai a Itália, com
# "JORGE JESUS" sai Portugal, mesmo que a carreira dele lá esteja fechada —
# a folha é de hoje, a carreira da API pode estar atrasada.
async def _af_coachs(path, params, ttl=None):
    return COACHS, None
_af_guardado = main._af_get
try:
    main._af_get = _com_times(_af_coachs)
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", "SIMONE INZAGHI"))[0] == "🇮🇹",
       "o técnico atual do Hilal não saiu com a bandeira da Itália")
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", "JORGE JESUS"))[0] == "🇵🇹",
       "o técnico escrito na folha perdeu para quem a API diz ser o atual. A "
       "folha oficial é do dia do jogo")
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", "ROBERTO"))[0] == "🇮🇹",
       "sem sobrenome que case, o ÚNICO técnico atual do clube devia ser "
       "usado — a folha às vezes traz só um nome, como 'BRUNO' e 'THOMAS'")
    # Clube que a API-Football não conhece: sem id, sem pergunta, e o motivo
    # diz o que houve — é ele que vai para o log.
    emo, motivo = asyncio.run(main._emoji_do_tecnico("CLUBE INVENTADO", "SIMONE INZAGHI"))
    ok(emo == "" and "lista de clubes da API-Football" in motivo,
       f"um clube que a API não conhece devolveu {emo!r} / {motivo!r}")
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", ""))[0] == "",
       "sem nome de técnico a função perguntou mesmo assim")
finally:
    main._af_get = _af_guardado

# ── QUANDO O CADASTRO DA API-FOOTBALL ESTÁ ATRASADO (24/10/26) ─────────
#
#   "Os técnicos todos estão vindo sem bandeira."
#
# Perguntar só "quem treina o clube X?" depende de a API já ter registrado a
# troca de técnico. Se ela ainda devolve o anterior, o nome da folha não casa
# e a bandeira some. A segunda pergunta é pelo sobrenome.
ANTIGO = {"response": [
    {"name": "J. Jesus", "firstname": "Jorge", "lastname": "Jesus",
     "nationality": "Portugal", "team": {"id": 2932},
     "career": [{"team": {"id": 2932}, "start": "2023-07-01", "end": None}]}]}
BUSCA_INZAGHI = {"response": [
    {"name": "F. Inzaghi", "firstname": "Filippo", "lastname": "Inzaghi",
     "nationality": "Italy", "team": {"id": 999},
     "career": [{"team": {"id": 999}, "start": "2024-07-01", "end": None}]},
    {"name": "S. Inzaghi", "firstname": "Simone", "lastname": "Inzaghi",
     "nationality": "Italy", "team": {"id": 505},
     "career": [{"team": {"id": 2932}, "start": "2025-06-03", "end": None},
                {"team": {"id": 505}, "start": "2021-07-01", "end": "2025-06-02"}]}]}
perguntas_feitas = []


async def _af_atrasada(path, params, ttl=None):
    perguntas_feitas.append(dict(params))
    if "team" in params:
        return ANTIGO, None
    if params.get("search") == "Inzaghi":
        return BUSCA_INZAGHI, None
    return {"response": []}, None


_af_guardado = main._af_get
try:
    main._af_get = _com_times(_af_atrasada)
    emo, motivo = asyncio.run(main._emoji_do_tecnico("AL HILAL", "SIMONE INZAGHI"))
    ok(emo == "🇮🇹",
       f"com a API ainda achando que o Jorge Jesus treina o Hilal, o Inzaghi "
       f"ficou sem bandeira ({motivo!r}). A busca pelo sobrenome da folha "
       "tinha de achá-lo")
    ok({"search": "Inzaghi"} in perguntas_feitas,
       "a segunda pergunta, pelo sobrenome, não foi feita")
    ok("Jesus" not in (motivo or ""),
       "o técnico antigo ganhou do nome escrito na folha")

    # Pela busca, sem ligação nenhuma com o clube, só o nome INTEIRO serve —
    # e só se for um. "Filippo Inzaghi" não é "Simone Inzaghi".
    async def _af_so_filippo(path, params, ttl=None):
        if "team" in params:
            return {"response": []}, None
        return {"response": [BUSCA_INZAGHI["response"][0]]}, None
    main._af_get = _com_times(_af_so_filippo)
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", "SIMONE INZAGHI"))[0] == "",
       "o Filippo Inzaghi foi aceito como técnico do Hilal só por ter o "
       "sobrenome. Bandeira errada no técnico é pior que nenhuma")

    # O CADASTRO ATRASADO E A BUSCA SEM NADA: a API diz que o Jorge Jesus
    # treina o Hilal e não acha nenhum Inzaghi. A folha diz SIMONE INZAGHI.
    # Dar a bandeira de Portugal aqui é pôr no ar a nacionalidade de outra
    # pessoa — o palpite "único atual" não vale para nome completo.
    async def _af_so_jesus(path, params, ttl=None):
        if "team" in params:
            return ANTIGO, None
        return {"response": []}, None
    main._af_get = _com_times(_af_so_jesus)
    emo, motivo = asyncio.run(main._emoji_do_tecnico("AL HILAL", "SIMONE INZAGHI"))
    ok(emo == "",
       f"a folha diz SIMONE INZAGHI e a arte saiu com a bandeira de quem a API "
       f"acha que treina o clube ({motivo!r}). Bandeira errada no técnico é "
       "pior que nenhuma")
    # Com UM nome só na folha, o único atual vale — pode ser apelido.
    ok(asyncio.run(main._emoji_do_tecnico("AL HILAL", "MISTER"))[0] == "🇵🇹",
       "folha com um nome só (como BRUNO, THOMAS) e um único técnico atual: "
       "esse devia ser usado")

    # A PERGUNTA VAI PARA O CLUBE CERTO. A folha do Hilal pergunta pelo id
    # do Hilal na API-Football (2932), e não pelo do adversário.
    perguntas_feitas.clear()
    _chamar({"texto": TEXTO, "clube": "AL HILAL", "adversario": "AL ITTIHAD",
             "tecnico": "SIMONE INZAGHI"}, af=_af_atrasada)
    ok({"team": 2932} in perguntas_feitas and {"team": 2938} not in perguntas_feitas,
       f"a API foi perguntada sobre {perguntas_feitas}: o técnico do Hilal tem "
       "de ser procurado no Hilal (2932)")

    # A LIGAÇÃO TAMBÉM PELO NOME DO TIME. Quando o id que a busca devolve não
    # bate com o da lista de clubes, o nome padronizado decide. Folha com uma
    # palavra só ("INZAGHI"), sem a regra do nome inteiro para salvar.
    async def _af_ids_trocados(path, params, ttl=None):
        if "team" in params:
            return {"response": []}, None
        return {"response": [
            {"name": "F. Inzaghi", "firstname": "Filippo", "lastname": "Inzaghi",
             "nationality": "Brazil", "team": {"id": 999, "name": "Benevento"},
             "career": [{"team": {"id": 999, "name": "Benevento"}, "end": None}]},
            {"name": "S. Inzaghi", "firstname": "Simone", "lastname": "Inzaghi",
             "nationality": "Italy", "team": {"id": 77777, "name": "Al-Hilal Saudi FC"},
             "career": [{"team": {"id": 77777, "name": "Al-Hilal Saudi FC"}, "end": None}]},
        ]}, None
    main._af_get = _com_times(_af_ids_trocados)
    emo, motivo = asyncio.run(main._emoji_do_tecnico("AL HILAL", "INZAGHI"))
    ok(emo == "🇮🇹",
       f"o técnico do Hilal veio com outro id e o nome do time não foi usado "
       f"para reconhecer o clube ({emo!r}, {motivo!r})")

    # E O MOTIVO VOLTA quando falha — é o que vai para o log.
    async def _af_fora(path, params, ttl=None):
        return None, "API-Football: limite diário atingido"
    main._af_get = _com_times(_af_fora)
    emo, motivo = asyncio.run(main._emoji_do_tecnico("AL HILAL", "SIMONE INZAGHI"))
    ok(emo == "" and "limite" in motivo,
       f"a API recusou e o motivo se perdeu ({motivo!r}). Foi a falta dele que "
       "deixou a bandeira faltando sem ninguém saber por quê")
finally:
    main._af_get = _af_guardado

ok('print(f"🎨 arte' in FONTE,
   "a arte parou de registrar no log o que aconteceu com a bandeira do técnico")


# ── CABEÇALHO COM Ě, Ć, Š NÃO PODE DERRUBAR A ARTE ──────────────────────
# No ar em 23/10/26: "J. STANĚK" no cabeçalho do destaque e erro 500 —
# cabeçalho HTTP só aceita latin-1. Com o Milinković-Savić ou o Rajković no
# destaque, a arte simplesmente não saía.
r15 = _chamar({"texto": "\U0001F1E8\U0001F1FF 36 J. STANĚK\n\U0001F1F7\U0001F1F8 22 S. MILINKOVIĆ-SAVIĆ\n",
               "clube": "AL HAZEM", "destaque": "S. MILINKOVIĆ-SAVIĆ",
               "tecnico": "MARINO PUŠIĆ"},
              elenco={"jogadores": []})
try:
    for _k, _v in r15.headers.items():
        str(_v).encode("latin-1")
    _cab_ok = True
except UnicodeEncodeError as _e:
    _cab_ok = False
    falhas.append(f"um cabeçalho não é latin-1 ({_e}). No ar isso é erro 500 "
                  "e a arte não sai — foi o 'STANĚK' de 23/10/26")
ok(_cab_ok and "MILINKOVIC" in (r15.headers.get("X-Destaque") or "").upper(),
   f"o destaque perdeu o nome no cabeçalho: {r15.headers.get('X-Destaque')!r}")


# ── UMA FUNÇÃO, UM NOME ─────────────────────────────────────────────────
# Eu escrevi uma segunda `_sem_acento` e ela substituiu a primeira no arquivo
# inteiro, em silêncio, por um commit. Nome repetido no módulo é isso.
import collections as _col                                 # noqa: E402

_defs = _col.Counter(n.name for n in ast.parse(FONTE).body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
_repetidas = sorted(n for n, q in _defs.items() if q > 1)
ok(not [n for n in _repetidas if n in ("_sem_acento", "_emoji_do_tecnico",
                                       "_cabecalho", "_nome_da_placa",
                                       "_linhas_da_escalacao")],
   f"funções definidas duas vezes no main.py: {_repetidas}. A segunda apaga "
   "a primeira em todo o arquivo")


# Sem a nacionalidade, o aviso aparece — só quando HÁ técnico na folha.
r14 = _chamar({"texto": TEXTO, "clube": "AL HILAL", "tecnico": "SIMONE INZAGHI"})
ok("bandeira-tecnico" in (r14.headers.get("X-Faltou") or ""),
   "a bandeira do técnico faltou e ninguém foi avisado")


# ── A BANDEIRA DA INGLATERRA ────────────────────────────────────────────
# No elenco ela é um emoji de outro tipo, que não vira sigla. A linha do PDF
# tem o 🇬🇧, e ele tem de ficar.
INGLATERRA = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
pedidos_ing = []


async def _anota_ing(cli, url):
    pedidos_ing.append(url or "")
    return b"PNG-FALSO" if url else None


_chamar({"texto": "\U0001F1EC\U0001F1E7 11 O. WATKINS\n", "clube": "AL HILAL"},
        _baixar=_anota_ing, _baixar_foto=_anota_ing,
        elenco={"jogadores": [{"numero": 11, "nome": "Ollie Watkins",
                               "pais_bandeira": INGLATERRA}]})
ok(any(u.endswith("/gb.png") for u in pedidos_ing),
   "o Watkins saiu sem bandeira: o emoji da Inglaterra do campinho não vira "
   "sigla e derrubou o 🇬🇧 que a linha do PDF já tinha")

# E a linha com esse emoji no TEXTO não pode sumir da arte.
_l = main._linhas_da_escalacao(INGLATERRA + " 09 TONEY\n\U0001F1F8\U0001F1E6 01 X")
ok(len(_l) == 2 and _l[0]["nome"] == "TONEY" and _l[0]["numero"] == "09",
   f"a linha com a bandeira da Inglaterra foi lida assim: {_l}")


# ── O SELETOR, RODADO NO NAVEGADOR DE VERDADE ───────────────────────────
#
#   "Não tá dando pra selecionar o jogador da foto."
#
# A expressão esperava a bandeira como 1 pedaço + 2, e no JavaScript ela são
# 4. Toda linha com bandeira sumia do seletor. Conferir o texto do código não
# pegaria isso — então aqui o JavaScript roda, no Node, com as linhas reais
# da folha do Hilal.
import json as _json                                       # noqa: E402
import shutil as _shutil                                   # noqa: E402
import subprocess as _sub                                  # noqa: E402
import tempfile as _tmp                                    # noqa: E402

_node = _shutil.which("node") or _shutil.which("nodejs")
_i = FONTE.find("function nomesDaEscalacao")
_j = FONTE.find("function prepararArte", _i)
ok(_i > 0 and _j > _i, "a função que enche o seletor sumiu da página")
if _node and _i > 0:
    # O HTML mora numa f-string: {{ vira {, e \\ vira \ — exatamente o
    # que o navegador recebe.
    _js = FONTE[_i:_j].replace("{{", "{").replace("}}", "}").replace("\\\\", "\\")
    _folha = ("\U0001F1F2\U0001F1E6 37 BONO\n\U0001F1F8\U0001F1F3 03 K. KOULIBALY\n"
              "\U0001F1F7\U0001F1F8 22 S. MILINKOVIĆ-SAVIĆ\n" + INGLATERRA
              + " 09 TONEY\n23 WIJNALDUM")
    with _tmp.NamedTemporaryFile("w", suffix=".js", delete=False,
                                 encoding="utf-8") as _arq:
        _arq.write(_js + "\nconsole.log(JSON.stringify(nomesDaEscalacao("
                   + _json.dumps(_folha) + ")));")
    _saida = _sub.run([_node, _arq.name], capture_output=True, text=True,
                      timeout=30)
    try:
        _nomes = _json.loads(_saida.stdout.strip() or "[]")
    except Exception:
        _nomes = []
    ok(_nomes == ["BONO", "K. KOULIBALY", "S. MILINKOVIĆ-SAVIĆ", "TONEY", "WIJNALDUM"],
       f"o seletor do navegador leu {_nomes}. Toda linha com bandeira tem de "
       "virar opção — foi o seletor vazio que ele não conseguiu usar")


# ── O TÉCNICO DA ARTE É O DO TRANSFERMARKT (24/10/26) ───────────────────
#
#   "Bruno Lage além de estar vindo sem bandeira tá vindo só 'Bruno'."
#
_desenhado = {}
_montar_real2 = _ec.montar
try:
    _ec.montar = lambda d: (_desenhado.update(d), _montar_real2(d))[1]
    _pedidos_tm = []

    async def _anota_tm(cli, url):
        _pedidos_tm.append(url or "")
        return b"PNG-FALSO" if url else None
    r16 = _chamar({"texto": TEXTO, "clube": "DIRIYAH CLUB", "adversario": "AL ITTIHAD",
                   "tecnico": "BRUNO"},
                  times={"times": [{"id": 1234, "nome": "Diriyah",
                                    "escudo": "https://spl/diriyah.webp"}]},
                  tm=({"nome": "Bruno Lage", "nacionalidades": ["Portugal"]}, None),
                  _baixar=_anota_tm)
finally:
    _ec.montar = _montar_real2
ok((_desenhado.get("tecnico") or {}).get("nome") == "Bruno Lage",
   f"o técnico desenhado foi {(_desenhado.get('tecnico') or {}).get('nome')!r}. "
   "A folha diz 'BRUNO'; o Transfermarkt diz 'Bruno Lage', e é ele que vale")
ok(any(u.endswith("/pt.png") for u in _pedidos_tm),
   "a bandeira de Portugal não foi pedida para o Bruno Lage")
ok("bandeira-tecnico" not in (r16.headers.get("X-Faltou") or ""),
   "com o técnico achado no Transfermarkt, o aviso de falta apareceu")


# ── O BOTÃO NA TELA ─────────────────────────────────────────────────────
ok("esc-arte" in FONTE and "🖼️ Arte" in FONTE,
   "o botão da arte sumiu da guia de Escalações")
ok("/api/elencos/card" in FONTE,
   "o botão não chama a rota da arte")
ok("esc-destaque" in FONTE and "prepararArte" in FONTE,
   "o seletor do jogador em destaque sumiu da tela")

# A arte lê o MESMO textarea do copiar — é isso que garante uma só verdade.
i = FONTE.find("function prepararArte(")
corpo_js = FONTE[i:FONTE.find("async function carregarMonitor", i)]
ok("document.getElementById(botao.dataset.alvo)" in corpo_js,
   "a arte parou de ler o textarea do copiar. Se ela buscar a escalação por "
   "outro caminho, a correção que ele faz na tela não entra na imagem")
ok("texto: campo.value" in corpo_js,
   "o que vai para a rota não é o conteúdo do campo editado")
ok("X-Faltou" in corpo_js,
   "a tela ignora o aviso do que faltou e ele publica a arte furada")

# O MESMO HTML MORA DENTRO DE UMA f-STRING DO PYTHON. Chave solta aqui
# derruba a página inteira com um erro de sintaxe lá no fim do arquivo — foi
# o que aconteceu ao escrever este botão.
trecho = FONTE[FONTE.find("jogos.forEach(function (j, i)"):
               FONTE.find("alvo.innerHTML = html;")]
soltas = [m.start() for m in re.finditer(r"(?<![{])\{(?![{])", trecho)]
ok(not soltas,
   f"há {len(soltas)} chave '{{' sem dobrar no HTML da guia. Esse arquivo é "
   "uma f-string: a página inteira vira SyntaxError")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ arte de escalação ligada na guia, com o capitão por padrão")
