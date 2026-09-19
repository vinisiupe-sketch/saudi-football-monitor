"""A arte dos desfalques: quem está fora, por quê, e até quando.

O PEDIDO (18/09/26)
    "Podemos tentar montar nessa base verde na parte do campinho algo como no
     anexo? Pegando o que temos de informações de lesionados e suspensos?"

O QUE ESTE ARQUIVO VIGIA, em ordem de importância
    1. QUE ARTE VAZIA NÃO EXISTE. Uma imagem publicada dizendo que o elenco
       está completo, quando na verdade o Transfermarkt bloqueou, é pior que
       imagem nenhuma — e é a que o Vini só descobriria pelo comentário de
       alguém embaixo do post. "Ninguém fora" e "não consegui olhar" têm de
       chegar à tela como frases diferentes.
    2. Que as DUAS fontes entram, e que quem aparece nas duas entra uma vez só.
       Elas sabem coisas diferentes: o TM tem tipo de lesão e prazo de volta, a
       API-Football tem suspensão. Sozinhas, cada uma mente por omissão.
    3. Que nada vaza da imagem — nome comprido, lesão com nome de manual.
    4. Que a identidade é a mesma do campinho: mesmo verde, mesmo grafite,
       mesmo disco. As duas artes vão para o mesmo feed, uma atrás da outra.
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

import desfalques_arte as D                               # noqa: E402
import escalacao_arte                                     # noqa: E402

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


UM = [{"nome": "Theo Hernández", "motivo": "Lesão muscular",
       "retorno": "No fim de setembro 2026", "tipo": "lesao",
       "foto": _foto()}]


# ─────────────────────────────────────────────────────────────────────────
# 1. ARTE VAZIA NÃO EXISTE
# ─────────────────────────────────────────────────────────────────────────
for vazio in ({"clube": "Al Hilal", "desfalques": []},
              {"clube": "Al Hilal"},
              {"clube": "Al Hilal", "desfalques": [{"nome": ""}]}):
    try:
        D.montar(vazio)
        falhas.append(
            f"montou uma arte sem ninguém na lista ({vazio!r}). Ela anunciaria "
            f"'elenco completo' com a mesma cara de informação — inclusive no "
            f"dia em que a fonte caiu")
    except ValueError:
        pass
    except Exception as e:
        falhas.append(f"arte vazia levantou {type(e).__name__} em vez de "
                      f"ValueError; quem chama não consegue distinguir")

# E A ROTA TRADUZ ISSO EM DUAS FRASES DIFERENTES.
_rota = FONTE[FONTE.index("async def api_elencos_desfalques_arte("):]
_rota = _rota[:_rota.index('\n@app.', 10)] if '\n@app.' in _rota[10:] else _rota
ok('if achado["fontes"]' in _rota or "achado[\"fontes\"]\n" in _rota,
   "a rota responde a lista vazia sem olhar se ALGUMA fonte respondeu. "
   "'Ninguém está fora' e 'não consegui consultar' viram a mesma frase, e a "
   "segunda tem cara de boa notícia")
ok("status_code=404" in _rota,
   "a lista vazia deixou de ser um estado próprio na resposta")


# ─────────────────────────────────────────────────────────────────────────
# 2. A ARTE MONTA, E NO TAMANHO DE POST
# ─────────────────────────────────────────────────────────────────────────
from PIL import Image                                     # noqa: E402

png = D.montar({"clube": "Al Hilal", "desfalques": UM,
                "fontes": "Transfermarkt"})
img = Image.open(io.BytesIO(png))
ok(img.size == (escalacao_arte.LARGURA, escalacao_arte.ALTURA),
   f"a arte saiu {img.size}, e o formato de post é "
   f"{escalacao_arte.LARGURA}x{escalacao_arte.ALTURA}")

# ── SEM FOTO NENHUMA NÃO PODE QUEBRAR ───────────────────────────────────
# É o caso do dia em que o Transfermarkt recusa as imagens: a lista existe, as
# fotos não. Melhor arte com disco vazio que erro no meio do dia de jogo.
try:
    D.montar({"clube": "Al Hilal",
              "desfalques": [{"nome": "Sem Foto", "motivo": "Lesão",
                              "retorno": "", "tipo": "lesao", "foto": None}]})
except Exception as e:
    falhas.append(f"a arte quebrou com jogador sem foto: {type(e).__name__}: {e}")

# ── O VERDE É O MESMO DO CAMPINHO ───────────────────────────────────────
ok(tuple(D.VERDE) == tuple(escalacao_arte.FOTO_VAZIA),
   f"o verde da arte de desfalques ({D.VERDE}) não é o mesmo do disco do "
   f"campinho ({escalacao_arte.FOTO_VAZIA}). As duas vão para o mesmo feed; "
   f"dois verdes quase iguais é pior que dois bem diferentes")
canto = img.convert("RGB").getpixel((img.width - 8, 8))
ok(canto == tuple(D.VERDE),
   f"o fundo da arte saiu {canto} em vez de {tuple(D.VERDE)}")


# ─────────────────────────────────────────────────────────────────────────
# 3. NADA VAZA DA IMAGEM
# ─────────────────────────────────────────────────────────────────────────
from PIL import ImageDraw                                 # noqa: E402

_d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
f_nome = D._fonte("WorkSans-SemiBold-latin.ttf", D.NOME_CORPO)
f_motivo = D._fonte("WorkSans-Regular-latin.ttf", D.MOTIVO_CORPO)
limite = D.LARGURA - D.TEXTO_X - D.MARGEM

COMPRIDOS = [
    ("Abdulrahman Mohammed Al-Ghamdi Al-Dawsari",
     "Lesão do ligamento cruzado anterior do joelho direito",
     "No meio do mês de abril de 2027"),
    ("S. Milinković-Savić", "Rotura muscular", "Incerto"),
]
for nome, motivo, retorno in COMPRIDOS:
    curto = D._encurtar(_d, nome.upper(), f_nome, limite)
    ok(_d.textlength(curto, font=f_nome) <= limite + 0.5,
       f"o nome '{nome}' saiu com {_d.textlength(curto, font=f_nome):.0f}px "
       f"numa faixa de {limite:.0f}px — ele passa da borda da imagem")
    linha = D._encurtar(_d, motivo + " / " + retorno, f_motivo, limite)
    ok(_d.textlength(linha, font=f_motivo) <= limite + 0.5,
       f"a linha de motivo do '{nome}' vaza da imagem")
    ok(curto and linha, "o encurtamento comeu o texto inteiro")

ok(D._encurtar(_d, "Curto", f_nome, limite) == "Curto",
   "o que cabia foi encurtado assim mesmo")
ok(D._encurtar(_d, "", f_nome, limite) == "",
   "texto vazio virou alguma coisa")
ok("…" in D._encurtar(_d, "M" * 200, f_nome, limite),
   "um texto que não coube saiu sem reticências — cortado no meio parece "
   "defeito, e ninguém sabe que falta pedaço")

# ── O TETO DE QUANTOS CABEM ─────────────────────────────────────────────
muitos = [dict(UM[0], nome=f"Jogador {i}") for i in range(25)]
png_muitos = D.montar({"clube": "Al Hilal", "desfalques": muitos})
ok(png_muitos, "a arte não monta com muita gente na lista")
# E A ARTE TEM DE DIZER QUE CORTOU. Mostrar dez de vinte e cinco sem avisar é
# publicar uma lista incompleta com cara de completa.
_i = FONTE.index("def montar(", 0) if False else 0
_fonte_mod = open(os.path.join(RAIZ, "desfalques_arte.py"),
                  encoding="utf-8").read()
ok("mostrando" in _fonte_mod,
   "a arte parou de avisar quando a lista foi cortada pelo teto. Dez de vinte "
   "e cinco, sem aviso, é uma lista incompleta com cara de completa")
ok(D.CABEM >= 8, f"o teto caiu para {D.CABEM}; um elenco em má fase passa disso")


# ─────────────────────────────────────────────────────────────────────────
# 4. AS DUAS FONTES, E O DE-PARA ENTRE ELAS
# ─────────────────────────────────────────────────────────────────────────
_junta = FONTE[FONTE.index("async def _desfalques_do_clube("):]
_junta = _junta[:_junta.index("\n@app.")]
_sql = "\n".join(l for l in _junta.split("\n")
                 if not l.strip().startswith("#"))

ok("_lesoes_do_tm" in _sql,
   "a junção parou de consultar o Transfermarkt — é a única fonte com o TIPO "
   "da lesão e a DATA de volta, que é o que ele narra")
ok("api_ausencias_af" in _sql,
   "a junção parou de consultar a API-Football — é a única que publica "
   "SUSPENSÃO. Sem ela a arte diz que o suspenso está à disposição")
# ── A JUNÇÃO, EXECUTADA ──────────────────────────────────────────────────
#
# Eu tinha escrito `ok("vistos" in _sql and "_chave_de_nome" in _sql)`. Plantei
# o defeito que tira a conferência do duplicado e o teste PASSOU — claro: as
# duas palavras continuavam no texto, só não estavam mais na condição que
# importa. Procurar palavra não mede comportamento; rodar mede.
import asyncio as _asyncio                                # noqa: E402
import re as _re                                          # noqa: E402
import unicodedata as _ud                                 # noqa: E402

_ichave = FONTE.index("def _chave_de_nome(")
_amb: dict = {"unicodedata": _ud, "re": _re, "asyncio": _asyncio,
              "print": lambda *a, **k: None}
exec(FONTE[_ichave:FONTE.index("\ndef ", _ichave + 10)], _amb)

TM = {"lesoes": [
    {"nome_elenco": "Theo Hernández", "clube_elenco": "Al Hilal",
     "motivo": "Lesão muscular", "retorno": "No fim de setembro", "foto": "t.png"},
    {"nome_elenco": "Outro Clube", "clube_elenco": "Al Nassr",
     "motivo": "Lesão", "retorno": "", "foto": ""}]}
AF = {"ausencias": [
    # O MESMO Theo, com a grafia e a informação mais pobre da outra fonte.
    {"jogador": "Theo Hernandez", "clube": "Al Hilal", "tipo": "Lesão",
     "motivo": "Injury", "jogo_em": "2026-09-20", "foto": "x.png"},
    {"jogador": "Ahmed Sharahili", "clube": "Al Hilal", "tipo": "Suspensão",
     "motivo": "Terceiro amarelo", "jogo_em": "2026-09-20", "foto": "s.png"}]}

_amb["_lesoes_do_tm"] = lambda: TM


async def _af_falso():
    return AF


_amb["api_ausencias_af"] = _af_falso
exec(_junta, _amb)
_r = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
_nomes = [x["nome"] for x in _r["desfalques"]]

ok(len(_nomes) == 2,
   f"a junção devolveu {len(_nomes)} linhas ({_nomes}) e esperava 2. O Theo "
   f"está nas DUAS fontes com grafias diferentes — sem o de-para ele aparece "
   f"duas vezes na mesma arte")
ok(_nomes and _nomes[0] == "Ahmed Sharahili",
   f"a ordem saiu {_nomes}: o suspenso tem de vir primeiro. A suspensão vale "
   f"para o próximo jogo; a lesão de seis meses continua lá na semana que vem")
_theo = [x for x in _r["desfalques"] if "Theo" in x["nome"]]
ok(_theo and _theo[0]["motivo"] == "Lesão muscular",
   f"a linha do Theo ficou com a versão pobre da API-Football "
   f"({_theo and _theo[0].get('motivo')!r}). Quando as duas fontes têm a "
   f"mesma pessoa, vale a do Transfermarkt: ela tem tipo e prazo")
ok(_theo and _theo[0]["retorno"] == "No fim de setembro",
   "o prazo de volta do Transfermarkt se perdeu no de-para")
_susp = [x for x in _r["desfalques"] if x["tipo"] == "suspensao"]
ok(len(_susp) == 1 and _susp[0]["nome"] == "Ahmed Sharahili",
   f"o suspenso não foi marcado como tal: {_r['desfalques']}")
ok("Transfermarkt" in _r["fontes"] and "API-Football" in _r["fontes"],
   f"as fontes que responderam não foram registradas: {_r['fontes']!r}")
ok(all("Nassr" not in x["nome"] for x in _r["desfalques"]),
   "entrou desfalque de outro clube na arte")

# ── UMA FONTE CAÍDA NÃO DERRUBA A OUTRA ─────────────────────────────────
def _explode():
    raise RuntimeError("Transfermarkt bloqueou")


_amb["_lesoes_do_tm"] = _explode
exec(_junta, _amb)
_amb["_lesoes_do_tm"] = _explode
_amb["api_ausencias_af"] = _af_falso
_r2 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(len(_r2["desfalques"]) == 2,
   f"com o Transfermarkt fora a lista veio com {len(_r2['desfalques'])} — a "
   f"API-Football ainda respondia, e uma fonte caída levou a outra junto")
ok("Transfermarkt" not in _r2["fontes"],
   f"o rodapé continua creditando o Transfermarkt ({_r2['fontes']!r}) mesmo "
   f"com ele fora do ar. É essa lista que sustenta a frase 'o elenco está "
   f"completo' — creditar quem não respondeu transforma silêncio em confirmação")

# ── AS DUAS CAÍDAS: lista vazia E nenhuma fonte ─────────────────────────
async def _af_explode():
    raise RuntimeError("API-Football fora")


exec(_junta, _amb)
_amb["_lesoes_do_tm"] = _explode
_amb["api_ausencias_af"] = _af_explode
_r3 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(_r3["desfalques"] == [] and _r3["fontes"] == "",
   f"com as duas fontes fora a junção devolveu {_r3!r}. Tem de sair vazio E "
   f"sem fonte nenhuma — é o par que deixa a rota dizer 'não consegui olhar' "
   f"em vez de 'elenco completo'")

# ── E O CONTRÁRIO: FONTE QUE RESPONDEU "NINGUÉM" É FONTE QUE RESPONDEU ───
#
# ESTE CASO ME PEGOU NA MUTAÇÃO, e o defeito era meu. Eu creditava a fonte só
# quando ela trazia alguém — `if r.get("lesoes")`. Só que o `_lesoes_do_tm`
# NUNCA levanta: bloqueado, ele devolve `{"lesoes": [], "erros": [...]}`. Com
# a guarda antiga, uma rodada sem lesão nenhuma na liga seria contada como
# "nenhuma fonte respondeu", e a tela diria "não consegui consultar" num dia
# em que tinha consultado muito bem.
#
# É a mesma distinção que este projeto persegue desde o começo: lista vazia
# não é falta de resposta.
exec(_junta, _amb)
_amb["_lesoes_do_tm"] = lambda: {"lesoes": [], "erros": []}


async def _af_vazia():
    return {"ausencias": []}


_amb["api_ausencias_af"] = _af_vazia
_r4 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok(_r4["desfalques"] == [],
   f"clube sem desfalque devolveu gente: {_r4['desfalques']}")
ok("Transfermarkt" in _r4["fontes"] and "API-Football" in _r4["fontes"],
   f"as duas fontes responderam 'ninguém está fora' e não foram creditadas "
   f"({_r4['fontes']!r}). A tela diria 'não consegui consultar' num dia em "
   f"que consultou — e o Vini iria procurar um defeito que não existe")

# E FONTE BLOQUEADA NÃO É CREDITADA, mesmo devolvendo uma lista vazia — que é
# exatamente como o Transfermarkt sinaliza bloqueio.
exec(_junta, _amb)
_amb["_lesoes_do_tm"] = lambda: {"lesoes": [], "erros": ["403 do Transfermarkt"]}
_amb["api_ausencias_af"] = _af_vazia
_r5 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok("Transfermarkt" not in _r5["fontes"],
   f"o Transfermarkt foi creditado mesmo tendo devolvido erro "
   f"({_r5['fontes']!r}). Ele NÃO levanta exceção quando bloqueia: devolve "
   f"lista vazia com a queixa em 'erros', e é por ali que se sabe")


# E A API-FOOTBALL QUE DEVOLVE UMA QUEIXA em vez de levantar. Hoje aquela rota
# responde 502 quando falha, mas uma resposta com "erro" dentro é a forma que
# metade deste projeto usa, e creditar quem se queixou é o mesmo defeito do
# Transfermarkt com outra roupa.
async def _af_com_queixa():
    return {"erro": "assinatura expirada", "ausencias": []}


exec(_junta, _amb)
_amb["_lesoes_do_tm"] = lambda: {"lesoes": [], "erros": []}
_amb["api_ausencias_af"] = _af_com_queixa
_r6 = _asyncio.run(_amb["_desfalques_do_clube"]("Al Hilal"))
ok("API-Football" not in _r6["fontes"],
   f"a API-Football foi creditada tendo respondido com uma queixa "
   f"({_r6['fontes']!r}). É ela que sustenta a frase 'o elenco está completo'")
ok('"suspensao"' in _sql,
   "a junção parou de marcar quem é suspenso. Na arte ele viraria mais um "
   "lesionado, e a diferença é entre 'volta quando sarar' e 'volta no "
   "próximo jogo'")
# CADA FONTE NO SEU `try`: se o TM cair, a API-Football ainda responde.
ok(_sql.count("except Exception") >= 2,
   "as duas fontes deixaram de ser protegidas em separado. Uma fonte fora do "
   "ar levaria a outra junto, e a arte sairia sem ninguém")
ok("fontes" in _sql and "append" in _sql,
   "a junção parou de registrar QUAIS fontes responderam. É o que permite "
   "dizer 'o elenco está completo' sem mentir")

# A ORDEM: suspenso primeiro, porque é a informação perecível.
ok('x["tipo"] != "suspensao"' in _sql,
   "os suspensos deixaram de vir primeiro. A suspensão vale para o próximo "
   "jogo; a lesão de seis meses continua lá na semana que vem")


# ─────────────────────────────────────────────────────────────────────────
# 5. O BOTÃO EXISTE E PEGA O NOME DO CLUBE CERTO
# ─────────────────────────────────────────────────────────────────────────
ok("baixarDesfalques" in PAGINA, "sumiu o botão de baixar os desfalques")
ok("/api/elencos/desfalques-arte" in PAGINA and
   "/api/elencos/desfalques-arte" in FONTE,
   "o botão chama um endereço que o servidor não atende")

def _sem_comentario(js: str) -> str:
    """O JavaScript sem as linhas de `//`.

    ISTO JÁ ME PEGOU QUATRO VEZES nesta suíte. Eu explico o defeito antigo por
    extenso logo acima do conserto — e o defeito antigo CITA o código errado.
    Procurar o texto no bloco inteiro encontra a minha própria explicação e
    acusa um erro que não existe mais.
    """
    return "\n".join(l for l in js.split("\n")
                     if not l.strip().startswith("//"))


_js = PAGINA[PAGINA.index("async function baixarDesfalques()"):]
_js = _sem_comentario(_js[:_js.index("\nfunction ")])
ok("TIME_ATUAL.nome" not in _js,
   "o botão dos desfalques pergunta por `TIME_ATUAL.nome`. O TIME_ATUAL é o "
   "ID do clube, um número — isso é `undefined`, e a arte sairia sem clube")
ok("TIME_NOME" in _js, "o botão não lê o nome do clube de lugar nenhum")

# E O MESMO DEFEITO NA ARTE DA ESCALAÇÃO, que estava lá desde sempre: o nome
# do arquivo caía no padrão e TODA escalação baixava como "escalacao.png".
_js2 = PAGINA[PAGINA.index("async function baixarArte()"):]
_js2 = _sem_comentario(_js2[:_js2.index("\n// ── a arte dos desfalques")])
ok("TIME_ATUAL.nome" not in _js2,
   "a arte da escalação voltou a montar o nome do arquivo com "
   "`TIME_ATUAL.nome`, que é `undefined`. Todo arquivo baixa como "
   "'escalacao.png' e a pasta de downloads vira escalacao(1), escalacao(2)")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ arte dos desfalques: duas fontes, nada vaza, e lista vazia não vira "
      "imagem")
