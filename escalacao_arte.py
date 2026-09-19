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
    A régua foi a arte que o Vini já publica: placa de nome com 35px, foto com
    86px de diâmetro e anel de 3,5px, numa imagem de 1080x1350. Não são
    números escolhidos por gosto, e por isso estão como constantes com nome em
    vez de espalhados pelo código. O CSS da guia Elencos carrega os mesmos
    valores em cqw, e o teste compara os dois — se divergirem, o que aparece na
    tela deixa de ser o que sai no arquivo.

O QUE ESTE MÓDULO NÃO FAZ
    Não decide nada. Nome, foto, bandeira e posição chegam prontos de quem
    chamou. Assim ele é testável sem rede — o teste monta a arte inteira com
    dados de mentira, sem tocar no Transfermarkt.
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
# O QUE FICA ATRÁS DA FOTO DENTRO DO DISCO (18/09/26)
#
#     "Quando clicamos em baixar, ela vem diferente do que tem no campinho,
#      onde o fundo da foto fica branco. Se é um problema com a transparência,
#      o fundo poderia ser esse verde padrão que estamos usando no campinho."
#
# Era problema de transparência, sim, e de um tipo específico: o `convert("RGB")`
# do Pillow não COMPÕE o canal alfa sobre nada — ele simplesmente descarta o
# alfa e fica com o RGB que estava embaixo, que num recorte da SPL é preto. Na
# tela nada disso aparece, porque o navegador compõe a foto sobre o fundo do
# disco antes de mostrar. Daí o mesmo arquivo render ar diferente nos dois
# lugares, e o PNG sair com um quarto de círculo preto em cima da cabeça.
#
# O verde é escolha dele, e é o mesmo da grama: assim o recorte não fica com
# uma aba clara em volta do ombro, ele encosta no campo. O valor está escrito
# aqui e no CSS do campinho, e há teste conferindo que os dois são o mesmo —
# duas cores que deviam ser iguais e não são é a divergência mais fácil de não
# enxergar, porque ninguém compara hexadecimal de cabeça.
FOTO_VAZIA = (1, 244, 104)     # #01f468, o verde do campo

# ── a projeção ──────────────────────────────────────────────────────────────
# Vem do formacoes.py, que é quem precisa dela para decidir se uma linha de
# quatro cabe. Tê-la duplicada aqui foi tentador e seria a terceira cópia da
# mesma conta no projeto (a outra é o JavaScript da página, que o teste
# compara com esta).
from formacoes import PROJ, APERTO, projetar          # noqa: F401  (reexporta)

# ── medidas da arte do Vini, em px de uma imagem 1080x1350 ───────────────────
FOTO_DIAM = 7.96 * CQ          # 86
FOTO_ANEL = 0.33 * CQ          # 3,5
PLACA_ALT = 3.24 * CQ          # 35
PLACA_PAD = 1.1 * CQ           # 12
PLACA_GAP = 0.7 * CQ           # 7,5
PLACA_SOBE = 1.1 * CQ          # o quanto a placa monta sobre a foto
NOME_CORPO = 2.04 * CQ         # 22
BANDEIRA_ALT = 1.47 * CQ       # ~16, a bandeirinha dentro da placa

# ── O ZOOM NO ROSTO, DENTRO DO DISCO (18/09/26) ─────────────────────────────
#
# O PEDIDO
#     "A gente consegue nesta guia, dar um zoom na foto do jogador quando for
#      pro campinho, pra aparecer o rosto? (...) É algo que quero apenas pra
#      dentro do campinho, quando se arrastar a foto pra lá."
#
#     A foto da liga é meio corpo. Num disco de 86px o rosto saía do tamanho de
#     uma ervilha, com metade do círculo ocupada por ombro e camisa. Na lista de
#     jogadores, ao lado do nome, isso não incomoda — o pedido é só do campo.
#
# A CONTA É A DO NAVEGADOR, E DE PROPÓSITO
#     Na tela isto é uma linha de CSS: `transform: scale(Z)` com
#     `transform-origin: 50% 15%`. Aqui eu poderia recortar do jeito que
#     quisesse — e aí a prévia na tela e o PNG baixado divergiriam, que é o
#     defeito que este projeto passou a semana inteira consertando.
#
#     Então eu reproduzo a conta do CSS, que sai assim: ampliar por Z em torno
#     de um ponto (ax, ay) mostra uma janela de lado l/Z cujo canto fica em
#     (ax·l·(1 − 1/Z), ay·l·(1 − 1/Z)). Com Z=1 dá a janela inteira, que é o
#     comportamento de antes — sem degrau, sem caso especial.
#
# POR QUE A ÂNCORA NÃO É O CENTRO
#     Porque rosto fica em cima. Ampliar pelo centro de um retrato de meio corpo
#     dá zoom no peito.
#
# E POR QUE ELA VIROU AJUSTE (18/09/26)
#     "Ficou quase bom, mas quero que o zoom possa ser maior, e que haja um
#      ajuste da foto mais pra baixo, sem cortar o topo da cabeça."
#
#     Os dois pedidos são o mesmo problema: quanto mais se amplia com a âncora
#     fixa, mais cedo o alto da cabeça encosta na borda. Quem resolve é BAIXAR
#     a âncora — e âncora menor é foto mais baixa no disco, porque a janela
#     sobe na foto e sobra o cabelo em cima em vez do queixo embaixo.
#
#     Em 0% a janela encosta no topo da foto e não sai de lá: seja qual for o
#     zoom, o alto da cabeça nunca é cortado. É o limite de baixo da faixa, e
#     não por acaso.
FOTO_ZOOM = 1.70               # o padrão; o Vini ajusta em Configurações
FOTO_ANCORA_X = 0.50
FOTO_ANCORA_Y = 0.10


def janela_do_zoom(lado: float, zoom: float, ancora_y=None) -> tuple:
    """(esquerda, topo, lado) da parte da foto que aparece no disco.

    A mesma conta que o `transform: scale()` do navegador faz. Devolver a
    janela em vez de já recortar deixa ela testável contra a CSS.
    """
    z = max(1.0, float(zoom or 1.0))
    ay = FOTO_ANCORA_Y if ancora_y is None else float(ancora_y)
    # A FAIXA É FECHADA AQUI, e não só na tela de Configurações. Acima de 0,5 a
    # janela desceria do centro para baixo e o zoom miraria o peito; abaixo de
    # 0 ela sairia da foto e entraria fundo transparente por cima da cabeça.
    ay = max(0.0, min(0.5, ay))
    l = float(lado)
    return (FOTO_ANCORA_X * l * (1 - 1 / z),
            ay * l * (1 - 1 / z),
            l / z)


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


SUPER = 4          # fator de superamostragem do círculo


def _circulo(dados: bytes | None, diam: float,
             zoom: float = 1.0, ancora_y=None) -> "Image.Image":
    """Foto recortada em círculo, com o anel #303030 por fora.

    DESENHADO GRANDE E REDUZIDO DEPOIS (08/09/26)
        O ImageDraw.ellipse do PIL não tem suavização: cada pixel entra ou não
        entra, sem meio-termo. Num círculo de 86px isso vira a escadinha que o
        Vini viu ao abrir o arquivo baixado — na tela o navegador suaviza, no
        PNG não havia quem suavizasse. O mesmo motivo fazia a foto "vazar":
        a borda serrilhada da máscara deixava passar canto de foto onde a
        borda do anel, também serrilhada, não cobria.

        A saída é desenhar tudo em 4x e reduzir com LANCZOS. A redução é o que
        cria os pixels intermediários — é antisserrilhamento de verdade, e não
        um filtro de desfoque por cima.

    O ANEL FICA POR DENTRO
        Antes ele era desenhado montado na borda, metade para fora do círculo.
        Metade de um anel de 3px é o que dava a impressão de anel "mais fino"
        que o da tela, e era ali que a foto escapava. Agora ele é traçado
        inteiramente dentro do disco.
    """
    from PIL import Image, ImageDraw
    lado = max(1, int(round(diam)))
    g = lado * SUPER
    anel = max(2.0, FOTO_ANEL * diam / FOTO_DIAM) * SUPER

    fora = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    d = ImageDraw.Draw(fora)
    d.ellipse([0, 0, g - 1, g - 1], fill=FOTO_VAZIA)

    if dados:
        try:
            # COMPOR O ALFA, e não descartá-lo.
            #
            # `convert("RGB")` direto joga o canal alfa fora e fica com o RGB
            # que estava embaixo — preto, nos recortes da SPL. Era o quarto de
            # círculo escuro que ele viu em cima da cabeça no arquivo baixado,
            # e que na tela não aparece porque lá quem compõe é o navegador.
            foto = Image.open(io.BytesIO(dados))
            if foto.mode in ("RGBA", "LA", "P"):
                foto = foto.convert("RGBA")
                fundo = Image.new("RGBA", foto.size, FOTO_VAZIA + (255,))
                foto = Image.alpha_composite(fundo, foto)
            foto = foto.convert("RGB")
            # Recorte quadrado pelo centro do lado MENOR: a foto do TM é
            # retangular e um resize direto achataria o rosto.
            l = min(foto.size)
            e = (foto.width - l) // 2
            t = (foto.height - l) // 2
            foto = foto.crop((e, t, e + l, t + l))
            # O ZOOM NO ROSTO vem DEPOIS do quadrado centralizado, e não no
            # lugar dele: o quadrado é o que a tela mostra com `object-fit:
            # cover`, e o zoom é o `transform: scale()` aplicado por cima. Nessa
            # ordem, e só nessa, o PNG sai igual à prévia.
            dx, dy, lz = janela_do_zoom(l, zoom, ancora_y)
            if lz < l:
                foto = foto.crop((int(round(dx)), int(round(dy)),
                                  int(round(dx + lz)), int(round(dy + lz))))
            foto = foto.resize((g, g), Image.LANCZOS)
            # A máscara para onde o anel começa: assim nenhum pixel de foto
            # aparece por fora dele, nem no pior arredondamento.
            mascara = Image.new("L", (g, g), 0)
            ImageDraw.Draw(mascara).ellipse(
                [anel, anel, g - 1 - anel, g - 1 - anel], fill=255)
            fora.paste(foto, (0, 0), mascara)
        except Exception:
            pass

    # O contorno do PIL cresce PARA DENTRO da caixa, e não centrado nela. Com a
    # caixa recuada de meio anel sobrava um aro claro entre o anel e a grama —
    # o mesmo halo que fazia o anel parecer mais fino do que o da tela. A caixa
    # aqui é o disco inteiro justamente por isso.
    d.ellipse([0, 0, g - 1, g - 1], outline=GRAFITE, width=int(round(anel)))
    return fora.resize((lado, lado), Image.LANCZOS)


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


# ── A SAIA: OS DESFALQUES DENTRO DA PRÓPRIA ARTE (18/09/26) ─────────────────
#
#     "Eu quero isso na 'saia' da imagem do campinho. Use a criatividade pra
#      fazer caber."
#
# Medi o template: abaixo da linha de fundo há uma barra escura (o banco) de
# y=1027 a 1084, e depois verde livre de 1085 até 1350 — 265px de altura por
# 1080 de largura. É pouco para uma lista e é muito para desperdiçar.
#
# A CRIATIVIDADE FOI NÃO INVENTAR NADA: a barra escura já existe, já é
# #303030 e já atravessa a imagem inteira. Ela vira o cabeçalho, com o texto
# em branco — o mesmo par de cores das placas de nome. Não precisei desenhar
# uma faixa nova nem empurrar o campo para cima.
#
# Embaixo, duas colunas de três. Seis é o que cabe legível num 1080; acima
# disso o rodapé diz quantos ficaram de fora, porque uma lista cortada sem
# aviso é uma lista incompleta com cara de completa.
#
# E DEPOIS ELE VIU A PRIMEIRA VERSÃO E CORTOU MAIS (18/09/26):
#
#     "Reduza o tamanho do texto e retire o sub-texto com a explicação.
#      Coloque só um ícone de cruz pra representar lesão e outro pra suspensão."
#
# Ele tem razão e o ganho é duplo. A segunda linha ("Lesão muscular · No fim de
# setembro") é informação de quem PESQUISA, não de quem passa o dedo no feed —
# e ela comia metade da altura de cada item. Sem ela cabe uma coluna a mais e
# uma linha a mais: de seis desfalques para nove, com o nome ainda legível.
#
# A cruz e o cartão dizem em um símbolo o que a frase dizia em seis palavras, e
# nenhum dos dois precisa de legenda num post de futebol.
SAIA_BARRA = (1027, 1084)      # a barra escura do template, medida a régua
SAIA_TOPO = 1100               # onde a primeira linha começa
SAIA_LINHAS, SAIA_COLUNAS = 3, 3
SAIA_CABEM = SAIA_LINHAS * SAIA_COLUNAS
SAIA_LINHA_ALT = 7.4 * CQ      # 80
SAIA_COL_LARG = 31.3 * CQ      # 338
SAIA_X = 3.0 * CQ              # 32, a margem lateral da saia
SAIA_DISCO = 5.0 * CQ          # 54
SAIA_NOME = 1.85 * CQ          # 20
SAIA_ICONE = 1.9 * CQ          # 20,5 — o lado da cruz e a altura do cartão
SAIA_TITULO = 2.4 * CQ         # 26


def _cortar(d, texto: str, fonte, limite: float) -> str:
    """O texto que cabe, com reticências quando não coube.

    Numa célula de 508px com disco ao lado sobram ~420px, e "Lesão do
    ligamento cruzado anterior" não cabe em nenhum tamanho legível. Cortar
    avisando é melhor que vazar por cima da coluna vizinha — e as duas são
    piores que caber.
    """
    texto = (texto or "").strip()
    if not texto or d.textlength(texto, font=fonte) <= limite:
        return texto
    while texto and d.textlength(texto + "…", font=fonte) > limite:
        texto = texto[:-1]
    return (texto.rstrip() + "…") if texto else ""


def _icone(d, tipo: str, x: float, meio: float, lado: float) -> None:
    """A cruz da lesão ou o cartão da suspensão, em grafite.

    DESENHADOS, E NÃO ESCRITOS COM FONTE. Emoji de cruz e de cartão existem,
    mas dependem de a fonte ter o glifo: foi assim que a arte da ficha saiu com
    quadradinhos no lugar dos acentos, e eu não vou repetir isso aqui. Duas
    primitivas do Pillow resolvem, e saem iguais em qualquer máquina.

    A cruz é a médica, de braços iguais. O cartão é um retângulo em pé, na
    proporção de um cartão de árbitro — em grafite, porque a arte inteira é
    grafite sobre verde e um vermelho aqui seria a única cor fora da paleta.
    """
    if tipo == "suspensao":
        larg = lado * 0.70
        d.rectangle([x + (lado - larg) / 2, meio - lado / 2,
                     x + (lado + larg) / 2, meio + lado / 2], fill=GRAFITE)
        return
    # A cruz: o braço tem um terço da largura, centrado nos dois eixos.
    braco = lado / 3.0
    d.rectangle([x + (lado - braco) / 2, meio - lado / 2,
                 x + (lado + braco) / 2, meio + lado / 2], fill=GRAFITE)
    d.rectangle([x, meio - braco / 2,
                 x + lado, meio + braco / 2], fill=GRAFITE)


def _desenhar_saia(base, dados: dict) -> None:
    """Escreve os desfalques na barra e no verde livre embaixo do campo."""
    from PIL import ImageDraw

    lista = [x for x in (dados.get("desfalques") or [])
             if (x.get("nome") or "").strip()]
    if not lista:
        # SEM NINGUÉM FORA, A SAIA FICA COMO SEMPRE FOI. Escrever "nenhum
        # desfalque" seria afirmar uma coisa que eu só sei quando as fontes
        # responderam — e quem sabe disso é a rota, não o desenho.
        return

    d = ImageDraw.Draw(base)
    f_titulo = _fonte("WorkSans-Bold-latin.ttf", SAIA_TITULO)
    f_nome = _fonte("WorkSans-SemiBold-latin.ttf", SAIA_NOME)

    # ── o cabeçalho, dentro da barra que o template já tem ──────────────────
    meio_barra = (SAIA_BARRA[0] + SAIA_BARRA[1]) / 2
    # A CONTAGEM VAI NA BARRA, e não num rodapé embaixo da última linha.
    # Tentei no rodapé primeiro e ele encostava no motivo do sexto jogador —
    # e, pior, um aviso de "tem mais gente" escondido no canto de baixo é um
    # aviso que ninguém lê. Aqui ele está na mesma linha do título.
    titulo = "DESFALQUES"
    if len(lista) > SAIA_CABEM:
        titulo += f" · {SAIA_CABEM} DE {len(lista)}"
    d.text((SAIA_X, meio_barra), titulo, font=f_titulo, fill=BRANCO,
           anchor="lm")
    clube = (dados.get("clube") or "").upper()
    if clube:
        d.text((LARGURA - SAIA_X, meio_barra), clube, font=f_titulo,
               fill=BRANCO, anchor="rm")

    mostrados = lista[:SAIA_CABEM]
    for i, j in enumerate(mostrados):
        col, lin = divmod(i, SAIA_LINHAS)
        x = SAIA_X + col * SAIA_COL_LARG
        topo = SAIA_TOPO + lin * SAIA_LINHA_ALT
        meio = topo + SAIA_DISCO / 2

        base.alpha_composite(
            _circulo(j.get("foto"), SAIA_DISCO,
                     float(dados.get("zoom") or 1.0), dados.get("ancora")),
            (int(x), int(topo)))

        # O ÍCONE, no lugar da frase. Ele vem ANTES do nome no cálculo porque
        # come largura: um sobrenome comprido tem de ser cortado contando com
        # ele, senão os dois se encavalam.
        icone_x = x + SAIA_DISCO + 1.3 * CQ
        _icone(d, j.get("tipo") or "", icone_x, meio, SAIA_ICONE)

        texto_x = icone_x + SAIA_ICONE + 1.1 * CQ
        cabe = SAIA_COL_LARG - (texto_x - x) - 1.2 * CQ

        nome = _cortar(d, (j.get("nome") or "").upper(), f_nome, cabe)
        d.text((texto_x, meio), nome, font=f_nome, fill=GRAFITE, anchor="lm")

    # DE ONDE VEIO A LISTA NÃO ENTRA NA ARTE, e não é esquecimento.
    #
    # Tentei creditar "nossa guia de Lesões e nossa guia de Pendurados" num
    # rodapé, e duas coisas aconteceram: ele encostou no motivo do último
    # jogador, e — pior — é jargão nosso. Para quem abre o post, essa frase não
    # diz nada. A procedência é informação PARA O VINI, e ela chega a ele na
    # tela, no aviso do botão, onde serve para decidir se publica.


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

    # O MESMO ZOOM DA TELA. Quem manda o número é a rota, que leu o ajuste do
    # Vini; sem ele a arte cai em 1.0, que é o enquadramento de antes.
    zoom = float(dados.get("zoom") or 1.0)
    ancora = dados.get("ancora")

    for j, cx, cy, esc in postos:
        diam = FOTO_DIAM * esc
        base.alpha_composite(_circulo(j.get("foto"), diam, zoom, ancora),
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

    # A SAIA POR ÚLTIMO: ela escreve embaixo do campo, onde nenhum jogador
    # cai, mas desenhar depois garante que uma placa de atacante recuado
    # nunca passe por cima do cabeçalho dos desfalques.
    _desenhar_saia(base, dados)

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG", optimize=True)
    return saida.getvalue()
