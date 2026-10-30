"""O gravador consegue COMEÇAR a gravar?

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR (30/10/26)
    A janela do gravador na máquina emprestada morreu com:

        File "gravador.py", line 726, in comecar_pedaco
          proc = subprocess.Popen(cmd, ...)
        TypeError: expected str, bytes or os.PathLike object, not list

    Em 16/10 o `_urls_do_fluxo` passou a devolver (endereços, motivo), para
    que a falha do yt-dlp dissesse o motivo em vez de "ainda está no ar?". O
    único lugar que a chamava continuou lendo o resultado como lista: a tupla
    inteira entrava no comando do ffmpeg, e o `-i` recebia uma lista.

    Nenhum teste chamava o `comecar_pedaco`, e a máquina não rodou essa versão
    por onze dias (a VERSAO não tinha mudado — ver teste_versao_do_gravador).
    Na primeira vez que rodou, caiu no primeiro jogo.

    Aqui o caminho é chamado de verdade, com o yt-dlp e o ffmpeg trocados por
    dublês: o comando que iria para o Windows é conferido argumento por
    argumento.
"""
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import gravador                                             # noqa: E402

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


ditas, comandos = [], []
guard = (gravador.diz, gravador.subprocess.Popen, gravador.GRAVACOES)


class _Processo:
    def poll(self):
        return None


def _popen(cmd, *a, **k):
    comandos.append(cmd)
    return _Processo()


try:
    gravador.diz = lambda t="", erro=False: ditas.append(t)
    gravador.subprocess.Popen = _popen
    gravador.GRAVACOES = tempfile.mkdtemp()

    g = gravador.Gravador("https://app.exemplo", "token",
                          ["C:\\Python314\\python.exe", "-m", "yt_dlp"],
                          "C:\\ffmpeg\\bin\\ffmpeg.exe")
    jogo = gravador.Jogo("abc123", "https://youtube.com/watch?v=abc123",
                         "AL SHABAB X AL AHLI")

    # ── VÍDEO E ÁUDIO SEPARADOS, como o YouTube manda ─────────────────────
    g._urls_do_fluxo = lambda url: (["https://v.exemplo/video", "https://a.exemplo/audio"], "")
    try:
        comecou = g.comecar_pedaco(jogo)
    except Exception as e:
        comecou = False
        falhas.append(f"o gravador caiu ao começar a gravar: {type(e).__name__}: {e}")
    ok(comecou, "com os dois endereços na mão, o gravador não começou a gravar")
    cmd = comandos[-1] if comandos else []
    ok(cmd and all(isinstance(x, str) for x in cmd),
       f"o comando do ffmpeg tem argumento que não é texto — é o que derrubou a "
       f"janela em 30/10: {[type(x).__name__ for x in cmd if not isinstance(x, str)]}")
    entradas = [cmd[i + 1] for i, x in enumerate(cmd[:-1]) if x == "-i"]
    ok(entradas == ["https://v.exemplo/video", "https://a.exemplo/audio"],
       f"as entradas do ffmpeg saíram {entradas}")
    ok("-map" in cmd and cmd[-1].endswith(".ts"),
       "o comando perdeu o -map (o clipe sairia mudo) ou o arquivo de saída")
    ok(len(jogo.pedacos) == 1, "a gravação não foi registrada no jogo")

    # ── O YT-DLP FALHOU: o motivo aparece, e nada cai ────────────────────
    ditas.clear()
    g._urls_do_fluxo = lambda url: ([], "Sign in to confirm you're not a bot")
    try:
        comecou = g.comecar_pedaco(jogo)
    except Exception as e:
        comecou = True
        falhas.append(f"o gravador caiu quando o yt-dlp falhou: {type(e).__name__}: {e}")
    ok(comecou is False, "sem endereço, o gravador disse que começou a gravar")
    ok(any("Sign in to confirm" in t for t in ditas),
       f"o motivo do yt-dlp não apareceu na janela: {ditas}")
finally:
    gravador.diz, gravador.subprocess.Popen, gravador.GRAVACOES = guard

if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ gravador começa a gravar: comando só com texto, e o motivo quando o yt-dlp falha")
