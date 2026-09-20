"""O clube também é uma entidade, com id interno e os três externos pendurados.

O MODELO QUE ELE DESENHOU (20/09/26)
    Ele mandou o star schema e apontou o que faltava:

        "Repare que as tabelas ao redor se conectam à DIM_JOGADOR por meio da
         chave primária jogador_id_interno. A lógica central é simples: todas
         as fontes externas devem convergir para esse ID interno. (...) Para
         clubes, a mesma arquitetura: fonte externa → ID externo do clube →
         clube_id_interno → DIM_CLUBE → nome, escudo e demais dados
         padronizados."

    O glossário de JOGADOR era exatamente isso desde setembro. O clube não era
    nada: um campo de TEXTO dentro da ficha do jogador, e cada tela resolvendo
    nome e escudo por conta própria, comparando string com string.

    O Al Nasr de Dubai aparecendo no lugar do Al-Nassr de Riade não foi um
    descuido pontual — foi o sintoma de não existir a entidade. Trancar a
    tabela mundial, como fiz na véspera, era remendo; o buraco era este.

O QUE ESTE ARQUIVO VIGIA
    1. Que as quatro portas respondem: af_id, tm_id, spl_id e nome.
    2. Que a mesma entidade devolve SEMPRE o mesmo nome e o mesmo escudo,
       venha a pergunta de onde vier — que é o pedido por extenso.
    3. Que o escudo sai do ID, e nunca de casamento por nome.
    4. Que ambiguidade continua virando "não sei", e que a ficha não vira
       homônima de si mesma (foi o primeiro defeito que eu plantei aqui).
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

import database                                           # noqa: E402
import glossario                                          # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


CLUBES = [
    {"id": 1, "nome_canonico": "Al Nassr", "nome_curto": "Nassr",
     "spl_id": "spl-1", "af_id": 2939, "tm_id": "18544", "escudo": "",
     "revisado": False},
    {"id": 2, "nome_canonico": "Al Hilal", "nome_curto": "Hilal",
     "spl_id": "spl-2", "af_id": 2932, "tm_id": "1885", "escudo": "",
     "revisado": False},
    # O clube SEM id externo: existe no glossário e não tem escudo. É a linha
    # que separa "ainda não cruzei" de "pode emprestar o de outro".
    {"id": 3, "nome_canonico": "Al Okhdood", "nome_curto": "", "spl_id": None,
     "af_id": None, "tm_id": None, "escudo": "", "revisado": False},
]
GRAFIAS = [
    {"clube_id": 1, "fonte": "semeadura", "idioma": "lat",
     "nome": "Al-Nassr FC", "nome_normalizado": ""},
    {"clube_id": 1, "fonte": "noticia", "idioma": "ar",
     "nome": "النصر", "nome_normalizado": ""},
]


def _plantar(clubes=None, grafias=None):
    database.clubes_completos = lambda: (
        [dict(c) for c in (CLUBES if clubes is None else clubes)],
        [dict(g) for g in (GRAFIAS if grafias is None else grafias)])
    glossario._CACHE_CLUBE["dados"] = None
    glossario._CACHE_CLUBE["quando"] = 0.0


_plantar()


# ─────────────────────────────────────────────────────────────────────────
# 1. AS QUATRO PORTAS, E A MESMA RESPOSTA EM TODAS
# ─────────────────────────────────────────────────────────────────────────
PERGUNTAS = [
    {"af_id": 2939}, {"tm_id": "18544"}, {"spl_id": "spl-1"},
    {"nome": "Al Nassr"}, {"nome": "Al-Nassr FC"}, {"nome": "AlNassr"},
    {"nome": "Nassr"}, {"nome": "النصر"},
]
respostas = [glossario.clube(**p) for p in PERGUNTAS]
for p, r in zip(PERGUNTAS, respostas):
    ok(r.get("id") == 1,
       f"a pergunta {p} não achou o Al Nassr; devolveu {r.get('nome') or '{}'}. "
       f"É o de-para inteiro que para de funcionar por essa porta")

nomes = {r.get("nome") for r in respostas}
escudos = {r.get("escudo") for r in respostas}
ok(len(nomes) == 1 and len(escudos) == 1,
   f"a MESMA entidade saiu com {len(nomes)} nomes e {len(escudos)} escudos "
   f"dependendo da porta: {nomes} / {escudos}. O pedido é literalmente o "
   f"contrário — 'o mesmo clube sempre apareça com o mesmo nome e o mesmo "
   f"escudo, independentemente da guia ou da fonte'")

# ── O ESCUDO SAI DO ID ───────────────────────────────────────────────────
ok("2939" in (respostas[0].get("escudo") or ""),
   f"o escudo não é derivado do id da API-Football: {respostas[0].get('escudo')}. "
   f"O número dentro da URL é o que impede um homônimo de entrar no lugar")
ok(glossario.clube(af_id=2932).get("escudo")
   != glossario.clube(af_id=2939).get("escudo"),
   "dois clubes diferentes saíram com o mesmo escudo")

# ── SEM ID EXTERNO, SEM ESCUDO — e isso é a regra, não a falha ───────────
_sem = glossario.clube(nome="Al Okhdood")
ok(_sem.get("id") == 3, "o clube sem ids externos sumiu do glossário")
ok(_sem.get("escudo") == "",
   f"o clube sem id da API-Football ganhou um escudo ({_sem.get('escudo')}). "
   f"Lacuna de cadastro não é licença para adivinhar: emprestar o emblema de "
   f"um homônimo é o defeito que derrubou isto duas vezes")

# ── O ESCUDO ESCRITO À MÃO GANHA do derivado ────────────────────────────
_plantar(clubes=[dict(CLUBES[0], escudo="https://eu/escolhi/este.png")])
ok(glossario.clube(af_id=2939).get("escudo") == "https://eu/escolhi/este.png",
   "o escudo que ele escreveu à mão foi ignorado em favor do derivado; a "
   "coluna existe justamente para ele corrigir um caso específico")
_plantar()


# ─────────────────────────────────────────────────────────────────────────
# 2. AMBIGUIDADE VIRA "NÃO SEI" — MAS A FICHA NÃO É HOMÔNIMA DE SI MESMA
# ─────────────────────────────────────────────────────────────────────────
# ESTE FOI O PRIMEIRO DEFEITO QUE EU PLANTEI AQUI, sem querer: o "Al Nassr"
# tem nome canônico "Al Nassr" e nome curto "Nassr", e o `padronizar_clube`
# leva os dois para a mesma chave — como deve. Sem conferir o id, a ficha
# entrava duas vezes na mesma lista e a consulta a descartava por
# "ambiguidade". O clube virava homônimo de si mesmo.
ok(glossario.clube(nome="Nassr").get("id") == 1,
   "a ficha voltou a ser contada duas vezes no índice e virou homônima de si "
   "mesma; a consulta por nome devolve {} para um clube que existe")

# E A GUARDA DE VERDADE CONTINUA: dois clubes diferentes com o mesmo nome
# normalizado têm de virar silêncio, e não um palpite.
_plantar(clubes=CLUBES + [{"id": 9, "nome_canonico": "Al Nassr",
                           "nome_curto": "", "spl_id": None, "af_id": 9999,
                           "tm_id": None, "escudo": "", "revisado": False}])
ok(glossario.clube(nome="Al Nassr") == {},
   "com dois clubes no mesmo nome normalizado a consulta escolheu um. É o "
   "caso Riade/Dubai: o certo é não responder")
ok(glossario.clube(af_id=2939).get("id") == 1,
   "a ambiguidade de NOME contaminou a consulta por ID — e o id é justamente "
   "o que existe para não ter ambiguidade")
_plantar()

ok(glossario.clube() == {} and glossario.clube(nome="Time Inventado") == {},
   "o glossário respondeu por clube que ele não conhece")
ok(glossario.clube(af_id=123456) == {},
   "um id que não está no glossário devolveu alguma coisa")


# ─────────────────────────────────────────────────────────────────────────
# 3. O ESCUDO DAS TELAS PASSA PELO DIM_CLUBE
# ─────────────────────────────────────────────────────────────────────────
i = FONTE.index("def _escudo_de_clube(nome: str, da_liga: dict, do_mundo: dict)")
# Leva o `_do_indice` junto: é ele que compara os dois lados normalizados.
PORTA = FONTE[i:FONTE.index("\ndef _escudo_do_clube_pelo_nome")]
_sem_comentario = "\n".join(l for l in PORTA.split("\n")
                            if not l.strip().startswith("#"))
ok("glossario.clube(nome=nome)" in _sem_comentario,
   "a porta do escudo parou de perguntar ao DIM_CLUBE. Ela volta a decidir "
   "por tabela de nome, que é de onde o Al Nasr de Dubai saiu")
ok(_sem_comentario.index("glossario.clube")
   < _sem_comentario.index("_do_indice(da_liga"),
   "o DIM_CLUBE deixou de ser a PRIMEIRA pergunta; as tabelas de nome voltaram "
   "a responder antes da entidade")

amb = {}
exec(PORTA, amb)
_porta = amb["_escudo_de_clube"]
LIGA = {"Al-Nassr": "riade-por-nome.png"}
# O "Al Okhdood" ENTRA NA TABELA DO MUNDO de propósito: sem ele ali, o teste
# do clube sem id externo passava mesmo com a tranca removida — o resultado
# era vazio porque não havia o que emprestar, e não porque a regra funcionava.
# A armadilha precisa estar armada para a conferência querer dizer algo.
MUNDO = {"Al-Nassr": "dubai.png", "Al Nasr": "dubai.png",
         "Al Okhdood": "de-outro-time.png", "Chelsea": "chelsea.png"}
ok("2939" in _porta("Al Nassr", LIGA, MUNDO),
   f"o escudo do Al Nassr veio de tabela de nome "
   f"({_porta('Al Nassr', LIGA, MUNDO)}) em vez do id do DIM_CLUBE")
ok(_porta("Al Okhdood", LIGA, MUNDO) == "",
   "o clube que está no DIM_CLUBE sem id externo pegou escudo emprestado de "
   "uma tabela de nome")
ok(_porta("Chelsea", LIGA, MUNDO) == "chelsea.png",
   "clube de fora da liga, que não está no DIM_CLUBE, ficou sem escudo — a "
   "tabela do mundo é a única que tem o emblema dele")


# ─────────────────────────────────────────────────────────────────────────
# 4. A SEMEADURA: a única vez que nome é comparado com nome
# ─────────────────────────────────────────────────────────────────────────
ok("def semear_clubes(" in BANCO, "sumiu a semeadura do DIM_CLUBE")
_semear = BANCO[BANCO.index("def semear_clubes("):]
_semear = _semear[:_semear.index("\ndef ")]
_sql = "\n".join(l for l in _semear.split("\n")
                 if not l.strip().startswith("#"))
ok("COALESCE(af_id, %s)" in _sql and "COALESCE(tm_id, %s)" in _sql,
   "a semeadura parou de usar COALESCE na ordem certa. Ela roda de novo a "
   "cada temporada, e sem isso passa por cima do id que ele já tinha "
   "conferido — a ordem COALESCE(o_que_ja_tem, o_novo) e a inversa são "
   "idênticas de relance")
ok("partida_liga" in _sql, "a semeadura parou de ler o id da API-Football do "
                           "calendário, que é o que dá o escudo")
ok("elenco_congelado" in _sql,
   "a semeadura parou de ler o id do Transfermarkt do elenco congelado")
ok("glossario_lab_jogador" in _sql,
   "a semeadura parou de ler os clubes do próprio glossário de jogadores")

ok("CREATE TABLE IF NOT EXISTS glossario_lab_clube" in BANCO,
   "sumiu a tabela do DIM_CLUBE")
ok("CREATE TABLE IF NOT EXISTS glossario_lab_clube_nome" in BANCO,
   "sumiu a tabela de grafias do clube — é ela que faz 'Al-Nassr', 'النصر' e "
   "'Al Nassr FC' caírem na mesma entidade")
ok('@app.post("/api/clubes/semear")' in FONTE and
   '@app.get("/api/diag/clubes"' in FONTE,
   "sumiu a rota de semeadura ou a de diagnóstico do DIM_CLUBE")

import coletas                                            # noqa: E402
ok("clubes" in coletas.POR_CHAVE,
   "o cadastro dos clubes não aparece na tela de Coletas; ele roda uma vez "
   "por temporada e ninguém saberia que existe")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ DIM_CLUBE: quatro portas, uma identidade, e o escudo pelo id")
