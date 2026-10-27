"""A arte da AGENDA DO DIA: foto, data e uma linha por jogo.

O QUE ELE PEDIU (26/10/26)
    "Conseguiríamos reproduzir isso aqui? Cria um botão de gerar agenda do
     dia?" — com a arte que ele faz à mão no Canva: AGENDA, a data, e uma
     linha por jogo com o logo da competição, os dois escudos, o confronto
     com os canais e o horário de Brasília.

    Decidido com ele: a foto de fundo ele sobe na hora (sem foto, entra a
    padrão); entram todas as competições do Bola Rolando, cada linha com o
    logo da sua; e a agenda vira post na home, como o de escalação.

AS CAMADAS
    foto (cobrindo a arte toda) → escurecido de baixo → camada de cima dele
    (formas verdes, título AGENDA e logo ARABÃO, já desenhados) → data →
    as linhas dos jogos.

    O escurecido não veio na camada de cima: na arte dele é um efeito sobre
    a foto. Medi o brilho da arte de 23/10 de cima a baixo e o reproduzi —
    começa por volta de y=650 e chega a quase preto em y=1200.

AS MEDIDAS SÃO DA ARTE DELE
    Linha de 100 px, 12 px entre linhas, quatro caixas (130, 181, 515, 130
    px de largura). Verde #01f468 com texto preto; cinza #303030 com texto
    #7d7d7d quando não há transmissão. Fontes e espaçamento calibrados pela
    altura e largura da tinta de cada texto da arte de 23/10 — ver
    `teste_agenda_arte.py`, que confere as medidas contra a arte dele.
"""
import io
import os

PASTA = os.path.dirname(os.path.abspath(__file__))
ARTE = os.path.join(PASTA, "public", "arte")
FONTES = os.path.join(PASTA, "public", "fonts")
SOBREPOSTO = os.path.join(ARTE, "agenda-sobreposto.png")
FOTO_PADRAO = os.path.join(ARTE, "agenda-fundo.jpg")
LOGOS = os.path.join(ARTE, "competicoes")

LARGURA, ALTURA = 1080, 1350

VERDE = (1, 244, 104, 255)
CINZA = (48, 48, 48, 255)
PRETO = (0, 0, 0, 255)
APAGADO = (125, 125, 125, 255)
BRANCO = (255, 255, 255, 255)

# ── AS CAIXAS DA LINHA (x, largura), medidas na arte de 23/10 ─────────────
CAIXA_LOGO = (47, 130)
CAIXA_ESCUDOS = (187, 181)
CAIXA_CONFRONTO = (378, 515)
CAIXA_HORA = (903, 130)
ALT_LINHA = 100
PASSO = 112                    # 100 da linha + 12 de intervalo
TOPO_ULTIMA = 1125             # a última linha fica sempre no mesmo lugar
TOPO_MINIMO = 322              # a data acaba em y=291; daqui para cima não sobe linha

# Dentro da linha, medido a partir do topo dela.
BASE_CONFRONTO = 49            # tinta de 28 a 48
BASE_CANAIS = 75               # tinta de 61 a 74
BASE_HORA = 63                 # tinta de 42 a 62
CENTRO_TEXTO_X = 640           # o centro da tinta do texto na caixa do meio
LOGO_MAX = (80, 73)            # o RSL ocupa 80x72 na arte dele
ESCUDO_MAX = 74
ESCUDOS_X = (234, 321)         # os centros dos dois escudos
CENTRO_Y = 49

# ── O TEXTO (corpo, espaçamento), calibrado pela tinta da arte dele ───────
FONTE_FORTE = "WorkSans-Bold-latin.ttf"
FONTE_LEVE = "WorkSans-Regular-latin.ttf"
CONFRONTO = (31, 3.3)
HORA = (31, 4.7)
CANAIS = (21, -1.6)
DATA = (27, 0.6)
DATA_X, DATA_TOPO = 74, 269

# O escurecido de baixo, na mesma curva da arte dele.
ESCURO_INICIO, ESCURO_FIM, ESCURO_MAX = 640, 1230, 235

# Competição → arquivo do logo. Os da AFC pelo nome que ele deu aos
# arquivos: `champions` é a Champions League Elite e `champions2` a Two.
LOGO_DA_COMPETICAO = {
    307: "rsl.png",
    504: "kingscup.png",
    826: "supercup.png",
    17: "champions.png",
    18: "champions2.png",
}

# O canal dele vai em negrito; os outros, não — como na arte de 23/10.
CANAIS_EM_NEGRITO = {"CANAL GOAT"}


def _fonte(arquivo, corpo):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONTES, arquivo), max(1, int(corpo)))


def _abrir(dados):
    if not dados:
        return None
    try:
        from PIL import Image
        if hasattr(dados, "mode"):
            return dados.convert("RGBA")
        return Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None


def _lanczos():
    from PIL import Image
    return Image.LANCZOS


def _cobrir(img, largura, altura, ancora_y=0.3):
    """A foto cobrindo a arte inteira, sem esticar: corta o que sobra.

    Corte vertical puxado para cima (0,3): em foto de jogador, o rosto quase
    sempre está no terço de cima, e um corte centrado cortaria a cabeça."""
    escala = max(largura / img.width, altura / img.height)
    nova = img.resize((max(1, round(img.width * escala)),
                       max(1, round(img.height * escala))), _lanczos())
    x = (nova.width - largura) // 2
    y = int((nova.height - altura) * ancora_y)
    return nova.crop((x, y, x + largura, y + altura))


def _escurecido():
    from PIL import Image
    faixa = Image.new("L", (1, ALTURA), 0)
    px = faixa.load()
    for y in range(ALTURA):
        if y <= ESCURO_INICIO:
            v = 0
        elif y >= ESCURO_FIM:
            v = ESCURO_MAX
        else:
            v = round(ESCURO_MAX * (y - ESCURO_INICIO) / (ESCURO_FIM - ESCURO_INICIO))
        px[0, y] = v
    preto = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 255))
    preto.putalpha(faixa.resize((LARGURA, ALTURA)))
    return preto


def _tingir(img, cor):
    """O logo branco no tom da linha: preto no verde, apagado no cinza."""
    from PIL import Image
    tinta = Image.new("RGBA", img.size, cor)
    tinta.putalpha(img.getchannel("A"))
    return tinta


def _caber(img, larg, alt):
    img = img.crop(img.getchannel("A").getbbox() or (0, 0, img.width, img.height))
    escala = min(larg / img.width, alt / img.height)
    return img.resize((max(1, round(img.width * escala)),
                       max(1, round(img.height * escala))), _lanczos())


def logo_da_competicao(competicao):
    arquivo = LOGO_DA_COMPETICAO.get(competicao)
    if not arquivo:
        return None
    caminho = os.path.join(LOGOS, arquivo)
    if not os.path.exists(caminho):
        return None
    from PIL import Image
    return Image.open(caminho).convert("RGBA")


def _pedacos_largura(d, pedacos, trk):
    total, n = 0.0, 0
    for texto, fonte in pedacos:
        for ch in texto:
            total += d.textlength(ch, font=fonte)
            n += 1
    return total + trk * max(0, n - 1)


def _escrever_centrado(base, pedacos, trk, centro_x, base_y, cor, limite=None):
    """Texto letra a letra, com o CENTRO DA TINTA em `centro_x`.

    Pela tinta, e não pela largura de avanço: é assim que a arte dele foi
    medida, e as duas diferem em alguns pixels. Se passar de `limite`, o
    espaçamento aperta até caber — nome longo de clube da AFC, por exemplo.
    """
    from PIL import Image, ImageDraw
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    if limite:
        while trk > -6 and _pedacos_largura(d0, pedacos, trk) > limite:
            trk -= 0.5
    larg = int(_pedacos_largura(d0, pedacos, trk)) + 60
    tela = Image.new("RGBA", (larg, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(tela)
    x = 20
    for texto, fonte in pedacos:
        for ch in texto:
            d.text((x, 110), ch, font=fonte, fill=cor, anchor="ls")
            x += d.textlength(ch, font=fonte) + trk
    caixa = tela.getbbox()
    if not caixa:
        return
    meio = (caixa[0] + caixa[2]) / 2
    base.alpha_composite(tela, (int(round(centro_x - meio)), int(base_y - 110)))


def _linha_de_canais(canais):
    """[(texto, negrito?)] — 'CANAL GOAT E XSPORTS', com o canal dele forte."""
    nomes = [n for n in (canais or []) if n]
    partes = []
    for i, nome in enumerate(nomes):
        if i:
            partes.append((" E " if i == len(nomes) - 1 else ", ", False))
        partes.append((nome, nome in CANAIS_EM_NEGRITO))
    return partes


def nome_de_canal(canal: str) -> str:
    """'Canal GOAT 🐐' → 'CANAL GOAT': sem emoji, em maiúsculas."""
    limpo = "".join(c for c in (canal or "") if c.isalnum() or c in " -")
    return " ".join(limpo.split()).upper()


def topos_das_linhas(n: int) -> list:
    """Os topos das linhas na MEDIDA DA ARTE DELE, de cima para baixo, com a
    última sempre em y=1125. Linha de 100 e intervalo de 12, sempre."""
    if n <= 0:
        return []
    return [TOPO_ULTIMA - (n - 1 - i) * PASSO for i in range(n)]


def escala_do_bloco(n: int) -> float:
    """1.0 até 8 jogos. Mais que isso, o bloco inteiro diminui POR IGUAL
    (quadros, intervalos, textos e escudos) para caber entre a data e o pé.

    A primeira versão apertava só o intervalo, e com 11 jogos (27/10/26) os
    quadros se encavalaram: 100 px de quadro num passo de 81."""
    if n <= 0:
        return 1.0
    altura = n * PASSO - (PASSO - ALT_LINHA)
    cabe = TOPO_ULTIMA + ALT_LINHA - TOPO_MINIMO
    return min(1.0, cabe / altura)


def montar(dados: dict) -> bytes:
    """O PNG 1080x1350 da agenda.

    dados = {"data": "23/10 - SEXTA", "foto": bytes|None,
             "jogos": [{"competicao": 307, "casa": "FAISALY", "fora": "NASSR",
                        "escudo_casa": bytes, "escudo_fora": bytes,
                        "hora": "10:30", "canais": ["CANAL GOAT", "XSPORTS"]}]}

    `canais`: lista com nomes = linha verde; vazia (ou None) = SEM
    TRANSMISSÃO, linha cinza. Jogo não confirmado na guia Agendamentos nem
    chega aqui (27/10/26).
    """
    from PIL import Image, ImageDraw

    foto = _abrir(dados.get("foto"))
    if foto is None:
        foto = Image.open(FOTO_PADRAO).convert("RGBA")
    base = _cobrir(foto, LARGURA, ALTURA)
    base.alpha_composite(_escurecido())
    capa = Image.open(SOBREPOSTO).convert("RGBA")
    if capa.size != (LARGURA, ALTURA):
        capa = capa.resize((LARGURA, ALTURA), _lanczos())
    base.alpha_composite(capa)

    d = ImageDraw.Draw(base)

    # ── A DATA ───────────────────────────────────────────────────────────
    texto_data = (dados.get("data") or "").upper()
    if texto_data:
        fd = _fonte(FONTE_LEVE, DATA[0])
        # A linha de base sai da MESMA frase medida na arte dele, para que um
        # acento (SÁBADO) suba a tinta sem descer o texto.
        topo_ref = fd.getbbox("23/10 - SEXTA", anchor="ls")[1]
        base_y = DATA_TOPO - topo_ref
        x = DATA_X - (fd.getmask(texto_data[0]).getbbox() or (0,))[0]
        for ch in texto_data:
            d.text((x, base_y), ch, font=fd, fill=BRANCO, anchor="ls")
            x += d.textlength(ch, font=fd) + DATA[1]

    # ── AS LINHAS ────────────────────────────────────────────────────────
    jogos = list(dados.get("jogos") or [])
    # As linhas vão para uma camada própria, na medida exata da arte dele.
    # Até 8 jogos a camada é colada como está; com mais, ela é reduzida por
    # igual e encostada no pé, centrada.
    escala = escala_do_bloco(len(jogos))
    topos = topos_das_linhas(len(jogos))
    desloc = max(0, -topos[0]) if topos else 0   # muitos jogos: topo acima de 0
    camada = Image.new("RGBA", (LARGURA, ALTURA + desloc), (0, 0, 0, 0))
    _desenhar_linhas(camada, jogos, desloc)
    if escala >= 1.0:
        base.alpha_composite(camada)
    else:
        fundo_bloco = TOPO_ULTIMA + ALT_LINHA
        bloco = camada.crop((0, topos[0] + desloc, LARGURA, fundo_bloco + desloc))
        bloco = bloco.resize((round(LARGURA * escala),
                              round(bloco.height * escala)), _lanczos())
        base.alpha_composite(bloco, ((LARGURA - bloco.width) // 2,
                                     fundo_bloco - bloco.height))

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG")
    return saida.getvalue()


def _desenhar_linhas(base, jogos: list, desloc: int = 0) -> None:
    """As linhas dos jogos, na medida da arte dele, `desloc` px abaixo do
    lugar normal (com muitos jogos o topo de cima ficaria acima de y=0)."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(base)
    f_conf = _fonte(FONTE_FORTE, CONFRONTO[0])
    f_hora = _fonte(FONTE_FORTE, HORA[0])
    f_can_forte = _fonte(FONTE_FORTE, CANAIS[0])
    f_can_leve = _fonte(FONTE_LEVE, CANAIS[0])

    for topo, jogo in zip(topos_das_linhas(len(jogos)), jogos):
        topo += desloc
        canais = jogo.get("canais")
        sem = not canais
        fundo = CINZA if sem else VERDE
        tinta = APAGADO if sem else PRETO
        for x, larg in (CAIXA_LOGO, CAIXA_ESCUDOS, CAIXA_CONFRONTO, CAIXA_HORA):
            d.rectangle((x, topo, x + larg - 1, topo + ALT_LINHA - 1), fill=fundo)

        logo = logo_da_competicao(jogo.get("competicao"))
        if logo is not None:
            logo = _tingir(_caber(logo, *LOGO_MAX), tinta)
            cx = CAIXA_LOGO[0] + CAIXA_LOGO[1] / 2
            base.alpha_composite(logo, (int(cx - logo.width / 2),
                                        int(topo + CENTRO_Y - logo.height / 2)))

        for centro, chave in zip(ESCUDOS_X, ("escudo_casa", "escudo_fora")):
            esc = _abrir(jogo.get(chave))
            if esc is None:
                continue
            esc = _caber(esc, ESCUDO_MAX, ESCUDO_MAX)
            base.alpha_composite(esc, (int(centro - esc.width / 2),
                                       int(topo + CENTRO_Y - esc.height / 2)))

        confronto = f"{(jogo.get('casa') or '').upper()} X {(jogo.get('fora') or '').upper()}"
        _escrever_centrado(base, [(confronto, f_conf)], CONFRONTO[1],
                           CENTRO_TEXTO_X, topo + BASE_CONFRONTO, tinta,
                           limite=CAIXA_CONFRONTO[1] - 40)

        if sem:
            pedacos = [("SEM TRANSMISSÃO", f_can_leve)]
        else:
            pedacos = [(t, f_can_forte if forte else f_can_leve)
                       for t, forte in _linha_de_canais(canais)]
        _escrever_centrado(base, pedacos, CANAIS[1], CENTRO_TEXTO_X,
                           topo + BASE_CANAIS, tinta,
                           limite=CAIXA_CONFRONTO[1] - 40)

        _escrever_centrado(base, [(jogo.get("hora") or "", f_hora)], HORA[1],
                           CAIXA_HORA[0] + CAIXA_HORA[1] / 2,
                           topo + BASE_HORA, tinta)
