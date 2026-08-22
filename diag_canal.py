"""
Diagnóstico: o que o yt-dlp enxerga na aba /streams do canal do parceiro.

POR QUE ISTO EXISTE
    A guia Clipes só mostra as transmissões que o gravador conta para o app.
    O gravador, por sua vez, confia num único campo do yt-dlp — live_status —
    para decidir o que está no ar. Se esse campo vier vazio, a transmissão
    some da tela sem nenhum erro aparecer em lugar nenhum.

    Já aconteceu duas vezes de a tela dizer "o canal não está transmitindo
    nada" com jogo rolando. Da primeira, o gravador nem falava com o app. Da
    segunda, os títulos do canal tinham barra ("Time A x Time B | AO VIVO E
    COM IMAGENS") e a barra era justamente o separador dos campos.

    Este arquivo não decide nada e não conserta nada. Ele mostra a lista crua,
    do jeito que o yt-dlp devolve, para a conversa ser sobre o que está lá e
    não sobre o que a gente imagina que está.

COMO RODAR
    Dois cliques em  diag_canal.bat

O relatório sai em  diag_canal_RELATORIO.txt
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "diag_canal_RELATORIO.txt")
CANAL = "https://www.youtube.com/@canalgoatbr"
QUANTOS = 25

linhas: list[str] = []


def diz(t: str = "") -> None:
    print(t, flush=True)
    linhas.append(t)


def achar(nome: str) -> str:
    return shutil.which(nome) or shutil.which(nome + ".exe") or ""


def achar_ytdlp() -> list:
    direto = achar("yt-dlp")
    if direto:
        return [direto]
    for interp in ("py", "python", "python3"):
        caminho = achar(interp)
        if not caminho:
            continue
        base = [caminho, "-3"] if interp == "py" else [caminho]
        try:
            r = subprocess.run(base + ["-m", "yt_dlp", "--version"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return base + ["-m", "yt_dlp"]
        except Exception:
            pass
    return []


def rodar(cmd: list, limite: int = 180) -> tuple:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=limite,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


diz("=" * 78)
diz("O QUE O CANAL ESTÁ TRANSMITINDO — " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
diz("=" * 78)
diz()

YTDLP = achar_ytdlp()
if not YTDLP:
    diz("    Não achei o yt-dlp.  py -3 -m pip install -U yt-dlp")
    open(RELATORIO, "w", encoding="utf-8").write("\n".join(linhas))
    input("\nEnter para fechar...")
    sys.exit(1)

cod, out, _ = rodar(YTDLP + ["--version"], 60)
diz(f"    yt-dlp {out.strip()[:20]}   ({' '.join(YTDLP)})")
diz(f"    canal  {CANAL}")
diz()

# Separador que não existe em título de vídeo. A barra existe, e foi ela que
# quebrou o gravador: "AL AHLI X ABHA | AO VIVO E COM IMAGENS" tem barra.
SEP = "\x1f"
diz(f"1) A ABA /streams, ACHATADA (as {QUANTOS} primeiras)")
diz("-" * 78)
cod, out, err = rodar(YTDLP + [
    "--no-warnings", "--flat-playlist", "--playlist-end", str(QUANTOS),
    "--print", f"%(id)s{SEP}%(live_status)s{SEP}%(title)s",
    CANAL.rstrip("/") + "/streams"])

if cod != 0 and not out.strip():
    diz(f"    o yt-dlp falhou: {err.strip()[:400]}")
    open(RELATORIO, "w", encoding="utf-8").write("\n".join(linhas))
    input("\nEnter para fechar...")
    sys.exit(1)

entradas = []
for linha in out.splitlines():
    partes = linha.split(SEP)
    if len(partes) < 3 or not partes[0].strip():
        continue
    entradas.append((partes[0].strip(), partes[1].strip(), partes[2].strip()))

diz(f"    {len(entradas)} entrada(s)")
diz()
diz(f"    {'id':13} {'live_status':13} título")
for vid, estado, titulo in entradas:
    marca = ">>" if estado == "is_live" else "  "
    diz(f" {marca} {vid:13} {estado:13} {titulo[:44]}")
diz()

no_ar = [e for e in entradas if e[1] == "is_live"]
duvida = [e for e in entradas if e[1] not in ("is_live", "was_live")]
diz(f"    no ar segundo a lista achatada: {len(no_ar)}")
diz()

# ── 2. Conferir uma por uma as que a lista achatada não deu como encerradas ──
#
# A extração achatada tira live_status de um selo na miniatura. Quando o
# YouTube muda o desenho da página, o selo some e o campo vem vazio — sem
# erro nenhum. Abrir o vídeo pergunta direto à fonte e não depende de selo.
diz("2) CONFERINDO UMA POR UMA (só as que não vieram como encerradas)")
diz("-" * 78)
if not duvida:
    diz("    nenhuma em dúvida — a lista achatada classificou todas.")
else:
    for vid, estado, titulo in duvida[:8]:
        cod, out2, err2 = rodar(YTDLP + [
            "--no-warnings", "--print", f"%(live_status)s{SEP}%(is_live)s",
            f"https://www.youtube.com/watch?v={vid}"], 120)
        real = (out2.strip().splitlines() or [""])[-1].split(SEP)
        certo = real[0] if real else "?"
        diz(f"    {vid}  achatada={estado:12} de verdade={certo:12} {titulo[:34]}")
        if cod != 0:
            diz(f"        (o yt-dlp reclamou: {err2.strip()[:120]})")
diz()

diz("3) O QUE ISSO QUER DIZER")
diz("-" * 78)
diz("    Se a coluna 'de verdade' disser is_live onde a 'achatada' não disse,")
diz("    o gravador está perdendo transmissão por causa do selo da miniatura,")
diz("    e ele precisa conferir uma por uma como este arquivo acabou de fazer.")
diz("    Se as duas colunas concordarem, a lista do app está certa e o jogo que")
diz("    você está vendo não está saindo por este canal.")
diz()

open(RELATORIO, "w", encoding="utf-8").write("\n".join(linhas))
diz(f"    relatório em  {os.path.basename(RELATORIO)}")
input("\nEnter para fechar...")
