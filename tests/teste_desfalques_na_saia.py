"""Os desfalques na saia da arte, tirados das guias DELE.

AS TRÊS CORREÇÕES (18/09/26)
    A primeira versão disto era uma arte separada, alimentada pelo
    Transfermarkt e pela API-Football, e saiu sem foto nenhuma. Ele apontou os
    três erros de uma vez:

        "Por que você usou transfermkt e api-football? Criamos duas guias:
         Pendurados e Suspensos e Lesões. Temos a informação lá, nossa, viva,
         atualizada. Era pra usar isso. Temos o glossário também, e
         principalmente, pra fazer estes links. Conserte.
         2 - As fotos não apareceram.
         3 - Eu quero isso na 'saia' da imagem do campinho."

    Os três têm a mesma origem: eu fui à fonte crua em vez de usar a camada
    que ele construiu em cima dela. As guias não são cópia das fontes — a de
    lesões cruza notícia com elenco e ele corrige à mão; a de pendurados
    aplica a regra dos quatro amarelos, que fonte nenhuma calcula. E as
    nossas tabelas não guardam foto: quem tem foto é o glossário, que é
    justamente "pra fazer estes links". Por isso os discos saíram vazios.

O QUE ESTE ARQUIVO VIGIA
    1. Que a lista sai das NOSSAS guias, e que a identidade e a foto passam
       pelo glossário.
    2. Que a saia cabe onde cabe — ela é desenhada num vão de 265px medido a
       régua no template, e nada pode invadir o campo nem sair da imagem.
    3. Que lista vazia não vira "elenco completo" sem que as guias tenham
       respondido.
    4. Que a arte continua saindo quando não há desfalque nenhum: a saia é um
       acréscimo, e não uma condição para o campinho existir.
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

import escalacao_arte as A                                # noqa: E402
import formacoes                                          # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
PAGINA = open(os.path.join(RAIZ, "public", "campinho.html"),
              encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def _foto():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (150, 200), (120, 90, 60)).save(b, "PNG")
    return b.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# 1. AS FONTES SÃO AS GUIAS DELE, E O GLOSSÁRIO FAZ O ELO
# ─────────────────────────────────────────────────────────────────────────
_junta = FONTE[FONTE.index("async def _desfalques_do_clube("):]
_junta = _junta[:_junta.index("\n@app.")]
_codigo = "\n".join(l for l in _junta.split("\n")
                    if not l.strip().startswith("#"))

ok("get_injuries" in _codigo,
   "a busca parou de usar a NOSSA guia de Lesões. Ela não é um espelho do "
   "Transfermarkt: cruza notícia com elenco e ele corrige à mão")
ok("api_pendurados" in _codigo,
   "a busca parou de usar a NOSSA guia de Pendurados. Ela aplica a regra dos "
   "quatro amarelos da liga, que fonte externa nenhuma calcula")
for crua in ("_lesoes_do_tm", "api_ausencias_af"):
    ok(crua not in _codigo,
       f"a busca voltou a chamar '{crua}' direto. Ir à fonte crua passando "
       f"por cima da guia dele foi o erro que ele mandou consertar")
ok("glossario.identidade" in _codigo and "glossario.ficha" in _codigo,
   "a busca parou de passar pelo glossário. É ele que diz QUEM é cada nome e "
   "de onde vem a foto — e foi por não usá-lo que a arte saiu sem foto")

# ── A JUNÇÃO, EXECUTADA ──────────────────────────────────────────────────
import asyncio as _asyncio                                # noqa: E402
import re as _re                                          # noqa: E402
import unicodedata as _ud                                 # noqa: E402

_ichave = FONTE.index("def _chave_de_nome(")
_amb: dict = {"unicodedata": _ud, "re": _re, "asyncio": _asyncio,
              "print": lambda *a, **k: None}
exec(FONTE[_ichave:FONTE.index("\ndef ", _ichave + 10)], _amb)

LESOES = [
    {"player_name": "Salem Al-Dawsari", "club": "Al Hilal",
     "injury_type": "Lesão", "body_part": "de tendão",
     "expected_return": "Voltou ao treinamento", "status": "em_recuperacao"},
    {"player_name": "De Outro Clube", "club": "Al Nassr",
     "injury_type": "Lesão", "body_part": "", "expected_return": ""},
]
PENDURADOS = {"suspensos": [
    {"jogador": "Ahmed Sharahili", "clube": "Al Hilal", "amarelos": 4,
     "vermelhos": 0, "volta_em": "2026-09-24"},
    # O MESMO Al-Dawsari, agora suspenso. Quem está nas duas entra uma vez.
    {"jogador": "Salem Al Dawsari", "clube": "Al Hilal", "amarelos": 4,
     "vermelhos": 0, "volta_em": ""},
]}

# O GLOSSÁRIO DE MENTIRA vai no MÓDULO, e não injetado no ambiente do exec: a
# função tem de achá-lo sozinha, como vai fazer no servidor. Foi injetando o
# `_db` que eu deixei passar um NameError para o ar ontem.
import glossario as _glossario                            # noqa: E402

_glossario.identidade = lambda nome, clube="": (
    {"id": 1} if "dawsari" in nome.lower() or "sharahili" in nome.lower()
    else {})
_glossario.ficha = lambda g: {"nome": "Salem Al-Dawsari",
                              "foto": "https://spl/foto.png"}


async def _pend_falso():
    return PENDURADOS


_amb["get_injuries"] = lambda incluir=False: LESOES
_amb["api_pendurados"] = _pend_falso
exec(_junta, _amb)
_r = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
_nomes = [x["nome"] for x in _r["desfalques"]]

ok(len(_nomes) == 2,
   f"a junção devolveu {len(_nomes)} linhas ({_nomes}) e esperava 2 — o "
   f"Al-Dawsari está nas duas guias, com grafias diferentes, e tem de entrar "
   f"uma vez só")
ok(all("Outro Clube" not in n for n in _nomes),
   "entrou desfalque de outro clube na saia")
ok(any(x["tipo"] == "suspensao" for x in _r["desfalques"]),
   "o suspenso não foi marcado; na saia ele viraria mais um lesionado")
_s = [x for x in _r["desfalques"] if x["tipo"] == "suspensao"][0]
ok(_s["motivo"] == "4º amarelo",
   f"o motivo do suspenso saiu {_s['motivo']!r}. A guia CONTA os cartões, e "
   f"'4º amarelo' é a frase que ele narra — 'suspenso' joga essa conta fora")
ok(all(x["foto_url"] for x in _r["desfalques"]),
   f"algum desfalque saiu sem endereço de foto: {_r['desfalques']}. Foi assim "
   f"que a primeira versão foi para a tela com todos os discos vazios")
ok("Lesões" in _r["fontes"] and "Pendurados" in _r["fontes"],
   f"as guias que responderam não foram registradas: {_r['fontes']!r}")

# ── UMA GUIA FORA NÃO DERRUBA A OUTRA, E NÃO É CREDITADA ────────────────
def _explode(incluir=False):
    raise RuntimeError("banco fora do ar")


exec(_junta, _amb)
_amb["get_injuries"] = _explode
_amb["api_pendurados"] = _pend_falso
_r2 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(len(_r2["desfalques"]) == 2,
   f"com a guia de Lesões fora a lista veio com {len(_r2['desfalques'])}; a "
   f"de Pendurados ainda respondia")
ok("Lesões" not in _r2["fontes"],
   f"a guia de Lesões foi creditada mesmo fora do ar ({_r2['fontes']!r}). É "
   f"essa lista que sustenta a frase 'o elenco está completo'")

exec(_junta, _amb)
_amb["get_injuries"] = _explode


async def _pend_explode():
    raise RuntimeError("fora")


_amb["api_pendurados"] = _pend_explode
_r3 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(_r3["desfalques"] == [] and _r3["fontes"] == "",
   f"com as duas guias fora a junção devolveu {_r3!r}: tem de sair vazia E "
   f"sem fonte, que é o par que distingue 'ninguém fora' de 'não consegui "
   f"olhar'")

# ── E GUIA QUE RESPONDEU "NINGUÉM" É GUIA QUE RESPONDEU ─────────────────
exec(_junta, _amb)
_amb["get_injuries"] = lambda incluir=False: []
_amb["api_pendurados"] = lambda: _vazio()


async def _vazio():
    return {"suspensos": []}


_amb["api_pendurados"] = _vazio
_r4 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(_r4["desfalques"] == [] and "Lesões" in _r4["fontes"]
   and "Pendurados" in _r4["fontes"],
   f"as duas guias responderam 'ninguém está fora' e não foram creditadas "
   f"({_r4!r}). A tela diria 'não consegui consultar' num dia em que "
   f"consultou — e ele iria procurar um defeito que não existe")


# ─────────────────────────────────────────────────────────────────────────
# 2. A SAIA CABE ONDE CABE
# ─────────────────────────────────────────────────────────────────────────
from PIL import Image                                     # noqa: E402

GENTE = [{"nome": n, "motivo": m, "retorno": r, "tipo": t, "foto": _foto()}
         for n, m, r, t in [
             ("Ahmed Sharahili", "4º amarelo", "Volta dia 24", "suspensao"),
             ("Theo Hernández", "Lesão muscular", "Fim de setembro", "lesao"),
             ("Ali Lajami", "Lesão isquiotibiais", "Outubro", "lesao"),
             ("Salem Al-Dawsari", "Lesão de tendão", "Voltou", "lesao"),
             ("Houssem Aouar", "Desconforto físico", "Incerto", "lesao"),
             ("Hamed Al-Ghamdi", "Ligamento cruzado", "Abril 2027", "lesao"),
             ("Saad Al-Mousa", "Tornozelo", "Voltou", "lesao"),
             ("Mais Um", "Coxa", "Incerto", "lesao")]]
ONZE = [{"nome": "AL-DAWSARI", "x": x, "y": y, "foto": None, "bandeira": None}
        for x, y, g in formacoes.QUADROS["4-3-3"]]

# A GEOMETRIA, conferida contra o vão que eu medi no template.
fim_da_saia = A.SAIA_TOPO + A.SAIA_LINHAS * A.SAIA_LINHA_ALT
ok(A.SAIA_TOPO > A.SAIA_BARRA[1],
   f"a primeira linha da saia ({A.SAIA_TOPO}) começa DENTRO da barra escura "
   f"(que acaba em {A.SAIA_BARRA[1]}) — o texto ficaria por cima do cabeçalho")
ok(fim_da_saia <= A.ALTURA,
   f"a saia termina em {fim_da_saia:.0f} e a imagem tem {A.ALTURA}: a última "
   f"linha sai pela borda de baixo")
ok(A.SAIA_X + A.SAIA_COLUNAS * A.SAIA_COL_LARG <= A.LARGURA,
   f"as duas colunas somam mais que a largura da imagem: a da direita vaza")

png = A.montar({"jogadores": ONZE, "clube": "Al Hilal",
                "desfalques": GENTE, "zoom": 1.7, "ancora": 0.10})
img = Image.open(io.BytesIO(png)).convert("RGB")
ok(img.size == (A.LARGURA, A.ALTURA), f"a arte saiu {img.size}")

# A SAIA ESCREVEU MESMO: o verde livre não pode ter ficado intocado.
px = img.load()
verdes = sum(1 for x in range(0, A.LARGURA, 4)
             for y in range(int(A.SAIA_TOPO), A.ALTURA - 20, 4)
             if px[x, y] == tuple(A.FOTO_VAZIA))
total = len(range(0, A.LARGURA, 4)) * len(range(int(A.SAIA_TOPO),
                                                A.ALTURA - 20, 4))
ok(verdes < total * 0.92,
   f"o vão embaixo do campo continuou {verdes / total:.0%} verde puro — a "
   f"saia não desenhou nada ali")

# E O CAMPO NÃO PODE TER SIDO INVADIDO: acima da barra escura, a arte com e
# sem desfalques tem de ser idêntica.
sem = A.montar({"jogadores": ONZE, "clube": "Al Hilal",
                "zoom": 1.7, "ancora": 0.10})
a_cima = Image.open(io.BytesIO(png)).crop((0, 0, A.LARGURA, A.SAIA_BARRA[0]))
b_cima = Image.open(io.BytesIO(sem)).crop((0, 0, A.LARGURA, A.SAIA_BARRA[0]))
ok(a_cima.tobytes() == b_cima.tobytes(),
   "a saia mexeu em algum pixel ACIMA da barra escura — ela invadiu o campo, "
   "que é a parte que ele posiciona jogador por jogador")

# ── SEM DESFALQUE, A ARTE CONTINUA SAINDO ───────────────────────────────
ok(sem and Image.open(io.BytesIO(sem)).size == (A.LARGURA, A.ALTURA),
   "sem desfalques a arte do campinho deixou de sair. A saia é um acréscimo; "
   "o campo não pode depender dela")
ok(png != sem, "a saia não mudou nada na imagem")

# ── NOME E MOTIVO COMPRIDOS NÃO VAZAM ───────────────────────────────────
from PIL import ImageDraw                                 # noqa: E402

_d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
f_nome = A._fonte("WorkSans-SemiBold-latin.ttf", A.SAIA_NOME)
cabe = A.SAIA_COL_LARG - A.SAIA_DISCO - 3.0 * A.CQ
for texto in ("ABDULRAHMAN MOHAMMED AL-GHAMDI AL-DAWSARI", "M" * 120):
    cortado = A._cortar(_d, texto, f_nome, cabe)
    ok(_d.textlength(cortado, font=f_nome) <= cabe + 0.5,
       f"'{texto[:20]}…' ficou com {_d.textlength(cortado, font=f_nome):.0f}px "
       f"numa célula de {cabe:.0f}px: ele invade a coluna vizinha")
    ok("…" in cortado, "o corte saiu sem reticências; parece defeito")
ok(A._cortar(_d, "CURTO", f_nome, cabe) == "CURTO", "o que cabia foi cortado")
ok(A._cortar(_d, "", f_nome, cabe) == "", "texto vazio virou alguma coisa")

# ── E A LISTA CORTADA AVISA, NO CABEÇALHO ───────────────────────────────
# O AVISO DE LISTA CORTADA, MEDIDO NA IMAGEM.
#
# Eu tinha escrito `ok("DE " in _corpo and "SAIA_CABEM" in _corpo)`. Plantei o
# defeito que remove o aviso e o teste PASSOU: o `SAIA_CABEM` continuava no
# `lista[:SAIA_CABEM]` logo abaixo, e o "DE " aparecia num comentário meu.
# Procurar palavra não mede nada — o que mede é o cabeçalho MUDAR quando a
# lista não coube inteira.
_cabe = A.SAIA_CABEM
_barra = (0, A.SAIA_BARRA[0], A.LARGURA, A.SAIA_BARRA[1])
_com_sobra = Image.open(io.BytesIO(A.montar(
    {"jogadores": ONZE, "clube": "Al Hilal", "desfalques": GENTE[:_cabe + 2],
     "zoom": 1.7, "ancora": 0.10}))).crop(_barra)
_sem_sobra = Image.open(io.BytesIO(A.montar(
    {"jogadores": ONZE, "clube": "Al Hilal", "desfalques": GENTE[:_cabe],
     "zoom": 1.7, "ancora": 0.10}))).crop(_barra)
ok(_com_sobra.tobytes() != _sem_sobra.tobytes(),
   f"o cabeçalho da saia saiu IGUAL com {_cabe} e com {_cabe + 2} desfalques. "
   f"Quando a lista não cabe inteira, quem lê precisa saber — seis de oito, "
   f"sem aviso, é uma lista incompleta com cara de completa")

# E O TETO SEGURA MESMO. Sem ele, o sétimo e o oitavo seriam desenhados
# abaixo da borda e sumiriam sem avisar — a arte pareceria certa e estaria
# faltando gente. Duas listas de tamanhos diferentes têm de produzir o MESMO
# corpo de saia; o que muda é só a contagem no cabeçalho.
_area = (0, A.SAIA_BARRA[1], A.LARGURA, A.ALTURA)
_oito = Image.open(io.BytesIO(A.montar(
    {"jogadores": ONZE, "clube": "Al Hilal", "desfalques": GENTE[:_cabe + 2],
     "zoom": 1.7, "ancora": 0.10}))).crop(_area)
_doze = Image.open(io.BytesIO(A.montar(
    {"jogadores": ONZE, "clube": "Al Hilal",
     "desfalques": (GENTE * 2)[:_cabe + 6], "zoom": 1.7,
     "ancora": 0.10}))).crop(_area)
ok(_oito.tobytes() == _doze.tobytes(),
   f"o corpo da saia mudou entre {_cabe + 2} e {_cabe + 6} desfalques. O teto "
   f"de {_cabe} parou de segurar: os que passam disso são desenhados fora da "
   f"imagem e somem sem avisar")


# ─────────────────────────────────────────────────────────────────────────
# 3. A ROTA E A TELA
# ─────────────────────────────────────────────────────────────────────────
_rota = FONTE[FONTE.index("async def api_elencos_arte("):]
_rota = _rota[:_rota.index("\nasync def _fotos_dos_desfalques")]
ok("_desfalques_do_clube" in _rota,
   "a rota da arte parou de buscar os desfalques; a saia sairia sempre vazia")
ok('"desfalques": ausentes["desfalques"]' in _rota,
   "a rota busca os desfalques e não os manda para a arte")
ok("except Exception" in _rota.split("_desfalques_do_clube")[1][:800],
   "a busca dos desfalques não está protegida. Uma guia fora do ar levaria "
   "junto a arte do campinho, que é o que ele usa todo dia")
ok("X-Fontes" in _rota and "X-Desfalques" in _rota,
   "a resposta parou de dizer quantos desfalques entraram e de quais guias. "
   "Saia vazia com as guias no ar e saia vazia com elas fora saem IGUAIS na "
   "imagem — o cabeçalho é o que separa as duas")

# ─────────────────────────────────────────────────────────────────────────
# 4. A PRÉVIA DESENHA A MESMA SAIA — foi o "tá vindo em branco"
# ─────────────────────────────────────────────────────────────────────────
# O PNG saía certo; a TELA é que não desenhava nada no vão de baixo. Ele
# montava a escalação olhando uma coisa e baixava outra — a regra que este
# projeto persegue a semana inteira, quebrada por mim no dia seguinte.
import re as _re2                                         # noqa: E402

ok("renderSaia" in PAGINA and "carregarDesfalques" in PAGINA,
   "a prévia do campinho parou de desenhar a saia. O PNG traz os desfalques e "
   "a tela não — ele monta a escalação vendo uma coisa e baixa outra")
# O ENDEREÇO EXATO, e não um pedaço dele. Plantei o defeito que renomeia a
# rota para "/api/elencos/desfalques-x" e o teste passou: a busca por
# substring achava o nome novo dentro do velho. Agora comparo o decorador
# inteiro dos dois lados.
ok('@app.get("/api/elencos/desfalques")' in FONTE,
   "sumiu a rota que alimenta a saia da prévia (ou ela mudou de endereço). A "
   "tela pediria a um lugar que não responde e a saia voltaria a ficar branca")
ok("'/api/elencos/desfalques?clube='" in PAGINA,
   "a tela parou de buscar os desfalques, ou mudou o endereço sem avisar a "
   "rota")
ok("carregarDesfalques()" in PAGINA.split("async function selecionarTime")[1]
   [:900],
   "a saia não é recarregada ao trocar de clube; ela mostraria os desfalques "
   "do time anterior")


def _cqw(px: float) -> float:
    """px de uma arte 1080 de largura → a unidade que o CSS do campo usa."""
    return px / A.LARGURA * 100


def _no_css(regra: str, prop: str) -> float:
    i = PAGINA.index(regra)
    trecho = PAGINA[i:PAGINA.index("}", i)]
    # O VALOR PODE VIR DENTRO DE UM `max(7px, 2.15cqw)` — o piso em px existe
    # para o texto não sumir num campinho miniatura no celular. Procuro o
    # primeiro cqw DENTRO do valor da propriedade, e não colado nos dois
    # pontos, senão estas duas linhas passavam batido.
    m = _re2.search(prop + r":[^;}]*?([\d.]+)cqw", trecho)
    return float(m.group(1)) if m else -1.0


# OS DOIS CONJUNTOS DE MEDIDAS TÊM DE BATER. O CSS não lê Python, então os
# números estão escritos duas vezes — e é exatamente por isso que existe esta
# conferência, a mesma que já guarda a âncora do zoom. Duas cópias das mesmas
# medidas é como a prévia e o arquivo começam a divergir.
for regra, prop, esperado, oque in (
        (".saia{", "top", _cqw(A.SAIA_BARRA[0]), "o topo da barra escura"),
        (".saia .barra{", "height", _cqw(A.SAIA_BARRA[1] - A.SAIA_BARRA[0]),
         "a altura da barra"),
        (".saia .linhas{", "top", _cqw(A.SAIA_TOPO - A.SAIA_BARRA[0]),
         "onde a primeira linha começa"),
        (".saia .linhas{", "grid-auto-rows", A.SAIA_LINHA_ALT / A.CQ,
         "a altura de cada linha"),
        (".saia .item .disco{", "width", A.SAIA_DISCO / A.CQ, "o disco"),
        (".saia .item .nm{", "font-size", A.SAIA_NOME / A.CQ, "o corpo do nome"),
        (".saia .item .mv{", "font-size", A.SAIA_MOTIVO / A.CQ,
         "o corpo do motivo")):
    achado = _no_css(regra, prop)
    ok(abs(achado - esperado) < 0.06,
       f"{oque}: o CSS diz {achado}cqw e o desenho do PNG diz "
       f"{esperado:.2f}cqw. A prévia e o arquivo saem diferentes, e a "
       f"diferença só aparece depois de publicado")

_i = PAGINA.index("const SAIA_CABEM = ")
ok(int(PAGINA[_i + 19:PAGINA.index(";", _i)]) == A.SAIA_CABEM,
   f"o teto da prévia não é o do PNG ({A.SAIA_CABEM}). A tela mostraria um "
   f"número de desfalques e o arquivo, outro")

# E A ORDEM DAS COLUNAS. O servidor enche a primeira coluna inteira antes de
# passar para a segunda (divmod por linha); o `grid` do CSS preenche por
# LINHA. Sem reordenar no JS, a mesma lista sai em ordem diferente nos dois.
_js_saia = PAGINA[PAGINA.index("function renderSaia()"):]
_js_saia = _js_saia[:_js_saia.index("\nfunction ")]
ok("col * 3 + lin" in _js_saia,
   "a prévia parou de reordenar para preencher coluna a coluna. O PNG enche a "
   "primeira coluna inteira antes de passar para a segunda; o grid do CSS "
   "enche por linha — a mesma lista sairia em ordem diferente nos dois")
ok("SUSPENSO · " in _js_saia,
   "a prévia não marca o suspenso; no PNG ele vem marcado")

ok("clube: TIME_NOME" in PAGINA,
   "a página parou de mandar o clube ao pedir a arte; sem ele o servidor não "
   "tem o que buscar")
ok("X-Desfalques" in PAGINA,
   "a tela não mostra quantos desfalques entraram na arte que acabou de baixar")

# A ARTE SEPARADA FOI EMBORA: ele pediu na saia, e duas saídas para a mesma
# informação é a segunda cópia de sempre.
ok(not os.path.exists(os.path.join(RAIZ, "desfalques_arte.py")),
   "o módulo da arte separada voltou. Ele pediu os desfalques NA SAIA; duas "
   "artes para a mesma informação é a segunda cópia que este projeto passa o "
   "tempo todo removendo")
ok("desfalques-arte" not in FONTE and "baixarDesfalques" not in PAGINA,
   "sobrou a rota ou o botão da arte separada")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ desfalques na saia, vindos das guias dele, com foto do glossário")
