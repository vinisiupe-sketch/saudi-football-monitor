"""
O gravador não pode cortar um trecho que ainda não existe no arquivo.

O QUE ACONTECEU (08/09/26, Al Ittihad x Al Fayha)
    Vários clipes seguidos do MESMO jogo voltaram com

        "o corte saiu com 261 bytes; provavelmente não havia vídeo
         naquele trecho"

    enquanto a outra partida da mesma tarde ia bem.

    A causa: `Gravacao.posicao()` responde "quantos segundos se passaram no
    RELÓGIO desde que abri o ffmpeg", e o código tratava esse número como se
    fosse "quantos segundos de vídeo existem no arquivo". São a mesma coisa só
    quando o fluxo chega em tempo real e sem falha. Quando a transmissão
    engasga, o relógio anda e o arquivo não — e a diferença ACUMULA, que é por
    que uma vez que aquele jogo começou a atrasar, todos os clipes seguintes
    dele caíram no mesmo buraco.

    O ffmpeg então buscava num segundo inexistente, escrevia um mp4 só com
    cabeçalho e SAÍA COM CÓDIGO 0 — do ponto de vista dele nada deu errado.
    Nada na corrente reclamava até a conferência de tamanho lá no fim, que só
    sabia dizer "provavelmente".

O QUE ESTE ARQUIVO VIGIA
    Que a decisão de cortar (e a espera antes dela) olhe o ARQUIVO, e não o
    relógio. Rodo o atender() de verdade, com um pedaço cuja duração real é
    menor que o tempo de relógio, e exijo que ele recuse ANTES de chamar o
    ffmpeg — dizendo o quanto está atrasado, que é a informação que faltava.
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import gravador

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _montar(duracao_real, segundos_de_relogio=600):
    """Um gravador com UM jogo, gravando há 10 minutos de relógio.

    `duracao_real` é o que o arquivo tem de verdade — o número que o ffprobe
    devolveria. Passar None é o ffprobe não respondendo.
    """
    g = gravador.Gravador.__new__(gravador.Gravador)
    g.ffmpeg = "ffmpeg"
    g.jogos = {}
    registro = {"falhou": None, "cortou": False, "entregou": False}

    inicio = datetime.now(timezone.utc) - timedelta(seconds=segundos_de_relogio)
    jogo = gravador.Jogo("live1", "http://x", "AL ITTIHAD X AL FAYHA")
    pedaco = gravador.Gravacao("/tmp/nao_existe.ts", inicio, None)
    jogo.pedacos.append(pedaco)
    g.jogos["live1"] = jogo

    g._gravado_de_verdade = lambda caminho: duracao_real
    g._falhou = lambda cid, motivo: registro.__setitem__("falhou", motivo)
    g._http = lambda *a, **k: (None, None)

    def _cortar_falso(origem, inicio_, dur, saida):
        # Escreve um arquivo de tamanho plausível: o atender() lê o resultado
        # logo depois, e um corte "bem-sucedido" que não deixa arquivo faria o
        # teste morrer por um motivo que não é o que ele investiga.
        registro["cortou"] = True
        os.makedirs(os.path.dirname(saida), exist_ok=True)
        with open(saida, "wb") as f:
            f.write(b"\0" * 20000)
        registro["saida"] = saida
        return None
    g._cortar = _cortar_falso
    return g, registro


def _pedido(alvo_atras_de_segundos):
    return {"id": 99, "live_id": "live1", "antes_seg": 20, "depois_seg": 20,
            "alvo_em": (datetime.now(timezone.utc)
                        - timedelta(seconds=alvo_atras_de_segundos)).isoformat()}


def testar():
    falhas.clear()

    # ── 1. o arquivo está muito atrás do relógio: recusa ANTES do ffmpeg ─────
    # 10 minutos de relógio, 3 minutos de vídeo. O lance de 60s atrás está, no
    # relógio, no segundo 540 — e o arquivo tem 180.
    g, reg = _montar(duracao_real=180.0)
    g.atender(_pedido(60))
    ok(not reg["cortou"],
       "o gravador chamou o ffmpeg para cortar um trecho que o arquivo não "
       "tem — é exatamente isso que devolve 261 bytes")
    ok(reg["falhou"] is not None, "não recusou o pedido impossível")
    if reg["falhou"]:
        ok("atrás do relógio" in reg["falhou"] or "só tem" in reg["falhou"],
           f"recusou sem dizer que a gravação está atrasada: {reg['falhou']!r}")
        ok("180" in reg["falhou"],
           "a recusa não diz quantos segundos o arquivo tem de verdade — sem "
           f"esse número não dá para entender o que houve: {reg['falhou']!r}")

    # ── 2. o arquivo tem o trecho: corta normalmente ─────────────────────────
    g, reg = _montar(duracao_real=600.0)
    g.atender(_pedido(60))
    ok(reg["cortou"],
       "com o vídeo todo gravado o corte deixou de acontecer — a conferência "
       "nova está recusando pedido bom")
    ok(reg["falhou"] is None,
       f"recusou um pedido que cabia no arquivo: {reg['falhou']!r}")

    # ── 3. sem ffprobe, volta a confiar no relógio ───────────────────────────
    # Máquina sem ffprobe não pode ficar sem clipe nenhum: a conta antiga é
    # pior, mas é melhor que nada.
    g, reg = _montar(duracao_real=None)
    g.atender(_pedido(60))
    ok(reg["cortou"],
       "sem resposta do ffprobe o gravador parou de cortar — a reserva pelo "
       "relógio sumiu, e uma máquina sem ffprobe fica sem clipe nenhum")

    # ── 4. a espera olha o arquivo, e não o relógio ──────────────────────────
    fonte = open(os.path.join(RAIZ, "gravador.py"), encoding="utf-8").read()
    ini = fonte.find("        espera = 0")
    trecho = fonte[ini:ini + 900]
    ok("_gravado_de_verdade" in trecho,
       "a espera do fim da janela voltou a se basear só no relógio — ela dava "
       "por satisfeita com um trecho que não existia")

    # ── 5. a versão subiu ────────────────────────────────────────────────────
    # O gravador roda na máquina do Vini e na do amigo, e se atualiza sozinho
    # comparando a versão com a que o app espera. Mexer no arquivo sem subir a
    # versão é deixar as duas máquinas rodando o defeito para sempre.
    principal = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    ok(f'VERSAO_GRAVADOR = "{gravador.VERSAO}"' in principal,
       f"o app espera outra versão do gravador — o gravador diz "
       f"{gravador.VERSAO!r} e o main.py não concorda")

    # Limpa o que os cortes de mentira deixaram para trás.
    for nome in ("clipe_99.mp4",):
        alvo = os.path.join(RAIZ, "gravacoes", nome)
        if os.path.exists(alvo):
            os.remove(alvo)

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ corte vazio: o gravador confere o arquivo antes de cortar")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
