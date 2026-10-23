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


# ── O NOME COMPRIDO NÃO PODE ESTOURAR ───────────────────────────────────
curtos = ["01 DUDA", "11 KANTÉ"]
longos = ["71 GLUŠČEVIĆ MONTENEGRINO", "61 ABDULRAHMAN AL DAWSARI"]
c1 = ec._corpo_que_cabe(curtos, 400)
c2 = ec._corpo_que_cabe(curtos + longos, 400)
ok(c2 < c1,
   "a lista com um nome comprido manteve o mesmo corpo de letra. Foi o "
   "'GLUŠČEVIĆ' passando da borda no rascunho dele que pediu isto")
ok(c2 >= ec.CORPO_MIN,
   "o corpo encolheu abaixo do mínimo legível para caber um nome")

d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
f = ec._fonte("WorkSans-SemiBold-latin.ttf", c2)
ok(all(d.textlength(ec.cortar(d, t, f, 400), font=f) <= 400
       for t in curtos + longos),
   "mesmo depois de encolher E abreviar, alguma linha passa do limite. É o "
   "texto invadindo a borda da arte, que foi o defeito do rascunho dele")
ok(ec.cortar(d, "01 DUDA", f, 400) == "01 DUDA",
   "um nome que cabia foi abreviado à toa")
ok(ec.cortar(d, longos[0], f, 400).endswith("…"),
   "o nome que não cabia foi desenhado inteiro, estourando a borda, em vez "
   "de sair com reticências")
ok(ec.cortar(d, "QUALQUER", f, 1) == "",
   "com limite impossível a função devolveu texto em vez de nada")

ok(ec._corpo_que_cabe(curtos, 400) == ec._corpo_que_cabe(curtos, 400),
   "o cálculo do corpo não é estável entre chamadas")


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


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ arte de escalação conferida contra o próprio template")
