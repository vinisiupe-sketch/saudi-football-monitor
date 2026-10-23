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


def _chamar(corpo, **stubs):
    """Roda a rota com o download e o glossário de mentira."""
    import glossario

    guardados = {
        "_baixar": main._baixar, "_baixar_foto": main._baixar_foto,
        "Response": main.Response, "JSONResponse": main.JSONResponse,
        "clube": glossario.clube, "quem": glossario.quem}
    main.Response = RespostaFalsa
    main.JSONResponse = RespostaFalsa

    async def baixar(cli, url):
        return b"PNG-FALSO" if url else None

    main._baixar = stubs.get("_baixar", baixar)
    main._baixar_foto = stubs.get("_baixar_foto", baixar)
    glossario.clube = stubs.get("clube", lambda **k: {
        "nome_curto": "ETTIFAQ", "escudo": "https://spl/escudo.png"})
    glossario.quem = stubs.get("quem", lambda **k: {"foto": "https://spl/foto.png"})
    try:
        return asyncio.run(main.api_elencos_card(PedidoFalso(corpo)))
    finally:
        main._baixar, main._baixar_foto = guardados["_baixar"], guardados["_baixar_foto"]
        main.Response, main.JSONResponse = guardados["Response"], guardados["JSONResponse"]
        glossario.clube, glossario.quem = guardados["clube"], guardados["quem"]


r = _chamar({"texto": TEXTO, "clube": "Al-Ettifaq", "adversario": "Al-Ittihad",
             "tecnico": "ARTHUR PAPAS", "capitao": "KANTÉ"})
ok(getattr(r, "media_type", "") == "image/png",
   f"a rota não devolveu um PNG: {getattr(r, 'media_type', '?')}")
ok(len(getattr(r, "body", b"")) > 10000,
   "o PNG veio pequeno demais para ser a arte")
ok(r.headers.get("X-Destaque") == "KANTÉ",
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
ok(r3.headers.get("X-Destaque") == "RODÁK",
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
rota = next(n for n in ast.walk(arvore)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "api_elencos_card")
importados = {a.name for n in ast.walk(rota) if isinstance(n, ast.Import)
              for a in n.names}
ok("glossario" in importados,
   "a rota usa `glossario` sem importar dentro dela. No topo do main ele não "
   "existe: em setembro um `_db` faltando assim virou NameError engolido por "
   "um `except` e o ajuste parou de funcionar em silêncio")
ok("escalacao_card" in importados,
   "a rota não importa o módulo da arte dentro dela")


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
