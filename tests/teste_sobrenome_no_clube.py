"""O sobrenome solto, resolvido dentro do elenco — e só quando é inequívoco.

O QUE ELE VIU (20/09/26)
    A guia de Lesões mostrava "Nández" e "Bouabré" com o selo SEM ID, e ele
    perguntou se eu não estava conseguindo resolver a padronização.

    A notícia escreve só o sobrenome. O `identidade` é consulta EXATA de
    propósito — é isso que faz o glossário ser autoridade em vez de mais um
    palpite na pilha, e foi a inversão que ele mesmo pediu em setembro.

    Só que nestes casos não há palpite a dar: "Nández" é uma palavra do nome
    de EXATAMENTE UM jogador do Al Qadsiah. Não é distância de edição, não é
    "parecido o bastante". É igualdade de palavra, dentro de um elenco de
    trinta pessoas, com unicidade exigida.

O QUE ESTE ARQUIVO VIGIA — as guardas, uma a uma
    Sem elas isto vira a heurística de que o projeto saiu. Cada uma existe
    porque a sua ausência produz um erro específico e caro.
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

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


FICHAS = [
    {"id": 1, "spl_id": "s1", "nome_principal": "Nahitan Nández",
     "nome_curto": "Nández", "clube": "Al-Qadsiah FC", "foto": "n.png"},
    {"id": 2, "spl_id": "s2", "nome_principal": "Saïmon Bouabré",
     "nome_curto": "Bouabré", "clube": "Al Hilal", "foto": "b.png"},
    {"id": 3, "spl_id": "s3", "nome_principal": "Ali Lajami",
     "nome_curto": "Lajami", "clube": "Al Hilal", "foto": "l.png"},
    # Dois "Ali" no mesmo elenco: é o caso que exige a unicidade.
    {"id": 4, "spl_id": "s4", "nome_principal": "Ali Al-Bulayhi",
     "nome_curto": "Al-Bulayhi", "clube": "Al Hilal", "foto": "x.png"},
    # Um homônimo de sobrenome em OUTRO clube: o escopo por elenco é o que
    # impede que ele atrapalhe.
    {"id": 5, "spl_id": "s5", "nome_principal": "Outro Nández",
     "nome_curto": "Nández", "clube": "Al Hilal", "foto": "y.png"},
]
database.glossario_completo = lambda: ([dict(f) for f in FICHAS], [])
database.valor_de_ajuste = lambda c: "melhor disponível"
glossario.recarregar()


def _nome(**k):
    return (glossario.so_no_clube(**k) or {}).get("nome_principal") or ""


# ── O CASO DELE ─────────────────────────────────────────────────────────
ok(_nome(nome="Nández", clube="Al Qadsiah") == "Nahitan Nández",
   "o 'Nández' da notícia continua sem identidade. Era o selo SEM ID que ele "
   "viu na guia de Lesões com o glossário cheio")
ok(_nome(nome="Bouabré", clube="Al Hilal") == "Saïmon Bouabré",
   "o 'Bouabré' continua sem identidade")
ok(_nome(nome="Lajami", clube="Al Hilal") == "Ali Lajami",
   "o 'Lajami' continua sem identidade")

# E O CLUBE PODE VIR ESCRITO DE OUTRO JEITO: a notícia diz "Al Qadsiah" e o
# glossário diz "Al-Qadsiah FC". Os dois lados passam pelo padronizador.
ok(_nome(nome="Nández", clube="Al-Qadsiah FC") == "Nahitan Nández",
   "o escopo por clube quebrou quando a grafia do clube mudou; a notícia e o "
   "glossário escrevem o nome do clube de jeitos diferentes, e é exatamente "
   "esse o normal")


# ── AS GUARDAS ──────────────────────────────────────────────────────────
ok(_nome(nome="Ali", clube="Al Hilal") == "",
   "'Ali' é palavra do nome de DOIS jogadores do Al Hilal e mesmo assim foi "
   "resolvido. Unicidade é a guarda que separa isto de adivinhação — citar o "
   "jogador errado num post é o erro que vira retratação no ar")

ok(_nome(nome="Nández", clube="") == "",
   "sem clube o universo é a liga inteira, e aí um sobrenome comum acha dez "
   "pessoas. O escopo por elenco é o que torna a igualdade de palavra "
   "suficiente")

ok(_nome(nome="Nan", clube="Al Qadsiah") == "",
   "um pedaço de palavra foi aceito. A igualdade tem de ser da palavra "
   "INTEIRA: 'Nan' não é 'Nández', e aceitar prefixo é reabrir a porta da "
   "semelhança de texto")

ok(_nome(nome="Al", clube="Al Hilal") == "",
   "uma palavra de duas letras foi aceita; 'Al' aparece em metade dos nomes "
   "desta liga")

ok(_nome(nome="Nahitan Nández", clube="Al Qadsiah") == "",
   "um nome de duas palavras entrou por esta porta. Quem manda o nome "
   "completo já devia ter sido achado pela consulta EXATA, que é a "
   "autoridade; deixar passar aqui cria um segundo caminho para a mesma "
   "pergunta, e dois caminhos divergem")

ok(_nome(nome="Bouabré", clube="Al Nassr") == "",
   "o sobrenome foi achado num clube onde o jogador não está. O escopo é o "
   "elenco, e não a liga")

ok(_nome(nome="Ninguém", clube="Al Hilal") == "" and _nome(nome="", clube="Al Hilal") == "",
   "a porta respondeu por quem não existe")

# ── O ESCOPO POR ELENCO RESOLVE O HOMÔNIMO ENTRE CLUBES ─────────────────
ok(_nome(nome="Nández", clube="Al Hilal") == "Outro Nández",
   "dois jogadores com o mesmo sobrenome em clubes DIFERENTES deviam ser "
   "resolvidos cada um no seu — é para isso que o escopo existe")


# ── A ORDEM NO IDENTIFICADOR: exata primeiro, sobrenome depois ──────────
_i = FONTE.index("def _identificar_jogador(")
_corpo = FONTE[_i:FONTE.index("\ndef _chave_de_nome", _i)]
_sem_comentario = "\n".join(l for l in _corpo.split("\n")
                            if not l.strip().startswith("#"))
ok("glossario.so_no_clube(nome, clube)" in _sem_comentario,
   "o identificador parou de tentar o sobrenome dentro do elenco; o 'Nández' "
   "volta ao selo SEM ID")
ok(_sem_comentario.index("glossario.identidade")
   < _sem_comentario.index("glossario.so_no_clube"),
   "o sobrenome passou a ser tentado ANTES da consulta exata. A exata é a "
   "autoridade e tem de mandar quando responde; inverter faz um apelido "
   "ganhar de um nome cadastrado")
ok(_sem_comentario.index("glossario.so_no_clube")
   < _sem_comentario.index("_e_nome_de_clube_da_liga"),
   "o sobrenome é tentado DEPOIS da desistência, e aí nunca roda para jogador "
   "de clube da liga — que é justamente o caso dele")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ sobrenome resolvido no elenco, e só quando é inequívoco")
