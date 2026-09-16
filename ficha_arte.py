"""
Monta o PNG 1080x1350 da ficha do jogador, no molde da arte que o Vini publica.

O PEDIDO (15/09/26)
    Um botão de baixar imagem na guia Elencos. Escolhido o jogador, sai a arte
    com nome, escudo do clube, bandeira do país, foto — e os três números
    (jogos, gols, assistências) do recorte de competição que estiver escolhido
    na ficha.

DE ONDE VÊM AS MEDIDAS
    Não foram escolhidas por gosto: saíram do `exemplo.png` que ele mandou,
    medido pixel a pixel. A foto dele naquele exemplo é a mesma que a API da
    SPL entrega (1024x1024, fundo transparente), e comparar a silhueta do
    exemplo com a silhueta da origem deu a escala e a posição com erro de
    menos de três pixels. Por isso `FOTO_LADO`, `FOTO_X` e `FOTO_Y` são
    números fechados: são a conta, não um palpite.

    Por isso também o teste compara o fundo montado com o `exemplo.png` de
    verdade, em vez de conferir se as constantes ainda existem.

AS DUAS CAMADAS DE FUNDO, E POR QUE MULTIPLICAR
    O `fundo.png` é a arte. O `fundo2-sobreposto.png` é um degradê de branco
    (em cima) a preto (embaixo) com um talho verde no canto inferior direito.

    Ele entra MULTIPLICANDO: branco não muda nada, preto apaga. É o que faz a
    camisa do jogador mergulhar no escuro na parte de baixo, onde depois vêm
    os números — sem isso, o amarelo do Al-Nassr brigaria com eles. Conferi
    a conta contra o exemplo: `exemplo = fundo x sobreposto` bate pixel a
    pixel no que não é foto nem texto.

    O talho verde é a exceção: ali não é multiplicação, é tinta por cima. Se
    fosse multiplicado sairia verde-escuro sujo, e no exemplo ele é o verde
    puro da marca.

A ORDEM DAS CAMADAS:
    fundo → NOME → foto → sobreposto → escudo, bandeira, números.

    O NOME vem antes da foto porque ele passa ATRÁS do jogador — pedido dele,
    e é o que faz nome comprido funcionar: a letra some atrás do ombro e
    reaparece do outro lado, em vez de virar uma tarja sobre o rosto.

    A FOTO vem antes do sobreposto porque precisa mergulhar no escuro embaixo.

    O RESTO vem depois porque no exemplo os números são branco puro numa faixa
    onde o sobreposto já está quase preto; embaixo dele sairiam cinza. O nome
    não tem esse problema: ele vive na faixa de cima, onde o sobreposto ainda
    é branco e multiplicar por branco não muda nada.

O QUE ESTE MÓDULO NÃO FAZ
    Não decide nada e não vai à rede. Nome, números, foto, escudo e bandeira
    chegam prontos de quem chamou — em bytes, no caso das imagens. É o que
    permite ao teste montar a arte inteira sem tocar na SPL nem no flagcdn.
"""
from __future__ import annotations

import io
import os

LARGURA, ALTURA = 1080, 1350

PASTA = os.path.dirname(os.path.abspath(__file__))
ARTE = os.path.join(PASTA, "public", "arte")
FUNDO = os.path.join(ARTE, "ficha-fundo.png")
SOBREPOSTO = os.path.join(ARTE, "ficha-sobreposto.png")
FONTES = os.path.join(PASTA, "public", "fonts")

FONTE_NOME = "DesenhoCondensado-Heavy.ttf"    # nome e números, pedido dele
FONTE_LEGENDA = "WorkSans-SemiBold-latin.ttf"  # a mesma do Campinho

BRANCO = (255, 255, 255)
VERDE = (1, 244, 104)          # o verde da marca, medido no sobreposto

# ── a foto ───────────────────────────────────────────────────────────────────
# A SPL entrega 1024x1024 com fundo transparente. No exemplo ela aparece a
# 1290px de lado, com o canto superior esquerdo em (96, 32) — ou seja,
# sangrando pela direita e parando 28px antes do rodapé. Foi assim que ele
# montou, e é assim que sai.
FOTO_LADO = 1290
FOTO_X, FOTO_Y = 96, 32

# ── os emblemas, na coluna da esquerda ───────────────────────────────────────
ESCUDO_X, ESCUDO_Y, ESCUDO_LADO = 34, 402, 129
BANDEIRA_X, BANDEIRA_Y, BANDEIRA_LADO = 39, 556, 120

# ── o nome ───────────────────────────────────────────────────────────────────
NOME_X = 31
NOME_ALTURA = 148              # altura da MAIÚSCULA, medida no "J" e no "X"
NOME_BASE = 188                # onde a primeira linha se apoia
NOME_ENTRELINHA = 171
# ATÉ ONDE O NOME PODE IR — e isto mudou depois que ele viu as primeiras artes.
#
# Antes o limite era 520px, a largura livre antes da foto, e o nome ENCOLHIA
# para caber. Deu dois problemas que ele apontou: "GABRIEL MARTINELLI" saía
# bem menor que "JOÃO FÉLIX", e como a entrelinha continuava a mesma, as duas
# linhas pareciam muito separadas — o espaço entre elas não encolheu junto.
#
# Ele resolveu os dois de uma vez: "o nome pode passar por trás da imagem do
# jogador, estilisticamente fica bom (...) mantenha o mesmo tamanho de fonte
# usada no João Félix". Então o limite agora é a BORDA DA ARTE, e não a foto.
# Só nome absurdamente comprido encolhe, e encolhe para não sair cortado no
# talho da direita — que é feio de um jeito diferente.
NOME_LARGURA_MAX = 1020
NOME_LINHAS_MAX = 2

# O ESPAÇO ENTRE LETRAS, em fração da altura da maiúscula.
#
# Pedido dele: "reduza um pouco mais a distância lateral entre as letras, a
# distância pode ter o mesmo tamanho que tem no corte (vazio) interior das
# letras, como na letra O". Medi as duas coisas nesta fonte, na altura de 148:
# a folga natural entre duas letras é 20px e o vazio de dentro do O é 7px.
# Daí -13px, que é -0,088 da altura da maiúscula.
#
# Vale só para o nome. Os números já foram acertados pelo aperto horizontal.
NOME_ENTRELETRA = -0.088

# ── os números ───────────────────────────────────────────────────────────────
# Três colunas em 18%, 50% e 82% da largura. Os centros saíram da média entre
# o centro dos números e o centro das legendas no exemplo — os dois discordam
# em alguns pixels porque o "1" tem folga lateral dos dois lados.
NUM_CENTROS = (194.4, 540.0, 885.6)
NUM_ALTURA = 188               # altura do algarismo
NUM_APERTO = 0.85              # o quanto os números são comprimidos na horizontal
NUM_BASE = 1200
LEGENDA_CORPO = 30
LEGENDA_BASE = 1256

SUPER = 4                      # superamostragem: recortes redondos e texto


def _fonte(arquivo: str, tamanho: float):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONTES, arquivo),
                              max(1, int(round(tamanho))))


_CAIXA_ALTA = {}


def _corpo_para_altura(arquivo: str, altura: float) -> float:
    """O tamanho de fonte que dá a ESTA fonte a altura de maiúscula pedida.

    Medir em vez de converter por tabela: "tamanho 210" não quer dizer nada
    sozinho — cada desenho de letra usa a caixa de um jeito, e o que o Vini
    mediu na arte dele foi a altura da letra, não o número que o Canva mostra.

    A razão entre corpo e altura de maiúscula é fixa dentro de uma fonte, então
    basta medir uma vez e guardar.
    """
    razao = _CAIXA_ALTA.get(arquivo)
    if razao is None:
        f = _fonte(arquivo, 200)
        caixa = f.getbbox("H")
        razao = (caixa[3] - caixa[1]) / 200.0
        _CAIXA_ALTA[arquivo] = razao
    return altura / razao if razao else altura


# ═══════════════════════════════════════════════════════════════════════════
#  OS ACENTOS, DESENHADOS À MÃO
# ═══════════════════════════════════════════════════════════════════════════
#
# O ARQUIVO DA FONTE TEM 68 LETRAS: A-Z, a-z, os dez algarismos, o hífen, o
# til solto e o circunflexo solto. Não tem Ã, É, Í, Ó, Ú, Ç — nenhum acento
# grudado em letra. A primeira arte de conferência saiu "JO▯O F▯LIX", com o
# quadradinho que toda fonte desenha quando não conhece o caractere.
#
# O Canva dele tem esses acentos; o arquivo exportado não veio com eles. Mostrei
# o problema e ele escolheu: "desenhe os acentos você".
#
# COMO FUNCIONA
#     Toda letra acentuada do Unicode se decompõe em letra + marca (NFD): "Ã"
#     é "A" mais um til combinante. Então eu desenho o A com a fonte dele — a
#     letra continua sendo a dele — e ponho a marca por cima.
#
#     O TIL E O CIRCUNFLEXO SÃO DA PRÓPRIA FONTE: ela tem "~" e "^" soltos, que
#     é exatamente o desenho que falta grudado. Uso o glifo dela, redimensionado.
#     O carón tcheco ("Š") é o circunflexo de cabeça para baixo, então sai do
#     mesmo lugar. Só o agudo, a crase, o trema, a cedilha, o anel, a breve, o
#     mácron e o ponto é que são traço meu — e são formas geométricas simples,
#     que é o que elas são numa fonte pesada como esta.
#
# O QUE NÃO SE DECOMPÕE
#     Ø, Æ, Đ, Ł e ß não são letra-mais-marca: são desenhos próprios. Para
#     esses há uma tabela pequena de substituição. Um Ø virando O é uma perda
#     pequena; um quadradinho no meio do nome é a arte inteira perdida.
#
#     O TRAVESSÃO ESTÁ NESSA TABELA, e quase me escapou. Ele é o que a arte
#     escreve quando o número é "não sei" — e a fonte tem hífen, mas não tem
#     travessão. Sem essa linha, a ficha de quem ainda não teve a partida lida
#     sairia publicada com um ponto de interrogação no lugar do número.
#
# TUDO ISTO É DESENHADO GRANDE E REDUZIDO DEPOIS
#     O ImageDraw não suaviza polígono nem arco, e um acento de 40px sairia
#     serrilhado ao lado de uma letra suave. Desenhar em 4x e reduzir com
#     LANCZOS é o mesmo remédio do círculo da foto — e de brinde é o que
#     permite APERTAR os números na horizontal, reduzindo mais em x do que em y.

SEM_DECOMPOSICAO = {"—": "-", "–": "-", "’": "'", "“": '"', "”": '"',
                    "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae",
                    "Đ": "D", "đ": "d", "Ð": "D", "ð": "d",
                    "Ł": "L", "ł": "l", "ß": "SS", "Þ": "TH", "þ": "th",
                    "Œ": "OE", "œ": "oe", "İ": "I", "ı": "i"}

# As marcas, e como cada uma é feita. "glifo" vem da fonte; o resto é desenho.
MARCAS = {
    "\u0303": ("glifo", "~"),        # til      — Ã Õ Ñ
    "\u0302": ("glifo", "^"),        # circunflexo — Â Ê Ô
    "\u030C": ("glifo", "^", True),  # carón    — Š Č Ž  (o circunflexo virado)
    "\u0301": ("agudo",),            # Á É Í Ó Ú
    "\u0300": ("crase",),            # À È
    "\u0308": ("trema",),            # Ä Ë Ï Ö Ü
    "\u030A": ("anel",),             # Å
    "\u0306": ("breve",),            # Ğ Ă
    "\u0304": ("macron",),           # Ā
    "\u0307": ("ponto",),            # Ż
    "\u0327": ("cedilha",),          # Ç Ş
    "\u0328": ("cedilha",),          # Ą — o ogonek vira cedilha, que é o
                                      # parente mais próximo que eu sei desenhar
}


_CONHECE = {}


def _conhece(arquivo: str, ch: str) -> bool:
    """Esta fonte tem um desenho para este caractere?

    SEM BIBLIOTECA NOVA, e isso importa: a primeira versão perguntava ao
    fontTools, que está instalado na minha máquina e NÃO está declarado no
    projeto. No Railway ele não existiria, a pergunta cairia no "não sei", o
    "não sei" viraria "tem" — e os quadradinhos voltariam, só no ar, só para
    ele. É a mesma armadilha do tzdata e do Pillow de carona.

    A pergunta é feita de outro jeito: toda fonte desenha um quadradinho (o
    `.notdef`) para o que não conhece, e desenha sempre O MESMO. Então eu
    renderizo um caractere que fonte nenhuma tem — um da área de uso privado —,
    guardo esse desenho e comparo. Se bater, é o quadradinho.

    Espaço em branco fica fora da conta: ele não tem tinta e empataria com o
    quadradinho de uma fonte que desenhe o `.notdef` vazio.
    """
    if not ch or ch.isspace():
        return True
    guardado = _CONHECE.get(arquivo)
    if guardado is None:
        fonte = _fonte(arquivo, 48)
        # U+E000 é da área de uso privado: nenhuma fonte de texto tem desenho
        # para ele, então o que sai é o quadradinho, seja ele qual for.
        guardado = (fonte, _desenho_de(fonte, chr(0xE000)))
        _CONHECE[arquivo] = guardado
    fonte, quadradinho = guardado
    try:
        return _desenho_de(fonte, ch) != quadradinho
    except Exception:
        return True


def _desenho_de(fonte, ch: str) -> bytes:
    """Os pixels desta letra nesta fonte. Serve só para comparar com outra."""
    from PIL import Image, ImageDraw
    lado = max(8, int(fonte.size * 2))
    tela = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(tela).text((4, 4), ch, font=fonte, fill=255)
    return tela.tobytes()


def _decompor(texto: str, arquivo: str) -> list:
    """O texto como uma lista de (letra que a fonte tem, marcas a desenhar)."""
    import unicodedata
    saida = []
    for ch in texto:
        if _conhece(arquivo, ch):
            saida.append((ch, []))
            continue
        for bruto, trocado in SEM_DECOMPOSICAO.items():
            if ch == bruto:
                saida.extend((c, []) for c in trocado)
                break
        else:
            partes = unicodedata.normalize("NFD", ch)
            base = partes[0] if partes else ch
            marcas = [m for m in partes[1:] if m in MARCAS]
            if _conhece(arquivo, base):
                saida.append((base, marcas))
            # SE NEM A BASE EXISTE, O CARACTERE SOME — e some de propósito.
            #
            # Antes eu punha um "?" no lugar. Parecia prudente e era pior: a
            # fonte também não tem o ponto de interrogação, então saía o
            # quadradinho do `.notdef` — a mesma coisa que eu estava tentando
            # evitar, agora com duas camadas de disfarce. Foi o que o Vini viu
            # em "S. MILINKOVIĆ-SAVIĆ": o ponto da inicial virou quadradinho,
            # e a primeira linha do nome ficou "S▯".
            #
            # Sumir é a única saída honesta: o quadradinho não informa nada e
            # estraga a arte inteira. Um sinal de pontuação a menos, ninguém vê.
    return saida


def _largura(pecas: list, fonte, entreletra: float = 0.0) -> float:
    """A largura do texto, somando letra por letra.

    Somar em vez de pedir a da linha inteira porque é letra por letra que eu
    DESENHO: se as duas contas discordassem, o texto sairia centrado num lugar
    e desenhado em outro. O `entreletra` entra aqui pelo mesmo motivo — ele
    muda a largura, e quem centraliza precisa saber."""
    if not pecas:
        return 0.0
    avanco = sum(fonte.getlength(letra) for letra, _ in pecas)
    return avanco + entreletra * (len(pecas) - 1)


def _pintar_marca(tela, d, tipo, esq, dir_, topo, base_y, cap, fonte, cor):
    """Desenha uma marca sobre (ou sob) a letra que vai de `esq` a `dir_`."""
    from PIL import Image, ImageDraw
    meio = (esq + dir_) / 2.0
    largura_letra = max(1.0, dir_ - esq)
    # A FOLGA E A ALTURA SAÍRAM DO EXEMPLO DELE, e não do meu gosto.
    #
    # Na primeira tentativa eu fiz o agudo com 27% da altura da maiúscula e 7%
    # de folga. Ficou alto demais: em "JOÃO / FÉLIX", o acento do É subia e
    # encostava na linha de cima, parecendo um rabinho pendurado no O. Medindo
    # a arte dele: o acento do É ocupa 23px numa maiúscula de 147, e começa
    # um pixel acima da letra. É marca de fonte pesada — curta, grossa e colada.
    traco = max(2.0, cap * 0.155)
    folga = cap * 0.03
    nome = tipo[0]

    if nome == "glifo":
        # O desenho vem da PRÓPRIA fonte: ela tem "~" e "^" soltos.
        marca = _glifo_solto(fonte, tipo[1], cor)
        if marca is None:
            return
        alvo_l = max(1, int(round(largura_letra * 0.66)))
        alvo_a = max(1, int(round(marca.height * alvo_l / marca.width)))
        marca = marca.resize((alvo_l, alvo_a), Image.LANCZOS)
        if len(tipo) > 2 and tipo[2]:
            marca = marca.transpose(Image.FLIP_TOP_BOTTOM)
        tela.alpha_composite(
            marca, (int(round(meio - alvo_l / 2)),
                    int(round(topo - folga - alvo_a))))
        return

    if nome == "agudo" or nome == "crase":
        alt, larg = cap * 0.19, traco
        inclina = cap * 0.085 * (1 if nome == "agudo" else -1)
        y1 = topo - folga
        y0 = y1 - alt
        d.polygon([(meio - larg / 2 - inclina / 2, y1),
                   (meio + larg / 2 - inclina / 2, y1),
                   (meio + larg / 2 + inclina / 2, y0),
                   (meio - larg / 2 + inclina / 2, y0)], fill=cor)
        return

    if nome == "trema":
        lado = traco * 1.15
        y1 = topo - folga
        for sinal in (-1, 1):
            cx = meio + sinal * lado * 1.15
            d.rectangle([cx - lado / 2, y1 - lado, cx + lado / 2, y1], fill=cor)
        return

    if nome == "ponto":
        lado = traco * 1.15
        y1 = topo - folga
        d.rectangle([meio - lado / 2, y1 - lado, meio + lado / 2, y1], fill=cor)
        return

    if nome == "macron":
        larg = largura_letra * 0.62
        y1 = topo - folga
        d.rectangle([meio - larg / 2, y1 - traco, meio + larg / 2, y1], fill=cor)
        return

    if nome == "anel":
        diam = cap * 0.24
        y1 = topo - folga
        d.ellipse([meio - diam / 2, y1 - diam, meio + diam / 2, y1],
                  outline=cor, width=int(round(traco * 0.8)))
        return

    if nome == "breve":
        larg = largura_letra * 0.58
        alt = cap * 0.24
        y1 = topo - folga
        d.arc([meio - larg / 2, y1 - alt, meio + larg / 2, y1 + alt * 0.2],
              0, 180, fill=cor, width=int(round(traco)))
        return

    if nome == "cedilha":
        # POR BAIXO da linha de base, e não por cima: é o único assim, e foi o
        # que quase me fez desenhá-la em cima do Ç.
        larg = cap * 0.30
        alt = cap * 0.34
        cx = meio + largura_letra * 0.05
        d.rectangle([cx - traco / 2, base_y, cx + traco / 2, base_y + alt * 0.42],
                    fill=cor)
        d.arc([cx - larg, base_y + alt * 0.25, cx + larg * 0.25, base_y + alt],
              0, 130, fill=cor, width=int(round(traco * 0.9)))
        return


_GLIFOS = {}


def _glifo_solto(fonte, ch: str, cor):
    """O desenho de um caractere solto da fonte, recortado na tinta."""
    from PIL import Image, ImageDraw
    # A CHAVE É O ARQUIVO, O TAMANHO E A LETRA — e não o id do objeto fonte.
    #
    # Com `id(fonte)` isto funcionava e era uma bomba-relógio: o objeto fonte
    # é criado a cada chamada e jogado fora depois, e o Python REAPROVEITA
    # endereço de memória. Uma fonte nova podia nascer no endereço de uma
    # morta e receber o til de volta quando pedisse o circunflexo.
    chave = (getattr(fonte, "path", ""), getattr(fonte, "size", 0), ch)
    if chave in _GLIFOS:
        return _GLIFOS[chave]
    lado = int(fonte.size * 3) or 3
    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    ImageDraw.Draw(tela).text((lado // 4, lado // 4), ch, font=fonte, fill=cor)
    caixa = tela.getbbox()
    achado = tela.crop(caixa) if caixa else None
    _GLIFOS[chave] = achado
    return achado


def texto(base, arquivo: str, conteudo: str, cap: float, x: float, base_y: float,
          ancora: str = "ls", aperto: float = 1.0, cor=(255, 255, 255),
          entreletra: float = 0.0) -> None:
    """Escreve `conteudo` em `base`, com os acentos desenhados quando faltam.

    `cap` é a altura da MAIÚSCULA, não o corpo da fonte: é o que o Vini mediu
    na arte dele. `base_y` é a linha de base. `aperto` comprime na horizontal —
    a fonte do arquivo é mais larga que a do Canva, e sem ele os três números
    do rodapé quase se encostam.

    `entreletra` é uma fração da altura da maiúscula e costuma ser NEGATIVA:
    aperta as letras umas contra as outras. Pedido dele para o nome.

    `ancora`: "ls" encosta à esquerda, "ms" centra no x.
    """
    from PIL import Image, ImageDraw
    if not conteudo:
        return
    pecas = _decompor(conteudo, arquivo)
    corpo = _corpo_para_altura(arquivo, cap) * SUPER
    fonte = _fonte(arquivo, corpo)
    alto = cap * SUPER
    passo = entreletra * alto            # já em pixels da tela superamostrada
    larg = _largura(pecas, fonte, passo)
    margem = int(round(alto))

    tela = Image.new("RGBA", (int(round(larg)) + margem * 2, int(round(alto * 3))),
                     (0, 0, 0, 0))
    d = ImageDraw.Draw(tela)
    linha = alto * 2                     # a linha de base dentro da tela
    caneta = float(margem)
    for letra, marcas in pecas:
        d.text((caneta, linha), letra, font=fonte, fill=cor, anchor="ls")
        caixa = fonte.getbbox(letra)
        esq = caneta + (caixa[0] if caixa else 0)
        dir_ = caneta + (caixa[2] if caixa else fonte.getlength(letra))
        for m in marcas:
            _pintar_marca(tela, d, MARCAS[m], esq, dir_, linha - alto,
                          linha, alto, fonte, cor)
        caneta += fonte.getlength(letra) + passo

    final_l = max(1, int(round(tela.width / SUPER * aperto)))
    final_a = max(1, int(round(tela.height / SUPER)))
    tela = tela.resize((final_l, final_a), Image.LANCZOS)

    largura_texto = larg / SUPER * aperto
    esquerda = x - (largura_texto / 2 if ancora == "ms" else 0)
    base.alpha_composite(tela, (int(round(esquerda - margem / SUPER * aperto)),
                                int(round(base_y - linha / SUPER))))


def largura_do_texto(arquivo: str, conteudo: str, cap: float,
                     aperto: float = 1.0, entreletra: float = 0.0) -> float:
    """Quanto este texto vai ocupar. Mesma conta do `texto`, para o nome saber
    se precisa encolher antes de ser desenhado."""
    pecas = _decompor(conteudo, arquivo)
    fonte = _fonte(arquivo, _corpo_para_altura(arquivo, cap) * SUPER)
    return _largura(pecas, fonte, entreletra * cap * SUPER) / SUPER * aperto


def _altura_de_maiuscula(arquivo: str, corpo: float) -> float:
    """A conta inversa do `_corpo_para_altura`. A legenda foi medida em CORPO
    (30, o que dá a largura do exemplo) e o `texto` fala em altura de
    maiúscula; esta é a ponte entre as duas."""
    _corpo_para_altura(arquivo, 1)          # garante a razão no cache
    return corpo * _CAIXA_ALTA[arquivo]


def _redondo(dados: bytes | None, diam: int):
    """Imagem recortada em círculo. Devolve None se não houver imagem.

    DESENHADO GRANDE E REDUZIDO DEPOIS, como no `escalacao_arte`: o
    ImageDraw.ellipse do PIL não suaviza borda, e um círculo de 120px sai com
    a escadinha que o Vini já pegou uma vez ao abrir o arquivo baixado.
    """
    from PIL import Image, ImageDraw
    if not dados:
        return None
    try:
        img = Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None
    g = diam * SUPER
    # Recorte quadrado pelo centro do lado MENOR: a bandeira do flagcdn é
    # retangular, e um resize direto esticaria o escudo dentro dela.
    lado = min(img.size)
    e = (img.width - lado) // 2
    t = (img.height - lado) // 2
    img = img.crop((e, t, e + lado, t + lado)).resize((g, g), Image.LANCZOS)
    mascara = Image.new("L", (g, g), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, g - 1, g - 1], fill=255)
    img.putalpha(mascara)
    return img.resize((diam, diam), Image.LANCZOS)


def _inteiro(dados: bytes | None, lado: int):
    """Imagem inteira, encaixada num quadrado, sem recorte e sem esticar.

    O escudo NÃO é recortado em círculo de propósito. O do Al-Nassr já é
    redondo e ficaria igual de qualquer jeito, mas há escudo em escudo de
    escudo nesta liga com formato de brasão — recortar em círculo comeria a
    ponta de baixo de cada um deles, calado.
    """
    from PIL import Image
    if not dados:
        return None
    try:
        img = Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None
    escala = min(lado / img.width, lado / img.height)
    novo = (max(1, int(round(img.width * escala))),
            max(1, int(round(img.height * escala))))
    img = img.resize(novo, Image.LANCZOS)
    caixa = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    caixa.alpha_composite(img, ((lado - novo[0]) // 2, (lado - novo[1]) // 2))
    return caixa


def quebrar_nome(nome: str, largura_max: float = NOME_LARGURA_MAX) -> list[str]:
    """O nome em até duas linhas, como "JOÃO / FÉLIX" no exemplo.

    POR QUE DUAS, E NÃO QUANTAS PRECISAR
        Abaixo do nome mora o escudo, a 402px do topo. Uma terceira linha
        passaria por cima dele. Com mais de duas palavras eu fico com as duas
        ÚLTIMAS — é assim que o jogador é chamado ("Cristiano Ronaldo" e não
        "Cristiano Ronaldo dos Santos Aveiro"), e quem chama já manda o nome
        curto do glossário quando ele existe.

    Uma palavra só ocupa uma linha, e a arte fica com o nome em cima. Não
    centralizo verticalmente de propósito: o exemplo tem a primeira linha
    encostada no topo, e é o topo que dá o alinhamento com a marca.
    """
    palavras = [p for p in (nome or "").upper().split() if p]

    # INICIAL SOLTA SAI FORA. "S. Milinković-Savić" tem duas palavras, e a
    # primeira é uma letra: a arte saía com uma linha inteira ocupada por um
    # "S". Foi o que o Vini relatou como "corta após a primeira letra". Uma
    # inicial não é como o jogador é chamado, e numa arte de nome grande ela
    # só ocupa lugar.
    #
    # Só descarto se sobrar alguma coisa: um jogador que se chamasse só "S"
    # continua saindo com o S.
    inteiras = [p for p in palavras if len(p.strip(".-'")) > 1]
    if inteiras:
        palavras = inteiras
    if not palavras:
        return []
    if len(palavras) > NOME_LINHAS_MAX:
        palavras = palavras[-NOME_LINHAS_MAX:]
    return palavras


def melhor_nome(curto: str, principal: str) -> str:
    """Entre o nome curto e o principal, qual vai para a arte.

    O curto ganha por padrão — é como o jogador é chamado, e é o que cabe em
    duas linhas grandes. Mas o glossário às vezes guarda o curto com inicial
    ("S. Milinković-Savić"), e aí o principal ("Sergej Milinković-Savić") é o
    melhor dos dois: tem as mesmas duas linhas, sem uma delas ser uma letra.

    Se os dois tiverem inicial, o `quebrar_nome` joga a inicial fora e sobra o
    sobrenome sozinho, que ainda é melhor que um "S" ocupando uma linha.
    """
    curto, principal = (curto or "").strip(), (principal or "").strip()
    def tem_inicial(n):
        return any(len(p.strip(".-'")) == 1 for p in n.split())
    if curto and tem_inicial(curto) and principal and not tem_inicial(principal):
        return principal
    return curto or principal


def _corpo_do_nome(linhas: list[str]) -> float:
    """A ALTURA DE MAIÚSCULA. Quase sempre a do exemplo; encolhe só no extremo.

    TODO MUNDO NO TAMANHO DO JOÃO FÉLIX, que é o que ele pediu depois de ver
    "GABRIEL MARTINELLI" sair menor. Passar por trás da foto é escolha de
    estilo dele, e não um problema a resolver.

    O único limite que sobrou é a borda da arte. "MILINKOVIĆ-SAVIĆ" tem
    dezesseis letras; se nem isso coubesse, a última sairia cortada no talho
    verde da direita — e letra cortada não é estilo, é defeito. Nesse caso
    encolhe o mínimo para caber inteira.
    """
    if not linhas:
        return NOME_ALTURA
    maior = max(largura_do_texto(FONTE_NOME, l, NOME_ALTURA,
                                 entreletra=NOME_ENTRELETRA) for l in linhas)
    if maior <= NOME_LARGURA_MAX:
        return NOME_ALTURA
    return NOME_ALTURA * NOME_LARGURA_MAX / maior


def _numero(valor) -> str:
    """O número, ou um travessão.

    Zero e "não sei" são coisas diferentes, e esta é a terceira vez que isso
    aparece no projeto. Jogador que entrou e não marcou tem 0 gols; jogador
    cuja partida eu ainda não li inteira tem NULO. Um traço diz a segunda
    coisa sem fingir que é a primeira.
    """
    return "—" if valor is None else str(valor)


def montar(dados: dict) -> bytes:
    """dados: {nome, jogos, gols, assistencias, foto: bytes|None,
    escudo: bytes|None, bandeira: bytes|None}. Devolve os bytes do PNG."""
    from PIL import Image, ImageChops, ImageDraw

    base = Image.open(FUNDO).convert("RGB")
    if base.size != (LARGURA, ALTURA):
        base = base.resize((LARGURA, ALTURA), Image.LANCZOS)
    base = base.convert("RGBA")

    # ── o nome, ATRÁS DA FOTO ────────────────────────────────────────────────
    #
    # Esta é a única razão de o nome ser desenhado aqui, antes de tudo o mais.
    # Pedido dele (16/09/26), com exemplo anexo: "o nome é pra passar na camada
    # ATRÁS da foto do jogador".
    #
    # É o que resolve de vez o nome comprido. "MILINKOVIĆ-SAVIĆ" atravessa a
    # arte inteira e passava POR CIMA do rosto do jogador — o que ele queria é
    # o contrário: a letra some atrás do ombro e reaparece do outro lado, que é
    # o efeito da arte dele. Sem isso, nome grande vira tarja sobre a cara do
    # cara.
    #
    # E é seguro pôr aqui, antes do degradê: o nome vive entre y=12 e y=360, e
    # nessa faixa o sobreposto ainda é branco puro — multiplicar por branco não
    # muda nada. Se um dia o nome descer, esta conta deixa de valer.
    linhas = quebrar_nome(dados.get("nome") or "")
    if linhas:
        cap = _corpo_do_nome(linhas)
        for i, linha in enumerate(linhas):
            texto(base, FONTE_NOME, linha, cap,
                  NOME_X, NOME_BASE + i * NOME_ENTRELINHA, "ls", cor=BRANCO,
                  entreletra=NOME_ENTRELETRA)

    # ── a foto, por cima do nome e por baixo do degradê ──────────────────────
    foto = dados.get("foto")
    if foto:
        try:
            f = Image.open(io.BytesIO(foto)).convert("RGBA")
            f = f.resize((FOTO_LADO, FOTO_LADO), Image.LANCZOS)
            base.alpha_composite(f, (FOTO_X, FOTO_Y))
        except Exception:
            pass

    # ── o degradê: multiplica, menos no talho verde ──────────────────────────
    sob = Image.open(SOBREPOSTO).convert("RGB")
    if sob.size != (LARGURA, ALTURA):
        sob = sob.resize((LARGURA, ALTURA), Image.LANCZOS)
    arte = ImageChops.multiply(base.convert("RGB"), sob)
    # O verde é tinta, não sombra. A máscara sai do próprio arquivo — assim,
    # se ele mudar o talho de lugar, nada aqui precisa saber.
    r, g, b = sob.split()
    verde = Image.eval(
        ImageChops.lighter(
            ImageChops.lighter(_dist(r, VERDE[0]), _dist(g, VERDE[1])),
            _dist(b, VERDE[2])),
        lambda v: 255 if v <= 12 else 0).convert("L")
    arte.paste(sob, mask=verde)
    arte = arte.convert("RGBA")

    d = ImageDraw.Draw(arte)

    # ── escudo e bandeira ────────────────────────────────────────────────────
    escudo = _inteiro(dados.get("escudo"), ESCUDO_LADO)
    if escudo:
        arte.alpha_composite(escudo, (ESCUDO_X, ESCUDO_Y))
    bandeira = _redondo(dados.get("bandeira"), BANDEIRA_LADO)
    if bandeira:
        arte.alpha_composite(bandeira, (BANDEIRA_X, BANDEIRA_Y))

    # ── os três números e suas legendas ──────────────────────────────────────
    #
    # O APERTO É SÓ NOS NÚMEROS. A fonte deste arquivo é mais larga que a que
    # ele usou no Canva, e na altura do exemplo (188px) os três quase se
    # encostavam. Ele escolheu comprimir na horizontal em vez de diminuir a
    # altura — e num algarismo ninguém nota a compressão, que é justamente por
    # que vale a pena aqui e não valeria no nome.
    #
    # A legenda não é apertada: ela sai na fonte do Campinho, que já tem a
    # largura certa e tem todos os acentos ("ASSISTÊNCIAS" precisa do Ê).
    colunas = ((_numero(dados.get("jogos")), "JOGOS"),
               (_numero(dados.get("gols")), "GOLS"),
               (_numero(dados.get("assistencias")), "ASSISTÊNCIAS"))
    cap_legenda = _altura_de_maiuscula(FONTE_LEGENDA, LEGENDA_CORPO)
    for centro, (valor, legenda) in zip(NUM_CENTROS, colunas):
        texto(arte, FONTE_NOME, valor, NUM_ALTURA, centro, NUM_BASE, "ms",
              aperto=NUM_APERTO, cor=BRANCO)
        texto(arte, FONTE_LEGENDA, legenda, cap_legenda, centro, LEGENDA_BASE,
              "ms", cor=BRANCO)

    saida = io.BytesIO()
    arte.convert("RGB").save(saida, format="PNG")
    return saida.getvalue()


def _dist(canal, alvo: int):
    """|canal - alvo|, pixel a pixel. Serve para achar o verde no sobreposto."""
    from PIL import Image
    return Image.eval(canal, lambda v: min(255, abs(v - alvo)))
