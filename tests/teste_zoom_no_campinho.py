"""O zoom no rosto dentro do campinho — e só dentro dele.

O PEDIDO (18/09/26)
    "A gente consegue nesta guia, dar um zoom na foto do jogador quando for pro
     campinho, pra aparecer o rosto? (...) É algo que quero apenas pra dentro
     do campinho, quando se arrastar a foto pra lá."

    A foto da liga é de meio corpo. Num disco de 86px o rosto saía do tamanho
    de uma ervilha, com metade do círculo ocupada por ombro e camisa. Na lista
    ao lado, onde a foto é um marcador de 26px ao lado do nome, isso não
    incomoda — e por isso o pedido é só do campo.

O QUE ESTE ARQUIVO VIGIA, em ordem de importância
    1. QUE A TELA E O PNG MOSTREM A MESMA COISA. O navegador faz o zoom com
       `transform: scale()`; o PNG é recortado pelo Pillow. São dois programas
       diferentes chegando ao mesmo enquadramento, e se um mudar sem o outro o
       Vini monta a escalação vendo uma coisa e publica outra. Foi o defeito
       que este projeto passou a semana consertando em três telas.
    2. Que a lista de jogadores NÃO foi afetada — era metade do pedido.
    3. Que zoom 100% devolve exatamente o enquadramento antigo, sem degrau.
    4. Que um banco fora do ar não tira a foto do campinho.
"""
import os
import re
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

import ajustes                                            # noqa: E402
import escalacao_arte                                     # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
PAGINA = open(os.path.join(RAIZ, "public", "campinho.html"),
              encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# 1. A TELA E O PNG TÊM DE CONCORDAR
# ─────────────────────────────────────────────────────────────────────────
# O NÚMERO DA ÂNCORA SAI DA PÁGINA, e é comparado com o do Python. São as duas
# pontas da mesma decisão escritas em dois arquivos e em duas linguagens; sem
# esta conferência, mexer numa e esquecer a outra é questão de tempo, e o
# sintoma seria uma arte publicada com o enquadramento diferente da prévia.
_css = re.search(r"transform-origin:\s*(\d+)%\s+var\(--ancora-foto,\s*(\d+)%\)",
                 PAGINA)
ok(_css is not None,
   "sumiu o `transform-origin` do CSS do disco, ou ele voltou a ter a âncora "
   "escrita à mão. Ela é ajuste do Vini agora, e quem manda o número é a mesma "
   "função que manda para o PNG — chumbar aqui reabre a divergência")
if _css:
    ok(int(_css.group(1)) == round(escalacao_arte.FOTO_ANCORA_X * 100),
       f"a âncora horizontal do CSS ({_css.group(1)}%) não bate com a do "
       f"Python ({escalacao_arte.FOTO_ANCORA_X:.2f})")
    # O NÚMERO DO `var(..., X)` É SÓ A REDE DE SEGURANÇA, para o caso de o
    # servidor não escrever nada. Mesmo ele tem de ser o padrão do Python: se
    # divergir, a página sem o marcador trocado enquadra de um jeito e o PNG de
    # outro — o pior caso, porque é o caso em que ninguém está olhando.
    ok(int(_css.group(2)) == round(escalacao_arte.FOTO_ANCORA_Y * 100),
       f"o padrão de emergência do CSS ({_css.group(2)}%) não bate com o do "
       f"Python ({escalacao_arte.FOTO_ANCORA_Y:.2f})")

ok("transform:scale(var(--zoom-foto,1))" in PAGINA.replace(" ", "")
   .replace("\n", ""),
   "o disco parou de aplicar o zoom, ou parou de ter um padrão seguro no "
   "`var(...,1)` para o caso de o servidor não escrever o número")

# ── A CONTA, EXECUTADA E CONFERIDA CONTRA A DO NAVEGADOR ─────────────────
#
# `transform: scale(Z)` com origem em (ax, ay) leva o ponto p para
# a + Z(p − a). A janela visível é o p que ainda cai dentro de [0, l]:
#
#     p ∈ [a − a/Z,  a + (l − a)/Z]        → tamanho l/Z, canto a(1 − 1/Z)
#
# Aqui eu refaço essa conta do zero, a partir da definição do transform, e
# comparo com o que a função devolve. Se eu tivesse copiado a fórmula da
# própria função, estaria conferindo ela contra ela mesma.
def _janela_como_o_navegador(lado, zoom, ancora):
    def volta(destino):
        # onde estava, antes do transform, o pixel que foi parar em `destino`
        a = ancora * lado
        return a + (destino - a) / zoom
    return volta(0.0), volta(lado) - volta(0.0)

for z in (1.0, 1.2, 1.45, 1.7, 2.0, 3.0):
    for a in (0.0, 0.10, 0.25, 0.50):
        dx, dy, lz = escalacao_arte.janela_do_zoom(200.0, z, a)
        ex, tam_x = _janela_como_o_navegador(
            200.0, z, escalacao_arte.FOTO_ANCORA_X)
        ey, tam_y = _janela_como_o_navegador(200.0, z, a)
        ok(abs(dx - ex) < 0.01 and abs(dy - ey) < 0.01
           and abs(lz - tam_x) < 0.01,
           f"em {int(z*100)}% com âncora {a} o recorte do PNG é "
           f"({dx:.1f},{dy:.1f},{lz:.1f}) e o do navegador seria "
           f"({ex:.1f},{ey:.1f},{tam_x:.1f}). O Vini montaria a escalação "
           f"vendo um enquadramento e publicaria outro")
        ok(abs(tam_x - tam_y) < 0.01,
           "a janela saiu retangular; o disco é redondo")

# ── DESCER A FOTO É SUBIR A JANELA, E EM 0 ELA NÃO SAI DO TOPO ───────────
#
# É o pedido dele por extenso: "que haja um ajuste da foto mais pra baixo, sem
# cortar o topo da cabeça".
_, dy_alto, _ = escalacao_arte.janela_do_zoom(200.0, 2.0, 0.40)
_, dy_baixo, _ = escalacao_arte.janela_do_zoom(200.0, 2.0, 0.05)
ok(dy_baixo < dy_alto,
   "baixar a âncora deixou de subir a janela na foto — é assim que a foto "
   "desce no disco, e era metade do pedido")

for z in (1.2, 2.0, 3.0, 10.0):
    _, dy0, _ = escalacao_arte.janela_do_zoom(200.0, z, 0.0)
    ok(dy0 == 0.0,
       f"com a âncora no fim da faixa e zoom {int(z*100)}% a janela começou em "
       f"{dy0}, e não no topo da foto. Nesse ponto o alto da cabeça tem de "
       f"estar garantido em QUALQUER zoom — é o que torna o ajuste útil")

# E FORA DA FAIXA NÃO PODE PASSAR, nem por uma chamada de dentro do código:
# acima de 0,5 o zoom mira o peito; abaixo de 0 entra fundo vazio por cima da
# cabeça, e um buraco transparente no disco é pior que um corte.
for fora, esperado in ((-0.5, 0.0), (0.9, 0.5), (2, 0.5)):
    _, dy, _ = escalacao_arte.janela_do_zoom(200.0, 2.0, fora)
    _, dy_ok, _ = escalacao_arte.janela_do_zoom(200.0, 2.0, esperado)
    ok(abs(dy - dy_ok) < 1e-9,
       f"âncora {fora} não foi presa na faixa; saiu {dy} em vez de {dy_ok}")

# ── ZOOM 100% É O DE ANTES, EXATAMENTE ───────────────────────────────────
dx, dy, lz = escalacao_arte.janela_do_zoom(200.0, 1.0)
ok((dx, dy, lz) == (0.0, 0.0, 200.0),
   f"em 100% o recorte virou {(dx, dy, lz)} em vez da foto inteira. O ajuste "
   f"precisa ter um valor que devolve o comportamento antigo, ou não há como "
   f"voltar atrás sem mexer no código")

# E VALOR ABSURDO NÃO PODE QUEBRAR A ARTE: menos de 1 não faz sentido (seria
# afastar), e a foto não pode sumir.
for ruim in (0, 0.5, -3, None):
    _, _, lz = escalacao_arte.janela_do_zoom(200.0, ruim)
    ok(lz == 200.0,
       f"zoom {ruim!r} devolveu uma janela de {lz}. Abaixo de 1 não é zoom, é "
       f"encolher a foto dentro do disco, e ninguém pediu isso")


# ─────────────────────────────────────────────────────────────────────────
# 2. O RECORTE, NA IMAGEM DE VERDADE
# ─────────────────────────────────────────────────────────────────────────
# Conferir a fórmula não prova que a foto foi recortada. Aqui eu monto um
# disco com uma imagem em que cada faixa tem uma cor, e leio a cor que saiu no
# meio dele: em 100% é a faixa do centro, e com zoom é uma faixa de cima.
try:
    import io

    from PIL import Image
    fita = Image.new("RGB", (100, 100))
    for y in range(100):
        fita.putpixel((50, y), (0, 0, 0))
    for y in range(100):
        for x in range(100):
            fita.putpixel((x, y), (min(255, y * 2), 30, 30))
    buf = io.BytesIO()
    fita.save(buf, "PNG")
    dados = buf.getvalue()

    meio_sem = escalacao_arte._circulo(dados, 80, 1.0).convert("RGB") \
        .getpixel((40, 40))[0]
    meio_com = escalacao_arte._circulo(dados, 80, 1.7).convert("RGB") \
        .getpixel((40, 40))[0]
    ok(meio_com < meio_sem - 10,
       f"com zoom o centro do disco continuou mostrando a mesma altura da foto "
       f"({meio_com} contra {meio_sem}). A conta pode estar certa e o recorte "
       f"não estar sendo aplicado")

    # E A ARTE INTEIRA, e não só o `_circulo` solto.
    #
    # ESTE AQUI EU PLANTEI E ESCAPOU: com `zoom = 1.0` fixo dentro do `montar`,
    # o número que a rota manda era simplesmente jogado fora e o PNG saía sem
    # zoom nenhum — com todo o resto do teste passando, porque eu só chamava o
    # `_circulo` direto. O caminho que o Vini usa é o `montar`, e é ele que
    # precisa ser exercido.
    def _arte(z, ancora=None):
        pedido = {"zoom": z,
                  "jogadores": [{"nome": "TESTE", "x": 50, "y": 50,
                                 "foto": dados, "bandeira": None}]}
        if ancora is not None:
            pedido["ancora"] = ancora
        return escalacao_arte.montar(pedido)

    ok(_arte(1.7) != _arte(1.0),
       "o PNG do campinho saiu idêntico com e sem zoom. O `montar` está "
       "ignorando o número que a rota manda, e o Vini publicaria a escalação "
       "com um enquadramento diferente do que viu na tela")
    ok(_arte(2.0, 0.0) != _arte(2.0, 0.5),
       "o PNG saiu idêntico com a foto no topo e no meio. O `montar` está "
       "ignorando a âncora — o ajuste de descer a foto valeria só na tela, e "
       "a imagem publicada sairia com a cabeça cortada")
    ok(_arte(1.0) == escalacao_arte.montar({
        "jogadores": [{"nome": "TESTE", "x": 50, "y": 50,
                       "foto": dados, "bandeira": None}]}),
       "sem `zoom` no pedido a arte saiu diferente de zoom 1.0. O padrão tem "
       "de ser o enquadramento antigo, para quem chamar sem saber do ajuste")
except ImportError:
    print("  (Pillow ausente — não conferi o recorte na imagem)")


# ─────────────────────────────────────────────────────────────────────────
# 2b. O QUE FICA ATRÁS DA FOTO — A TRANSPARÊNCIA
# ─────────────────────────────────────────────────────────────────────────
# O QUE ELE VIU (18/09/26)
#     "Quando clicamos em baixar, ela vem diferente do que tem no campinho.
#      (...) Se é um problema com a transparência, o fundo poderia ser esse
#      verde padrão que estamos usando no campinho."
#
#     Era: o `convert("RGB")` do Pillow DESCARTA o canal alfa em vez de
#     compor, e fica com o RGB que estava embaixo — preto, num recorte da SPL.
#     Na tela nunca apareceu porque lá quem compõe é o navegador.
_css_fundo = re.search(r"\.slot\.ocupado \.disco\{[^}]*background:\s*#([0-9a-fA-F]{6})",
                       PAGINA)
ok(_css_fundo is not None, "sumiu o fundo do disco ocupado no CSS")
if _css_fundo:
    _hex = tuple(int(_css_fundo.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    ok(_hex == tuple(escalacao_arte.FOTO_VAZIA),
       f"o fundo do disco na tela é {_css_fundo.group(1)} e no PNG é "
       f"{escalacao_arte.FOTO_VAZIA}. São a mesma coisa vista em dois lugares; "
       f"divergir aqui é o tipo de erro que ninguém enxerga, porque ninguém "
       f"compara hexadecimal de cabeça")

try:
    import io as _io

    from PIL import Image as _Img
    # Uma foto TODA transparente: o disco inteiro tem de sair da cor do fundo.
    # Com o defeito antigo ele saía preto, que é o RGB que sobra quando o alfa
    # é descartado em vez de composto.
    _vazia = _Img.new("RGBA", (100, 100), (0, 0, 0, 0))
    _b = _io.BytesIO()
    _vazia.save(_b, "PNG")
    _disco = escalacao_arte._circulo(_b.getvalue(), 80).convert("RGB")
    _meio = _disco.getpixel((40, 40))
    ok(_meio == tuple(escalacao_arte.FOTO_VAZIA),
       f"o miolo do disco com uma foto transparente saiu {_meio}, e não "
       f"{tuple(escalacao_arte.FOTO_VAZIA)}. Se saiu preto, o alfa voltou a "
       f"ser descartado em vez de composto — é o quarto de círculo escuro que "
       f"ele viu em cima da cabeça no arquivo baixado")

    # E O QUE É OPACO NÃO PODE SER TINGIDO: compor não é pintar por cima.
    _cheia = _Img.new("RGBA", (100, 100), (200, 30, 40, 255))
    _b2 = _io.BytesIO()
    _cheia.save(_b2, "PNG")
    _meio2 = escalacao_arte._circulo(_b2.getvalue(), 80).convert("RGB") \
        .getpixel((40, 40))
    ok(abs(_meio2[0] - 200) < 6 and abs(_meio2[1] - 30) < 6,
       f"uma foto opaca saiu {_meio2} em vez da cor dela. A composição está "
       f"misturando o fundo onde não devia")
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────
# 3. SÓ DENTRO DO CAMPO — ERA METADE DO PEDIDO
# ─────────────────────────────────────────────────────────────────────────
for seletor in (".jog img", ".cartao img"):
    i = PAGINA.index(seletor + "{")
    regra = PAGINA[i:PAGINA.index("}", i)]
    ok("transform" not in regra and "zoom-foto" not in regra,
       f"a regra `{seletor}` ganhou o zoom. Ele é para o disco dentro do "
       f"campo; na lista, ao lado do nome, o Vini quer a foto inteira")

_i = PAGINA.index(".slot .disco img.foto{")
_disco = PAGINA[_i:PAGINA.index("}", _i)]
ok("--zoom-foto" in _disco, "o disco do campo perdeu o zoom")

# E O QUE SEGURA A FOTO DENTRO DO ANEL. Sem isto a foto ampliada transborda o
# círculo e invade a grama — o mesmo "vazamento" que a arte já teve uma vez.
ok(re.search(r"\.slot \.disco\{[^}]*overflow:\s*hidden", PAGINA)
   or re.search(r"\.slot \.disco\{overflow:hidden\}", PAGINA),
   "o disco ficou sem `overflow:hidden`. A foto ampliada passa a transbordar "
   "o anel e a aparecer por cima da grama")

# A PLACA DO NOME NÃO PODE SER RECORTADA JUNTO. Ela mora no `.slot`, irmã do
# disco, e é por isso que o `overflow:hidden` não a atinge — mas se um dia ela
# virar filha do disco, some sem avisar.
_render = PAGINA[PAGINA.index("function renderCampo()"):]
_render = _render[:_render.index("\nfunction ")]
ok("el.innerHTML = disco + rot" in _render,
   "a placa do nome deixou de ser irmã do disco. Dentro dele, o "
   "`overflow:hidden` a cortaria — e um campinho sem nome nenhum é bem pior "
   "que um campinho sem zoom")


# ─────────────────────────────────────────────────────────────────────────
# 4. UM LUGAR SÓ LÊ O AJUSTE, E OS DOIS CONSUMIDORES USAM ELE
# ─────────────────────────────────────────────────────────────────────────
A = ajustes.POR_CHAVE.get("campinho_zoom_foto")
D = ajustes.POR_CHAVE.get("campinho_descer_foto")
ok(A is not None, "sumiu o ajuste do zoom do campinho")
ok(D is not None,
   "sumiu o ajuste de descer a foto. Sem ele, ampliar mais corta o alto da "
   "cabeça e não há o que fazer a não ser desistir do zoom")
if A:
    ok(A["min"] <= 100 <= A["max"] and A["padrao"] >= 100,
       "a faixa do ajuste não inclui 100%, que é como se volta ao "
       "enquadramento antigo sem mexer no código")
    ok(A["max"] >= 300,
       f"o teto do zoom voltou para {A['max']}%. Ele pediu que pudesse ser "
       f"maior, e agora dá — porque descer a foto segura a cabeça")
    ok(A["grupo"] in [g for s in ajustes.secoes() for g in s["grupos"]],
       f"o grupo '{A['grupo']}' não aparece em nenhuma seção de Configurações")
if D:
    ok(D["min"] == 0 and D["max"] == 100,
       f"a faixa de descer a foto virou {D['min']}–{D['max']}. Ela precisa "
       f"chegar aos 100, que é o ponto em que o topo da cabeça fica garantido")
    ok(D["grupo"] == (A or {}).get("grupo"),
       "os dois ajustes ficaram em grupos diferentes. Eles são um par: quem "
       "aumenta o zoom vai precisar do outro na linha de baixo")

ok("def _enquadramento_do_campinho()" in FONTE,
   "sumiu a leitura única dos ajustes")
# QUANTOS CONSUMIDORES, e não um número exato.
#
# Eu tinha fixado "três": a definição, a página e a arte da escalação. Aí
# nasceu a arte dos desfalques, que desenha o mesmo disco e leu daqui — o
# certo — e o teste acusou um defeito que era, na verdade, um consumidor novo
# fazendo a coisa certa. Número mágico envelhece; a regra é que TODO mundo que
# desenha o disco pergunte aqui, e ninguém invente o próprio enquadramento.
_usos = FONTE.count("_enquadramento_do_campinho()")
ok(_usos >= 3,
   f"o `_enquadramento_do_campinho` é chamado {_usos} vezes; esperava ao "
   f"menos três (a definição, a página e a arte). Se um consumidor parou de "
   f"usá-lo, a tela e o PNG divergem")
# E NINGUÉM PODE LER O AJUSTE POR FORA. É assim que a segunda cópia nasce.
_fora = [l for l in FONTE.split("\n")
         if "campinho_zoom_foto" in l or "campinho_descer_foto" in l]
_fora = [l for l in _fora if "_db.valor_de_ajuste" in l]
ok(len(_fora) <= 2,
   f"alguém passou a ler os ajustes do campinho fora do "
   f"`_enquadramento_do_campinho`: {_fora}. Duas leituras é como a prévia e o "
   f"arquivo começam a discordar")
for marcador in ("__ZOOM_FOTO__", "__ANCORA_FOTO__"):
    ok(f'.replace("{marcador}"' in FONTE,
       f"a página do campinho parou de receber o {marcador} do servidor")
    ok(marcador in PAGINA,
       f"o marcador {marcador} sumiu da página; o servidor escreveria no vazio")
ok('"zoom": _zoom, "ancora": _ancora' in FONTE,
   "a rota da arte parou de mandar o enquadramento; o PNG sairia sempre com o "
   "de fábrica, diferente do que está na tela")

# E A LEITURA, EXECUTADA. Banco fora do ar não pode derrubar o campinho.
_i = FONTE.index("def _enquadramento_do_campinho()")
_corpo = FONTE[_i:FONTE.index("\n@app.get", _i)]
import database                                           # noqa: E402
_guardado = database.valor_de_ajuste

try:
    _amb: dict = {}
    exec(_corpo, _amb)
    ler = _amb["_enquadramento_do_campinho"]

    def _ajustes(zoom, descer):
        database.valor_de_ajuste = lambda c: (
            zoom if c == "campinho_zoom_foto" else descer)

    _ajustes(170, 80)
    z, a = ler()
    ok(abs(z - 1.70) < 1e-9,
       f"170 no ajuste virou {z}; esperava 1.70 (o CSS quer fator, a tela "
       f"mostra por cento)")
    ok(abs(a - 0.10) < 1e-9,
       f"'descer 80%' virou âncora {a}; esperava 0.10. A conversão é o que "
       f"deixa a tela falar 'descer a foto' e o desenho falar 'onde mirar'")

    _ajustes(100, 0)
    z, a = ler()
    ok(z == 1.0 and abs(a - 0.50) < 1e-9,
       f"o começo das duas faixas deu ({z}, {a}); esperava (1.0, 0.50), que é "
       f"o enquadramento de antes do zoom existir")

    _ajustes(300, 100)
    z, a = ler()
    ok(abs(z - 3.0) < 1e-9 and a == 0.0,
       f"o fim das duas faixas deu ({z}, {a}); esperava (3.0, 0.0), que é o "
       f"zoom máximo com o topo da cabeça garantido")

    _ajustes(40, 250)
    z, a = ler()
    ok(z == 1.0 and 0.0 <= a <= 0.5,
       f"valores fora da faixa passaram: ({z}, {a})")

    def _explode(c):
        raise RuntimeError("banco fora do ar")
    database.valor_de_ajuste = _explode
    z, a = ler()
    ok(z == 1.0 and 0.0 <= a <= 0.5,
       f"com o banco fora do ar a leitura levantou ou devolveu {(z, a)}. Sem "
       f"ajuste o campinho tem de continuar de pé, sem zoom")
finally:
    database.valor_de_ajuste = _guardado


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ zoom no rosto só dentro do campo, e a tela enquadra igual ao PNG")
