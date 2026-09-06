"""
O clipe em 9:16, com a janela do corte ACOMPANHANDO o lance.

POR QUE NÃO É FUNDO DESFOCADO
    Fundo desfocado é o caminho seguro e é o que eu tinha proposto primeiro.
    O Vini recusou com razão: os canais grandes postam gol em 9:16 com a
    imagem cheia e a câmera seguindo a jogada, e ninguém quer parecer o
    amador ao lado deles.

POR QUE NÃO É RASTREIO DE BOLA
    Em plano aberto de transmissão a bola tem de 5 a 15 pixels, borra no
    chute, some atrás de perna e é confundida com meia branca e marcação de
    campo. Detector pronto erra muito nesse enquadramento e ainda custa
    minutos de CPU por clipe — num fluxo em que a graça é postar enquanto a
    comemoração rola, isso mata a ideia sozinho.

O QUE ELE FAZ, ENTÃO
    Grama é a cor dominante e não interessa. O que interessa — jogadores,
    árbitro, bola, trave — é tudo que NÃO é verde. Então a janela segue o
    centro de massa do não-verde, olhando só a faixa do campo (fora
    arquibancada, placar e o letreiro de patrocínio no rodapé).

    Isto é a mesma família do "auto reframe" do Premiere e do CapCut:
    saliência mais suavização. A transmissão já fez o trabalho difícil — o
    cinegrafista seguiu a bola — e aqui só é preciso não jogar fora o que
    ele enquadrou.

O QUE FAZ PARECER EDITADO, E NÃO AUTOMÁTICO
    Não é a detecção: é a SUAVIZAÇÃO e o LIMITE DE VELOCIDADE. Sem os dois,
    a janela treme a cada passe (o centro de massa pula quando um jogador
    entra ou sai do quadro) e panorâmica rápida em cima de panorâmica rápida
    embrulha o estômago de quem assiste. Tremor é o que denuncia automação.

MEDIDO EM CLIPE DE VERDADE (05/09/26)
    Num clipe de 22s do Al Hilal x Al Ahli, a janela andou 218 px dos 875
    possíveis, acompanhando árbitro e jogadores. Análise + recodificação
    levaram segundos, sem placa de vídeo.
"""
import glob
import os
import shutil
import subprocess
import tempfile

# Quadros por segundo da ANÁLISE. Não é a taxa do vídeo final: é de quantos
# em quantos instantes eu pergunto "onde está a ação?". Seis por segundo é
# mais que suficiente para uma janela que se move devagar, e mantém a conta
# barata.
FPS_ANALISE = 6.0
LARG_ANALISE = 320          # os quadros da análise são reduzidos para isto

# A faixa do quadro que eu olho. Fora dela: arquibancada em cima (torcida é
# "não-verde" e puxaria a janela para o alto o tempo todo) e o letreiro de
# patrocínio embaixo, que é fixo e não é lance.
TOPO_UTIL, BASE_UTIL = 0.38, 0.96

# Quanto tempo de janela a média móvel cobre. Dois segundos: curto demais
# treme, longo demais chega atrasado no contra-ataque.
SUAVIZACAO_SEG = 2.0

# Teto de velocidade da panorâmica, em pixels do quadro original por segundo.
VELOCIDADE_MAX = 55.0


def _mascara_nao_grama(img):
    """Uma imagem em cinza: claro onde NÃO é gramado."""
    from PIL import Image, ImageChops
    r, g, b = img.convert("RGB").split()
    # Verde domina quando g é maior que r E que b. O que sobra do máximo
    # entre (g-r) e (g-b) é o quanto aquele pixel é "verde"; invertendo,
    # tenho o quanto ele é qualquer outra coisa.
    verde = ImageChops.lighter(ImageChops.subtract(g, r),
                               ImageChops.subtract(g, b))
    return ImageChops.invert(verde.point(lambda v: 255 if v > 12 else 0))


def _centro_da_acao(caminho: str) -> float | None:
    """A coluna onde está a ação neste quadro, de 0 a LARG_ANALISE."""
    from PIL import Image
    with Image.open(caminho) as img:
        larg, alt = img.size
        faixa = img.crop((0, int(alt * TOPO_UTIL), larg, int(alt * BASE_UTIL)))
        mascara = _mascara_nao_grama(faixa)
        # Reduzir para uma linha dá a média de cada coluna numa chamada só —
        # em vez de varrer 57 mil pixels em Python, que seria lento no
        # servidor e é onde uma versão ingênua deste arquivo morreria.
        linha = mascara.resize((larg, 1), Image.BILINEAR)
        pesos = list(linha.getdata())
    total = sum(pesos)
    if total <= 0:
        return None
    return sum(i * p for i, p in enumerate(pesos)) / total


def _curva(quadros: list[str], larg_fonte: int, larg_corte: int) -> list[float]:
    """A posição da janela ao longo do tempo, já suavizada e freada."""
    escala = larg_fonte / float(LARG_ANALISE)
    max_x = float(larg_fonte - larg_corte)
    meio = max_x / 2.0

    brutos = []
    for q in quadros:
        c = _centro_da_acao(q)
        # Quadro sem informação (corte para a torcida, replay em preto)
        # repete o anterior em vez de jogar a janela para o meio: um salto
        # ali apareceria como um tranco no vídeo.
        if c is None:
            brutos.append(brutos[-1] if brutos else LARG_ANALISE / 2.0)
        else:
            brutos.append(c)

    alvo = [min(max(c * escala - larg_corte / 2.0, 0.0), max_x) for c in brutos]
    if not alvo:
        return [meio]

    jan = max(3, int(SUAVIZACAO_SEG * FPS_ANALISE) | 1)
    metade = jan // 2
    esticado = [alvo[0]] * metade + alvo + [alvo[-1]] * metade
    suave = [sum(esticado[i:i + jan]) / jan for i in range(len(alvo))]

    passo_max = VELOCIDADE_MAX / FPS_ANALISE
    saida = [suave[0]]
    for v in suave[1:]:
        delta = max(-passo_max, min(v - saida[-1], passo_max))
        saida.append(min(max(saida[-1] + delta, 0.0), max_x))
    return saida


def _dimensoes(ffmpeg: str, video: str) -> tuple[int, int]:
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", video],
                       capture_output=True, text=True, timeout=60)
    larg, alt = (r.stdout or "0x0").strip().split("x")[:2]
    return int(larg), int(alt)


def montar(dados: bytes, ffmpeg: str, altura_saida: int = 1920
           ) -> tuple[bytes, str]:
    """Recebe o mp4 16:9 e devolve (mp4 9:16, erro). Nunca levanta."""
    if not ffmpeg:
        return b"", "este servidor está sem ffmpeg"
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return b"", ("falta a biblioteca Pillow neste servidor — sem ela eu "
                     "não consigo olhar os quadros para enquadrar")

    pasta = tempfile.mkdtemp(prefix="reels_")
    entrada = os.path.join(pasta, "entra.mp4")
    saida = os.path.join(pasta, "sai.mp4")
    cmds = os.path.join(pasta, "cmds.txt")
    try:
        with open(entrada, "wb") as f:
            f.write(dados)

        larg, alt = _dimensoes(ffmpeg, entrada)
        if larg <= 0 or alt <= 0:
            return b"", "não consegui medir o vídeo"
        larg_corte = int(alt * 9 / 16) // 2 * 2
        if larg_corte >= larg:
            # Já é vertical (ou mais estreito): não há o que enquadrar.
            return dados, ""

        r = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", entrada,
             "-vf", f"fps={FPS_ANALISE},scale={LARG_ANALISE}:-2",
             "-q:v", "6", os.path.join(pasta, "q%05d.jpg")],
            capture_output=True, text=True, timeout=180)
        quadros = sorted(glob.glob(os.path.join(pasta, "q*.jpg")))
        if r.returncode != 0 or not quadros:
            return b"", f"não consegui extrair quadros: {(r.stderr or '')[:160]}"

        pontos = _curva(quadros, larg, larg_corte)
        with open(cmds, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{i / FPS_ANALISE:.3f} crop x {v:.0f};"
                              for i, v in enumerate(pontos)))

        larg_saida = int(altura_saida * 9 / 16) // 2 * 2
        filtro = (f"sendcmd=f='{cmds}',"
                  f"crop=w={larg_corte}:h={alt}:x={pontos[0]:.0f}:y=0,"
                  f"scale={larg_saida}:{altura_saida}:flags=bicubic,setsar=1")
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", entrada, "-vf", filtro,
             "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
             "-pix_fmt", "yuv420p", "-b:v", "5M",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-movflags", "+faststart", saida],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(saida):
            return b"", f"a montagem falhou: {(r.stderr or '')[:200]}"
        with open(saida, "rb") as f:
            return f.read(), ""
    except Exception as e:
        return b"", f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
