"""Gravação viva mas parada: o gravador tem de perceber e recomeçar.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR (31/10/26)
    Al Hilal x Al Fateh, três clipes seguidos:
        "a gravação está 382s / 412s / 437s atrás do relógio"
    O atraso crescia junto com o relógio: o arquivo tinha parado, com o
    ffmpeg ainda de pé. O gravador só recomeçava a gravação quando o processo
    MORRIA, e todo clipe daquele jogo caía no mesmo buraco até o fim.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import gravador                                             # noqa: E402

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


class _Processo:
    def __init__(self):
        self.encerrado = False

    def poll(self):
        return 0 if self.encerrado else None

    def terminate(self):
        self.encerrado = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.encerrado = True


ditas = []
guard = (gravador.diz,)
pasta = tempfile.mkdtemp()


def _cenario(segundos_de_jogo, real=None):
    """Um jogo gravando há `segundos_de_jogo`, com o arquivo já visto uma vez."""
    g = gravador.Gravador("https://app.exemplo", "t", ["yt-dlp"], "ffmpeg")
    g.ffprobe = "ffprobe"
    g._gravado_de_verdade = lambda caminho: real
    recomecos = []
    g.comecar_pedaco = lambda jogo: recomecos.append(jogo.id) or True
    jogo = gravador.Jogo("x1", "https://yt/x1", "AL HILAL X AL FATEH")
    caminho = os.path.join(pasta, f"x1_{len(os.listdir(pasta))}.ts")
    open(caminho, "wb").write(b"\0" * 1000)
    inicio = datetime.now(timezone.utc) - timedelta(seconds=segundos_de_jogo)
    pedaco = gravador.Gravacao(caminho, inicio, _Processo())
    jogo.pedacos.append(pedaco)
    g.jogos[jogo.id] = jogo
    return g, jogo, pedaco, recomecos


try:
    gravador.diz = lambda t="", erro=False: ditas.append(t)

    # ── TRAVADO: o arquivo não cresce há mais que o limite ──────────────
    g, jogo, pedaco, recomecos = _cenario(600, real=590)
    g.vigiar_gravacoes()                       # primeira olhada: anota o tamanho
    ok(not recomecos and not pedaco.processo.encerrado,
       "o vigia recomeçou uma gravação que acabou de ser vista crescendo")
    pedaco.cresceu_em = time.time() - 50       # 50s sem crescer
    g.cuidar_das_gravacoes()
    ok(pedaco.processo.encerrado, "o ffmpeg travado (arquivo parado há 50s) não foi encerrado")
    ok(recomecos == ["x1"], "depois de encerrar o travado, a gravação não recomeçou")
    ok(pedaco.fim is not None, "o pedaço travado não foi fechado — clipes iriam buscá-lo")
    ok(not any("a gravação caiu" in t for t in ditas),
       "o aviso de 'a gravação caiu' saiu repetido em cima do de 'travou'")
    ok(any("travou" in t and "não cresce" in t for t in ditas),
       f"a janela não disse que a gravação travou: {ditas[-3:]}")

    # ── ATRASADO: o arquivo ainda pinga, mas está 437s atrás ────────────
    ditas.clear()
    g, jogo, pedaco, recomecos = _cenario(1500, real=1500 - 437)
    g.cuidar_das_gravacoes()
    ok(pedaco.processo.encerrado and recomecos == ["x1"],
       "a gravação 437s atrás do relógio não foi recomeçada — é o caso de Al Hilal "
       "x Al Fateh em 31/10")
    ok(any("437s atrás" in t for t in ditas), f"a janela não disse o atraso: {ditas[-3:]}")

    # ── SAUDÁVEL: cresce e acompanha o relógio ──────────────────────────
    g, jogo, pedaco, recomecos = _cenario(1500, real=1490)
    for _ in range(3):
        open(pedaco.caminho, "ab").write(b"\0" * 1000)
        g.cuidar_das_gravacoes()
        pedaco.medido_em = 0
    ok(not recomecos and not pedaco.processo.encerrado,
       "o vigia derrubou uma gravação saudável (10s de folga é o tempo de conectar)")

    # ── RECÉM-ABERTA: o tempo de conectar não conta como atraso ─────────
    # 100s de vida e só 5s de vídeo: parece "95s atrás", mas é o yt-dlp e o
    # ffmpeg conectando. A primeira medida só vem depois de 2 minutos.
    g, jogo, pedaco, recomecos = _cenario(100, real=5)
    g.cuidar_das_gravacoes()
    ok(not recomecos, "uma gravação com 100s de vida foi derrubada por 'atraso'")

    # ── O LAÇO CHAMA O VIGIA ────────────────────────────────────────────
    g, jogo, pedaco, recomecos = _cenario(600, real=590)
    g.vigiar_gravacoes()
    pedaco.cresceu_em = time.time() - 120
    g.cuidar_das_gravacoes()
    ok(pedaco.processo.encerrado,
       "o cuidar_das_gravacoes, que roda a cada volta, não chama o vigia")
finally:
    (gravador.diz,) = guard

if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ gravação travada ou atrasada é recomeçada na ponta ao vivo; a saudável fica")
