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
_css = re.search(r"transform-origin:\s*(\d+)%\s+(\d+)%", PAGINA)
ok(_css is not None,
   "sumiu o `transform-origin` do CSS do disco. Sem ele o `scale` amplia pelo "
   "centro, que num retrato de meio corpo é o peito")
if _css:
    ok(int(_css.group(1)) == round(escalacao_arte.FOTO_ANCORA_X * 100),
       f"a âncora horizontal do CSS ({_css.group(1)}%) não bate com a do "
       f"Python ({escalacao_arte.FOTO_ANCORA_X:.2f})")
    ok(int(_css.group(2)) == round(escalacao_arte.FOTO_ANCORA_Y * 100),
       f"a âncora vertical do CSS ({_css.group(2)}%) não bate com a do Python "
       f"({escalacao_arte.FOTO_ANCORA_Y:.2f}). A tela e o PNG passam a "
       f"enquadrar em alturas diferentes, e a prévia vira mentira")

ok("transform:scale(var(--zoom-foto,1))" in PAGINA.replace(" ", ""),
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
    dx, dy, lz = escalacao_arte.janela_do_zoom(200.0, z)
    ex, tam_x = _janela_como_o_navegador(200.0, z, escalacao_arte.FOTO_ANCORA_X)
    ey, tam_y = _janela_como_o_navegador(200.0, z, escalacao_arte.FOTO_ANCORA_Y)
    ok(abs(dx - ex) < 0.01 and abs(dy - ey) < 0.01 and abs(lz - tam_x) < 0.01,
       f"em {int(z*100)}% o recorte do PNG é ({dx:.1f},{dy:.1f},{lz:.1f}) e o "
       f"do navegador seria ({ex:.1f},{ey:.1f},{tam_x:.1f}). O Vini montaria a "
       f"escalação vendo um enquadramento e publicaria outro")
    ok(abs(tam_x - tam_y) < 0.01, "a janela saiu retangular; o disco é redondo")

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
    def _arte(z):
        return escalacao_arte.montar({
            "zoom": z,
            "jogadores": [{"nome": "TESTE", "x": 50, "y": 50,
                           "foto": dados, "bandeira": None}]})

    ok(_arte(1.7) != _arte(1.0),
       "o PNG do campinho saiu idêntico com e sem zoom. O `montar` está "
       "ignorando o número que a rota manda, e o Vini publicaria a escalação "
       "com um enquadramento diferente do que viu na tela")
    ok(_arte(1.0) == escalacao_arte.montar({
        "jogadores": [{"nome": "TESTE", "x": 50, "y": 50,
                       "foto": dados, "bandeira": None}]}),
       "sem `zoom` no pedido a arte saiu diferente de zoom 1.0. O padrão tem "
       "de ser o enquadramento antigo, para quem chamar sem saber do ajuste")
except ImportError:
    print("  (Pillow ausente — não conferi o recorte na imagem)")


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
ok(A is not None, "sumiu o ajuste do zoom do campinho")
if A:
    ok(A["min"] <= 100 <= A["max"] and A["padrao"] >= 100,
       "a faixa do ajuste não inclui 100%, que é como se volta ao "
       "enquadramento antigo sem mexer no código")
    ok(A["grupo"] in [g for s in ajustes.secoes() for g in s["grupos"]],
       f"o grupo '{A['grupo']}' não aparece em nenhuma seção de Configurações")

ok("def _zoom_do_campinho()" in FONTE, "sumiu a leitura única do ajuste")
ok(FONTE.count("_zoom_do_campinho()") == 3,
   f"o `_zoom_do_campinho` é chamado {FONTE.count('_zoom_do_campinho()')} "
   f"vezes; esperava três (a definição, a página e a arte). Se um dos dois "
   f"consumidores parou de usá-lo, a tela e o PNG divergem")
ok('.replace("__ZOOM_FOTO__", f"{_zoom_do_campinho():.3f}")' in FONTE,
   "a página do campinho parou de receber o zoom do servidor")
ok('"zoom": _zoom_do_campinho()' in FONTE,
   "a rota da arte parou de mandar o zoom; o PNG sairia sempre sem ele")
ok("__ZOOM_FOTO__" in PAGINA,
   "o marcador __ZOOM_FOTO__ sumiu da página; o servidor escreveria no vazio")

# E A LEITURA, EXECUTADA. Banco fora do ar não pode derrubar o campinho.
_i = FONTE.index("def _zoom_do_campinho()")
_corpo = FONTE[_i:FONTE.index("\n@app.get", _i)]
import database                                           # noqa: E402
_guardado = database.valor_de_ajuste

try:
    _amb: dict = {}
    exec(_corpo, _amb)
    ler = _amb["_zoom_do_campinho"]

    database.valor_de_ajuste = lambda c: 145
    ok(abs(ler() - 1.45) < 1e-9,
       f"145 no ajuste virou {ler()} no CSS; esperava 1.45 (o CSS quer fator, "
       f"a tela mostra por cento)")
    database.valor_de_ajuste = lambda c: 100
    ok(ler() == 1.0, "100% não devolveu 1.0")
    database.valor_de_ajuste = lambda c: 40
    ok(ler() == 1.0, "um valor abaixo de 100 virou redução da foto")

    def _explode(c):
        raise RuntimeError("banco fora do ar")
    database.valor_de_ajuste = _explode
    ok(ler() == 1.0,
       "com o banco fora do ar a leitura do zoom levantou ou devolveu outra "
       "coisa. Sem ajuste o campinho tem de continuar de pé, sem zoom")
finally:
    database.valor_de_ajuste = _guardado


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ zoom no rosto só dentro do campo, e a tela enquadra igual ao PNG")
