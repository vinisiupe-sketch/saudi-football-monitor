"""O post de escalação: nasce sozinho, aparece na home, troca a foto, publica.

O QUE ELE PEDIU (24/10/26)
    "Preciso que disponibilize pra postar direto já no twitter na homepage,
     como tem o do bola rolando. Já com a legenda de acordo com o jogo e a
     foto dos dois times anexada. Assim como o do bola rolando, opção de
     clicar e abrir pra ver e trocar o jogador da imagem se for o caso. Por
     padrão, sete o capitão na foto. Tem que ficar disponível logo após
     montar automaticamente a foto (que vai ser logo após estar disponível a
     lista das duas equipes)."

AS DECISÕES QUE ESTE ARQUIVO DEFENDE
    · o post nasce quando a folha é GRAVADA, sem ninguém clicar;
    · arte e legenda saem das MESMAS funções do botão da guia;
    · a escolha dele do jogador da foto sobrevive à releitura da folha;
    · o ✓ da home publica NA HORA — o aprovado comum esperaria o pontapé;
    · a arte fica no banco, porque o disco do Railway se apaga no deploy.
"""
import asyncio
import ast
import os
import sys
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

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

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ARVORE = ast.parse(FONTE)


class Resposta:
    def __init__(self, conteudo=None, status_code=200, **k):
        self.dados, self.status_code = conteudo, status_code


class Pedido:
    def __init__(self, corpo):
        self._c = corpo

    async def json(self):
        return self._c


# ── O BANCO DE MENTIRA ──────────────────────────────────────────────────
ARTES, FILA, MONTAGENS = {}, {}, []


def _salvar_arte(chave, png, dados):
    ARTES[chave] = {"png": png, "dados": dict(dados)}
    return True


def _obter_arte(chave):
    a = ARTES.get(chave)
    return {"png": a["png"], "dados": dict(a["dados"])} if a else None


def _enfileirar(tipo, chave, texto, imagens=None, agendado_para=None):
    if chave in FILA:
        return "ja_existia"
    FILA[chave] = {"id": len(FILA) + 1, "tipo": tipo, "chave_unica": chave,
                   "texto": texto, "imagens": list(imagens or []),
                   "agendado_para": agendado_para, "status": "pendente"}
    return "novo"


async def _montar_arte(corpo):
    MONTAGENS.append(dict(corpo))
    return (b"PNG|" + (corpo.get("clube") or "").encode() + b"|"
            + (corpo.get("destaque") or "").encode()), {"X-Destaque": corpo.get("destaque"),
                                                         "X-Faltou": "nada"}


async def _montar_legenda(corpo):
    return {"texto": "🔴🔵📋 Escalações de " + corpo["casa"]["nome"] + " e "
                     + corpo["fora"]["nome"], "avisos": []}


async def _times(**k):
    return {"times": [{"id": 2010, "nome": "Al Qadsiah"}, {"id": 1114, "nome": "Al Hilal"}]}


def _instalar():
    guard = (database.salvar_post_arte, database.obter_post_arte, database.enfileirar_post,
             main._montar_arte_escalacao, main._montar_legenda, main.api_elencos_times)
    database.salvar_post_arte = _salvar_arte
    database.obter_post_arte = _obter_arte
    database.enfileirar_post = _enfileirar
    main._montar_arte_escalacao = _montar_arte
    main._montar_legenda = _montar_legenda
    main.api_elencos_times = _times
    return guard


def _desinstalar(guard):
    (database.salvar_post_arte, database.obter_post_arte, database.enfileirar_post,
     main._montar_arte_escalacao, main._montar_legenda, main.api_elencos_times) = guard


# A folha como ela é gravada — o mesmo formato de /api/escalacao-pdf.
FOLHA = {"rodada": "11", "data": "23 October 2026", "hora": "21:00",
         "casa": {"time": "AL QADSIAH", "tecnico": "BRENDAN RODGERS",
                  "texto": "🇧🇪 01 K. CASTEELS\n🇺🇾 08 N. NÁNDEZ",
                  "capitao": "K. CASTEELS"},
         "fora": {"time": "AL HILAL", "tecnico": "SIMONE INZAGHI",
                  "texto": "🇲🇦 37 BONO\n🇸🇦 06 NASSER AL DAWSARI",
                  "capitao": "NASSER AL DAWSARI"}}
CHAVE = "escalacao:23 October 2026|AL QADSIAH|AL HILAL"

# ── A HORA DO JOGO VEM DA FOLHA, EM HORA DA ARÁBIA ──────────────────────
ok(main._quando_da_folha(FOLHA) == "2026-10-23T18:00:00+00:00",
   f"21:00 da Arábia saiu {main._quando_da_folha(FOLHA)!r}, e devia ser 18:00 "
   "UTC. É esse horário que tira o post da home depois do pontapé")
ok(main._quando_da_folha({"data": "sei la", "hora": ""}) == "",
   "uma data ilegível virou horário inventado")

g = _instalar()
try:
    r = asyncio.run(main.gerar_post_escalacao(FOLHA))
    post = FILA.get(CHAVE) or {}

    # ── O POST NASCE SOZINHO, COM AS DUAS ARTES E A LEGENDA ─────────────
    ok(r.get("post") == "novo" and post.get("tipo") == "escalacao",
       f"o post de escalação não entrou na fila ({r})")
    ok(post.get("imagens") == [f"arte:{CHAVE}:casa", f"arte:{CHAVE}:fora"],
       f"as duas artes não foram anexadas ao post: {post.get('imagens')}")
    ok((post.get("texto") or "").startswith("🔴🔵📋 Escalações de Al Qadsiah e Al Hilal"),
       f"a legenda do post não saiu com os nomes de exibição da SPL: "
       f"{post.get('texto')!r}")
    ok(post.get("agendado_para") == "2026-10-23T18:00:00+00:00",
       "o post não ficou marcado para o pontapé; é o que o tira da home depois "
       "que o jogo começa, quando 'logo mais' já não é verdade")

    # ── POR PADRÃO, O CAPITÃO ───────────────────────────────────────────
    ok(ARTES[f"{CHAVE}:casa"]["dados"]["destaque"] == "K. CASTEELS"
       and ARTES[f"{CHAVE}:fora"]["dados"]["destaque"] == "NASSER AL DAWSARI",
       "a foto das artes automáticas não é a do capitão")
    ok(main._bytes_da_imagem(f"arte:{CHAVE}:fora") == ARTES[f"{CHAVE}:fora"]["png"],
       "a publicação não acha a arte guardada no banco — o post sairia sem foto")

    # ── A FOLHA RELIDA SEM MUDANÇA NÃO REFAZ NADA ───────────────────────
    MONTAGENS.clear()
    asyncio.run(main.gerar_post_escalacao(FOLHA))
    ok(MONTAGENS == [],
       f"a mesma folha relida refez {len(MONTAGENS)} arte(s). O monitor relê a "
       "folha de tempos em tempos; refazer é trabalho e risco à toa")

    # ── A ESCOLHA DELE SOBREVIVE À RELEITURA ────────────────────────────
    _obter = database.obter_post
    database.obter_post = lambda pid: dict(post, id=pid)
    try:
        resp_dest = asyncio.run(main.api_posts_destaque(
            1, Pedido({"lado": "fora", "jogador": "BONO"})))
    finally:
        database.obter_post = _obter
    ok(isinstance(resp_dest, dict) and resp_dest.get("ok"),
       f"a troca do jogador da foto falhou: {getattr(resp_dest, 'dados', resp_dest)}")
    ok(ARTES[f"{CHAVE}:fora"]["dados"]["destaque"] == "BONO"
       and ARTES[f"{CHAVE}:fora"]["png"].endswith(b"BONO"),
       "a troca do jogador não refez a arte com o novo destaque")
    ok(ARTES[f"{CHAVE}:casa"]["dados"]["destaque"] == "K. CASTEELS",
       "trocar o jogador de um time mexeu na arte do outro")

    corrigida = dict(FOLHA, fora=dict(FOLHA["fora"],
                                      texto=FOLHA["fora"]["texto"] + "\n🇧🇷 07 GABRIEL MARTINELLI"))
    MONTAGENS.clear()
    asyncio.run(main.gerar_post_escalacao(corrigida))
    ok(len(MONTAGENS) == 1 and MONTAGENS[0].get("destaque") == "BONO",
       f"com a folha corrigida, a arte foi refeita sem a escolha dele "
       f"({[m.get('destaque') for m in MONTAGENS]}). Ele trocou para o Bono; a "
       "releitura não pode devolver o capitão")
    ok(FILA[CHAVE]["texto"] == post["texto"],
       "a releitura reescreveu o texto do post, que ele pode ter editado")
finally:
    _desinstalar(g)

# ── A TROCA SÓ VALE PARA POST DE ESCALAÇÃO PENDENTE, E LADO CERTO ───────
main.JSONResponse = Resposta
_obter = database.obter_post
try:
    database.obter_post = lambda pid: {"id": pid, "tipo": "bola_rolando", "status": "pendente",
                                       "imagens": []}
    r1 = asyncio.run(main.api_posts_destaque(1, Pedido({"lado": "casa", "jogador": "X"})))
    database.obter_post = lambda pid: {"id": pid, "tipo": "escalacao", "status": "publicado",
                                       "imagens": [f"arte:{CHAVE}:casa"]}
    r2 = asyncio.run(main.api_posts_destaque(1, Pedido({"lado": "casa", "jogador": "X"})))
    database.obter_post = lambda pid: {"id": pid, "tipo": "escalacao", "status": "pendente",
                                       "imagens": [f"arte:{CHAVE}:casa"]}
    r3 = asyncio.run(main.api_posts_destaque(1, Pedido({"lado": "meio", "jogador": "X"})))
finally:
    database.obter_post = _obter
ok(getattr(r1, "status_code", 200) == 404, "a troca de jogador mexeu num post que não é de escalação")
ok(getattr(r2, "status_code", 200) == 409,
   "a foto de um post já PUBLICADO foi trocada — a imagem no ar não muda mais")
ok(getattr(r3, "status_code", 200) == 400, "um lado que não é casa nem fora foi aceito")

# ── O ✓ DA HOME PUBLICA NA HORA O DE ESCALAÇÃO, E SÓ ELE ────────────────
chamadas = []


async def _publicar_ja(pid):
    chamadas.append(("publicar", pid))
    return {"ok": True, "post_id": "X123"}


def _marcar(pid, status, **k):
    chamadas.append(("marcar", pid, status))
    return True


guard = (main._publicar_post_agora, main.obter_post, main.marcar_post)
try:
    main._publicar_post_agora, main.marcar_post = _publicar_ja, _marcar
    main.obter_post = lambda pid: {"id": pid, "tipo": "escalacao", "status": "pendente"}
    re1 = asyncio.run(main.api_aprovacao_decidir("posts", 7, decisao="sim"))
    main.obter_post = lambda pid: {"id": pid, "tipo": "bola_rolando", "status": "pendente"}
    re2 = asyncio.run(main.api_aprovacao_decidir("posts", 8, decisao="sim"))
    main.obter_post = lambda pid: {"id": pid, "tipo": "escalacao", "status": "pendente"}
    re3 = asyncio.run(main.api_aprovacao_decidir("posts", 9, decisao="nao"))
finally:
    main._publicar_post_agora, main.obter_post, main.marcar_post = guard
ok(("publicar", 7) in chamadas and isinstance(re1, dict) and re1.get("estado") == "publicado",
   "o ✓ do post de escalação não publicou na hora. Aprovar o comum faria ele "
   "esperar o pontapé — e a escalação é para sair quando ele decide")
ok(("marcar", 8, "aprovado") in chamadas and ("publicar", 8) not in chamadas,
   "o ✓ do bola rolando passou a publicar na hora; ele tem de esperar o pontapé")
ok(("marcar", 9, "cancelado") in chamadas and ("publicar", 9) not in chamadas,
   "o ✕ do post de escalação publicou em vez de cancelar")

# ── O GATILHO: A FOLHA GRAVADA DISPARA O POST ───────────────────────────
# Pelo NOME, e recortando as linhas à mão: `ast.get_source_segment` relê o
# main.py inteiro a cada chamada, e chamá-lo para cada função do arquivo fez
# este teste levar 27 segundos — e estourar o tempo no meio de uma rodada de
# mutações, deixando um defeito plantado no código.
rota_pdf = next(n for n in ARVORE.body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "api_escalacao_pdf")
_linhas_fonte = FONTE.splitlines()
_src_pdf = "\n".join(_linhas_fonte[rota_pdf.lineno - 1:rota_pdf.end_lineno])
ok("agendar_post_escalacao(dados)" in _src_pdf
   and _src_pdf.index("agendar_post_escalacao(dados)") > _src_pdf.index('dados["salvo"] = True'),
   "a folha gravada não dispara o post de escalação — ele não apareceria na "
   "home sem alguém clicar")
_src_gerar = FONTE[FONTE.find("async def gerar_post_escalacao"):
                   FONTE.find("_TAREFAS_DE_FUNDO: set")]
ok("await _montar_arte_escalacao(" in _src_gerar and "await _montar_legenda(" in _src_gerar,
   "o post automático monta arte ou legenda por um caminho que não é o do "
   "botão da guia — as duas versões divergiriam")

# ── A HOME ──────────────────────────────────────────────────────────────
_home_js = FONTE[FONTE.find('_HOME_JS = r"""'):]
_home_js = _home_js[:_home_js.find('"""', 20)]
ok("i.tipo_post === 'escalacao'" in _home_js and "/destaque'" in _home_js,
   "a home não mostra as artes do post de escalação com o seletor de jogador")
ok("if (publicaJa && !confirm(" in _home_js,
   "o ✓ que publica na hora não pede confirmação — é envio público, sem volta")
ok("foco.tagName === 'SELECT'" in _home_js and "abertos.has(" in _home_js,
   "a atualização de minuto em minuto fecha o card ou atropela o seletor no "
   "meio da troca do jogador")
ok('"onde"] = "/escalacao-pdf"' in FONTE,
   "o link do post de escalação na home aponta para uma guia que não existe")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ post de escalação: nasce sozinho, troca a foto e publica pela home")
