"""
A porta de trás da escalação por PDF: eu buscando o PDF no mediahub e
mandando pra cá sozinho, sem você subir nada.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    Testei ao vivo: logada no mediahub, eu consigo achar o PDF certo e
    baixar os bytes — mas mandar esses bytes pra este app de DENTRO da
    página do mediahub é um pedido de OUTRA ORIGEM (CORS), e o navegador
    também não leva o cookie de sessão deste app para lá. A rota de upload
    já existia (você, pela tela, logado); esta segunda porta tinha que
    nascer sem depender de sessão de navegador — só um token, que só eu
    conheço, provando que fui eu que busquei o PDF.

    Dois jeitos de isso quebrar em silêncio, que são o que este arquivo
    vigia:
    1. Abrir CORS geral (`*`) em vez de só para mediahub.spl.media — qualquer
       site da internet passaria a poder mandar PDF pra essa rota e ler a
       resposta.
    2. Um caminho de erro novo (arquivo vazio, PDF grande demais, etc.)
       esquecer de levar o cabeçalho CORS — a resposta de erro fica muda
       para quem chamou de fora, e o defeito não aparece testando pela tela
       normal (que nunca passa por CORS, é sempre mesma origem).

Estes testes IMPORTAM main.py de verdade (com os módulos pesados — fastapi,
psycopg2 — trocados por dublês, o mesmo truque do /tmp/subir.py que já uso
antes de cada deploy), porque `_escalacao_autorizada` e `_com_cors_mediahub`
são funções pequenas e sem banco por trás — dá para chamar de verdade em vez
de só ler o texto do arquivo.
"""
import os
import sys
import types
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


class _Dublê(types.ModuleType):
    def __getattr__(self, nome):
        v = MagicMock(name=f"{self.__name__}.{nome}")
        setattr(self, nome, v)
        return v


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
        sys.modules.setdefault(nome, _Dublê(nome))
    sys.modules.pop("main", None)
    import main
    return main


class _RequestFalso:
    """Só o suficiente de fastapi.Request para as funções que eu testo."""

    def __init__(self, cookie: str = "", token: str = ""):
        self.cookies = {"iar_sessao": cookie} if cookie else {}
        self.headers = {"X-Escalacao-Token": token} if token else {}


class _RespostaFalsa:
    """fastapi vem trocado por dublê (MagicMock) neste teste — inclusive
    JSONResponse e Response, cujo `.headers` de mock não guarda o que eu
    escrevo nele. Preciso de um `.headers` que seja um dict de verdade para
    conferir os cabeçalhos de CORS que as funções escrevem."""

    def __init__(self, *args, status_code=200, **kw):
        self.headers = {}
        self.status_code = status_code
        self.corpo = args[0] if args else None


def _funcao_real_por_tras_do_decorador(main, metodo: str, caminho: str):
    """Acha a função de verdade escondida atrás de `@app.<metodo>(caminho)`.

    Com fastapi trocado por dublê, `app` é um MagicMock — o decorador não
    devolve a função original, devolve outro mock. A função de verdade só
    sobrevive presa no call_args de quando o decorador foi chamado com ela.
    `app.<metodo>(caminho)` devolve sempre o MESMO mock (`.return_value`),
    então a ORDEM em que os caminhos foram registrados é a mesma ordem em
    que as funções foram passadas para decorar — casar os dois pelo índice
    é seguro contanto que cada `@app.<metodo>(caminho)` no arquivo seja único
    (que é o caso aqui: um só `@app.options`)."""
    alvo = getattr(main.app, metodo)
    caminhos = [c.args[0] for c in alvo.call_args_list if c.args]
    if caminhos.count(caminho) != 1:
        raise AssertionError(
            f"esperava exatamente um @app.{metodo}({caminho!r}) no arquivo, "
            f"achei {caminhos.count(caminho)} — o teste não sabe mais qual "
            "função pegar")
    indice = caminhos.index(caminho)
    return alvo.return_value.call_args_list[indice].args[0]


def testar():
    falhas.clear()
    main = _importar_main()
    import contas

    ok("/api/escalacao-pdf" in main.LIVRES,
       "/api/escalacao-pdf sumiu de LIVRES — o middleware de login volta a "
       "barrar o pedido antes dele chegar em _escalacao_autorizada, e o "
       "fluxo automatizado (sem cookie de sessão) para de funcionar")
    print("  /api/escalacao-pdf isento do middleware de sessão (LIVRES)")

    # ── sessão de navegador vale, mesmo sem token ───────────────────────
    cookie_valido = contas.criar_sessao("vini@example.com")
    os.environ.pop("ESCALACAO_TOKEN", None)
    ok(main._escalacao_autorizada(_RequestFalso(cookie=cookie_valido)) is True,
       "sessão de navegador válida deveria bastar, sem token nenhum — é "
       "assim que você usa a tela hoje")

    # ── sem sessão e sem ESCALACAO_TOKEN configurado: nunca autoriza ────
    ok(main._escalacao_autorizada(_RequestFalso(token="qualquer-coisa")) is False,
       "sem ESCALACAO_TOKEN configurado no ambiente, NENHUM token deveria "
       "autorizar — falhar fechado, não aberto")
    print("  sem token configurado no servidor: nenhum token de fora entra")

    # ── com ESCALACAO_TOKEN configurado ──────────────────────────────────
    os.environ["ESCALACAO_TOKEN"] = "segredo-de-teste"
    try:
        ok(main._escalacao_autorizada(_RequestFalso(token="segredo-de-teste")) is True,
           "token certo deveria autorizar — é assim que eu mando o PDF do "
           "mediahub sem sessão de navegador")
        ok(main._escalacao_autorizada(_RequestFalso(token="chute-errado")) is False,
           "token errado não pode autorizar")
        ok(main._escalacao_autorizada(_RequestFalso()) is False,
           "sem cookie e sem token, tem que recusar")
    finally:
        os.environ.pop("ESCALACAO_TOKEN", None)
    print("  token certo autoriza, token errado e ausência de token recusam")

    # ── CORS: só o mediahub, nunca "*" ──────────────────────────────────
    ok(main._ORIGEM_ESCALACAO == "https://mediahub.spl.media",
       f"a origem liberada mudou para {main._ORIGEM_ESCALACAO!r} — confira "
       "se não virou um curinga (\"*\") por engano")
    # main.JSONResponse é um MagicMock (fastapi vem trocado por dublê) — o
    # `.headers` dele não guarda o que eu escrevo. Uso uma resposta falsa
    # com `.headers` de dict de verdade só para conferir a LÓGICA de
    # _com_cors_mediahub, que não olha para o tipo do objeto, só escreve em
    # `.headers`.
    resp = main._com_cors_mediahub(_RespostaFalsa({"ok": True}))
    ok(resp.headers.get("Access-Control-Allow-Origin") == "https://mediahub.spl.media",
       "_com_cors_mediahub não está pondo o cabeçalho Access-Control-Allow-Origin "
       "certo na resposta")
    ok(resp.headers.get("Vary") == "Origin",
       "faltou o cabeçalho Vary: Origin — sem ele, um cache no meio do "
       "caminho pode servir a resposta liberada para o mediahub a QUALQUER "
       "outra origem que pedir depois")
    print("  CORS: liberado só para https://mediahub.spl.media, com Vary: Origin")

    # ── o preflight (OPTIONS) devolve os três cabeçalhos que o navegador exige ──
    # A função de verdade está presa atrás do decorador @app.options (que
    # virou mock) — busco ela pelo call_args, e troco Response (também
    # mock) por uma versão com `.headers` de dict de verdade só para este
    # teste, senão os cabeçalhos que ela escreve somem num MagicMock.
    import asyncio
    preflight_fn = _funcao_real_por_tras_do_decorador(
        main, "options", "/api/escalacao-pdf")
    main.Response = _RespostaFalsa
    preflight = asyncio.run(preflight_fn())
    ok(preflight.headers.get("Access-Control-Allow-Origin") == "https://mediahub.spl.media",
       "preflight sem Access-Control-Allow-Origin certo")
    ok(preflight.headers.get("Access-Control-Allow-Methods") == "POST",
       "preflight sem Access-Control-Allow-Methods: POST")
    ok("X-Escalacao-Token" in (preflight.headers.get("Access-Control-Allow-Headers") or ""),
       "preflight não libera o cabeçalho X-Escalacao-Token — o navegador vai "
       "barrar o POST de verdade antes dele sair")
    print("  preflight (OPTIONS) libera origem, método POST e o cabeçalho do token")

    # ── nenhum caminho de erro da rota pode esquecer o CORS ─────────────
    # Cada "return JSONResponse(" dentro de api_escalacao_pdf tem que estar
    # embrulhado em _com_cors_mediahub(...) — senão a mensagem de erro fica
    # muda para quem chamou de fora (CORS bloqueia a LEITURA da resposta,
    # não o envio, então o defeito não aparece testando pela tela normal).
    import ast
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    corpo = ""
    for n in ast.walk(ast.parse(fonte)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "api_escalacao_pdf":
            corpo = "\n".join(fonte.split("\n")[n.lineno - 1:n.end_lineno])
            break
    ok(bool(corpo), "não achei a função api_escalacao_pdf no código-fonte")
    total_respostas = corpo.count("JSONResponse(")
    com_cors = corpo.count("_com_cors_mediahub(\n            JSONResponse(") + \
        corpo.count("_com_cors_mediahub(JSONResponse(")
    ok(total_respostas > 0 and total_respostas == com_cors,
       f"{total_respostas} 'JSONResponse(' na rota, mas só {com_cors} "
       "embrulhados em _com_cors_mediahub — algum caminho de erro vai ficar "
       "mudo para o mediahub")
    print(f"  todo caminho de erro da rota ({total_respostas}) leva o cabeçalho CORS")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ escalação PDF: sessão OU token autoriza, CORS só para o mediahub")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
