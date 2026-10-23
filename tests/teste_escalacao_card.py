"""A arte de escalação: as medidas saem do template, não do meu chute.

O QUE ELE PEDIU (22/10/26)
    "Eu queria que as escalações saíssem automatizadas numa arte como essa."

    Ele mandou o template em duas camadas — fundo opaco e sobreposto com o
    miolo transparente. As constantes do módulo (onde começa o painel escuro,
    onde ficam os três blocos de escudo) foram MEDIDAS nesse PNG.

POR QUE ESTE ARQUIVO CONFERE O PNG, E NÃO SÓ O CÓDIGO
    Constante medida à mão é verdade com prazo de validade. No dia em que ele
    reexportar o template com o painel dois pixels pro lado, o código continua
    rodando e a arte sai torta sem ninguém errar — o pior tipo de defeito,
    porque não reclama. Então aqui as constantes são conferidas contra o
    arquivo: se o template mudar, o teste cai e diz o número novo.
"""
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

from PIL import Image, ImageDraw                            # noqa: E402

import escalacao_card as ec                                 # noqa: E402

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ── AS CONSTANTES CONTRA O PRÓPRIO TEMPLATE ─────────────────────────────
fundo = Image.open(ec.FUNDO).convert("RGBA")
capa = Image.open(ec.SOBREPOSTO).convert("RGBA")

ok(fundo.size == (ec.LARGURA, ec.ALTURA),
   f"o fundo não é {ec.LARGURA}x{ec.ALTURA}, e sim {fundo.size}")
ok(capa.size == (ec.LARGURA, ec.ALTURA),
   f"o sobreposto não é {ec.LARGURA}x{ec.ALTURA}, e sim {capa.size}")

alfa = capa.getchannel("A").load()
ok(min(capa.getchannel("A").getextrema()) == 0,
   "o sobreposto veio SEM transparência. Ele é a camada que deixa a foto "
   "aparecer; opaco, a arte sai sem jogador nenhum")

# onde o painel escuro começa: primeira coluna opaca de cima a baixo
meio_y = ec.ALTURA // 2
col = next((x for x in range(300, ec.LARGURA) if alfa[x, meio_y] > 128), None)
ok(col == ec.PAINEL_ESQ,
   f"o painel escuro começa em x={col} no template, mas o código usa "
   f"PAINEL_ESQ={ec.PAINEL_ESQ}. A lista seria desenhada fora dele")
ok(ec.FOTO_DIR == ec.PAINEL_ESQ,
   "a faixa da foto não termina onde o painel começa; sobra ou falta fundo")

# os três blocos do canto, pela cor chapada
px = capa.load()


def _confere_bloco(bloco, cor, nome):
    """A cor tem de valer nos QUATRO CANTOS do bloco e parar logo fora dele.

    Conferir só o centro não serve: um bloco declarado 30px fora do lugar
    continua caindo dentro da mancha de cor e passaria calado — foi o que uma
    versão anterior deste teste deixou escapar."""
    x, y, larg, alt = bloco
    cantos = [(x + 1, y + 1), (x + larg - 2, y + 1),
              (x + 1, y + alt - 2), (x + larg - 2, y + alt - 2)]
    for cx, cy in cantos:
        if px[cx, cy][:3] != cor:
            falhas.append(f"o {nome} não é {cor} em ({cx},{cy}), e sim "
                          f"{px[cx, cy][:3]}. As coordenadas saíram do lugar")
            return
    fora = [(x + larg // 2, y - 3), (x + larg // 2, y + alt + 2)]
    if all(px[fx, fy][:3] == cor for fx, fy in fora if 0 <= fy < ec.ALTURA):
        falhas.append(f"a cor do {nome} continua igual ACIMA e ABAIXO da "
                      "caixa declarada: ela não está medindo a borda real do "
                      "bloco, só um ponto dentro da mancha")


_confere_bloco(ec.BLOCO_CASA, (1, 244, 104), "bloco do escudo da casa (verde)")
_confere_bloco(ec.BLOCO_FORA, (48, 48, 48), "bloco do adversário (cinza)")
_confere_bloco(ec.BLOCO_RSL, (255, 255, 255), "bloco do RSL (branco)")
ok(ec.MARGEM_DIR <= 1054 and ec.MARGEM_ESQ > ec.PAINEL_ESQ,
   "as margens do texto caíram fora do painel escuro")


# ── O NÚMERO ────────────────────────────────────────────────────────────
ok(ec._linha_de({"numero": "4", "nome": "Hendry"}) == "04 HENDRY",
   "o número de um dígito saiu sem o zero. '4 HENDRY' ao lado de "
   "'71 GLUŠČEVIĆ' desencontra a coluna inteira")
ok(ec._linha_de({"numero": "99", "nome": "haroun"}) == "99 HAROUN",
   "o nome não saiu em maiúsculas")
ok(ec._linha_de({"numero": "", "nome": "Duda"}) == "DUDA",
   "sem número a linha ficou com um espaço sobrando na frente")
ok(ec._linha_de({"numero": "GK", "nome": "Rodák"}) == "GK RODÁK",
   "um número que não é dígito foi estragado pelo preenchimento com zero")


# ── A INICIAL ABREVIADA CAI (23/10/26) ──────────────────────────────────
#
#   "o nome curto dos jogadores, se n tiver, o ideal é cortar o nome que tá
#    abreviado deixando só o outro"
#
for bruto, esperado in (("C. MBEMBA", "MBEMBA"), ("B. DJIMSITI", "DJIMSITI"),
                        ("L. CHELFI", "CHELFI"), ("E. MILLOT", "MILLOT"),
                        ("A AL GHAMDI", "AL GHAMDI")):
    ok(ec.sem_inicial(bruto) == esperado,
       f"'{bruto}' virou '{ec.sem_inicial(bruto)}' e devia virar "
       f"'{esperado}'. A inicial não informa nada e come a largura do "
       "sobrenome")

for intacto in ("ÓSCAR RODRÍGUEZ", "HUSSAIN AL QAHT", "AL OTAIBI",
                "WIJNALDUM", "AL NEMR"):
    ok(ec.sem_inicial(intacto) == intacto,
       f"'{intacto}' foi mutilado para '{ec.sem_inicial(intacto)}'. Só a "
       "INICIAL cai — 'AL' tem duas letras e é metade dos nomes desta liga")

ok(ec.sem_inicial("R. K.") == "R. K." and ec.sem_inicial("") == "",
   "um nome só de iniciais ficou vazio. Linha sem nome é linha inútil")
ok(ec._linha_de({"numero": "99", "nome": "C. Mbemba"}) == "99 MBEMBA",
   "o corte da inicial não chegou à linha desenhada")


# ── A BANDEIRA É A DO CAMPINHO (23/10/26) ───────────────────────────────
#
# Eu tentei desenhar o emoji direto e a arte do Hilal saiu com "MA", "FR",
# "SA" em letras azuis no lugar das bandeiras: o Pillow não junta as duas
# letras do emoji numa bandeira, igual ao Windows dele — defeito que o
# campinho já documentava e resolvia desde setembro, convertendo o emoji em
# sigla e desenhando a IMAGEM do país. Este módulo faz o mesmo, e esta guarda
# impede que alguém volte a desenhar emoji como texto aqui dentro.
_FONTE_CARD = open(os.path.join(RAIZ, "escalacao_card.py"), encoding="utf-8").read()
_codigo_card = "\n".join(l for l in _FONTE_CARD.split("\n")
                         if not l.strip().startswith("#"))
ok("embedded_color" not in _codigo_card and "NotoColorEmoji" not in _codigo_card,
   "a arte voltou a desenhar a bandeira como EMOJI DE TEXTO. Sem quem junte "
   "as duas letras, ela sai \"SA\", \"NL\", \"MA\" — foi a arte do Hilal")


def _bandeira_de(larg, alt):
    im = Image.new("RGBA", (larg, alt), (200, 30, 30, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


# A CAIXA É FIXA: 60x40. Croácia é 2:1, Suíça é quadrada, Catar é 28:11.
for nome_pais, (lw, lh) in (("Croácia", (80, 40)), ("Suíça", (80, 80)),
                            ("Catar", (80, 31)), ("Brasil", (80, 56))):
    band = ec._bandeira(_bandeira_de(lw, lh))
    ok(band is not None, f"a bandeira da {nome_pais} sumiu")
    if band is not None:
        ok(band.width <= ec.BANDEIRA_LARG and band.height <= ec.BANDEIRA_ALT,
           f"a bandeira da {nome_pais} saiu {band.size} e passou da caixa "
           f"{ec.BANDEIRA_LARG}x{ec.BANDEIRA_ALT}. Foi a da Croácia invadindo "
           "o número em \"25 L. CHELFI\"")
        ok(band.width == ec.BANDEIRA_LARG or band.height == ec.BANDEIRA_ALT,
           f"a bandeira da {nome_pais} ficou menor que a caixa nos dois lados "
           f"({band.size}); ela tem de encostar em um deles")

ok(ec._bandeira(None) is None and ec._bandeira(b"lixo") is None,
   "sem imagem a bandeira não devolveu vazio")

# E a bandeira, por mais larga que seja, termina ANTES de o número começar.
texto_x = ec.MARGEM_ESQ + int(ec.BANDEIRA_ALT * 1.5) + ec.BANDEIRA_GAP
larga = Image.open(io.BytesIO(ec.montar({
    "clube": "X",
    "jogadores": [{"numero": "25", "nome": "CHELFI",
                   "bandeira": _bandeira_de(200, 40)}]}))).convert("RGB")
vermelho_no_numero = any(
    larga.getpixel((x, ec.LINHA_1))[0] > 150 and larga.getpixel((x, ec.LINHA_1))[1] < 80
    for x in range(texto_x - 4, texto_x + 30))
ok(not vermelho_no_numero,
   "uma bandeira 5:1 foi desenhada por cima do número da camisa")


# ── O TAMANHO É UM SÓ, EM TODAS AS ARTES (23/10/26) ─────────────────────
#
#   "Notei que cada arte tem um tamanho diferente de fonte, o ideal é
#    padronizar a menor dos tamanhos entre todas."
#
d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
TEXTO_X = ec.MARGEM_ESQ + int(ec.BANDEIRA_ALT * 1.5) + ec.BANDEIRA_GAP
CABE = ec.MARGEM_DIR - TEXTO_X
f = ec._fonte(ec.FONTE_LISTA, ec.CORPO_LISTA)
TRK = ec.CORPO_LISTA * ec.TRACKING

# As placas mais longas da liga, como o campinho as escreve. O corpo fixo é
# "o menor de todos" justamente porque a mais longa delas tem de caber.
for placa in ("22 MILINKOVIĆ-SAVIĆ", "10 KORTAJARENA", "07 AL-KUWAYKIBI",
              "71 GLUŠČEVIĆ", "38 SUMMERVILLE"):
    ok(ec.largura(d, placa, f, TRK) <= CABE,
       f"'{placa}' não cabe no corpo fixo {ec.CORPO_LISTA}. O tamanho único "
       "tem de ser o que serve para a placa mais longa da liga, senão ela sai "
       "abreviada em toda arte do clube dela")

# E A PROVA DE QUE NÃO VARIA: o corpo usado na lista é o MESMO numa arte de
# nomes curtos e numa de nomes longos. Era essa a variação que ele viu.
_usados = []
_fonte_real = ec._fonte


def _espia(arquivo, tamanho):
    if arquivo in (ec.FONTE_LISTA, ec.FONTE_TECNICO):
        _usados.append((arquivo, int(tamanho)))
    return _fonte_real(arquivo, tamanho)


try:
    ec._fonte = _espia
    ec.montar({"clube": "HILAL", "tecnico": {"nome": "BRUNO"},
               "jogadores": [{"numero": "1", "nome": "DUDA"}]})
    curtas = set(_usados)
    _usados.clear()
    ec.montar({"clube": "HILAL", "tecnico": {"nome": "ATHANASIOS PAPASTAMATIOU"},
               "jogadores": [{"numero": "22", "nome": "MILINKOVIĆ-SAVIĆ"},
                             {"numero": "61", "nome": "ABDULRAHMAN AL DAWSARI MONTENEGRINO"}]})
    longas = set(_usados)
finally:
    ec._fonte = _fonte_real
ok(curtas == longas and {t for _, t in curtas} == {ec.CORPO_LISTA},
   f"o corpo da lista mudou conforme os nomes ({curtas} x {longas}). A "
   "variação entre uma arte e outra é exatamente o que ele pediu para acabar")

# Quem passar do corpo fixo sai abreviado — a lista não encolhe por um nome.
_longo = "61 ABDULRAHMAN AL DAWSARI MONTENEGRINO"
ok(ec.cortar(d, _longo, f, CABE, TRK).endswith(ec.RETICENCIAS)
   and ec.largura(d, ec.cortar(d, _longo, f, CABE, TRK), f, TRK) <= CABE,
   "o nome longo demais passou da borda em vez de sair abreviado")
ok(ec.cortar(d, "01 DUDA", f, CABE, TRK) == "01 DUDA",
   "um nome que cabia foi abreviado à toa")

# As reticências têm de APARECER. O caractere "…" não existe na WorkSans do
# projeto (recorte latin) e saía invisível: "KALIDOU KOULIBA" parecia erro
# de digitação na arte do Hilal, sem nada dizendo que tinha sido cortado.
from fontTools.ttLib import TTFont as _TTFont               # noqa: E402

_cmap = _TTFont(os.path.join(ec.FONTES, ec.FONTE_LISTA)).getBestCmap()
ok(all(ord(c) in _cmap for c in ec.RETICENCIAS),
   f"as reticências {ec.RETICENCIAS!r} usam um caractere que a fonte da lista "
   "não tem; o corte sai invisível e o nome parece digitado errado")
ok(ec.cortar(d, "QUALQUER", f, 1) == "",
   "com limite impossível a função devolveu texto em vez de nada")


# ── O TÉCNICO NÃO DITA O TAMANHO ────────────────────────────────────────
ft = ec._fonte(ec.FONTE_TECNICO, ec.CORPO_LISTA)
ok(ec.tecnico_que_cabe(d, "SIMONE INZAGHI", ft, CABE, TRK) == "SIMONE INZAGHI",
   "um técnico que cabia inteiro perdeu o primeiro nome")
_papas = ec.tecnico_que_cabe(d, "ATHANASIOS PAPASTAMATIOU", ft, CABE, TRK)
ok(_papas == "PAPASTAMATIOU",
   f"'ATHANASIOS PAPASTAMATIOU' virou '{_papas}'. Quando não cabe, caem os "
   "primeiros nomes e fica o sobrenome — 'ATHANASIOS PAPAS...' ninguém "
   "reconhece")
_carille = ec.tecnico_que_cabe(d, "FABIO LUIZ CARILLE DA SILVA SANTOS", ft, CABE, TRK)
ok(ec.largura(d, _carille, ft, TRK) <= CABE and _carille.endswith("SANTOS"),
   f"o nome composto longo saiu '{_carille}': tinha de perder os primeiros "
   "nomes um a um e manter o fim")
ok(ec.tecnico_que_cabe(d, "", ft, CABE, TRK) == "",
   "técnico sem nome devolveu texto")

# E A ARTE USA ISSO. A função certa existir não prova nada — uma versão em
# que `montar` chamava o corte com reticências passou pelas asserções acima.
# Aqui se olha o que foi DESENHADO na linha do técnico.
_escritos = []
_escrever_real = ec.escrever
try:
    ec.escrever = lambda d_, b_, xy, texto, *a, **k: (
        _escritos.append(texto), _escrever_real(d_, b_, xy, texto, *a, **k))
    ec.montar({"clube": "ETTIFAQ",
               "tecnico": {"nome": "ATHANASIOS PAPASTAMATIOU"},
               "jogadores": [{"numero": "1", "nome": "RODAK"}]})
finally:
    ec.escrever = _escrever_real
ok("PAPASTAMATIOU" in _escritos,
   f"a linha do técnico foi desenhada como {_escritos[-1:]!r}. Quando o nome "
   "não cabe, a arte tem de mostrar o sobrenome inteiro — e não "
   "'ATHANASIOS PAPAS...'")


# ── O NOME DO CLUBE: MAIOR, MAIS FECHADO, E O MESMO TAMANHO PARA TODOS ──
#
#   "A fonte com nome do clube pode ser maior, basta condensá-la mais,
#    fechando o espaço entre as letras."
#
CLUBES_DA_TEMPORADA = ("HAZEM", "FAYHA", "FATEH", "SHABAB", "FAISALY", "NASSR",
                       "ITTIHAD", "DIRIYAH", "QADSIAH", "HILAL", "AHLI",
                       "KHALEEJ", "NEOM", "ABHA", "KHOLOOD", "ETTIFAQ",
                       "RIYADH", "TAAWOUN")
ok(ec.NOME_CLUBE_CORPO > 128 and ec.TRACKING_CLUBE < ec.TRACKING,
   "o nome do clube não ficou maior e mais condensado que antes")
for nome_clube in CLUBES_DA_TEMPORADA:
    fc, _trk = ec._nome_do_clube(d, nome_clube, ec.MARGEM_DIR - ec.MARGEM_ESQ)
    ok(fc.size == ec.NOME_CLUBE_CORPO,
       f"'{nome_clube}' saiu no corpo {fc.size} e não no {ec.NOME_CLUBE_CORPO}. "
       "Todos os clubes da temporada têm de caber no mesmo tamanho, senão o "
       "nome do clube varia de uma arte para a outra")
fc_longo, _ = ec._nome_do_clube(d, "BUKAYRIYAHHHHH", ec.MARGEM_DIR - ec.MARGEM_ESQ)
ok(fc_longo.size < ec.NOME_CLUBE_CORPO,
   "um nome de clube que não cabe não encolheu: passaria da borda da arte")


# ── A FOTO: apoiada na base, com respiro em cima ────────────────────────
def silhueta(larg=400, alt=900, margem=60):
    im = Image.new("RGBA", (larg + 2 * margem, alt + 2 * margem), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle(
        (margem, margem, margem + larg, margem + alt), fill=(10, 120, 90, 255))
    return im


corte = ec.recortar_no_conteudo(silhueta())
ok(corte.size == (401, 901),
   f"o recorte não tirou a moldura vazia da imagem da SPL: {corte.size}. "
   "Metade do arquivo de 1024x1024 é transparente; sem cortar, o jogador sai "
   "pequeno e boiando")

img, onde = ec.encaixar_foto(silhueta())
ok(onde[1] + img.height == ec.ALTURA,
   "a foto não ficou apoiada na base da arte; o jogador fica boiando")
# 40 ESCRITO À MÃO, de propósito: medir contra `ec.FOTO_TOPO` faria a régua
# andar junto com a constante, e zerar o respiro passaria calado.
ok(onde[1] >= 40,
   f"com zoom 1 a foto chegou a y={onde[1]} e praticamente encostou no topo. "
   "Cortar o topo da cabeça é exatamente o que ele já reclamou no campinho")
# O que passa de FOTO_DIR fica ESCONDIDO atrás do painel, que é opaco, e isso
# é de propósito: na arte dele o ombro do jogador é cortado pela borda do
# painel. O que não pode é a figura ficar quase toda escondida.
visivel = min(img.width, ec.FOTO_DIR - onde[0])
ok(visivel >= img.width * 0.6,
   f"só {visivel} de {img.width} px da figura aparecem; o resto sumiu atrás "
   "do painel escuro. Um pedaço do ombro cortado é o desenho dele; o jogador "
   "inteiro escondido é defeito")

maior, _ = ec.encaixar_foto(silhueta(), zoom=1.4)
ok(maior.height > img.height,
   "o zoom não aumentou a figura; é o controle que ele já usa no campinho")

esq, _ = ec.encaixar_foto(silhueta(), ancora=0.0)
dirr, pos_d = ec.encaixar_foto(silhueta(), ancora=1.0)
ok(ec.encaixar_foto(silhueta(), ancora=0.0)[1][0] == 0,
   "âncora 0 não encostou a figura na esquerda")
ok(pos_d[0] + dirr.width == ec.FOTO_DIR,
   "âncora 1 não encostou a figura na direita da faixa")

ok(ec.encaixar_foto(None) == (None, (0, 0)),
   "sem foto a função levantou em vez de devolver vazio")


# ── A ARTE INTEIRA, E O QUE FALTA NÃO PODE DERRUBAR ─────────────────────
def _montar(**extra):
    base = {"clube": "ETTIFAQ",
            "jogadores": [{"numero": str(i + 1), "nome": f"JOGADOR {i}",
                           "bandeira": None} for i in range(11)],
            "tecnico": {"nome": "ARTHUR PAPAS", "bandeira": None}}
    base.update(extra)
    return ec.montar(base)


b = io.BytesIO()
silhueta().save(b, "PNG")
png = _montar(foto=b.getvalue())
arte = Image.open(io.BytesIO(png))
ok(arte.size == (ec.LARGURA, ec.ALTURA),
   f"a arte não saiu 1080x1350, e sim {arte.size}")
ok(len(png) > 10000, "a arte saiu pequena demais para ter conteúdo")

for falta in ({}, {"foto": b"nao e imagem"}, {"escudo": b"lixo"},
              {"clube": ""}, {"jogadores": []}, {"tecnico": {}}):
    try:
        _montar(**falta)
    except Exception as exc:
        falhas.append(f"a arte caiu quando faltou {falta or 'a foto'}: {exc}. "
                      "Em dia de jogo, arte com um buraco é melhor que erro")

# Onze é a regra do jogo. Com vinte na lista, a arte tem de sair IDÊNTICA à
# dos onze primeiros — comparar os bytes é o que prova que o décimo segundo
# não foi desenhado por cima do rodapé.
onze_j = [{"numero": str(i), "nome": f"N{i}"} for i in range(11)]
vinte_j = [{"numero": str(i), "nome": f"N{i}"} for i in range(20)]
ok(_montar(foto=b.getvalue(), jogadores=onze_j)
   == _montar(foto=b.getvalue(), jogadores=vinte_j),
   "a arte muda quando chegam mais de onze jogadores: os reservas estão "
   "sendo desenhados para fora do painel, por cima dos escudos")


# ── OS TRÊS AJUSTES DE 23/10/26 ─────────────────────────────────────────
#
#   "somente o nome do técnico em negrito, dos jogadores, não"
#   "condensaria um pouco o espaço entre as letras"
#   "a primeira letra do nome do clube tem que tá alinhada com a bandeira"
#
ok("Bold" in ec.FONTE_TECNICO and "Bold" not in ec.FONTE_LISTA,
   "o negrito voltou para a lista dos jogadores. Ele pediu negrito SÓ no "
   "técnico")
ok(os.path.exists(os.path.join(ec.FONTES, ec.FONTE_LISTA))
   and os.path.exists(os.path.join(ec.FONTES, ec.FONTE_TECNICO)),
   "uma das fontes escolhidas não existe na pasta; a arte cairia no deploy")

ok(ec.TRACKING < 0, "o espaço entre as letras deixou de ser condensado")
f50 = ec._fonte(ec.FONTE_LISTA, 50)
ok(ec.largura(d, "AL OTAIBI", f50, 50 * ec.TRACKING)
   < ec.largura(d, "AL OTAIBI", f50, 0),
   "condensar não diminuiu a largura da linha; o tracking não está sendo "
   "aplicado na medida")
# E o condensado tem de chegar nos PIXELS: medir certo e desenhar solto
# passou calado numa versão anterior deste teste.
def _tinta(texto, fonte, tracking):
    tela = Image.new("RGBA", (900, 120), (0, 0, 0, 255))
    ec.escrever(ImageDraw.Draw(tela), tela, (20, 60), texto, fonte, tracking)
    caixa = tela.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    return (caixa[2] - caixa[0]) if caixa else 0


solto = _tinta("61 AL OTAIBI", f50, 0)
apertado = _tinta("61 AL OTAIBI", f50, 50 * ec.TRACKING)
ok(apertado < solto,
   f"a linha desenhada ocupa {apertado}px condensada e {solto}px solta — ou "
   "seja, o tracking foi calculado e não chegou ao desenho")
ok(abs(apertado - ec.largura(d, "61 AL OTAIBI", f50, 50 * ec.TRACKING)) < 12,
   "a largura medida e a largura desenhada discordam; é por essa conta que o "
   "limite da borda decide abreviar, então ela tem de bater")

ok(ec.largura(d, "A", f50, 50 * ec.TRACKING) == ec.largura(d, "A", f50, 0),
   "uma letra sozinha mudou de largura: o tracking está sendo somado depois "
   "da última letra, e aí a medida não bate com o desenho")

# O ALINHAMENTO, MEDIDO NOS PIXELS: a primeira letra do nome do clube e a
# bandeira do jogador têm de começar na MESMA coluna. Conferir a constante não
# bastava — era um `anchor="rs"` que jogava o nome para a direita, e a
# constante estava certa o tempo todo.
marca = Image.new("RGBA", (60, 40), (255, 0, 0, 255))
mb = io.BytesIO()
marca.save(mb, "PNG")
arte2 = Image.open(io.BytesIO(_montar(
    clube="ETTIFAQ",
    jogadores=[{"numero": "01", "nome": "RODAK", "bandeira": mb.getvalue()}]
    + [{"numero": str(i + 2), "nome": f"N{i}"} for i in range(10)]))).convert("RGB")
pix = arte2.load()


def _primeira_coluna(y0, y1, teste):
    for x in range(ec.PAINEL_ESQ, ec.MARGEM_DIR):
        if any(teste(pix[x, y]) for y in range(y0, y1)):
            return x
    return None


x_band = _primeira_coluna(ec.LINHA_1 - 20, ec.LINHA_1 + 20,
                          lambda c: c[0] > 180 and c[1] < 80 and c[2] < 80)
x_clube = _primeira_coluna(ec.NOME_CLUBE_BASE - 110, ec.NOME_CLUBE_BASE,
                           lambda c: min(c) > 200)
ok(x_band is not None and x_clube is not None,
   "não achei a bandeira ou o nome do clube na arte para comparar")
if x_band is not None and x_clube is not None:
    ok(abs(x_clube - x_band) <= 2,
       f"o nome do clube começa em x={x_clube} e a bandeira em x={x_band}. "
       "Era esse vão à esquerda do ETTIFAQ que ele estranhou")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ arte de escalação conferida contra o próprio template")
