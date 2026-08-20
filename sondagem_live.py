"""
Sondagem: dá para gravar a live do parceiro e recortar um clipe no padrão do X?

POR QUE ISTO EXISTE
    O plano de publicar gol durante a partida depende de uma máquina gravando
    a transmissão desde o apito inicial. Antes de escrever esse gravador, quero
    saber três coisas que só se descobrem tentando:

      1. o yt-dlp consegue puxar ESTA transmissão, deste canal, da sua conexão?
      2. o arquivo que sai é íntegro, ou vem cortado/corrompido?
      3. o recorte de 15 segundos sai no formato que o X aceita?

    Se qualquer uma falhar, é melhor descobrir hoje, com 3 minutos de gravação,
    do que no meio de um jogo.

COMO RODAR
    1. Ponha o link da transmissão num arquivo  live_url.txt  nesta pasta.
       (Ou rode e cole quando ela perguntar.)
    2. Dois cliques em  sondagem_live.bat

    Precisa de yt-dlp e ffmpeg. Se faltar, a sondagem te diz como instalar e
    para — ela não baixa nem instala nada sozinha.

O QUE ELA NÃO FAZ
    Não publica nada, não fala com o X, não sobe arquivo para lugar nenhum.
    Grava, corta, mede e escreve um relatório. Os arquivos ficam nesta pasta.

O relatório sai em  sondagem_live_RELATORIO.txt
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem_live_RELATORIO.txt")
BRUTO = os.path.join(PASTA, "sondagem_live_gravacao.ts")
CLIPE = os.path.join(PASTA, "sondagem_live_clipe.mp4")

SEGUNDOS_GRAVANDO = 180      # 3 minutos: o bastante para ver se ela se sustenta
SEGUNDOS_CLIPE = 15          # a janela que você quer no gol

linhas: list[str] = []


def diz(t: str = "") -> None:
    print(t, flush=True)
    linhas.append(t)


def salvar() -> None:
    with open(RELATORIO, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def rodar(cmd: list, limite: int = 300) -> tuple[int, str]:
    """Executa e devolve (código, saída). Nunca levanta."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=limite, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -9, "estourou o tempo limite"
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def achar(nome: str) -> str:
    return shutil.which(nome) or shutil.which(nome + ".exe") or ""


def achar_ytdlp() -> list:
    """Devolve o comando para chamar o yt-dlp, ou [] se não houver.

    Não basta procurar o executável no PATH. O Python 3.14 instala os
    programas dos pacotes num diretório que o Windows não põe no PATH por
    padrão — foi exatamente o que aconteceu nesta máquina: o pacote estava
    instalado e o 'yt-dlp' não era reconhecido. Chamar como MÓDULO
    (py -3 -m yt_dlp) funciona sempre que o pacote existe, PATH ou não.
    """
    direto = achar("yt-dlp")
    if direto:
        return [direto]
    for interp in ("py", "python", "python3"):
        caminho = achar(interp)
        if not caminho:
            continue
        base = [caminho, "-3"] if interp == "py" else [caminho]
        cod, _ = rodar(base + ["-m", "yt_dlp", "--version"], 60)
        if cod == 0:
            return base + ["-m", "yt_dlp"]
    return []


diz("=" * 76)
diz("SONDAGEM DA LIVE — " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
diz("=" * 76)
diz()

# ── 0. As ferramentas existem? ───────────────────────────────────────────
diz("0) FERRAMENTAS")
diz("-" * 76)
YTDLP = achar_ytdlp()
FFMPEG = achar("ffmpeg")
FFPROBE = achar("ffprobe")

diz(f"    {'yt-dlp':8} {'ok  ' + ' '.join(YTDLP) if YTDLP else 'NÃO ENCONTRADO'}")
for nome, caminho in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
    diz(f"    {nome:8} {'ok  ' + caminho if caminho else 'NÃO ENCONTRADO'}")

if not YTDLP or not FFMPEG or not FFPROBE:
    diz()
    diz("    Falta ferramenta. Como instalar no Windows:")
    if not YTDLP:
        diz("      yt-dlp :  py -3 -m pip install -U yt-dlp")
        diz("                (se o pip disser que ja esta instalado, o problema")
        diz("                 e outro e o relatorio acima ja teria achado)")
    if not FFMPEG or not FFPROBE:
        diz("      ffmpeg :  winget install Gyan.FFmpeg")
        diz("                (depois FECHE e reabra o terminal, para o PATH atualizar)")
    diz()
    diz("    Instale e rode de novo. Não instalo nada por você de propósito —")
    diz("    baixar executável sem você ver não é coisa que eu deva fazer.")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)

cod, saida = rodar(YTDLP + ["--version"], 60)
diz(f"    versão do yt-dlp: {saida.strip()[:40]}")
diz()

# ── 1. Que link é esse? ──────────────────────────────────────────────────
diz("1) A TRANSMISSÃO")
diz("-" * 76)
arq_url = os.path.join(PASTA, "live_url.txt")
URL = ""
if os.path.exists(arq_url):
    URL = open(arq_url, encoding="utf-8").read().strip()
    diz(f"    li o link de live_url.txt")
if not URL:
    URL = input("    cole o link da transmissão e dê Enter: ").strip()
if not URL:
    diz("    sem link, não há o que sondar.")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)

cod, saida = rodar(YTDLP + ["--no-warnings", "--print",
                    "%(is_live)s|%(live_status)s|%(title)s|%(duration)s", URL], 120)
if cod != 0:
    diz(f"    yt-dlp não conseguiu nem ler o vídeo:")
    diz(f"    {saida.strip()[:600]}")
    diz()
    diz("    Este já é o resultado: se ele não lê, não grava.")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)

campos = (saida.strip().splitlines() or [""])[-1].split("|")
ao_vivo = campos[0] if campos else "?"
estado = campos[1] if len(campos) > 1 else "?"
titulo = campos[2] if len(campos) > 2 else "?"
diz(f"    título    : {titulo[:60]}")
diz(f"    ao vivo   : {ao_vivo}   (live_status: {estado})")
if ao_vivo != "True":
    diz()
    diz("    ATENÇÃO: não está ao vivo agora. A sondagem continua e ainda diz")
    diz("    se o corte funciona, mas o teste que interessa — aguentar duas")
    diz("    horas de transmissão — só vale com jogo rolando.")
diz()

cod, saida = rodar(YTDLP + ["--no-warnings", "-F", URL], 120)
formatos = [l for l in saida.splitlines() if "m3u8" in l or "mp4" in l or "audio" in l.lower()]
diz(f"    {len(formatos)} formato(s). Listo TODOS: na primeira tentativa eu só")
diz("    mostrei os de vídeo e não percebi que eram todos 'video only'.")
for l in formatos:
    diz(f"      {l.strip()[:104]}")
so_video = [l for l in formatos if "video only" in l]
tem_audio = [l for l in formatos if "audio only" in l]
diz()
diz(f"    {len(so_video)} só-vídeo, {len(tem_audio)} só-áudio, "
    f"{len(formatos) - len(so_video) - len(tem_audio)} com os dois juntos")
diz()

# ── 2. Gravar ────────────────────────────────────────────────────────────
diz(f"2) GRAVANDO {SEGUNDOS_GRAVANDO}s")
diz("-" * 76)
for antigo in (BRUTO, CLIPE):
    if os.path.exists(antigo):
        os.remove(antigo)

# Pego a URL do fluxo com o yt-dlp e gravo com o ffmpeg. É de propósito: com
# -t o ffmpeg para na hora certa e FECHA o arquivo direito. Matar o yt-dlp no
# meio deixaria um arquivo sem finalizar, e eu não saberia se o defeito foi da
# transmissão ou da minha própria interrupção.
diz("    pedindo a URL do fluxo ao yt-dlp...")
# "bv*+ba" = melhor vídeo MAIS melhor áudio, como fluxos separados. O seletor
# anterior era "best[height<=720]", que pede um formato único contendo áudio e
# vídeo — e nesta transmissão não existe nenhum assim, todos são "video only".
# Daí o "Requested format is not available". As alternativas depois das barras
# cobrem o caso de um canal que ofereça formato combinado.
SELETOR = "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b"
cod, saida = rodar(YTDLP + ["--no-warnings", "-f", SELETOR, "-g", URL], 120)
fluxos = [l.strip() for l in saida.splitlines() if l.startswith("http")]
if not fluxos:
    diz(f"    não veio URL de fluxo: {saida.strip()[:400]}")
    diz("    (sem isso não dá para gravar com o ffmpeg)")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)
# Com fluxos separados o yt-dlp devolve DUAS urls: vídeo primeiro, áudio depois.
diz(f"    {len(fluxos)} fluxo(s) obtido(s) "
    f"({'vídeo + áudio separados' if len(fluxos) > 1 else 'único, já combinado'})")
diz("    (não mostro as URLs: elas carregam token da sessão)")

t0 = time.time()
diz(f"    gravando... (leva {SEGUNDOS_GRAVANDO}s, pode ir tomar um café)")
cmd = [FFMPEG, "-y", "-loglevel", "warning"]
for f in fluxos[:2]:
    cmd += ["-i", f]
cmd += ["-t", str(SEGUNDOS_GRAVANDO), "-c", "copy"]
if len(fluxos) > 1:
    # Duas entradas: pego o vídeo da primeira e o áudio da segunda. Sem o -map
    # o ffmpeg escolheria sozinho e poderia gravar só a primeira entrada, que
    # é a de vídeo — e o clipe sairia mudo.
    cmd += ["-map", "0:v:0", "-map", "1:a:0"]
cmd += [BRUTO]
cod, saida = rodar(cmd, SEGUNDOS_GRAVANDO + 180)
gasto = time.time() - t0
diz(f"    ffmpeg terminou em {gasto:.0f}s com código {cod}")
if saida.strip():
    diz(f"    avisos: {saida.strip()[:400]}")
if not os.path.exists(BRUTO) or os.path.getsize(BRUTO) < 1000:
    diz("    NÃO GRAVOU. Arquivo vazio ou inexistente.")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)

tam = os.path.getsize(BRUTO)
diz(f"    arquivo: {tam/1024/1024:.1f} MB")


def medir(caminho: str) -> dict:
    cod, saida = rodar([FFPROBE, "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", caminho], 120)
    try:
        return json.loads(saida)
    except Exception:
        return {}


d = medir(BRUTO)
dur = float((d.get("format") or {}).get("duration") or 0)
diz(f"    duração medida: {dur:.1f}s (pedi {SEGUNDOS_GRAVANDO}s)")
if dur < SEGUNDOS_GRAVANDO * 0.9:
    diz(f"    >>> veio {SEGUNDOS_GRAVANDO - dur:.0f}s a MENOS que o pedido.")
    diz("    >>> a transmissão caiu, engasgou, ou o fluxo terminou antes.")
for s in (d.get("streams") or []):
    diz(f"      {s.get('codec_type'):5} {s.get('codec_name'):6} "
        f"{s.get('width') or ''}x{s.get('height') or ''} "
        f"{s.get('pix_fmt') or ''} {s.get('r_frame_rate') or ''}")
diz()

# ── 3. Recortar no padrão do X ───────────────────────────────────────────
diz(f"3) RECORTE DE {SEGUNDOS_CLIPE}s NO PADRÃO DO X")
diz("-" * 76)
inicio = max(0, dur / 2 - SEGUNDOS_CLIPE / 2)
diz(f"    cortando de {inicio:.0f}s a {inicio + SEGUNDOS_CLIPE:.0f}s")
t0 = time.time()
# -ss antes do -i posiciona rápido; recodifico porque cópia bruta cortaria no
# keyframe mais próximo e o clipe começaria fora da hora.
cod, saida = rodar([FFMPEG, "-y", "-loglevel", "warning",
                    "-ss", f"{inicio:.2f}", "-i", BRUTO,
                    "-t", str(SEGUNDOS_CLIPE),
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-b:v", "5M", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                    "-movflags", "+faststart", CLIPE], 300)
diz(f"    ffmpeg código {cod} em {time.time()-t0:.1f}s")
if saida.strip():
    diz(f"    avisos: {saida.strip()[:300]}")

if not os.path.exists(CLIPE):
    diz("    NÃO GEROU O CLIPE.")
    salvar()
    input("\nEnter para fechar...")
    sys.exit(1)

c = medir(CLIPE)
cdur = float((c.get("format") or {}).get("duration") or 0)
ctam = os.path.getsize(CLIPE)
video = next((s for s in (c.get("streams") or []) if s.get("codec_type") == "video"), {})
audio = next((s for s in (c.get("streams") or []) if s.get("codec_type") == "audio"), {})
diz(f"    clipe: {ctam/1024/1024:.2f} MB, {cdur:.1f}s")
diz(f"      vídeo: {video.get('codec_name')} {video.get('width')}x{video.get('height')} "
    f"{video.get('pix_fmt')}")
diz(f"      áudio: {audio.get('codec_name')} {audio.get('sample_rate')}Hz "
    f"{audio.get('channels')}ch")
diz()

# O X publica estas exigências; confiro uma a uma em vez de torcer.
checagens = [
    ("vídeo em H.264", video.get("codec_name") == "h264"),
    ("pix_fmt yuv420p", video.get("pix_fmt") == "yuv420p"),
    ("tem faixa de áudio", bool(audio)),
    ("áudio em AAC", audio.get("codec_name") == "aac"),
    ("duração até 140s", 0 < cdur <= 140),
    ("tamanho até 512 MB", ctam <= 512 * 1024 * 1024),
    ("largura par", (video.get("width") or 0) % 2 == 0),
    ("altura par", (video.get("height") or 0) % 2 == 0),
]
diz("    CONTRA AS EXIGÊNCIAS DO X:")
falhas = 0
for rot, ok in checagens:
    diz(f"      {'ok   ' if ok else 'FALHA'} {rot}")
    if not ok:
        falhas += 1
diz()

diz("=" * 76)
diz("VEREDITO")
diz("-" * 76)
if falhas == 0 and dur >= SEGUNDOS_GRAVANDO * 0.9:
    diz("    Gravou íntegro e o clipe saiu no padrão do X.")
    diz("    O gravador é viável nesta máquina, nesta conexão, neste canal.")
elif falhas == 0:
    diz("    O recorte está certo, mas a GRAVAÇÃO veio curta.")
    diz("    Antes de construir, vale repetir com o jogo rolando — pode ter")
    diz("    sido oscilação de rede ou fim de transmissão.")
else:
    diz(f"    {falhas} exigência(s) do X não atendida(s). Dá para ajustar os")
    diz("    parâmetros do ffmpeg, mas eu precisaria ver o relatório antes.")
diz()
diz(f"    Abra {os.path.basename(CLIPE)} e veja se a imagem e o som estão bons.")
diz("    Nenhum número acima substitui você olhar o clipe.")
diz("=" * 76)

salvar()
print()
print(f"Relatório: {RELATORIO}")
print(f"Clipe    : {CLIPE}")
input("Enter para fechar...")
