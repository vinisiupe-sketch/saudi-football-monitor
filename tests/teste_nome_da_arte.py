"""Qual nome vai na imagem é escolha dele, e a prévia não pode discordar dela.

A PERGUNTA (16/09/26)
    Ele abriu a ficha do goleiro do Al-Hilal, viu "Yassine Bounou #37", baixou
    a arte e ela saiu "BONO".

        "me explica pq a padronização do nome no card tá diferente da imagem
         que geramos?"

    Era decisão minha, escrita no meio da rota e nunca mostrada a ele: a arte
    preferia o `nome_curto` do glossário. As duas saídas são defensáveis —
    ninguém narra "Yassine Bounou pegou", narra "o Bono pegou" — e ele mesmo
    tinha dito na mensagem anterior o que importava: "precisamos padronizar".

    Ele recusou as três opções que ofereci e pediu a quarta:

        "Nenhum dos 3. Vira opção nas configurações pra eu selecionar o que eu
         achar melhor."

O QUE ESTE ARQUIVO VIGIA, em ordem de importância
    1. QUE A ESCOLHA DELE É EXECUTADA. Conferir que a linha certa está escrita
       não diz nada sobre qual nome SAI — e o nome que sai é a coisa toda. Por
       isso eu recorto a função do main.py e rodo de verdade.
    2. Que os rótulos das opções em ajustes.py são exatamente as palavras que
       o código compara. Se as duas pontas desandarem, a tela oferece uma opção
       que não faz nada — e opção que não faz nada é pior que opção nenhuma.
    3. Que a caixa de ajuste anuncia o MESMO nome que a imagem vai trazer. Era
       a caixa que dizia "Bono · todas as competições"; se ela continuasse
       aplicando a regra por conta própria, voltaríamos à mesma pessoa com dois
       nomes na mesma tela.
    4. Que a inicial solta continua fora dos dois caminhos.
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

import ajustes                                            # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# 1. O AJUSTE EXISTE, E COM OS RÓTULOS QUE O CÓDIGO COMPARA
# ─────────────────────────────────────────────────────────────────────────
A = ajustes.POR_CHAVE.get("arte_nome")
ok(A is not None,
   "sumiu o ajuste 'arte_nome'. Sem ele a arte volta a decidir sozinha qual "
   "nome usar, que foi exatamente o que ele pegou")

if A:
    OPCOES = A["opcoes"]
    ok(OPCOES == ["como é chamado", "o mesmo das telas"],
       f"as opções viraram {OPCOES!r}. O `_nome_para_arte` COMPARA com o texto "
       f"literal 'o mesmo das telas'; mudar o rótulo aqui sem mudar lá deixa a "
       f"tela oferecendo uma escolha que não muda nada")
    ok(A["padrao"] in OPCOES,
       "o padrão do ajuste não é uma das opções; a tela mostraria um valor que "
       "ela mesma não oferece")
    ok(A["padrao"] == "como é chamado",
       "o padrão mudou. Não é errado, mas é uma troca silenciosa de "
       "comportamento para todas as artes que ele já publicou com o apelido — "
       "se for de propósito, atualize esta linha junto")
    ok(A["grupo"] in ajustes.grupos(),
       "o grupo do ajuste sumiu da lista de grupos")
    # E O GRUPO TEM DE ESTAR NUMA SEÇÃO. Grupo órfão cai em "Outros" e não
    # desaparece — mas "Outros" é onde os ajustes ficam quando alguém esqueceu
    # deles, e este nasceu de um pedido direto.
    _secoes = [s for s in ajustes.secoes() if A["grupo"] in s["grupos"]]
    ok(len(_secoes) == 1 and _secoes[0]["chave"] != "outros",
       f"o grupo '{A['grupo']}' não tem seção própria na guia de "
       f"Configurações — ele foi parar em "
       f"{[s['chave'] for s in _secoes] or 'lugar nenhum'}")


# ─────────────────────────────────────────────────────────────────────────
# 2. A ESCOLHA, EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
# Recorto a função do main.py e rodo com um banco de mentira. O `ficha_arte`
# é o de verdade: é lá que mora a regra da inicial solta, e testá-la contra
# uma cópia minha não provaria nada.
_i = FONTE.index("def _nome_para_arte(")
CORPO = FONTE[_i:FONTE.index("\ndef _nome_de_arquivo", _i)]

ESCOLHA = [None]

# O BANCO DE MENTIRA VAI NO MÓDULO DE VERDADE, e não num `_db` que eu entrego
# pronto no ambiente do exec.
#
# ISTO AQUI JÁ ME PEGOU, e pegou caro. Na primeira versão deste arquivo eu
# escrevi `ambiente = {"_db": _BancoDeMentira}`. Só que `_db` NÃO existe no
# escopo do main.py: é um apelido local, `import database as _db`, feito dentro
# de cada função que precisa. Eu esqueci o import no `_nome_para_arte`, o
# NameError caiu no `except` de lá, a escolha virou o padrão — e a arte saiu
# "BONO" com a configuração dele marcada em "o mesmo das telas". O teste passou
# porque eu estava fornecendo justamente a peça que faltava.
#
# É a segunda vez na mesma semana que eu injeto o valor que deveria estar
# conferindo. Agora o ambiente do exec vai VAZIO: a função que se vire para
# achar o que precisa, como ela vai ter de fazer no servidor.
import database                                           # noqa: E402

_real_valor_de_ajuste = database.valor_de_ajuste


def _valor_de_mentira(chave):
    assert chave == "arte_nome", f"leu o ajuste errado: {chave!r}"
    return ESCOLHA[0]


database.valor_de_ajuste = _valor_de_mentira

ambiente: dict = {}
exec(CORPO, ambiente)
nome_da_arte = ambiente["_nome_para_arte"]

# E A PROVA DE QUE O AMBIENTE ESTAVA MESMO VAZIO: se alguém reintroduzir a
# muleta, este teste volta a ser decorativo.
ok("_db" not in ambiente or ambiente.get("_db") is None
   or getattr(ambiente.get("_db"), "__name__", "") == "database",
   "o ambiente do exec ganhou um `_db` que não veio do import do próprio "
   "main.py. Foi assim que um NameError passou despercebido e a escolha dele "
   "não valeu nada")

BONO = {"nome": "Yassine Bounou", "nome_curto": "Bono"}

if A:
    APELIDO, DAS_TELAS = A["opcoes"][0], A["opcoes"][1]

    ESCOLHA[0] = APELIDO
    ok(nome_da_arte(BONO) == "Bono",
       f"com '{APELIDO}' escolhido a arte saiu {nome_da_arte(BONO)!r} em vez "
       f"de 'Bono'. É o nome do placar da transmissão, e era o comportamento "
       f"que ele já tinha")

    ESCOLHA[0] = DAS_TELAS
    ok(nome_da_arte(BONO) == "Yassine Bounou",
       f"com '{DAS_TELAS}' escolhido a arte saiu {nome_da_arte(BONO)!r}. A "
       f"opção existe justamente para a imagem dizer o mesmo que a ficha diz — "
       f"assim ela não faz nada, e o Vini não teria como saber")

    # O PADRÃO TEM DE BATER COM O QUE O BANCO DEVOLVE QUANDO NINGUÉM ESCOLHEU.
    # O `valor_de_ajuste` já devolve o padrão do ajustes.py nesse caso; se um
    # dia parar de devolver, a arte passaria a obedecer a um padrão diferente
    # do que a tela exibe como padrão — e os dois pareceriam certos.
    ESCOLHA[0] = A["padrao"]
    _com_padrao = nome_da_arte(BONO)
    ESCOLHA[0] = None
    ok(nome_da_arte(BONO) == _com_padrao,
       f"sem nada escolhido a arte saiu {nome_da_arte(BONO)!r}, e com o padrão "
       f"do ajustes.py ({A['padrao']!r}) ela sai {_com_padrao!r}. A tela "
       f"mostraria um padrão e a arte obedeceria a outro")

# ── SEM NOME CURTO, OS DOIS CAMINHOS DÃO NO MESMO ────────────────────────
SO_PRINCIPAL = {"nome": "Ângelo Gabriel", "nome_curto": ""}
for escolha in (A["opcoes"] if A else []):
    ESCOLHA[0] = escolha
    ok(nome_da_arte(SO_PRINCIPAL) == "Ângelo Gabriel",
       f"com '{escolha}' quem não tem nome curto no glossário saiu "
       f"{nome_da_arte(SO_PRINCIPAL)!r} — ficaria sem nome na arte")

# ── A INICIAL SOLTA CONTINUA FORA DOS DOIS CAMINHOS ──────────────────────
#
# Foi o defeito original que ele relatou como "corta após a primeira letra":
# o curto do glossário vem "S. Milinković-Savić" e a arte gastava uma linha
# inteira com um "S".
SERGEJ = {"nome": "Sergej Milinković-Savić", "nome_curto": "S. Milinković-Savić"}
for escolha in (A["opcoes"] if A else []):
    ESCOLHA[0] = escolha
    ok(nome_da_arte(SERGEJ) == "Sergej Milinković-Savić",
       f"com '{escolha}' o nome saiu {nome_da_arte(SERGEJ)!r}. A inicial solta "
       f"volta a ocupar uma linha inteira da arte com um 'S'")

# E QUANDO SÓ EXISTE A GRAFIA COM INICIAL, ela ainda é melhor que nada: quem
# joga a inicial fora é o `quebrar_nome`, na hora de desenhar.
SO_INICIAL = {"nome": "S. Milinković-Savić", "nome_curto": ""}
for escolha in (A["opcoes"] if A else []):
    ESCOLHA[0] = escolha
    ok(nome_da_arte(SO_INICIAL) == "S. Milinković-Savić",
       f"com '{escolha}' um jogador cuja única grafia tem inicial ficou sem "
       f"nome nenhum na arte")

# ── BANCO CAÍDO NÃO DERRUBA A ARTE ───────────────────────────────────────
def _explode(chave):
    raise RuntimeError("banco fora do ar")


database.valor_de_ajuste = _explode
try:
    _r = nome_da_arte(BONO)
    ok(_r == "Bono",
       f"com o banco fora do ar a arte saiu {_r!r}; devia cair no "
       f"comportamento antigo, que é o apelido")
except Exception as e:
    falhas.append(f"o banco fora do ar derrubou a montagem da arte: "
                  f"{type(e).__name__}: {e}. Um ajuste que não pôde ser lido "
                  f"não pode impedir a imagem de existir")

# ── E NÃO PODE QUEBRAR COM DICIONÁRIO VAZIO ──────────────────────────────
database.valor_de_ajuste = _valor_de_mentira
ESCOLHA[0] = A["padrao"] if A else None
try:
    ok(nome_da_arte({}) == "",
       "jogador sem nome nenhum devolveu alguma coisa inventada")
    nome_da_arte({"nome": None, "nome_curto": None})
except Exception as e:
    falhas.append(f"o nome da arte quebrou com campos vazios: "
                  f"{type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 3. UM LUGAR SÓ DECIDE — A ROTA E A CAIXA LEEM DELE
# ─────────────────────────────────────────────────────────────────────────
rota = FONTE[FONTE.index("async def api_jogador_arte("):]
rota = rota[:rota.index("\ndef _nome_para_arte")]
ok("nome = _nome_para_arte(j)" in rota,
   "a rota da arte parou de perguntar qual nome usar; ela voltaria a decidir "
   "por conta própria e a escolha dele nas Configurações não valeria")
ok("melhor_nome(" not in rota,
   "a rota da arte voltou a chamar o `melhor_nome` direto. Aí são duas regras "
   "escritas em dois lugares, e elas só precisam divergir uma vez")

ficha = FONTE[FONTE.index("async def _ficha_do_jogador("):]
ficha = ficha[:ficha.index("\ndef _idade_em_anos")]
ok('"nome_arte": _nome_para_arte(f)' in ficha,
   "a ficha parou de publicar o `nome_arte`. A caixa de ajuste ficaria sem o "
   "nome que a imagem vai trazer, e teria de adivinhar de novo")

_js = FONTE[FONTE.index("function abrirCaixaDaArte()"):]
_js = _js[:_js.index("\nfunction ", _js.index("arte-controles"))]
ok("g.nome_arte" in _js,
   "o cabeçalho da caixa de ajuste parou de ler o `nome_arte` que o servidor "
   "manda")
# E NÃO PODE APLICAR A REGRA SOZINHO. Era assim que estava escrito, e é o
# motivo de a caixa anunciar "Bono" com a ficha ao lado dizendo "Yassine
# Bounou". Procuro a FORMA do código, e não a palavra solta: o comentário
# logo acima da linha explica o que mudou, e citar-se a si mesmo é o erro que
# esta suíte já cometeu três vezes.
ok("g.nome_curto ||" not in _js,
   "a caixa de ajuste voltou a escolher o nome sozinha, com uma segunda cópia "
   "da regra. Ela anunciaria um nome e a imagem embaixo traria outro — a "
   "mesma pessoa com dois nomes na mesma tela")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ o nome da arte é escolha dele, e a prévia diz o mesmo que a imagem")
