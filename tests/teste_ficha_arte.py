"""
A arte 1080x1350 da ficha do jogador, conferida contra o exemplo que ele mandou.

O PEDIDO (15/09/26)
    "Inclua um botão de baixar imagem na guia de elencos. Ao selecionar um
    perfil de jogador, você irá montar em background uma imagem com nome, logo
    do clube, símbolo do país, e foto de jogador. Conforme exemplo da imagem 1
    anexada. (...) As informações de jogos, gols e assistências virão do que
    for filtrado de competições lá no perfil do jogador."

COMO ESTE ARQUIVO CONFERE
    Com o exemplo de verdade. `tests/fixtures/ficha_exemplo_360.png` é a arte
    que ele mandou, reduzida a um terço — pequena o bastante para morar no
    repositório e grande o bastante para denunciar qualquer deslocamento.

    A comparação é só onde NÃO há foto nem texto: o degradê do fundo. É ali
    que mora a decisão que mais fácil se quebra sem aviso — a ordem das camadas
    e a multiplicação. Se alguém trocar multiplicar por colar, ou puser a foto
    por cima do degradê, o rodapé deixa de escurecer e a diferença é enorme.
    Comparar o texto não daria: a fonte do Canva dele não é esta, e largura de
    letra não é o que se está vigiando.

    O resto é medido por EFEITO, e não procurando constante no código: eu monto
    a arte com peças de cor chapada e olho onde a tinta caiu. Conferir que
    `FOTO_X = 96` continua escrito é conferir que eu sei copiar um número.

SÓ PIL, SEM NUMPY
    O numpy deixaria estas contas mais curtas e não está declarado no projeto.
    Este teste roda no gancho de pre-push, na máquina Windows do Vini — e
    biblioteca que falta ali vira aviso vermelho que não é defeito nenhum. A
    rede de segurança dele já deu falso alarme demais; não vou plantar mais um
    para economizar cinco linhas.
"""
import io
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    _t = types.ModuleType("psycopg2")
    _t.extras = types.ModuleType("psycopg2.extras")
    _t.extras.RealDictCursor = object
    _t.Error = Exception
    sys.modules["psycopg2"] = _t
    sys.modules["psycopg2.extras"] = _t.extras

from PIL import Image, ImageChops, ImageStat            # noqa: E402

import ficha_arte                                       # noqa: E402

# ── AS MEDIDAS DO EXEMPLO, ESCRITAS AQUI DE NOVO ────────────────────────────
#
# De propósito, e é a correção de um erro meu: eu conferia a altura dos
# algarismos comparando com `ficha_arte.NUM_ALTURA`. Plantei o defeito
# (algarismo de 140px em vez de 188) e o teste passou — claro: ele comparava a
# arte com a constante que o defeito tinha acabado de mudar. Um teste assim
# confere que o código concorda consigo mesmo.
#
# Estes números vieram do `exemplo.png` medido pixel a pixel, e é contra ELES
# que a arte tem de bater. Se um dia mudarem, é porque ele mandou outra arte —
# e aí os dois lugares mudam, o que é exatamente o atrito que se quer.
DO_EXEMPLO = {
    "foto": (96, 32, 1290),            # x, y, lado
    "escudo": (34, 402, 129),
    "bandeira": (39, 556, 120),
    "nome_x": 31, "nome_topo": 40, "nome_largura_max": 1020,
    "num_centros": (194.4, 540.0, 885.6),
    "num_altura": 188,
    "num_largura_124": 230,            # a tinta do "124" na arte dele
}

EXEMPLO = os.path.join(RAIZ, "tests", "fixtures", "ficha_exemplo_360.png")
FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

MAGENTA, CIANO, LARANJA = (255, 0, 255), (0, 255, 255), (255, 128, 0)

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ── ferramentas de olhar pixel ──────────────────────────────────────────────
def _quadrado(cor, lado=1024) -> bytes:
    """Uma peça de cor chapada, para eu ver ONDE ela foi parar."""
    saida = io.BytesIO()
    Image.new("RGBA", (lado, lado), tuple(cor) + (255,)).save(saida, format="PNG")
    return saida.getvalue()


def _arte(**kw):
    dados = {"nome": "João Félix", "jogos": 124, "gols": 123,
             "assistencias": 101}
    dados.update(kw)
    return Image.open(io.BytesIO(ficha_arte.montar(dados))).convert("RGB")


def _mascara_cor(im, cor, tol=40):
    """255 onde o pixel é (quase) esta cor. A soma satura em 255, e tudo bem:
    saturar já quer dizer 'longe', que é o que a comparação vai concluir."""
    soma = None
    for canal, alvo in zip(im.split(), cor):
        dist = canal.point(lambda v, a=alvo: min(255, abs(v - a)))
        soma = dist if soma is None else ImageChops.add(soma, dist)
    return soma.point(lambda v: 255 if v < tol else 0)


def _mascara_branca(im, limiar=200):
    r, g, b = im.split()
    escuro = ImageChops.darker(ImageChops.darker(r, g), b)
    return escuro.point(lambda v: 255 if v > limiar else 0)


def _mascara_mudou(a, b, tol=20):
    """Onde as duas artes diferem. Serve para achar a caixa da foto no rodapé,
    onde o degradê já apagou a cor da peça."""
    d = ImageChops.difference(a, b).convert("L")
    return d.point(lambda v: 255 if v > tol else 0)


def _colunas_com_tinta(masc, y0, y1):
    """Quais colunas têm tinta nesta faixa. Um OU de todas as linhas.

    O OU sai de um inteiro gigante: `int.from_bytes` da linha inteira e `|`
    entre elas. É o mesmo que um laço por pixel e roda em C.
    """
    faixa = masc.crop((0, y0, masc.width, y1))
    larg, dados, acc = faixa.width, faixa.tobytes(), 0
    for y in range(faixa.height):
        acc |= int.from_bytes(dados[y * larg:(y + 1) * larg], "big")
    perfil = acc.to_bytes(larg, "big")
    return [x for x, v in enumerate(perfil) if v]


def _blocos(colunas, junta=60, minimo=8):
    """As colunas agrupadas em blocos. Sem juntar, cada ALGARISMO vira um
    bloco e "124 123 101" devolve nove — e o que eu quero saber é onde estão
    os três grupos, que ficam a 350px um do outro."""
    if not colunas:
        return []
    saida = [[colunas[0], colunas[0]]]
    for x in colunas[1:]:
        if x - saida[-1][1] <= junta:
            saida[-1][1] = x
        else:
            saida.append([x, x])
    return [tuple(g) for g in saida if g[1] - g[0] > minimo]


def _diferenca_media(a, b, caixa):
    d = ImageChops.difference(a.crop(caixa), b.crop(caixa))
    return sum(ImageStat.Stat(d).mean)


def _brilho(im, caixa):
    return sum(ImageStat.Stat(im.crop(caixa)).mean) / 3.0


# ─────────────────────────────────────────────────────────────────────────
# 1. O FUNDO É O DO EXEMPLO — mesmo degradê, mesmas camadas
# ─────────────────────────────────────────────────────────────────────────
arte = _arte()
ok(arte.size == (1080, 1350), f"a arte saiu {arte.size}, e não (1080, 1350)")

pequena = arte.resize((360, 450), Image.LANCZOS)
exemplo = Image.open(EXEMPLO).convert("RGB")

# Três janelas: o degradê do meio à esquerda, o rodapé quase preto e o talho
# verde do canto. Nenhuma tem foto nem texto na arte dele.
JANELAS = [((0, 230, 95, 315), "o degradê do meio", 6),
           ((0, 420, 100, 448), "o rodapé escuro", 6),
           ((300, 432, 358, 449), "o talho verde do canto", 26)]
for caixa, t, teto in JANELAS:
    d = _diferenca_media(pequena, exemplo, caixa)
    ok(d < teto, f"{t} não bate com o exemplo (diferença média {d:.1f}, teto "
                 f"{teto}). Confira se o sobreposto ainda MULTIPLICA o fundo "
                 f"e se o verde continua sendo colado por cima")

# E o degradê tem de escurecer de cima para baixo. É o que faz a camisa
# mergulhar no escuro onde entram os números.
ok(_brilho(arte, (0, 100, 60, 200)) > _brilho(arte, (0, 1250, 60, 1330)) + 40,
   "o fundo parou de escurecer no rodapé — sem isso os números brancos caem "
   "em cima do amarelo da camisa")


# ─────────────────────────────────────────────────────────────────────────
# 2. CADA PEÇA CAI NO LUGAR DO EXEMPLO
# ─────────────────────────────────────────────────────────────────────────
a = _arte(foto=_quadrado(MAGENTA), escudo=_quadrado(CIANO),
          bandeira=_quadrado(LARANJA))

# A CAIXA DA FOTO, medida pela DIFERENÇA contra a arte sem foto.
#
# Pela diferença, e não procurando a cor da peça — por dois motivos, os dois
# aprendidos errando. No rodapé o degradê já é quase preto, e magenta
# multiplicado por preto é preto: foi assim que uma foto de 1080px em vez de
# 1290px passou batido, porque só o topo era conferido. E no topo o NOME passa
# por cima da foto, então varrer uma linha atrás de magenta encontra a letra
# antes da foto — o teste acusou "a foto começa em x=114" quando o nome ficou
# maior, e a foto não tinha saído do lugar.
#
# Na diferença as duas artes têm o mesmo nome e o mesmo fundo: o que sobra é
# só a foto.
sem = _arte()
caixa_foto = _mascara_mudou(_arte(foto=_quadrado(MAGENTA)), sem).getbbox()
ok(caixa_foto is not None, "a foto não mudou nada na arte")
if caixa_foto:
    fx0, fy0, fx1, fy1 = caixa_foto          # getbbox devolve o limite EXCLUSIVO
    x0, y0, lado = DO_EXEMPLO["foto"]
    ok(abs(fy0 - y0) <= 3, f"o topo da foto ficou em y={fy0}, e no exemplo é {y0}")
    ok(abs(fy1 - (y0 + lado)) <= 3,
       f"o pé da foto ficou em y={fy1}, e no exemplo é {y0 + lado} — ou seja: "
       f"o tamanho da foto mudou")
    ok(abs(fx0 - x0) <= 3,
       f"a esquerda da foto ficou em x={fx0}, e no exemplo é {x0}")
    ok(fx1 >= 1080,
       "a foto parou antes da borda direita — no exemplo ela sangra para fora")

# O ESCUDO e a BANDEIRA são desenhados DEPOIS do degradê, então saem com a cor
# inteira. É a prova de que estão por cima, e não por baixo.
cx = _mascara_cor(a, CIANO).getbbox()
ok(cx is not None, "o escudo do clube não apareceu")
if cx:
    ok(abs(cx[0] - DO_EXEMPLO["escudo"][0]) <= 2
       and abs(cx[1] - DO_EXEMPLO["escudo"][1]) <= 2,
       f"o escudo ficou em {cx[:2]}, e no exemplo fica em "
       f"{DO_EXEMPLO['escudo'][:2]}")
    ok(abs((cx[2] - cx[0]) - DO_EXEMPLO["escudo"][2]) <= 2,
       f"o escudo saiu com {cx[2]-cx[0]}px de lado, e no exemplo tem "
       f"{DO_EXEMPLO['escudo'][2]}")

bd = _mascara_cor(a, LARANJA).getbbox()
ok(bd is not None, "a bandeira não apareceu")
if bd:
    ok(abs(bd[0] - DO_EXEMPLO["bandeira"][0]) <= 3
       and abs(bd[1] - DO_EXEMPLO["bandeira"][1]) <= 3,
       f"a bandeira ficou em {bd[:2]}, e no exemplo fica em "
       f"{DO_EXEMPLO['bandeira'][:2]}")

# REDONDA, e não quadrada: o canto da caixa tem de estar VAZIO. Com recorte
# quadrado este teste passaria.
canto_band = _mascara_cor(a.crop((43, 560, 49, 566)), LARANJA).getbbox()
ok(canto_band is None,
   "a bandeira não está recortada em círculo — o canto da caixa tem tinta")

# O ESCUDO, AO CONTRÁRIO, NÃO É RECORTADO. Escudo em forma de brasão perderia
# a ponta de baixo, e isso sairia calado.
canto_esc = _mascara_cor(a.crop((36, 404, 42, 410)), CIANO).getbbox()
ok(canto_esc is not None,
   "o escudo passou a ser recortado em círculo — brasão perde a ponta assim")


# ─────────────────────────────────────────────────────────────────────────
# 3. OS NÚMEROS: três colunas, e "não sei" não é zero
# ─────────────────────────────────────────────────────────────────────────
branco = _mascara_branca(arte)
cols = _blocos(_colunas_com_tinta(branco, 1000, 1205))
ok(len(cols) == 3, f"esperava três colunas de número e achei {len(cols)}")
if len(cols) == 3:
    for (e, d), alvo in zip(cols, DO_EXEMPLO["num_centros"]):
        ok(abs((e + d) / 2 - alvo) <= 18,
           f"uma coluna ficou centrada em {(e+d)/2:.0f}, e devia ser {alvo:.0f}")

# A LARGURA DO "124", que é o que o aperto horizontal existe para acertar.
#
# A fonte deste arquivo é mais larga que a do Canva: na altura do exemplo os
# três números quase se encostavam, e ele escolheu comprimir na horizontal.
# Sem o aperto, "124" sai com 269px de tinta em vez de 230 e a folga entre as
# colunas cai de 124px para 83. A altura sozinha não denunciaria isso — é por
# isso que esta medida existe separada.
if len(cols) == 3:
    larg124 = cols[0][1] - cols[0][0] + 1
    ok(abs(larg124 - DO_EXEMPLO["num_largura_124"]) <= 20,
       f'o "124" saiu com {larg124}px de largura, e na arte dele tem '
       f'{DO_EXEMPLO["num_largura_124"]}px — confira o aperto horizontal')
    ok(cols[1][0] - cols[0][1] >= 100,
       f"sobraram só {cols[1][0]-cols[0][1]}px entre a primeira e a segunda "
       f"coluna de números; na arte dele sobram mais de 120")

# ALTURA DO ALGARISMO: é a medida do exemplo, e é ela que dá o peso da arte.
alt = branco.crop((0, 950, 1080, 1210)).getbbox()
ok(alt is not None, "não há número nenhum desenhado")
if alt:
    altura = alt[3] - alt[1]
    ok(abs(altura - DO_EXEMPLO["num_altura"]) <= 4,
       f"os algarismos saíram com {altura}px de altura, e no exemplo têm "
       f"{DO_EXEMPLO['num_altura']}px")

# ZERO E "NÃO SEI" SÃO COISAS DIFERENTES. É a terceira vez que este erro
# aparece no projeto; aqui ele sairia publicado.
com_zero = _blocos(_colunas_com_tinta(_mascara_branca(_arte(gols=0)), 1000, 1205))
com_nulo = _blocos(_colunas_com_tinta(_mascara_branca(_arte(gols=None)), 1000, 1205))
ok(len(com_zero) == 3 and len(com_nulo) == 3,
   "com gols nulo ou zero, a arte deixou de ter três colunas")
if len(com_zero) == 3 and len(com_nulo) == 3:
    ok(com_zero[1] != com_nulo[1],
       "gols=None saiu desenhado igual a gols=0. Jogador que entrou e não "
       "marcou tem zero; partida que eu não li inteira não tem número nenhum")

# As legendas, embaixo dos números.
leg = _blocos(_colunas_com_tinta(branco, 1230, 1270))
ok(len(leg) == 3, f"esperava três legendas e achei {len(leg)}")


# ─────────────────────────────────────────────────────────────────────────
# 4. O NOME: duas linhas, e encolhe em vez de vazar
# ─────────────────────────────────────────────────────────────────────────
ok(ficha_arte.quebrar_nome("João Félix") == ["JOÃO", "FÉLIX"],
   "o nome deixou de quebrar em duas linhas")
ok(ficha_arte.quebrar_nome("Ronaldo") == ["RONALDO"],
   "nome de uma palavra só não pode virar duas linhas")
# AS DUAS ÚLTIMAS PALAVRAS, e não as duas primeiras: é assim que o jogador é
# chamado. "CRISTIANO RONALDO" seria certo por sorte; "ABDULRAHMAN GHAREEB"
# sobrenome primeiro já não é o nome de ninguém.
ok(ficha_arte.quebrar_nome("Cristiano Ronaldo dos Santos Aveiro")
   == ["SANTOS", "AVEIRO"],
   "nome comprido tem de caber em duas linhas, e são as duas ÚLTIMAS "
   "palavras — a terceira linha passaria por cima do escudo, que fica a "
   "402px do topo, e as duas primeiras palavras não são como ele é chamado")
ok(ficha_arte.quebrar_nome("") == [], "nome vazio não pode virar linha vazia")

# ── O NOME SAI IGUAL PARA TODO MUNDO ────────────────────────────────────────
#
# Ele viu as primeiras artes e pediu três coisas (16/09/26):
#   "mantenha o mesmo tamanho de fonte usada no João Félix"
#   "mantenha também a proximidade entre o nome na primeira linha com o nome
#    na segunda linha, como rola no João Félix, pra todos"
#   "o nome pode passar por trás da imagem do jogador, estilisticamente fica
#    bom. Não há problemas nisto."
#
# Antes o nome ENCOLHIA para caber antes da foto. "GABRIEL MARTINELLI" saía
# bem menor que "JOÃO FÉLIX" e, como a entrelinha continuava fixa, as duas
# linhas pareciam afastadas. Os dois sintomas tinham a mesma causa.
def _linhas_do_nome(quem):
    """(altura da maiúscula da 1ª linha, distância entre as duas bases)."""
    m = _mascara_branca(_arte(nome=quem))
    a = m.crop((0, 0, 1080, 200)).getbbox()
    b = m.crop((0, 200, 1080, 400)).getbbox()
    if not a or not b:
        return None
    return (a[3] - a[1], (200 + b[3]) - a[3])

# NOMES SEM "J", de propósito: nesta fonte o J desce abaixo da linha de base,
# e a medida da entrelinha sairia 24px maior só por causa dele. Foi o primeiro
# resultado deste teste, e não era defeito da arte.
CURTO = _linhas_do_nome("Ali Nasser")
LONGO = _linhas_do_nome("Abdulrahman Ghareeb")
ok(CURTO and LONGO, "um dos nomes de teste não foi desenhado")
if CURTO and LONGO:
    ok(abs(CURTO[0] - LONGO[0]) <= 3,
       f"o nome comprido saiu com letra de {LONGO[0]}px e o curto com "
       f"{CURTO[0]}px. Todo mundo tem de sair no tamanho do João Félix, "
       f"mesmo que o nome passe por trás da foto")
    ok(abs(CURTO[0] - 148) <= 5,
       f"a maiúscula do nome saiu com {CURTO[0]}px; na arte dele tem 148")
    ok(abs(CURTO[1] - LONGO[1]) <= 3,
       f"a distância entre as duas linhas mudou com o nome ({CURTO[1]} contra "
       f"{LONGO[1]}px) — ela tem de ser a mesma para todos")
    ok(abs(CURTO[1] - 171) <= 4,
       f"as duas linhas do nome ficaram a {CURTO[1]}px uma da outra; na arte "
       f"dele são 171")

# NENHUM NOME PODE SAIR CORTADO NA BORDA. Passar por trás da foto é estilo;
# sumir no talho verde da direita é defeito. É o único motivo que sobrou para
# o nome encolher.
#
# O último da lista é inventado e comprido de propósito: os nomes reais da
# liga cabem, e um teste em que o limite nunca é atingido não prova que o
# limite existe. Plantei "limite = 3000" e ele passou — só com uma palavra que
# de fato estoura é que a rede pega.
for gigante in ("Sergej Milinković-Savić", "Abdulrahman Al Aboud",
                "Konstantinos Mavropanos", "Abdulrahmanalobaidalmalki"):
    caixa = _mascara_branca(_arte(nome=gigante)).crop((0, 0, 1080, 400)).getbbox()
    ok(caixa is not None, f"o nome '{gigante}' não foi desenhado")
    if caixa:
        ok(caixa[2] <= 1075,
           f"'{gigante}' encostou na borda direita (x={caixa[2]}) — a última "
           f"letra sai cortada")
        ok(abs(caixa[0] - DO_EXEMPLO["nome_x"]) <= 12,
           f"'{gigante}' deixou de começar na margem da esquerda")

# O ESPAÇO ENTRE AS LETRAS É O VAZIO DE DENTRO DO "O".
#
# Palavra dele: "a distância pode ter o mesmo tamanho que tem no corte (vazio)
# interior das letras, como na letra O". Então o teste mede as DUAS coisas na
# arte montada e compara uma com a outra — não com um número que eu escrevi.
def _folga_entre_letras():
    tela = Image.new("RGBA", (900, 400), (0, 0, 0, 255))
    ficha_arte.texto(tela, ficha_arte.FONTE_NOME, "OO", 148, 40, 300, "ls",
                     cor=(255, 255, 255),
                     entreletra=ficha_arte.NOME_ENTRELETRA)
    col = _colunas_com_tinta(_mascara_branca(tela.convert("RGB")), 0, 400)
    blocos = _blocos(col, junta=3)
    return (blocos[1][0] - blocos[0][1] - 1) if len(blocos) == 2 else None

def _vazio_do_o():
    tela = Image.new("RGBA", (400, 400), (0, 0, 0, 255))
    ficha_arte.texto(tela, ficha_arte.FONTE_NOME, "O", 148, 40, 300, "ls",
                     cor=(255, 255, 255))
    m = _mascara_branca(tela.convert("RGB"))
    caixa = m.getbbox()
    meio = (caixa[1] + caixa[3]) // 2
    col = _colunas_com_tinta(m, meio, meio + 1)
    blocos = _blocos(col, junta=1, minimo=0)
    return (blocos[1][0] - blocos[0][1] - 1) if len(blocos) == 2 else None

FOLGA, VAZIO = _folga_entre_letras(), _vazio_do_o()
ok(FOLGA is not None and VAZIO is not None,
   "não consegui medir a folga entre letras ou o vazio do O")
if FOLGA is not None and VAZIO is not None:
    ok(abs(FOLGA - VAZIO) <= 4,
       f"a folga entre as letras é {FOLGA}px e o vazio de dentro do O é "
       f"{VAZIO}px. Ele pediu que fossem iguais")

alto = _mascara_branca(_arte(nome="Ali Nasser")).crop((0, 0, 1080, 400)).getbbox()
ok(alto is not None and abs(alto[1] - DO_EXEMPLO["nome_topo"]) <= 12,
   f"o nome começa em y={alto[1] if alto else '?'}, e no exemplo começa em "
   f"{DO_EXEMPLO['nome_topo']}")

# ── A INICIAL SOLTA E O QUADRADINHO ─────────────────────────────────────────
#
# "Tem jogadores que não aparece o nome. Corta após a primeira letra." Era o
# "S. Milinković-Savić": a primeira linha virava "S" mais um quadradinho,
# porque a fonte não tem o PONTO — e o "?" que eu punha no lugar do que ela
# não conhece também não existe nela, então virava quadradinho também.
ok(ficha_arte.quebrar_nome("S. Milinković-Savić") == ["MILINKOVIĆ-SAVIĆ"],
   "a inicial solta voltou a ocupar uma linha inteira do nome")
ok(ficha_arte.quebrar_nome("S") == ["S"],
   "quem se chama só 'S' ficou sem nome nenhum — descartar a inicial só vale "
   "quando sobra alguma coisa")
ok(ficha_arte.melhor_nome("S. Milinković-Savić", "Sergej Milinković-Savić")
   == "Sergej Milinković-Savić",
   "com o nome curto abreviado, o principal é que tem de ir para a arte")
ok(ficha_arte.melhor_nome("João Félix", "João Félix Sequeira") == "João Félix",
   "o nome curto deixou de ganhar no caso normal")

# E O QUADRADINHO NÃO PODE APARECER NUNCA. O que a fonte não tem, some.
ok(ficha_arte._decompor("S.", ficha_arte.FONTE_NOME) == [("S", [])],
   "o ponto voltou a virar alguma coisa desenhada — na fonte dele isso é o "
   "quadradinho do .notdef")
ok(ficha_arte._decompor("?", ficha_arte.FONTE_NOME) == [],
   "a interrogação voltou a ser desenhada, e a fonte não tem nem ela")
# E na arte montada: "A. Lajami" tem de sair com o sobrenome inteiro, e não
# com uma linha de uma letra só.
_abreviado = _mascara_branca(_arte(nome="A. Lajami"))
_linha1 = _abreviado.crop((0, 0, 1080, 200)).getbbox()
ok(_linha1 is not None and (_linha1[2] - _linha1[0]) > 200,
   "com o nome abreviado, a primeira linha da arte saiu com "
   f"{(_linha1[2]-_linha1[0]) if _linha1 else 0}px de largura — é a inicial "
   "sozinha de novo")

# ── OS ACENTOS QUE A FONTE NÃO TEM, DESENHADOS ──────────────────────────────
#
# O arquivo que ele mandou tem 68 desenhos: A-Z, a-z, algarismos, hífen, til
# solto e circunflexo solto. Nenhuma letra acentuada. A primeira conferência
# saiu "JO▯O F▯LIX", com o quadradinho do `.notdef`.
#
# O teste NÃO procura a função que desenha: ele compara o desenho, UMA MARCA
# DE CADA VEZ. Comparar o nome inteiro não serve — plantei "o agudo não existe
# mais" e o teste passou, porque o til de JOÃO sozinho já deixava a linha com
# mais tinta que JOAO. Cada acento precisa do seu próprio par.
def _tinta_da_palavra(palavra):
    """Quanta tinta esta palavra deixa. Desenhada direto, sem a arte inteira:
    é mais rápido e mede só o que interessa."""
    tela = Image.new("RGBA", (900, 400), (0, 0, 0, 255))
    ficha_arte.texto(tela, ficha_arte.FONTE_NOME, palavra, 120, 20, 300, "ls",
                     cor=(255, 255, 255))
    return sum(ImageStat.Stat(_mascara_branca(tela.convert("RGB"))).mean)

PARES = [("Ã", "A", "o til"), ("É", "E", "o acento agudo"),
         ("À", "A", "a crase"), ("Ê", "E", "o circunflexo"),
         ("Ü", "U", "o trema"), ("Ç", "C", "a cedilha"),
         ("Ñ", "N", "o til do N"), ("Š", "S", "o carón"),
         ("Ğ", "G", "a breve"), ("Å", "A", "o anel")]
for acentuada, base, comoSeChama in PARES:
    com = _tinta_da_palavra("A" + acentuada + "A")
    sem = _tinta_da_palavra("A" + base + "A")
    ok(com > sem * 1.02,
       f"{comoSeChama} não apareceu: '{acentuada}' desenha a mesma tinta que "
       f"'{base}'. A fonte não tem essa letra, então ou a marca é desenhada "
       f"ou o nome sai errado")
    ok(com < sem * 1.9,
       f"'{acentuada}' tem tinta demais para ser {comoSeChama} — é o "
       f"quadradinho do `.notdef` de volta no lugar da letra")

# E a detecção do quadradinho tem de continuar funcionando sem o fontTools,
# que não está declarado no projeto.
ok(ficha_arte._conhece(ficha_arte.FONTE_NOME, "A") is True,
   "a fonte desenha o A e o app acha que não")
for acentuada in "ÃÉÍÓÚÇÑ":
    ok(ficha_arte._conhece(ficha_arte.FONTE_NOME, acentuada) is False,
       f"o app acha que a fonte tem o {acentuada}, e ela não tem — o "
       f"quadradinho vai sair no nome")
ok(ficha_arte._conhece(ficha_arte.FONTE_LEGENDA, "Ê") is True,
   "a fonte da legenda TEM o Ê (ASSISTÊNCIAS precisa dele) e o app acha que "
   "não — ia decompor letra que já está desenhada")
ok("from fontTools" not in open(os.path.join(RAIZ, "ficha_arte.py"),
                                encoding="utf-8").read(),
   "o ficha_arte voltou a importar o fontTools, que não está no "
   "requirements.txt. No Railway ele não existe: a detecção cairia no 'não "
   "sei', e o quadradinho voltaria só no ar")

# O que não se decompõe em letra+marca tem tabela própria. Ø não é O com
# barra no Unicode: é um desenho só, e sem a tabela sairia quadradinho.
ok(ficha_arte._decompor("Ø", ficha_arte.FONTE_NOME) == [("O", [])],
   "o Ø parou de virar O — ele não se decompõe, e sem a tabela sai "
   "quadradinho no meio do nome")
ok([p[0] for p in ficha_arte._decompor("Æ", ficha_arte.FONTE_NOME)] == ["A", "E"],
   "o Æ parou de virar AE")

# O TRAVESSÃO É O CASO QUE MAIS DOERIA: é o que a arte escreve quando o número
# é "não sei", e a fonte tem hífen mas não tem travessão. Sem a tabela, a
# ficha de quem ainda não teve a partida lida sai com "?" no lugar do número.
ok(ficha_arte._decompor(ficha_arte._numero(None), ficha_arte.FONTE_NOME)
   == [("-", [])],
   "o travessão de 'não sei' virou outra coisa — se for '?', é o quadradinho "
   "disfarçado e vai publicado")


# ─────────────────────────────────────────────────────────────────────────
# 5. NADA DISSO PODE IR À REDE, e a arte aguenta peça faltando
# ─────────────────────────────────────────────────────────────────────────
mod = open(os.path.join(RAIZ, "ficha_arte.py"), encoding="utf-8").read()
for proibido in ("httpx", "requests", "urlopen", "http://", "https://"):
    ok(proibido not in mod,
       f"o ficha_arte.py passou a falar '{proibido}'. Ele monta e só: quem "
       f"busca é a rota, e é isso que deixa o teste rodar sem rede")

ok(_arte(foto=None, escudo=None, bandeira=None).size == (1080, 1350),
   "sem foto, sem escudo e sem bandeira a arte tem de sair assim mesmo — "
   "arte pela metade é melhor que erro na cara dele")
ok(_arte(foto=b"isto nao e uma imagem").size == (1080, 1350),
   "foto corrompida derrubou a montagem")


# ─────────────────────────────────────────────────────────────────────────
# 6. A ROTA E O BOTÃO
# ─────────────────────────────────────────────────────────────────────────
rota = FONTE[FONTE.index('@app.post("/api/jogador/arte")'):]
rota = rota[:rota.index("\ndef _nome_de_arquivo")]

ok("_ficha_do_jogador(" in rota,
   "a rota da arte parou de usar a MESMA ficha da tela — daí para números que "
   "a tela não mostra é um passo")
ok("_somar_partidas(partidas)" in rota,
   "a arte passou a ter a conta dela dos totais. Duas contas para o mesmo "
   "número é exatamente como elas divergem")
ok('p.get("competicao") == escolhida' in rota,
   "a arte parou de respeitar o filtro de competição da tela")
ok('foto_da_fonte(bruto, "spl")' in rota,
   "a foto da arte deixou de vir da SPL. A configuração de Ajustes é para a "
   "tela; a arte precisa do enquadramento igual para todos")

# ── A CAIXA DE AJUSTE ───────────────────────────────────────────────────────
#
# Ela entrou em 16/09/26: "quero que antes de baixar, apareça uma opção na tela
# pra alterações nos números se for necessário e na foto (...) e só depois
# dessa caixa flutuante, a gente poder baixar".
ok("onclick=\"abrirCaixaDaArte()\"" in FONTE,
   "o botão voltou a baixar direto, sem passar pela caixa de ajuste")

corpo = FONTE[FONTE.index("function corpoDaArte(previa){"):]
corpo = corpo[:corpo.index("\n}\n")]
ok("competicao: COMP_ESCOLHIDA" in corpo,
   "a caixa parou de mandar qual competição está filtrada")
for campo in ("jogos:", "gols:", "assistencias:"):
    ok(campo in corpo,
       f"a caixa parou de mandar '{campo}' — sem isso a correção à mão que ele "
       f"pediu não chega ao servidor")

# O SERVIDOR CONTINUA SENDO QUEM CALCULA O PADRÃO. A caixa corrige por cima;
# ela não substitui a conta. Se um dia o servidor passar a aceitar os números
# da tela como verdade, o filtro de competição deixa de valer e a arte pode
# sair com um número que a ficha não mostra.
ok("_somar_partidas(partidas)" in rota,
   "a arte passou a confiar nos números da tela em vez de calcular os dela")

# CAMPO VAZIO É "DEIXA COMO ESTÁ", E NÃO ZERO. Executado, não lido: recorto o
# laço que aplica os ajustes e rodo com os casos que importam.
_i2 = rota.index('    for campo in ("jogos", "gols", "assistencias"):')
_j2 = rota.index('    j = d["jogador"]')
_laco = rota[_i2:_j2]
for entrada, esperado, porque in (
        ({}, {"jogos": 7, "gols": 4, "assistencias": None}, "nada digitado"),
        ({"gols": ""}, {"jogos": 7, "gols": 4, "assistencias": None},
         "campo apagado não é zero"),
        ({"gols": "0"}, {"jogos": 7, "gols": 0, "assistencias": None},
         "zero digitado é zero"),
        ({"assistencias": "2"}, {"jogos": 7, "gols": 4, "assistencias": 2},
         "preencher o que estava vazio"),
        ({"jogos": "abc"}, {"jogos": 7, "gols": 4, "assistencias": None},
         "texto que não é número não pode derrubar nem zerar")):
    amb = {"totais": {"jogos": 7, "gols": 4, "assistencias": None},
           "corpo": entrada}
    exec("\n".join(l[4:] if l.startswith("    ") else l
                   for l in _laco.split("\n")), amb)
    ok(amb["totais"] == esperado,
       f"ajuste à mão errado ({porque}): com {entrada} saiu {amb['totais']}, "
       f"esperava {esperado}")

# A FOTO PODE VIR DE TRÊS LUGARES: a da SPL (padrão), um endereço colado ou um
# arquivo do computador. As duas últimas são o "adicionar aos que não tem ou
# substituir alguma" que ele pediu.
ok("_imagem_colada(corpo.get" in rota,
   "a caixa deixou de aceitar foto enviada do computador")
ok("_endereco_de_imagem_seguro(corpo.get" in rota,
   "a caixa deixou de aceitar endereço de foto colado")
ok("do_computador or baixados[0]" in rota,
   "a foto enviada do computador parou de ter prioridade sobre a da SPL — "
   "quem substitui tem de ganhar de quem é padrão")

_i3 = FONTE.index("def _endereco_de_imagem_seguro(url: str) -> str:")
_amb3 = {}
exec(FONTE[_i3:FONTE.index("\n\n\n", _i3)], _amb3)
_seguro = _amb3["_endereco_de_imagem_seguro"]
ok(_seguro("https://media-sdp.spl.com.sa/x.webp"),
   "endereço normal da SPL foi recusado")
for ruim in ("http://localhost:8000/x.png", "http://127.0.0.1/x.png",
             "http://169.254.169.254/latest/meta-data",
             "http://10.0.0.5/x.png", "http://192.168.1.1/x.png",
             "http://172.16.0.1/x.png", "file:///etc/passwd", "", "x.png"):
    ok(_seguro(ruim) == "",
       f"'{ruim}' passou pela peneira. Quem busca o endereço colado é o "
       f"servidor, de dentro do Railway — ele enxerga o que a internet não "
       f"enxerga")
ok(_seguro("http://172.32.0.1/x.png"),
   "172.32 não é rede privada (só 172.16 a 172.31) e foi recusado à toa")

_i4 = FONTE.index("def _imagem_colada(valor: str) -> bytes | None:")
_amb4 = {}
exec(FONTE[_i4:FONTE.index("\n\n\n", _i4)], _amb4)
_colada = _amb4["_imagem_colada"]
ok(_colada("data:image/png;base64,aGVsbG8=") == b"hello",
   "a imagem enviada do computador não foi decodificada")
for nao in ("", "hello", "data:text/html;base64,aGVsbG8=",
            "data:image/png;base64,!!!nao-e-base64!!!"):
    ok(_colada(nao) is None,
       f"'{nao[:30]}' foi aceito como imagem enviada do computador")

# A PRÉVIA NÃO PODE BAIXAR SOZINHA. Sem isso, cada tecla digitada na caixa
# derrubaria um arquivo na pasta de downloads dele.
ok('entrega = "inline" if corpo.get("previa") else "attachment"' in rota,
   "a prévia voltou a ser entregue como download")
previa = FONTE[FONTE.index("async function montarPreviaDaArte(){"):]
previa = previa[:previa.index("\n}\n")]
ok("previa: previa ? 1 : 0" in corpo,
   "a caixa parou de avisar ao servidor que aquilo é prévia")
ok("X-Pecas" in previa and "X-Pecas" in rota,
   "sumiu o aviso do que faltou na arte — sem ele, uma arte sem escudo parece "
   "escolha de design e ele só descobre depois de publicar")

# E O QUE BAIXA É O QUE ELE VIU. Montar de novo na hora do download abriria a
# porta para baixar uma imagem diferente da que estava na prévia.
baixa = FONTE[FONTE.index("async function baixarArte(botao){"):]
baixa = baixa[:baixa.index("\n}\n")]
ok("ARTE_BLOB" in baixa and "fetch(" not in baixa,
   "o download voltou a montar uma arte nova em vez de usar a da prévia")


# O JAVASCRIPT DA CAIXA TEM DE SER JAVASCRIPT VÁLIDO.
#
# Ele mora dentro de uma string de Python, que mora dentro de um arquivo de
# vinte mil linhas: uma chave a menos aqui derruba a página inteira, e o
# py_compile não tem como perceber. Guardado pelo `node` quando ele existe —
# ferramenta ausente não pode virar acusação contra o código, que é a regra
# que o teste de estrutura já segue.
import subprocess                                       # noqa: E402
import tempfile                                         # noqa: E402
try:
    _tem_node = subprocess.run(["node", "--version"],
                               capture_output=True).returncode == 0
except (FileNotFoundError, OSError):
    _tem_node = False
if _tem_node:
    _i5 = FONTE.index("// ── A CAIXA DE AJUSTE, ANTES DE BAIXAR ─")
    _j5 = FONTE.index("\nfunction dataBr(iso){", _i5)
    _js = os.path.join(tempfile.gettempdir(), "_conf_arte.js")
    try:
        with open(_js, "w", encoding="utf-8") as _f:
            _f.write("let FICHA_DADOS=null, COMP_ESCOLHIDA='';\n"
                     "function esc(x){return String(x);}\n"
                     "function somarPartidas(p){return {};}\n"
                     "function partidasVisiveis(d){return [];}\n"
                     + FONTE[_i5:_j5])
        _r = subprocess.run(["node", "--check", _js], capture_output=True,
                            text=True)
        ok(_r.returncode == 0,
           f"a caixa de ajuste não é JavaScript válido: {_r.stderr[:200]}")
    except (FileNotFoundError, OSError) as _e:
        print(f"  (não consegui rodar o node: {type(_e).__name__})")

# O nome do arquivo não pode levar acento por três sistemas.
#
# EXECUTADO, e não lido: recorto a função do main.py e rodo de verdade. O main
# inteiro não importa aqui (ele puxa o FastAPI), e conferir que a função existe
# não diz nada sobre o que ela devolve.
_i = FONTE.index("def _nome_de_arquivo(nome: str) -> str:")
_amb = {}
exec(FONTE[_i:FONTE.index("\n\n\n", _i)], _amb)
_arq = _amb["_nome_de_arquivo"]
ok(_arq("João Félix") == "joao-felix", f"nome de arquivo saiu '{_arq('João Félix')}'")
ok(_arq("") == "", "nome vazio tem de dar string vazia")
ok("/" not in _arq("Al-Hilal / Al Nassr"),
   "barra no nome do arquivo vira caminho de pasta")


# ─────────────────────────────────────────────────────────────────────────
# 7. OS MATERIAIS ESTÃO NO REPOSITÓRIO
# ─────────────────────────────────────────────────────────────────────────
for caminho, t in ((ficha_arte.FUNDO, "o fundo"),
                   (ficha_arte.SOBREPOSTO, "o degradê sobreposto"),
                   (os.path.join(ficha_arte.FONTES, ficha_arte.FONTE_NOME),
                    "a fonte Desenho Condensado"),
                   (os.path.join(ficha_arte.FONTES, ficha_arte.FONTE_LEGENDA),
                    "a fonte da legenda")):
    ok(os.path.exists(caminho), f"{t} não está no repositório ({caminho})")

for caminho in (ficha_arte.FUNDO, ficha_arte.SOBREPOSTO):
    ok(Image.open(caminho).size == (1080, 1350),
       f"{os.path.basename(caminho)} não tem 1080x1350")

# A FOTO DA SPL VEM EM WEBP. Descobri abrindo uma: o endereço termina em
# `_middle.webp`. Sem suporte a webp no Pillow, a arte sairia sem rosto e sem
# erro nenhum — a montagem engole foto que não abre, de propósito.
from PIL import features                                # noqa: E402
ok(features.check("webp"),
   "este Pillow não lê webp, e é nesse formato que a SPL entrega a foto")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ arte da ficha: bate com o exemplo, peça por peça")
