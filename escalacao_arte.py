"""
Monta o PNG 1080x1350 da provável escalação, pronto para postar.

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
APERTO = 0.80

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

TITULO_TOPO, TITULO_CAP, TITULO_LARG = 77, 109, 890
DATA_BASE, DATA_CORPO = 301, 26
CONFRONTO_BASE, CONFRONTO_CORPO = 323, 24

FAIXA_X0, FAIXA_X1 = 0, 127
FAIXA_BLOCOS = ((330, 449), (450, 569), (570, 689))

RODAPE_X, RODAPE_LARG = 89, 483
RODAPE_TOPO, RODAPE_CORPO, RODAPE_LINHA = 1127, 22, 29
MARCA_DIR, MARCA_BASE, MARCA_CAP = 1064, 1329, 42


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


def _cabe(arquivo: str, texto: str, cap_alvo: int, larg_max: int):
    """Maior corpo que respeita a altura de caixa alta E a largura disponível.

    As duas restrições existem: só pela altura, um nome de confronto comprido
    estoura a margem; só pela largura, um curto fica gigante."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    corpo = 10
    for tam in range(10, 400):
        f = _fonte(arquivo, tam)
        alto = -f.getbbox("H")[1] + f.getbbox("H")[3]
        if alto > cap_alvo or d.textlength(texto, font=f) > larg_max:
            break
        corpo = tam
    return _fonte(arquivo, corpo)


def _texto_centrado(d, cx, base, texto, fonte, cor, espaco=0.0):
    """Desenha centrado em cx com a BASE da caixa alta em `base`.

    Alinhar pela base, e não pelo topo, é o que faz duas linhas de corpos
    diferentes ficarem visualmente encaixadas."""
    larg = d.textlength(texto, font=fonte) + espaco * max(0, len(texto) - 1)
    x = cx - larg / 2
    topo = base - (fonte.getbbox("H")[3] - fonte.getbbox("H")[1])
    if not espaco:
        d.text((x, topo - fonte.getbbox("H")[1]), texto, font=fonte, fill=cor)
        return
    for ch in texto:
        d.text((x, topo - fonte.getbbox("H")[1]), ch, font=fonte, fill=cor)
        x += d.textlength(ch, font=fonte) + espaco


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


def _quebrar(d, rotulo, nomes, f_rotulo, f_nome, larg_max):
    """Distribui 'LESIONADOS: a, b, c' em linhas que cabem na coluna."""
    linhas, atual = [], [(rotulo, f_rotulo)]
    largura = d.textlength(rotulo, font=f_rotulo)
    for i, nome in enumerate(nomes):
        pedaco = (" " if i == 0 else ", ") + nome + ("" if i == len(nomes) - 1 else "")
        w = d.textlength(pedaco, font=f_nome)
        if largura + w > larg_max and atual:
            linhas.append(atual)
            atual, largura = [], 0
            pedaco = pedaco.lstrip(", ").lstrip()
            w = d.textlength(pedaco, font=f_nome)
        atual.append((pedaco, f_nome))
        largura += w
    if atual:
        linhas.append(atual)
    return linhas


def montar(dados: dict) -> bytes:
    """dados: ver o docstring do módulo. Devolve os bytes do PNG."""
    from PIL import Image, ImageDraw

    base = Image.open(ARTE_FUNDO).convert("RGB")
    if base.size != (LARGURA, ALTURA):
        base = base.resize((LARGURA, ALTURA), Image.LANCZOS)
    base = base.convert("RGBA")
    d = ImageDraw.Draw(base)

    # ── faixa da esquerda: escudo, competição, escudo ────────────────────────
    for imagem, (y0, y1) in zip(dados.get("faixa") or [None, None, None], FAIXA_BLOCOS):
        if not imagem:
            continue
        try:
            logo = Image.open(io.BytesIO(imagem)).convert("RGBA")
        except Exception:
            continue
        cx, cy = (FAIXA_X0 + FAIXA_X1) / 2, (y0 + y1) / 2
        cabe = min(FAIXA_X1 - FAIXA_X0, y1 - y0) * 0.72
        k = cabe / max(logo.size)
        logo = logo.resize((max(1, int(logo.width * k)), max(1, int(logo.height * k))),
                           Image.LANCZOS)
        base.alpha_composite(logo, (int(cx - logo.width / 2), int(cy - logo.height / 2)))

    # ── título e cabeçalho ───────────────────────────────────────────────────
    titulo = (dados.get("titulo") or "PROVÁVEL ESCALAÇÃO").upper()
    f_tit = _cabe("Antonio-Bold.ttf", titulo, TITULO_CAP, TITULO_LARG)
    _texto_centrado(d, LARGURA / 2, TITULO_TOPO + TITULO_CAP, titulo, f_tit, BRANCO)

    if dados.get("linha_data"):
        _texto_centrado(d, LARGURA / 2, DATA_BASE, dados["linha_data"].upper(),
                        _fonte("WorkSans-Regular-latin.ttf", DATA_CORPO), BRANCO, 1.6)
    if dados.get("confronto"):
        _texto_centrado(d, LARGURA / 2, CONFRONTO_BASE, dados["confronto"].upper(),
                        _fonte("WorkSans-Bold-latin.ttf", CONFRONTO_CORPO), BRANCO, 1.2)

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
        band = _bandeira(j.get("bandeira"), NOME_CORPO * esc * 0.72)
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

    # ── rodapé: lesionados, suspensos e a marca ──────────────────────────────
    f_rot = _fonte("WorkSans-Bold-latin.ttf", RODAPE_CORPO)
    f_nom = _fonte("WorkSans-Regular-latin.ttf", RODAPE_CORPO)
    y = RODAPE_TOPO
    for rotulo, lista in (("LESIONADOS:", dados.get("lesionados") or []),
                          ("SUSPENSOS:", dados.get("suspensos") or [])):
        if not lista:
            continue
        for linha in _quebrar(d, rotulo, [n.upper() for n in lista],
                              f_rot, f_nom, RODAPE_LARG):
            x = RODAPE_X
            for pedaco, fonte in linha:
                # Alinhado pelo TOPO DA CAIXA ALTA: o topo da caixa da fonte
                # inclui espaço para acentos, e usá-lo faria a linha com "Ç"
                # descer em relação às outras.
                d.text((x, y - fonte.getbbox("H")[1]), pedaco, font=fonte, fill=GRAFITE)
                x += d.textlength(pedaco, font=fonte)
            y += RODAPE_LINHA
        y += RODAPE_LINHA * 0.6

    # A marca é a palavra, no mesmo tipo do título — o logo redondo de
    # public/masks é outra coisa e não é o que a arte do Vini usa aqui.
    f_marca = _cabe("Antonio-Bold.ttf", "ARABÃO", MARCA_CAP, 400)
    larg_marca = d.textlength("ARABÃO", font=f_marca)
    _texto_centrado(d, MARCA_DIR - larg_marca / 2, MARCA_BASE, "ARABÃO",
                    f_marca, GRAFITE)

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG", optimize=True)
    return saida.getvalue()
