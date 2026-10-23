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


def _bandeira(dados, alt=BANDEIRA_ALT):
    """A bandeirinha na altura da linha, proporção preservada."""
    img = _abrir(dados)
    if img is None:
        return None
    larg = max(1, int(round(img.width * alt / img.height)))
    return img.resize((larg, int(alt)), _lanczos())


def _linha_de(j):
    """'01 RODÁK' — número com dois dígitos, nome em maiúsculas.

    Dois dígitos porque é o que alinha a coluna: '1 DUDA' ao lado de
    '71 GLUŠČEVIĆ' desencontra a lista inteira."""
    numero = str(j.get("numero") or "").strip()
    if numero.isdigit():
        numero = numero.zfill(2)
    nome = (j.get("nome") or "").strip().upper()
    return f"{numero} {nome}".strip()


def _corpo_que_cabe(linhas, limite, arquivo="WorkSans-SemiBold-latin.ttf"):
    """O maior corpo em que TODAS as linhas cabem.

    Uniforme, e não por linha: diminuir só o nome comprido faz a lista parecer
    desalinhada. Foi o `GLUŠČEVIĆ` estourando a borda no rascunho dele que
    pediu isto."""
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    corpo = CORPO_LISTA
    while corpo > CORPO_MIN:
        f = _fonte(arquivo, corpo)
        if all(d.textlength(t, font=f) <= limite for t in linhas):
            break
        corpo -= 1
    return corpo


def cortar(d, texto: str, fonte, limite: float) -> str:
    """O que não couber nem no corpo mínimo sai com reticências.

    Encolher a lista inteira abaixo do legível por causa de um nome só é pior
    que abreviar esse nome. Só chega aqui quem o glossário não encurtou."""
    if d.textlength(texto, font=fonte) <= limite:
        return texto
    corte = texto
    while corte and d.textlength(corte + "…", font=fonte) > limite:
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

    clube = (dados.get("clube") or "").strip().upper()
    if clube:
        f = _nome_do_clube(d, clube, MARGEM_DIR - PAINEL_ESQ - 20)
        d.text((MARGEM_DIR, NOME_CLUBE_BASE), clube, font=f,
               fill=BRANCO, anchor="rs")

    jogadores = (dados.get("jogadores") or [])[:11]
    tecnico = dados.get("tecnico") or {}
    texto_x = MARGEM_ESQ + int(BANDEIRA_ALT * 1.5) + BANDEIRA_GAP
    linhas = [_linha_de(j) for j in jogadores]
    nome_tec = (tecnico.get("nome") or "").strip().upper()
    corpo = _corpo_que_cabe(linhas + ([nome_tec] if nome_tec else []),
                            MARGEM_DIR - texto_x)
    f_lista = _fonte("WorkSans-SemiBold-latin.ttf", corpo)
    f_tec = _fonte("WorkSans-Bold-latin.ttf", corpo)

    for i, j in enumerate(jogadores):
        meio = LINHA_1 + i * LINHA_PASSO
        band = _bandeira(j.get("bandeira"))
        if band is not None:
            base.alpha_composite(band, (MARGEM_ESQ, int(meio - band.height / 2)))
        d.text((texto_x, meio), cortar(d, linhas[i], f_lista, MARGEM_DIR - texto_x),
               font=f_lista, fill=BRANCO, anchor="lm")

    if nome_tec:
        band = _bandeira(tecnico.get("bandeira"))
        if band is not None:
            base.alpha_composite(band, (MARGEM_ESQ, int(TECNICO_Y - band.height / 2)))
        d.text((texto_x, TECNICO_Y), cortar(d, nome_tec, f_tec, MARGEM_DIR - texto_x),
               font=f_tec, fill=BRANCO, anchor="lm")

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG")
    return saida.getvalue()
