"""
Monta o PNG 1080x1350 do campinho com os onze, sobre o template do Vini.

O QUE ESTE ARQUIVO DESENHA
    O template e os jogadores. Só isso. Teve uma versão que também escrevia
    título, dia e hora, confronto, escudos, lesionados, suspensos e a marca —
    o Vini pediu para tirar tudo: o resto da arte ele monta no Canva, e o que
    ele precisa daqui é o campinho pronto.

POR QUE NO SERVIDOR, E NÃO NO NAVEGADOR
    O caminho óbvio seria desenhar num <canvas> e chamar toBlob(). Não dá: as
    fotos dos jogadores vêm do Transfermarkt, de outro domínio, e qualquer
    pixel estrangeiro CONTAMINA o canvas — o toBlob passa a lançar exceção de
    segurança. Daria para passar as onze fotos pelo nosso proxy só para
    despoluir, mas aí são onze requisições extras a cada clique, no celular,
    para no fim recolorir o que o servidor já sabe montar de uma vez.

    Aqui as fotos e as bandeiras são buscadas uma vez, em paralelo, e o que
    volta é o arquivo final.

DE ONDE VÊM AS MEDIDAS
    Todas as posições foram tiradas a régua da arte que o Vini já publica
    (a de Al Najmah x Al Ittihad): título com 109px de altura de caixa alta,
    placa de nome com 35px, foto com 86px de diâmetro e anel de 3px, faixa dos
    escudos em x 0..127. Não são números escolhidos por gosto — são a arte
    dele, e é por isso que estão escritos como constantes com nome, e não
    espalhados pelo código.

O QUE ESTE MÓDULO NÃO FAZ
    Não decide nada. Nome, foto, bandeira, posição, lista de lesionados: tudo
    chega pronto de quem chamou. Assim ele é testável sem rede — e o teste
    monta a arte inteira com dados de mentira, sem tocar no Transfermarkt.
"""
from __future__ import annotations

import io
import os

LARGURA, ALTURA = 1080, 1350
CQ = LARGURA / 100.0                      # 1% da largura, a unidade de tudo

PASTA = os.path.dirname(os.path.abspath(__file__))
ARTE_FUNDO = os.path.join(PASTA, "public", "masks", "campo-perspectiva.png")
FONTES = os.path.join(PASTA, "public", "fonts")

GRAFITE = (48, 48, 48)                    # #303030, o cinza da identidade
BRANCO = (255, 255, 255)
FOTO_VAZIA = (238, 242, 245)

# ── a projeção, a MESMA da tela ──────────────────────────────────────────────
# Repetida aqui porque lá ela é JavaScript. Se um dia divergirem, o que o Vini
# arrasta na tela deixa de ser o que sai no arquivo — e o defeito só aparece
# comparando as duas imagens lado a lado. teste_escalacao_arte.py compara os
# dois números para cada casa de cada formação, justamente por isso.
PROJ = dict(cx=49.95, y_longe=29.19, y_meio=42.15, y_perto=70.59,
            w_longe=34.54, w_perto=75.78)
APERTO = 1.00

_PB = PROJ["y_longe"]
_PC = (2 * PROJ["y_meio"] - _PB - PROJ["y_perto"]) / (PROJ["y_perto"] - PROJ["y_meio"])
_PA = PROJ["y_meio"] * _PC + 2 * PROJ["y_meio"] - 2 * _PB


def projetar(x: float, y: float) -> tuple[float, float, float]:
    """(x,y) do campo visto de cima -> (x%, y%, escala) sobre a arte."""
    u = 0.5 + (x / 100 - 0.5) * APERTO
    v = max(0.0, min(1.0, y / 100))
    py = (_PA * v + _PB) / (_PC * v + 1)
    larg = (PROJ["w_longe"] + (py - PROJ["y_longe"])
            * (PROJ["w_perto"] - PROJ["w_longe"])
            / (PROJ["y_perto"] - PROJ["y_longe"]))
    esc = 0.88 + 0.12 * (larg - PROJ["w_longe"]) / (PROJ["w_perto"] - PROJ["w_longe"])
    return PROJ["cx"] + (u - 0.5) * larg, py, esc


# ── medidas da arte do Vini, em px de uma imagem 1080x1350 ───────────────────
FOTO_DIAM = 7.96 * CQ          # 86
FOTO_ANEL = 0.33 * CQ          # 3,5
PLACA_ALT = 3.24 * CQ          # 35
PLACA_PAD = 1.1 * CQ           # 12
PLACA_GAP = 0.7 * CQ           # 7,5
PLACA_SOBE = 1.1 * CQ          # o quanto a placa monta sobre a foto
NOME_CORPO = 2.04 * CQ         # 22
BANDEIRA_ALT = 1.47 * CQ       # ~16, a bandeirinha dentro da placa

def iso_da_bandeira(emoji: str | None) -> str | None:
    """🇧🇷 -> 'br'. O emoji de bandeira JÁ É o código do país.

    Cada bandeira é um par de "indicadores regionais", que são as letras A-Z
    deslocadas para o bloco 1F1E6. Ou seja: não preciso de mais um mapa de país
    para país — o dado que a tela já mostra carrega a sigla dentro dele.

    Bandeiras que não são de país (a da Inglaterra, por exemplo, que é uma
    sequência de tags) não casam com isso e voltam None. É o certo: placa sem
    bandeira é melhor que placa com a bandeira de outro país."""
    if not emoji:
        return None
    letras = [chr(ord("A") + ord(c) - 0x1F1E6) for c in emoji
              if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    return "".join(letras).lower() if len(letras) == 2 else None


def _fonte(arquivo: str, tamanho: int):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONTES, arquivo), max(1, int(tamanho)))


def _circulo(dados: bytes | None, diam: float) -> "Image.Image":
    """Foto recortada em círculo, com o anel #303030 por fora."""
    from PIL import Image, ImageDraw
    lado = int(round(diam))
    fora = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(fora)
    d.ellipse([0, 0, lado - 1, lado - 1], fill=FOTO_VAZIA)
    if dados:
        try:
            foto = Image.open(io.BytesIO(dados)).convert("RGB")
            # Recorte quadrado pelo centro do lado MENOR: a foto do TM é
            # retangular e um resize direto achataria o rosto.
            l = min(foto.size)
            e = (foto.width - l) // 2
            t = (foto.height - l) // 2
            foto = foto.crop((e, t, e + l, t + l)).resize((lado, lado), Image.LANCZOS)
            mascara = Image.new("L", (lado, lado), 0)
            ImageDraw.Draw(mascara).ellipse([0, 0, lado - 1, lado - 1], fill=255)
            fora.paste(foto, (0, 0), mascara)
        except Exception:
            pass
    anel = max(2, int(round(FOTO_ANEL * diam / FOTO_DIAM)))
    d.ellipse([anel / 2, anel / 2, lado - 1 - anel / 2, lado - 1 - anel / 2],
              outline=GRAFITE, width=anel)
    return fora


def _bandeira(dados: bytes | None, alt: float):
    from PIL import Image
    if not dados:
        return None
    try:
        b = Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None
    larg = max(1, int(round(b.width * alt / b.height)))
    return b.resize((larg, int(round(alt))), Image.LANCZOS)


def montar(dados: dict) -> bytes:
    """dados: {"jogadores": [{nome, x, y, foto: bytes|None,
    bandeira: bytes|None}]}. Devolve os bytes do PNG."""
    from PIL import Image, ImageDraw

    base = Image.open(ARTE_FUNDO).convert("RGB")
    if base.size != (LARGURA, ALTURA):
        base = base.resize((LARGURA, ALTURA), Image.LANCZOS)
    base = base.convert("RGBA")
    d = ImageDraw.Draw(base)

    # ── jogadores ────────────────────────────────────────────────────────────
    # Duas passagens: TODAS as fotos, depois TODAS as placas. Numa passagem só,
    # o círculo de um jogador cobre o fim da placa do vizinho — aconteceu com
    # "RENAN LODI" atrás do zagueiro, e some sem avisar.
    postos = []
    for j in dados.get("jogadores") or []:
        px, py, esc = projetar(float(j.get("x", 50)), float(j.get("y", 50)))
        postos.append((j, px * LARGURA / 100, py * ALTURA / 100, esc))

    for j, cx, cy, esc in postos:
        diam = FOTO_DIAM * esc
        base.alpha_composite(_circulo(j.get("foto"), diam),
                             (int(cx - diam / 2), int(cy - diam / 2)))

    for j, cx, cy, esc in postos:
        nome = (j.get("nome") or "").upper()
        if not nome:
            continue
        f = _fonte("WorkSans-SemiBold-latin.ttf", NOME_CORPO * esc)
        alt = PLACA_ALT * esc
        pad, gap = PLACA_PAD * esc, PLACA_GAP * esc
        band = _bandeira(j.get("bandeira"), BANDEIRA_ALT * esc)
        larg_band = (band.width + gap) if band else 0
        larg = pad * 2 + larg_band + d.textlength(nome, font=f)
        topo = cy + FOTO_DIAM * esc / 2 - PLACA_SOBE * esc
        x0 = cx - larg / 2
        d.rectangle([x0, topo, x0 + larg, topo + alt], fill=GRAFITE)
        if band:
            base.alpha_composite(band, (int(x0 + pad),
                                        int(topo + (alt - band.height) / 2)))
        cima, baixo = f.getbbox("H")[1], f.getbbox("H")[3]
        d.text((x0 + pad + larg_band, topo + (alt - (baixo - cima)) / 2 - cima),
               nome, font=f, fill=BRANCO)

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG", optimize=True)
    return saida.getvalue()
