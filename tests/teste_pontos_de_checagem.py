"""O navegador só abre nos pontos de checagem — é ele que pesa na conta.

O QUE ELE VIU (22/10/26)
    "O media hub tá gastando muito no railway. precisamos baratear."

    A medição deu razão a ele: o monitor usava 1,38 GB de RAM em média contra
    0,50 GB do app inteiro, com CPU média de 0,026. A conta do Railway é
    RAM × tempo, e o que ocupa essa RAM é o Chromium — aberto 24 h por dia
    para um portal que publica nove PDFs uma vez por rodada.

    A regra que ele deu: 1:15 antes do jogo, 1:10, 1:05, 1:00, 0:55, 0:50,
    depois disso para; se receber antes, para.

O QUE ESTE ARQUIVO VIGIA
    Cada guarda aqui existe porque a sua ausência traz o gasto de volta — ou,
    pior, faz a escalação não chegar, que é o motivo de o serviço existir.
"""
import ast
import os
import sys
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import mediahub_monitor as mh                               # noqa: E402

FONTE = open(os.path.join(RAIZ, "mediahub_monitor.py"), encoding="utf-8").read()
ARVORE = ast.parse(FONTE)

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


JOGO = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


def em(minutos_antes, segundos=0):
    return JOGO - timedelta(minutes=minutos_antes, seconds=-segundos)


# ── A REGRA QUE ELE DITOU ───────────────────────────────────────────────
ok(mh.PONTOS_PADRAO == (75, 70, 65, 60, 55, 50),
   "os pontos deixaram de ser os que ele pediu: 1:15, 1:10, 1:05, 1:00, "
   "0:55 e 0:50 antes do jogo")

P = mh.PONTOS_PADRAO

ok(mh.no_ponto(JOGO, em(75), P), "o primeiro ponto, 1:15 antes, não abre o navegador")
ok(mh.no_ponto(JOGO, em(50), P), "o último ponto, 0:50 antes, não abre o navegador")
ok(mh.no_ponto(JOGO, em(60), P), "o ponto de 1 hora antes não abre o navegador")

ok(not mh.no_ponto(JOGO, em(80), P),
   "o navegador abriu 1:20 antes, fora de qualquer ponto. Cada abertura fora "
   "de hora é 1,38 GB de RAM que entra na fatura sem motivo")
ok(not mh.no_ponto(JOGO, em(44), P),
   "o navegador continuou aberto depois de 0:45. Ele disse 'depois disso, "
   "para'")
ok(not mh.no_ponto(JOGO, JOGO + timedelta(minutes=30), P),
   "o navegador abriu DEPOIS do apito inicial, quando a escalação já não "
   "serve para nada")


# ── A TOLERÂNCIA: o relógio do agendador nunca bate exato ───────────────
ok(mh.no_ponto(JOGO, em(75) + timedelta(seconds=40), P),
   "quarenta segundos de atraso do agendador fizeram o ponto ser perdido "
   "inteiro. É a falha mais cara possível: a escalação não chega e ninguém "
   "percebe, porque não há erro nenhum")
ok(mh.no_ponto(JOGO, em(75) + timedelta(minutes=4, seconds=59), P),
   "a faixa de cinco minutos encolheu; com cron de 5 em 5 minutos sobra "
   "buraco entre um ponto e o seguinte")
ok(not mh.no_ponto(JOGO, em(75) - timedelta(seconds=1), P),
   "a faixa começou ANTES do ponto; aí ela invade o ponto anterior e a "
   "contagem dele deixa de valer")
ok(not mh.no_ponto(JOGO, em(76), P, tolerancia=1),
   "a tolerância configurada foi ignorada")


# ── QUANTO DORMIR: é o que mantém o navegador fechado ───────────────────
ok(mh.espera_ate_o_ponto([JOGO], em(90), P) == 15 * 60,
   "a espera até o primeiro ponto saiu errada; dormir de menos é reabrir o "
   "Chromium à toa, e é exatamente o gasto que ele mandou cortar")
ok(mh.espera_ate_o_ponto([JOGO], em(74), P) == 4 * 60,
   "a espera não apontou para o PRÓXIMO ponto")
ok(mh.espera_ate_o_ponto([JOGO], em(49), P) == 900,
   "passado o último ponto deste jogo, o monitor devia cair no teto de 15 "
   "minutos em vez de ficar girando")
ok(mh.espera_ate_o_ponto([], em(90), P) == 900,
   "sem jogo nenhum na agenda o monitor não dormiu o teto")
ok(mh.espera_ate_o_ponto([JOGO + timedelta(hours=6), JOGO], em(90), P) == 15 * 60,
   "com dois jogos no dia a espera tem de ser até o ponto MAIS PRÓXIMO; "
   "olhar só para o primeiro da lista perde a escalação do outro")
ok(mh.espera_ate_o_ponto([JOGO + timedelta(days=1)], em(90), P) == 900,
   "um jogo de amanhã fez o monitor dormir horas; o teto existe para que a "
   "agenda seja reconsultada")
ok(mh.espera_ate_o_ponto([JOGO], em(75), P) == 5 * 60,
   "parado em cima de um ponto, a espera devia ser até o SEGUINTE")


# ── "SE RECEBER ANTES, PARA" ────────────────────────────────────────────
class EstadoFalso(mh.Estado):
    def __init__(self, registros):
        self.dados = {"registros": registros}
        self.pasta = __import__("pathlib").Path(
            __import__("tempfile").mkdtemp())


vazio = EstadoFalso({})
cheio = EstadoFalso({"https://x/record/1": {
    "sha256": "abc", "inicio": JOGO.isoformat(), "checado": 1}})

ok(not vazio.jogo_entregue(JOGO),
   "um jogo sem PDF confirmado foi dado como entregue; assim a escalação "
   "nunca é buscada")
ok(cheio.jogo_entregue(JOGO),
   "o PDF deste jogo já foi confirmado e mesmo assim o jogo continua na "
   "agenda. É o 'se receber antes, para' que ele pediu, e cada ponto a mais "
   "é uma abertura inteira de Chromium")
ok(cheio.jogo_entregue(JOGO + timedelta(seconds=30)),
   "trinta segundos de diferença no horário gravado no PDF desfizeram o "
   "reconhecimento do jogo")
ok(not cheio.jogo_entregue(JOGO + timedelta(hours=3)),
   "o PDF de um jogo foi aceito como se fosse o de outro jogo do mesmo dia; "
   "aí a segunda escalação nunca chega")
ok(not EstadoFalso({"u": {"sha256": "a"}}).jogo_entregue(JOGO)
   and not EstadoFalso({"u": {"inicio": "sei lá"}}).jogo_entregue(JOGO)
   and not EstadoFalso({"u": {"inicio": "2026-10-24T15:00:00"}}).jogo_entregue(JOGO),
   "um registro antigo, torto ou sem fuso derrubou a consulta em vez de ser "
   "ignorado; o estado em /data atravessa versões do código")


# ── A LEITURA DA VARIÁVEL ───────────────────────────────────────────────
ok(mh.pontos_de_checagem("") == list(P) and mh.pontos_de_checagem(None) == list(P),
   "sem a variável configurada o padrão não valeu")
ok(mh.pontos_de_checagem("30, 10,20") == [30, 20, 10],
   "a lista não foi lida em ordem decrescente; a ordem é o que torna "
   "max(pontos) o ponto mais distante do jogo")
ok(mh.pontos_de_checagem("10,10") == [10],
   "um ponto repetido viraria duas aberturas do navegador no mesmo minuto")
for ruim in ("abc", "10,abc", "-5", " , "):
    try:
        mh.pontos_de_checagem(ruim)
        falhas.append(f"MEDIAHUB_CHECKPOINTS={ruim!r} passou calado. Uma "
                      "variável torta tem de parar o serviço na partida, e "
                      "não virar uma lista vazia que nunca busca nada")
    except mh.MonitorError:
        pass


# ── A GUARDA DE `processar` NÃO PODE SER MAIS ESTREITA QUE OS PONTOS ────
_init = next(n for n in ast.walk(ARVORE)
             if isinstance(n, ast.FunctionDef) and n.name == "__init__"
             and any("MEDIAHUB_BEFORE_MINUTES" in ast.dump(f) for f in ast.walk(n)))
_texto = ast.get_source_segment(FONTE, _init)
ok("max(self.antecedencia, max(self.pontos)" in _texto,
   "a antecedência deixou de acompanhar o ponto mais distante. `processar` "
   "recusaria o PDF achado no primeiro ponto segundos depois de baixá-lo — o "
   "trabalho todo feito e jogado fora")


# ── O CICLO TEM DE USAR ISTO DE VERDADE ─────────────────────────────────
_ciclo = next(n for n in ast.walk(ARVORE)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "ciclo")
_chamadas = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
             for n in ast.walk(_ciclo) if isinstance(n, ast.Call)}

ok("no_ponto" in _chamadas,
   "o ciclo não consulta os pontos de checagem. As funções existem, os testes "
   "acima passam e o Chromium continua aberto o dia inteiro — foi assim que o "
   "teste estático já me enganou antes")
# Não basta a função ser citada em algum canto do ciclo: ela tem de mandar na
# lista que decide o que vai ser buscado. Uma versão anterior deste teste
# passava com o filtro já desfeito, porque `jogo_entregue` ainda aparecia duas
# linhas acima, no cálculo da espera.
_ativos = next((n for n in ast.walk(_ciclo)
                if isinstance(n, ast.Assign)
                and any(getattr(a, "id", "") == "ativos" for a in n.targets)), None)
ok(_ativos is not None, "a lista `ativos` sumiu do ciclo")
_dentro = {c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
           for c in ast.walk(_ativos) if isinstance(c, ast.Call)} if _ativos else set()
ok("jogo_entregue" in _dentro,
   "o jogo cuja escalação já chegou continua na lista de busca. Ele disse "
   "'se receber antes, para', e cada ponto a mais é uma abertura inteira de "
   "Chromium depois de o trabalho já estar feito")
ok("no_ponto" in _dentro,
   "a escolha dos jogos a buscar não passa pelos pontos de checagem")
ok("espera_ate_o_ponto" in _chamadas,
   "o ciclo não calcula a espera, então o laço volta a girar de minuto em "
   "minuto")
ok("na_janela" not in _chamadas,
   "o ciclo ainda escolhe os jogos pela janela de 100 minutos. Enquanto ela "
   "mandar, os pontos de checagem são decoração")
ok(any(isinstance(n, ast.Return) and n.value is not None
       for n in ast.walk(_ciclo)),
   "o ciclo não devolve a espera para quem chama")

_executar = next(n for n in ast.walk(ARVORE)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "executar")
_fonte_exec = ast.get_source_segment(FONTE, _executar)
ok("espera = await monitor.ciclo(" in _fonte_exec,
   "o laço joga fora a espera devolvida pelo ciclo e dorme o intervalo fixo")
ok("if erros else espera" in _fonte_exec,
   "o recuo progressivo passou a valer também quando não houve erro, ou a "
   "espera dos pontos passou a valer durante um erro — são coisas diferentes")


# ── E AGORA RODANDO O CICLO DE VERDADE ──────────────────────────────────
# A inspeção acima prova que as funções são CITADAS. Não prova que mandam:
# `[j for j in jogos if True] or [j for j in jogos if no_ponto(...)]` passaria
# nela com o filtro desfeito. O que decide é abrir ou não o navegador, então é
# isso que se mede aqui.
import asyncio                                              # noqa: E402


class PaginaFalsa:
    def get_by_role(self, *a, **k):
        class _R:
            async def inner_text(self):
                return "0 results"
        return _R()


class ContextoFalso:
    async def storage_state(self, path=None):
        return {}


class RespostaFalsa:
    status_code = 200

    def __init__(self, dados):
        self._dados = dados

    def json(self):
        return self._dados


class ClienteFalso:
    def __init__(self, dados):
        self._dados = dados

    async def get(self, url):
        return RespostaFalsa(self._dados)


def rodar_ciclo(pontape, momento, registros=None):
    """Devolve (abriu_navegador, espera) para um ciclo nessas condições."""
    monitor = mh.Monitor.__new__(mh.Monitor)
    monitor.app = "https://exemplo.invalido"
    monitor.token = "x"
    monitor.estado = EstadoFalso(registros or {})
    monitor.pontos = list(P)
    monitor.tolerancia = 5
    monitor.antecedencia = 100
    monitor.recuperacao = 240
    monitor.browser = monitor.context = monitor.page = None
    aberturas = []

    class NavegadorFalso:
        async def close(self):
            return None

    async def abrir(pw):
        aberturas.append(True)
        monitor.page = PaginaFalsa()
        monitor.context = ContextoFalso()
        monitor.browser = NavegadorFalso()

    async def status(cli, estado, mensagem, **extra):
        return None

    async def titulos(url):
        return []

    monitor.abrir, monitor.status, monitor.titulos = abrir, status, titulos
    dia = momento.astimezone(mh.ARABIA).date()
    cli = ClienteFalso({"data_arabia": dia.isoformat(),
                        "jogos": [{"pontape_utc": pontape.isoformat()}]})
    real = mh.agora
    mh.agora = lambda: momento
    try:
        espera = asyncio.run(monitor.ciclo(cli, None))
    finally:
        mh.agora = real
    return bool(aberturas), espera, monitor.browser is not None


_abriu, _espera, _ = rodar_ciclo(JOGO, em(90))
ok(not _abriu,
   "o ciclo abriu o navegador 1:30 antes do jogo, longe de qualquer ponto. "
   "É esta abertura, multiplicada pelas 24 horas do dia, que faz o monitor "
   "custar 1,38 GB de média contra 0,50 GB do app inteiro")
ok(_espera == 15 * 60,
   "fora dos pontos o ciclo não devolveu a espera até o primeiro ponto")

_abriu, _, _vivo = rodar_ciclo(JOGO, em(75))
ok(_abriu, "no ponto de 1:15 o navegador NÃO abriu — a escalação não chega, "
           "que é o motivo de o serviço existir")
ok(_vivo, "o navegador foi fechado entre dois pontos colados um no outro; "
          "reabrir e relogar a cada cinco minutos custa mais do que manter")

_abriu, _, _vivo = rodar_ciclo(JOGO, em(50))
ok(_abriu, "o último ponto, 0:50 antes, não consultou o portal")
ok(not _vivo,
   "passado o último ponto o Chromium ficou aberto. São 1,38 GB parados até "
   "o próximo jogo, e é exatamente a conta que ele mandou cortar")

_abriu, _, _ = rodar_ciclo(JOGO, em(44))
ok(not _abriu, "o ciclo continuou abrindo o navegador depois do último ponto")

_abriu, _, _ = rodar_ciclo(
    JOGO, em(75), {"r": {"sha256": "a", "inicio": JOGO.isoformat()}})
ok(not _abriu,
   "a escalação deste jogo já tinha chegado e o ciclo abriu o navegador "
   "assim mesmo. 'Se receber antes, para'")

_abriu, _, _ = rodar_ciclo(
    JOGO, em(75), {"r": {"sha256": "a", "inicio": (JOGO + timedelta(hours=3)).isoformat()}})
ok(_abriu,
   "chegou a escalação de OUTRO jogo do dia e este deixou de ser buscado")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ navegador só nos pontos de checagem, e o jogo entregue sai da agenda")
