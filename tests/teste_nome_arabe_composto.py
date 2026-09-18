"""Onde a imprensa aperta o espaço não muda quem é a pessoa.

O QUE ELE VIU (18/09/26)
    Um tweet do Asharq sobre o Hayder Abdulkareem, do Al Nassr, saiu no app
    como "Haidar Abd al-Karim". O jogador está no glossário, mapeado, com a
    grafia árabe da SPL — e mesmo assim a IA transliterou por conta própria.

        "Se já temos esse jogador mapeado no glossário, porque as noticias
         ainda estão saindo com transliteração diferente do que está lá?"

    A causa, medida com o texto real do tweet:

        glossário (SPL) : حيدر عبدالكريم    → chave 'حيدر عبدالكريم'
        tweet do Asharq : حيدر عبد الكريم   → chave 'حيدر عبد كريم'

    Duas diferenças empilhadas. A primeira é o espaço no meio de عبدالكريم, que
    cada fonte aperta onde quer. A segunda é pior: a `chave_arabe` tira o ال do
    COMEÇO de cada palavra, então o الكريم separado vira كريم enquanto o ال do
    عبدالكريم junto, que está no miolo, fica. As duas formas se afastam MAIS
    depois de normalizadas do que antes — e por isso nem a `chave_colada`, que
    nasceu exatamente para عبدالله/عبد الله, dava conta.

O QUE ESTE ARQUIVO VIGIA, em ordem de importância
    1. QUE O CASO DELE FUNCIONA, com o texto do tweet como ele chegou.
    2. QUE OS CLUBES NÃO FORAM ATINGIDOS. A `chave_arabe` é a mesma função que
       reconhece النصر, e lá o artigo é justamente o que separa o time da
       palavra "vitória". A regra nova é um índice A MAIS; se ela tivesse
       virado uma alteração na chave de sempre, o app passaria a achar o Al
       Nassr em toda frase que fala em vencer.
    3. Que o que já era reconhecido continua sendo.
    4. Que chave ambígua continua virando "não sei", e não um palpite.
"""
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

import glossario                                          # noqa: E402
import glossary                                           # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# O TEXTO COMO ELE CHEGOU, copiado do tweet que o Vini mandou. Não é um exemplo
# que eu inventei para passar: é o post do @aawsat_spt de 16/09, e é por isso
# que ele vale como prova.
TWEET = ("قرر الأسترالي غراهام أرنولد، مدرب المنتخب العراقي، منح النجم الشاب "
         "حيدر عبد الكريم لاعب النصر السعودي فرصة المشاركة في بطولة كأس الخليج "
         "الـ27 المقررة إقامتها في جدة.")


# ─────────────────────────────────────────────────────────────────────────
# 1. A REGRA, EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
c = glossary.chave_arabe_composta

ok(c("حيدر عبدالكريم") == c("حيدر عبد الكريم"),
   f"junto e separado continuam sendo duas pessoas: "
   f"{c('حيدر عبدالكريم')!r} contra {c('حيدر عبد الكريم')!r}. É o caso do "
   f"Hayder Abdulkareem, e é onde tudo começou")

# E O CASO CONTRÁRIO TAMBÉM: nada garante que o glossário seja sempre o lado
# que escreve junto.
ok(c("عبدالله الحمدان") == c("عبد الله الحمدان"),
   "Abdullah, o nome mais comum desta liga, continua com duas formas")
ok(c("حمد الله") == c("حمدالله"),
   "Hamdallah continua com duas formas. Aqui quem manda é a palavra da "
   "direita (الله), e não o prefixo")
ok(c("عبدالرحمن غريب") == c("عبد الرحمن غريب"),
   "Abdulrahman continua com duas formas")

# ── O ال SOZINHO, QUE O DIAGNÓSTICO NO GLOSSÁRIO DELE REVELOU ────────────
#
# O #558 Abdullah Al Salem, do Al Qadsiah, está escrito عبدالله آل سالم. O آل
# é "casa de", vira ال depois de normalizado, e fica um token de duas letras
# que a guarda do artigo não toca — com razão, porque sem ela "الله" viraria
# "له". Só que aí عبدالله آل سالم e عبدالله السالم deixam de ser a mesma
# pessoa, de novo por causa de onde alguém apertou espaço.
ok(len({c("عبدالله آل سالم"), c("عبدالله السالم"), c("عبدالله سالم")}) == 1,
   f"o #558 Abdullah Al Salem continua partido: "
   f"{c('عبدالله آل سالم')!r}, {c('عبدالله السالم')!r} e "
   f"{c('عبدالله سالم')!r} deviam ser a mesma chave")
ok(c("الله") == glossary.chave_arabe("الله"),
   "'الله' sozinho foi estragado. É a palavra que a guarda `len(p) > 4` "
   "protege desde o começo: sem ela vira 'له', que não é nada")

# ── E O QUE NÃO É NOME COMPOSTO NÃO PODE SER UNIDO ───────────────────────
#
# É o limite da regra, e o que a separa de semelhança de texto: ela une
# metades de nome composto, não palavras vizinhas quaisquer.
ok(c("سالم الدوسري") != c("سالمالدوسري"),
   "a regra uniu duas palavras que não formam nome composto. Assim ela deixa "
   "de ser ortografia e vira 'parecido o bastante', que é de onde a gente saiu")
ok(c("سالم الدوسري") == glossary.chave_arabe("سالم الدوسري"),
   "um nome sem عبد/ابو/الله saiu diferente da chave de sempre; a regra está "
   "mexendo em nome que não é da conta dela")
ok(c("") == "" and c(None) == "",
   "nome vazio devolveu alguma coisa")

# A LISTA É EXPLÍCITA, e tem de continuar curta. Uma lista que cresce por
# conveniência vira a heurística de que este projeto fugiu.
ok(set(glossary.PREFIXOS_COMPOSTOS) == {"عبد", "ابو"},
   f"a lista de prefixos compostos virou {glossary.PREFIXOS_COMPOSTOS!r}. Cada "
   f"palavra a mais aproxima nomes que não são a mesma pessoa")
ok(set(glossary.SEGUNDAS_COMPOSTAS) == {"الله"},
   f"a lista de segundas metades virou {glossary.SEGUNDAS_COMPOSTAS!r}")

# ── E O QUE PARECE COMPOSTO E NÃO É ──────────────────────────────────────
#
# O #456 Abdou Diallo, do Abha: عبدو ديالو. O token começa com عبد e é mais
# longo — mas "عبدو" é Abdou, o nome senegalês, e não عبد + alguma coisa.
# A regra de união não encosta nele porque só age com عبد SOZINHO, e é assim
# que tem de continuar.
ok(c("عبدو ديالو") == glossary.chave_arabe("عبدو ديالو"),
   "'عبدو' (Abdou Diallo) foi tratado como nome composto. Ele só PARECE: a "
   "união vale para عبد separado, não para toda palavra que comece com essas "
   "três letras")


# ─────────────────────────────────────────────────────────────────────────
# 2. OS CLUBES NÃO PODEM TER SIDO ATINGIDOS
# ─────────────────────────────────────────────────────────────────────────
# Este é o teste que protege o resto do app. A `chave_arabe` é a mesma função
# que procura clube dentro de notícia, e lá o artigo é o que separa النصر (o
# time) de نصر ("vitória"). Se a regra nova tivesse entrado dentro dela em vez
# de ao lado, o app passaria a achar o Al Nassr em toda frase que fala em
# vencer — e acharia com ar de certeza.
ok(glossary.chave_arabe("النصر", manter_artigo=True) == "النصر",
   "o clube perdeu o artigo. 'النصر' vira 'نصر', que é a palavra comum "
   "'vitória' — e o app passa a achar o Al Nassr em qualquer notícia")
ok(glossary.chave_arabe("النصر", manter_artigo=True)
   != glossary.chave_arabe("نصر", manter_artigo=True),
   "o time e a palavra 'vitória' viraram a mesma coisa")
ok(glossary.chave_arabe("حيدر عبد الكريم") == "حيدر عبد كريم",
   "a `chave_arabe` de sempre MUDOU. Ela responde por clubes, por identidade e "
   "pelo que o laboratório já gravou no banco; a regra nova tinha de ser um "
   "índice a mais, não uma troca")

# E o `chave_arabe_composta` NÃO oferece `manter_artigo`: ele é de nome de
# pessoa. Se um dia for usado para clube, que seja por decisão e não por
# descuido.
import inspect                                            # noqa: E402
ok("manter_artigo" not in inspect.signature(c).parameters,
   "a chave composta ganhou `manter_artigo` e virou candidata a procurar "
   "clube. Ela une metades de nome de pessoa; em clube, o artigo é o dado")


# ─────────────────────────────────────────────────────────────────────────
# 3. O GLOSSÁRIO INTEIRO, COM O TWEET DE VERDADE
# ─────────────────────────────────────────────────────────────────────────
FICHAS = [
    # O caso dele: a SPL escreve junto.
    {"id": 314, "spl_id": "s314", "af_id": 420243, "tm_id": "1032334",
     "nome_principal": "Hayder Abdulkareem", "nome_curto": "Abdulkareem",
     "nome_ar": "حيدر عبدالكريم", "clube": "Al Nassr",
     "posicao": "Midfielder", "nacionalidade": "Iraque", "foto": "h.png"},
    # O contrário: glossário separado, imprensa junta.
    {"id": 7, "spl_id": "s7", "af_id": 7, "tm_id": "7",
     "nome_principal": "Abderrazak Hamdallah", "nome_curto": "Hamdallah",
     "nome_ar": "عبد الرزاق حمد الله", "clube": "Al Ittihad",
     "posicao": "Atacante", "nacionalidade": "Marrocos", "foto": "a.png"},
    # Um jogador sem nada de composto, para provar que ele não mudou.
    {"id": 9, "spl_id": "s9", "af_id": 9, "tm_id": "9",
     "nome_principal": "Salem Al-Dawsari", "nome_curto": "Al-Dawsari",
     "nome_ar": "سالم الدوسري", "clube": "Al Hilal",
     "posicao": "Ponta", "nacionalidade": "Arábia Saudita", "foto": "s.png"},
    # E o que PARECE composto e não é: عبدو é Abdou, o nome senegalês. Ele
    # está aqui porque o diagnóstico rodado no glossário de verdade o contou
    # como composto, inflando o número que ia embasar a decisão.
    {"id": 456, "spl_id": "s456", "af_id": 456, "tm_id": "456",
     "nome_principal": "Abdou Diallo", "nome_curto": "Diallo",
     "nome_ar": "عبدو ديالو", "clube": "Abha",
     "posicao": "Zagueiro", "nacionalidade": "Senegal", "foto": "d.png"},
]
GRAFIAS: list = []


def _plantar(fichas=None, grafias=None):
    import database
    fs = [dict(f) for f in (fichas if fichas is not None else FICHAS)]
    gs = [dict(g) for g in (grafias if grafias is not None else GRAFIAS)]
    for g in gs:
        if not g.get("nome_normalizado"):
            g["nome_normalizado"] = glossario._chave(g["nome"])
    database.glossario_completo = lambda: (fs, gs)
    glossario.recarregar()


_plantar()

# ── O TESTE QUE RESUME TUDO ──────────────────────────────────────────────
achados = glossario.jogadores_no_texto(TWEET)
ids = {a["id"] for a in achados}
ok(314 in ids,
   f"o Hayder Abdulkareem NÃO foi achado no tweet do Asharq — achei {ids or 'ninguém'}. "
   f"É exatamente a notícia que ele mandou, e sem esse achado o jogador não "
   f"entra no prompt e a IA translitera sozinha: 'Haidar Abd al-Karim'")

# E A LIÇÃO CHEGA MONTADA, com a grafia dele. Achar e não ensinar não serve
# de nada: quem conserta a notícia é o texto que entra no prompt.
licao = glossario.licao_para_a_ia(TWEET)
ok("Hayder Abdulkareem" in licao,
   f"o jogador foi achado mas a lição não leva o nome dele para o prompt. "
   f"Saiu: {licao[:200]!r}")
ok("حيدر عبدالكريم" in licao,
   "a lição não leva a grafia árabe, que é o de-para que a IA precisa ver")

# ── O CAMINHO CONTRÁRIO: glossário separado, imprensa junta ──────────────
ok(7 in {a["id"] for a in glossario.jogadores_no_texto(
        "سجل عبدالرزاق حمدالله هدفين أمس")},
   "o Hamdallah não foi achado quando a imprensa escreve junto e o glossário "
   "guarda separado. A regra tem de valer para os dois lados, senão ela só "
   "conserta metade dos casos")

# ── O QUE JÁ FUNCIONAVA CONTINUA ─────────────────────────────────────────
ok(glossario.identidade("حيدر عبدالكريم").get("id") == 314,
   "a grafia exata do glossário parou de responder — a regra nova quebrou o "
   "caminho antigo em vez de acrescentar um")
ok(glossario.identidade("حيدر عبد الكريم").get("id") == 314,
   "a grafia da imprensa não responde pela consulta direta")
ok(glossario.identidade("Hayder Abdulkareem").get("id") == 314,
   "o nome latino parou de responder")
ok(glossario.identidade("سالم الدوسري").get("id") == 9,
   "um nome sem composto parou de responder")
ok(glossario.identidade("Cristiano Ronaldo") == {},
   "o glossário passou a responder por quem não está nele")
ok(9 not in {a["id"] for a in glossario.jogadores_no_texto(TWEET)},
   "um jogador que não é citado no tweet foi achado nele")

# ── AMBÍGUO CONTINUA SENDO "NÃO SEI" ─────────────────────────────────────
#
# É o preço da regra, e ele precisa ser cobrado do jeito certo: aproximar
# grafias aproxima pessoas, e duas pessoas na mesma chave têm de virar
# silêncio, nunca uma das duas. O /api/diag/nomes-arabes conta quantos casos
# assim existem no glossário dele.
_plantar(fichas=FICHAS + [
    {"id": 315, "spl_id": "s315", "af_id": 8888, "tm_id": "8888",
     "nome_principal": "Haider Abdul Kareem", "nome_curto": "",
     "nome_ar": "حيدر عبد الكريم", "clube": "Al Ittihad",
     "posicao": "Zagueiro", "nacionalidade": "Iraque", "foto": "x.png"}])
ok(glossario.identidade("حيدر عبد الكريم") == {},
   "com duas pessoas caindo na mesma chave o glossário escolheu uma. "
   "Homônimo tem de virar 'não sei': citar o jogador errado num post é pior "
   "que não citar nenhum")
ok(glossario.jogadores_no_texto(TWEET) == [],
   "a varredura do texto pegou um dos dois homônimos. Aqui não há clube para "
   "desempatar, e um palpite vira nome errado publicado")
_plantar()


# ─────────────────────────────────────────────────────────────────────────
# 4. A VARREDURA DE TEXTO USA A CHAVE NOVA, E O DIAGNÓSTICO EXISTE
# ─────────────────────────────────────────────────────────────────────────
_varre = open(os.path.join(RAIZ, "glossario.py"), encoding="utf-8").read()
_i = _varre.index("def jogadores_no_texto(")
_corpo = _varre[_i:_varre.index("\ndef ", _i + 10)]
# A FORMA, e não a palavra solta: o comentário logo acima EXPLICA a chave
# composta, e procurar o nome dela no texto todo acharia a minha explicação.
# Esta suíte já se autocitou três vezes.
ok("glossary.chave_arabe_composta)" in _corpo
   or "glossary.chave_arabe_composta," in _corpo,
   "a varredura de texto voltou a rodar só com as duas chaves antigas. Unir "
   "as metades só no índice não adianta: a chave nova ficaria procurando por "
   "uma palavra que o texto nunca escreve junto")

ok('@app.get("/api/diag/nomes-arabes"' in FONTE,
   "sumiu o diagnóstico. Ele é o que diz, no glossário DELE, quantos jogadores "
   "a regra alcança e quantas chaves ela ambiguiza — sem isso a gente está "
   "confiando numa regra cujo efeito ninguém mediu")
_diag = FONTE[FONTE.index('@app.get("/api/diag/nomes-arabes"'):]
_diag = _diag[:_diag.index('@app.get("/api/diag/saude"')]

# O DIAGNÓSTICO, EXECUTADO CONTRA UM GLOSSÁRIO DE MENTIRA.
#
# Eu tinha escrito `ok("piorou" in _diag and "AMBIGUIZA" in _diag)`. Plantei o
# defeito que zera a conta — `piorou = []` — e o teste passou, claro: a palavra
# continuava lá. Procurar a palavra que eu mesmo escolhi não mede nada; o que
# mede é o NÚMERO que sai.
_i = _diag.index("    def _medir():")
_corpo_medir = _diag[_i:_diag.index("\n    linhas = [", _i)]
_corpo_medir = "\n".join(l[4:] if l.startswith("    ") else l
                         for l in _corpo_medir.split("\n"))
_amb: dict = {}
exec(_corpo_medir, _amb)
medir = _amb["_medir"]

# Sem homônimo: alcança o Hayder e o Hamdallah, e não ambiguiza nada.
_plantar()
_arabes, _alcanca, (_ex, _piorou, _sep) = medir()
ok(len(_alcanca) >= 2,
   f"o diagnóstico diz que a regra alcança {len(_alcanca)} grafias num "
   f"glossário em que ela alcança pelo menos duas (Hayder e Hamdallah). Ele "
   f"está medindo outra coisa")
ok(314 in {d["id"] for d, _, _, _ in _alcanca},
   "o diagnóstico não conta o jogador que originou tudo isto. Foi o meu "
   "primeiro critério: eu contava 'a chave muda com a regra', e a do Hayder "
   "não muda — a SPL já escreve عبدالكريم junto. Quem escreve separado é a "
   "notícia. Contar assim mediria um número que não é o do problema")
ok(7 in {d["id"] for d, _, _, _ in _alcanca},
   "o diagnóstico não conta o Hamdallah, que é o caso escrito SEPARADO no "
   "glossário. Ele tem de contar as duas direções")
ok(9 not in {d["id"] for d, _, _, _ in _alcanca},
   "o diagnóstico conta um jogador sem nome composto; ele infla o número e a "
   "decisão passa a ser tomada em cima de um total que não quer dizer nada")
ok(456 not in {d["id"] for d, _, _, _ in _alcanca},
   "o diagnóstico voltou a contar o Abdou Diallo (عبدو ديالو) como nome "
   "composto. Ele só parece: a regra nem encosta nele, e contá-lo apresenta "
   "um número maior do que o efeito, como se fosse o efeito")
ok(_sep == 1,
   f"o diagnóstico diz que {_sep} grafias estão escritas separado, quando é "
   f"uma (o Hamdallah). É a quebra que mostra de que lado está cada metade")
ok(_piorou == [],
   f"o diagnóstico inventou {len(_piorou)} ambiguidade(s) num glossário que "
   f"não tem nenhuma; ele assustaria à toa")

# Com os dois homônimos, ele TEM de acusar. É a única informação que justifica
# confiar na regra — ou não.
_plantar(fichas=FICHAS + [
    {"id": 315, "spl_id": "s315", "af_id": 8888, "tm_id": "8888",
     "nome_principal": "Haider Abdul Kareem", "nome_curto": "",
     "nome_ar": "حيدر عبد الكريم", "clube": "Al Ittihad",
     "posicao": "Zagueiro", "nacionalidade": "Iraque", "foto": "x.png"}])
_arabes, _alcanca, (_ex, _piorou, _sep) = medir()
ok(len(_piorou) == 1,
   f"o diagnóstico acusou {len(_piorou)} ambiguidade(s) onde há exatamente "
   f"uma: duas pessoas cujo nome árabe só difere pelo espaço do عبد. Contar "
   f"só o que a regra alcança, e não o que ela custa, é propaganda")
if _piorou:
    ok(set(_piorou[0][1]) == {314, 315},
       f"a ambiguidade acusada não é a dos dois homônimos: {_piorou[0]!r}")
_plantar()
for proibido in ("INSERT", "UPDATE", "DELETE"):
    ok(proibido not in _diag,
       f"o diagnóstico passou a escrever no banco ({proibido}). Ele é uma "
       f"leitura e uma conta; medir não pode mudar o que está sendo medido")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ o espaço do عبد não esconde mais o jogador, e os clubes não mudaram")
