"""A arte de escalação: foto grande à esquerda, a lista dos onze à direita.

O QUE ELE PEDIU (22/10/26)
    "Eu queria que as escalações saíssem automatizadas numa arte como essa."

    O template é dele, feito no Canva, e veio em duas camadas: o FUNDO (verde,
    diagonais) e o SOBREPOSTO (o painel escuro da direita e os três blocos do
    canto, com o miolo transparente). A arte se monta no meio das duas, do
    mesmo jeito que a `ficha_arte` já fazia:

        fundo → FOTO do destaque → sobreposto → escudos, nome, lista

    A FOTO vem antes do sobreposto porque o bloco dos escudos passa por cima
    do short do jogador — é assim no template dele, e é o que dá profundidade.
    O NOME e a LISTA vêm depois porque vivem dentro do painel escuro.

DE ONDE VEM CADA COISA
    número e nome      folha oficial do Media Hub (matchsheet.py)
    técnico            idem, "Head Coach" da página 2
    capitão            idem, a marca "C" ao lado do número
    nome de exibição   glossário (o de-para que ele montou à mão)
    bandeira           nacionalidade do glossário → flagcdn
    nome curto, escudo DIM_CLUBE
    foto do destaque   recorte transparente da SPL

AS MEDIDAS SÃO DO PRÓPRIO TEMPLATE
    Não chutei nenhuma: li o `escalacao-sobreposto.png` e tirei as caixas de
    onde o alfa muda. Se ele reexportar o template com a geometria diferente,
    `teste_escalacao_card.py` acusa, porque confere as constantes contra o PNG
    em vez de confiar nelas.
"""
import io
import os

PASTA = os.path.dirname(os.path.abspath(__file__))
ARTE = os.path.join(PASTA, "public", "arte")
FONTES = os.path.join(PASTA, "public", "fonts")
FUNDO = os.path.join(ARTE, "escalacao-fundo.png")
SOBREPOSTO = os.path.join(ARTE, "escalacao-sobreposto.png")

LARGURA, ALTURA = 1080, 1350

# ── MEDIDAS LIDAS NO SOBREPOSTO ────────────────────────────────────────────
# O miolo transparente vai de x=0 a x=520: é por ali que a foto aparece.
FOTO_DIR = 521                 # primeira coluna do painel escuro
PAINEL_ESQ, PAINEL_DIR = 521, 1054

# Os três blocos do canto, 180x168 cada, medidos no alfa do template.
BLOCO_RSL = (0, 962, 181, 168)      # já desenhado no template, não mexo
BLOCO_CASA = (0, 1131, 180, 168)    # verde  #01f468 → escudo do clube da arte
BLOCO_FORA = (181, 1131, 180, 168)  # cinza  #303030 → escudo do adversário
ESCUDO_FOLGA = 0.70                 # o escudo ocupa 70% do bloco
FOTO_TOPO = 56                      # respiro acima da cabeça, com zoom 1

# ── O PAINEL DA DIREITA ────────────────────────────────────────────────────
MARGEM_ESQ = 560               # onde a bandeira começa
MARGEM_DIR = 1014              # onde nada pode passar
NOME_CLUBE_BASE = 190          # linha de base do nome do clube
NOME_CLUBE_CORPO = 128
LINHA_1 = 300                  # centro da primeira linha da lista
LINHA_PASSO = 78
TECNICO_Y = 1180
BANDEIRA_ALT = 40
BANDEIRA_GAP = 22
CORPO_LISTA = 50               # teto; encolhe junto se o nome mais longo não couber
CORPO_MIN = 34
# Fração do corpo tirada de cada espaço entre letras. Negativo = condensado.
TRACKING = -0.035
# Os jogadores NÃO são negrito; só o técnico é. Pedido dele em 23/10/26.
FONTE_LISTA = "WorkSans-Regular-latin.ttf"
FONTE_TECNICO = "WorkSans-Bold-latin.ttf"

BRANCO = (255, 255, 255, 255)


def _fonte(arquivo: str, tamanho: float):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONTES, arquivo), max(1, int(tamanho)))


def _abrir(dados):
    """Bytes de imagem → RGBA, ou None. Nunca levanta.

    Arte com um escudo faltando é melhor que erro 500 em dia de jogo — a mesma
    regra que já vale no campinho."""
    if not dados:
        return None
    try:
        from PIL import Image
        if hasattr(dados, "mode"):
            return dados.convert("RGBA")
        return Image.open(io.BytesIO(dados)).convert("RGBA")
    except Exception:
        return None


def recortar_no_conteudo(img):
    """Tira a moldura vazia em volta do jogador.

    A SPL entrega 1024x1024 com fundo transparente e o jogador no meio, então
    metade do arquivo é vazio. Usar a imagem inteira deixaria a figura pequena
    e boiando; o que importa é a silhueta. Sem alfa (JPEG), devolve como veio.
    """
    if img is None:
        return None
    try:
        caixa = img.getchannel("A").getbbox()
    except Exception:
        caixa = None
    return img.crop(caixa) if caixa else img


def encaixar_foto(img, zoom=1.0, ancora=0.5, altura=ALTURA, direita=FOTO_DIR):
    """O destaque na faixa da esquerda, apoiado na base.

    APOIADO NA BASE, com respiro em cima
        O jogador fica de pé no chão da arte. Centralizar o deixaria boiando, e
        `FOTO_TOPO` existe porque cortar o topo da cabeça é o erro que ele já
        apontou no campinho — com zoom 1 isso não acontece nunca.

    ZOOM E ÂNCORA, como no campinho
        São os mesmos dois controles que ele já ajusta lá, com o mesmo sentido:
        `zoom` acima de 1 aproxima (e o que passar da base sai cortado),
        `ancora` corre a figura na horizontal, 0 à esquerda e 1 à direita.
        Recortes da SPL não vêm todos com o jogador no mesmo lugar, então a
        regra fixa resolve a maioria e a mão resolve o resto.
    """
    img = recortar_no_conteudo(img)
    if img is None:
        return None, (0, 0)
    util = max(1.0, (altura - FOTO_TOPO) * max(0.2, float(zoom or 1.0)))
    escala = util / img.height
    larg = max(1, int(round(img.width * escala)))
    img = img.resize((larg, max(1, int(round(util)))), _lanczos())
    x = int(round((direita - larg) * min(1.0, max(0.0, float(ancora)))))
    return img, (x, int(altura - img.height))


def _lanczos():
    from PIL import Image
    return Image.LANCZOS


def _escudo_no_bloco(base, dados, bloco):
    """O escudo centrado dentro de um dos blocos do canto."""
    img = recortar_no_conteudo(_abrir(dados))
    if img is None:
        return
    x, y, larg, alt = bloco
    cabe = min(larg, alt) * ESCUDO_FOLGA
    escala = min(cabe / img.width, cabe / img.height)
    novo = (max(1, int(img.width * escala)), max(1, int(img.height * escala)))
    img = img.resize(novo, _lanczos())
    base.alpha_composite(img, (int(x + (larg - novo[0]) / 2),
                               int(y + (alt - novo[1]) / 2)))


# ── A BANDEIRA É EMOJI ──────────────────────────────────────────────────
#
# ELE PEDIU (23/10/26): "as bandeiras dos jogadores tem que ser de emoji".
#
# O desenho da bandeira saudita tem a shahada escrita; o PNG do flagcdn
# reduzido a 40px vira um borrão verde. O emoji é desenhado para ser lido
# nesse tamanho, e é o que o template dele usa.
#
# A fonte não entra no repositório: `nixpacks.toml` instala o pacote
# `fonts-noto-color-emoji` na imagem. Se ela não estiver lá, a bandeira volta
# a ser a imagem baixada — perder a bandeira seria pior que ter a antiga.
EMOJI_CANDIDATAS = (
    os.path.join(FONTES, "NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf",
    "/usr/share/fonts/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
)
# O NotoColorEmoji é fonte de BITMAP: o Pillow só a abre no tamanho em que
# ela foi desenhada. Desenho nesse tamanho e reduzo depois.
EMOJI_CORPO = 109

_EMOJI_CACHE = []


def fonte_de_emoji():
    """A fonte de emoji colorido, ou None. Procura uma vez só."""
    if _EMOJI_CACHE:
        return _EMOJI_CACHE[0]
    from PIL import ImageFont
    achada = None
    for caminho in EMOJI_CANDIDATAS:
        if not os.path.exists(caminho):
            continue
        try:
            achada = ImageFont.truetype(caminho, EMOJI_CORPO)
            break
        except Exception:
            continue
    _EMOJI_CACHE.append(achada)
    return achada


def bandeira_de_emoji(emoji: str, alt=BANDEIRA_ALT):
    """O emoji desenhado e reduzido para a altura da linha, ou None."""
    if not emoji:
        return None
    fonte = fonte_de_emoji()
    if fonte is None:
        return None
    try:
        from PIL import Image, ImageDraw
        tela = Image.new("RGBA", (EMOJI_CORPO * 2, EMOJI_CORPO * 2), (0, 0, 0, 0))
        ImageDraw.Draw(tela).text(
            (EMOJI_CORPO // 2, EMOJI_CORPO // 2), emoji, font=fonte,
            embedded_color=True, anchor="mm")
        caixa = tela.getbbox()
        if not caixa:
            return None
        corte = tela.crop(caixa)
        larg = max(1, int(round(corte.width * alt / corte.height)))
        return corte.resize((larg, int(alt)), _lanczos())
    except Exception:
        # Pillow sem suporte a bitmap colorido, fonte estranha, o que for: a
        # imagem baixada assume e a arte sai com bandeira do mesmo jeito.
        return None


def _bandeira(dados, emoji="", alt=BANDEIRA_ALT):
    """A bandeirinha na altura da linha: emoji primeiro, imagem depois."""
    desenhada = bandeira_de_emoji(emoji, alt)
    if desenhada is not None:
        return desenhada
    img = _abrir(dados)
    if img is None:
        return None
    larg = max(1, int(round(img.width * alt / img.height)))
    return img.resize((larg, int(alt)), _lanczos())


def sem_inicial(nome: str) -> str:
    """'C. MBEMBA' vira 'MBEMBA'. 'ÓSCAR RODRÍGUEZ' fica como está.

    ELE PEDIU (23/10/26): "o nome curto dos jogadores, se não tiver, o ideal é
    cortar o nome que tá abreviado deixando só o outro".

    Quem tem nome curto no glossário não passa por aqui — este é o caso em que
    o nome veio do PDF, e a liga escreve "C. MBEMBA". Na arte a inicial não
    informa nada e come a largura que o sobrenome precisa.

    Só corta o que é INICIAL de verdade: uma letra, com ponto ou sem. E nunca
    esvazia o nome — se sobrarem só iniciais, devolve o que veio."""
    pedacos = (nome or "").split()
    resto = [p for p in pedacos if len(p.rstrip(".")) > 1]
    return " ".join(resto) if resto else (nome or "").strip()


def _linha_de(j):
    """'01 RODÁK' — número com dois dígitos, nome em maiúsculas.

    Dois dígitos porque é o que alinha a coluna: '1 DUDA' ao lado de
    '71 GLUŠČEVIĆ' desencontra a lista inteira."""
    numero = str(j.get("numero") or "").strip()
    if numero.isdigit():
        numero = numero.zfill(2)
    nome = sem_inicial((j.get("nome") or "").strip().upper())
    return f"{numero} {nome}".strip()


def largura(d, texto: str, fonte, tracking: float = 0.0) -> float:
    """A largura do texto JÁ CONDENSADO.

    Medida letra a letra porque é letra a letra que ele vai ser desenhado — se
    a conta usasse `textlength` da palavra inteira e o desenho fosse
    condensado, a medida e a arte discordariam, e o limite da borda deixaria
    de valer."""
    if not texto:
        return 0.0
    return (sum(d.textlength(c, font=fonte) for c in texto)
            + tracking * (len(texto) - 1))


def escrever(d, base, xy, texto: str, fonte, tracking: float = 0.0) -> None:
    """O texto com o espaço entre letras apertado.

    ELE PEDIU (23/10/26): "condensaria um pouco o espaço entre as letras pra
    evitar quebra de linha". Condensar ganha espaço sem diminuir a letra, que
    é melhor que encolher a lista inteira por causa de um nome só."""
    x, y = xy
    for c in texto:
        d.text((x, y), c, font=fonte, fill=BRANCO, anchor="lm")
        x += d.textlength(c, font=fonte) + tracking


def _corpo_que_cabe(linhas, limite, arquivo=FONTE_LISTA):
    """O maior corpo em que TODAS as linhas cabem, já com o tracking.

    Uniforme, e não por linha: diminuir só o nome comprido faz a lista parecer
    desalinhada. Foi o `GLUŠČEVIĆ` estourando a borda no rascunho dele que
    pediu isto."""
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    corpo = CORPO_LISTA
    while corpo > CORPO_MIN:
        f = _fonte(arquivo, corpo)
        if all(largura(d, t, f, corpo * TRACKING) <= limite for t in linhas):
            break
        corpo -= 1
    return corpo


def cortar(d, texto: str, fonte, limite: float, tracking: float = 0.0) -> str:
    """O que não couber nem condensado no corpo mínimo sai com reticências.

    Encolher a lista inteira abaixo do legível por causa de um nome só é pior
    que abreviar esse nome. Só chega aqui quem o glossário não encurtou."""
    if largura(d, texto, fonte, tracking) <= limite:
        return texto
    corte = texto
    while corte and largura(d, corte + "…", fonte, tracking) > limite:
        corte = corte[:-1]
    return (corte + "…") if corte else ""


def _nome_do_clube(d, texto, limite):
    """O nome do clube, o maior possível sem passar da borda."""
    corpo = NOME_CLUBE_CORPO
    while corpo > 40:
        f = _fonte("DesenhoCondensado-Heavy.ttf", corpo)
        if d.textlength(texto, font=f) <= limite:
            return f
        corpo -= 2
    return _fonte("DesenhoCondensado-Heavy.ttf", 40)


def montar(dados: dict) -> bytes:
    """O PNG 1080x1350 da escalação.

    `dados` traz o que a tela já tem:
        clube, escudo, escudo_adversario, foto (do destaque),
        tecnico {nome, bandeira}, jogadores [{numero, nome, bandeira}]
    """
    from PIL import Image, ImageDraw

    base = Image.open(FUNDO).convert("RGBA")
    if base.size != (LARGURA, ALTURA):
        base = base.resize((LARGURA, ALTURA), _lanczos())

    foto, onde = encaixar_foto(_abrir(dados.get("foto")),
                               float(dados.get("zoom") or 1.0),
                               float(dados.get("ancora", 0.5)))
    if foto is not None:
        base.alpha_composite(foto, onde)

    capa = Image.open(SOBREPOSTO).convert("RGBA")
    if capa.size != (LARGURA, ALTURA):
        capa = capa.resize((LARGURA, ALTURA), _lanczos())
    base.alpha_composite(capa, (0, 0))

    _escudo_no_bloco(base, dados.get("escudo"), BLOCO_CASA)
    _escudo_no_bloco(base, dados.get("escudo_adversario"), BLOCO_FORA)

    d = ImageDraw.Draw(base)

    # O nome do clube começa NA MESMA COLUNA da bandeira dos jogadores. Antes
    # ele era alinhado à direita, e foi o vão que sobrava à esquerda que ele
    # estranhou: "não entendi o espaço a esquerda do ETTIFAQ" (23/10/26).
    clube = (dados.get("clube") or "").strip().upper()
    if clube:
        f = _nome_do_clube(d, clube, MARGEM_DIR - MARGEM_ESQ)
        # Desconta o espaço interno do glifo: o que tem de encostar na coluna
        # da bandeira é a TINTA da primeira letra, não a origem dela. Num
        # corpo de 128 esse vão passa de seis pixels e se enxerga.
        #
        # Pela MÁSCARA, e não por `textbbox`: a caixa de layout devolve x0=0
        # mesmo quando o desenho só começa sete pixels adiante. Foi medindo
        # pelo lugar errado que o primeiro conserto não consertou nada.
        folga = (f.getmask(clube).getbbox() or (0,))[0]
        d.text((MARGEM_ESQ - folga, NOME_CLUBE_BASE), clube, font=f,
               fill=BRANCO, anchor="ls")

    jogadores = (dados.get("jogadores") or [])[:11]
    tecnico = dados.get("tecnico") or {}
    texto_x = MARGEM_ESQ + int(BANDEIRA_ALT * 1.5) + BANDEIRA_GAP
    cabe = MARGEM_DIR - texto_x
    linhas = [_linha_de(j) for j in jogadores]
    nome_tec = (tecnico.get("nome") or "").strip().upper()
    corpo = _corpo_que_cabe(linhas + ([nome_tec] if nome_tec else []), cabe)
    tracking = corpo * TRACKING
    f_lista = _fonte(FONTE_LISTA, corpo)
    f_tec = _fonte(FONTE_TECNICO, corpo)

    for i, j in enumerate(jogadores):
        meio = LINHA_1 + i * LINHA_PASSO
        band = _bandeira(j.get("bandeira"), j.get("emoji") or "")
        if band is not None:
            base.alpha_composite(band, (MARGEM_ESQ, int(meio - band.height / 2)))
        escrever(d, base, (texto_x, meio),
                 cortar(d, linhas[i], f_lista, cabe, tracking), f_lista, tracking)

    if nome_tec:
        band = _bandeira(tecnico.get("bandeira"), tecnico.get("emoji") or "")
        if band is not None:
            base.alpha_composite(band, (MARGEM_ESQ, int(TECNICO_Y - band.height / 2)))
        escrever(d, base, (texto_x, TECNICO_Y),
                 cortar(d, nome_tec, f_tec, cabe, tracking), f_tec, tracking)

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG")
    return saida.getvalue()
