"""
O escudo do clube sai do ID, e o botão traz as outras competições.

O QUE O VINI VIU (15/09/26)
    "O logo do Al Nassr diferente. Já superamos isto! Temos um GLOSSÁRIO! Se
    temos um glossário, como você ainda tá pareando um logo por assimilação de
    nome se cada jogador tem um time vinculado? Você colocou o logo do Al Nassr
    de dubai. Que gambiarra é esta que tá fazendo?"

    Ele estava certo, e o pior é que o erro tinha nome e endereço: a consulta
    que monta a ficha já devolvia `casa_id` e `fora_id` em toda linha, e eu
    pegava o `adversario` (texto) para procurar numa tabela de escudos do mundo
    inteiro cuja chave é o nome normalizado. "Al-Nassr" (Riade) e "Al Nasr"
    (Dubai) caem na mesma chave. Havia um número exato sendo ignorado ao lado
    de um nome sendo adivinhado.

    Na mesma mensagem: "as outras competições seguem sem aparecer". A
    descoberta dos jogos de AFC e Copa do Rei existia, mas num endereço
    separado que ele teria de abrir na mão — o que na prática é não existir.

O QUE ESTE ARQUIVO VIGIA
    1. Que o escudo vem do id e não do nome.
    2. Que a ficha usa o lado CERTO: o adversário de quem jogou em casa é o
       visitante, não o mandante.
    3. Que a tela de lesões pergunta à tabela da liga ANTES da tabela mundial —
       e que a ordem é de verdade, e não um `update` que só funciona quando as
       duas grafam o nome igual.
    4. Que "Completar agora" atualiza as competições antes de ler.
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

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def conferir(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# 1. O escudo sai do número
# ─────────────────────────────────────────────────────────────────────────
from database import escudo_de_af_id  # noqa: E402

conferir(escudo_de_af_id(2939).endswith("/2939.png"),
         "escudo_de_af_id deveria montar o endereço com o id dentro")
conferir(escudo_de_af_id(0) == "", "id zero é 'não sei', não é um clube")
conferir(escudo_de_af_id(None) == "", "id ausente tem de devolver vazio")
conferir(escudo_de_af_id("") == "", "id vazio tem de devolver vazio")
conferir(escudo_de_af_id("abc") == "", "id que não é número não pode explodir")
conferir(escudo_de_af_id(-5) == "", "id negativo não é clube")

# O ponto todo: dois clubes diferentes, dois escudos diferentes. É isto que a
# busca por nome não conseguia garantir.
conferir(escudo_de_af_id(2939) != escudo_de_af_id(10515),
         "dois ids diferentes têm de dar escudos diferentes — era exatamente "
         "isto que colidia quando a chave era o nome")


# ─────────────────────────────────────────────────────────────────────────
# 2. A ficha escolhe o lado certo
# ─────────────────────────────────────────────────────────────────────────
# Recorto o trecho da rota e executo com as partidas inventadas, em vez de
# procurar o texto do código: teste que confere se uma linha existe passa
# quando a linha existe e está errada.
i = FONTE.index("    for p in partidas:\n        do_adversario =")
j = FONTE.index("p[\"competicao\"] =", i)
j = FONTE.index("\n", j) + 1
TRECHO = FONTE[i:j]
conferir("casa_id" in TRECHO and "fora_id" in TRECHO,
         "o trecho recortado não é o que eu pensava — confira o teste")

partidas = [
    # Ele jogou EM CASA: o adversário é o visitante (id 99).
    {"em_casa": True, "casa_id": 2939, "fora_id": 99, "liga_nome": "AFC"},
    # Ele jogou FORA: o adversário é o mandante (id 77).
    {"em_casa": False, "casa_id": 77, "fora_id": 2939, "liga_nome": ""},
    # Partida sem ids: não pode inventar escudo nenhum.
    {"em_casa": True, "casa_id": None, "fora_id": None, "liga_nome": ""},
]
ambiente = {"partidas": partidas, "escudo_de_af_id": escudo_de_af_id}
exec(TRECHO.replace("    for p in partidas:", "for p in partidas:")
          .replace("\n        ", "\n    "), ambiente)

conferir(partidas[0]["escudo_adversario"] == escudo_de_af_id(99),
         "jogando em casa, o adversário é o VISITANTE — saiu o escudo errado")
conferir(partidas[1]["escudo_adversario"] == escudo_de_af_id(77),
         "jogando fora, o adversário é o MANDANTE — saiu o escudo errado")
conferir(partidas[2]["escudo_adversario"] == "",
         "sem id não há escudo; vazio é honesto, escudo chutado não")
conferir(partidas[0]["competicao"] == "AFC",
         "a competição da partida tem de vir da partida")
conferir(partidas[1]["competicao"] == "Saudi Pro League",
         "sem nome de competição, o padrão é a liga")

# E o escudo DELE: sai do lado que era o dele.
k = FONTE.index("    escudo_dele = \"\"\n    for p in partidas:")
m = FONTE.index("    if not escudo_dele:", k)
DELE = FONTE[k:m]
amb2 = {"partidas": partidas, "escudo_de_af_id": escudo_de_af_id}
exec("\n".join(l[4:] if l.startswith("    ") else l
               for l in DELE.split("\n")), amb2)
conferir(amb2["escudo_dele"] == escudo_de_af_id(2939),
         "o escudo do jogador tem de sair do lado dele no jogo mais recente")

# A rota não pode mais montar escudo por nome.
rota = FONTE[FONTE.index('@app.get("/api/jogador/ficha")'):]
rota = rota[:rota.index("\n@app.")]
conferir("padronizar_clube" not in rota,
         "a ficha voltou a normalizar nome de clube para achar escudo")
conferir("_escudos_em_cache" not in rota,
         "a ficha voltou à tabela de escudos do mundo inteiro")
conferir("escudo_de_af_id" in rota, "a ficha deveria resolver escudo por id")


# ─────────────────────────────────────────────────────────────────────────
# 3. Na tela de lesões, a liga responde primeiro
# ─────────────────────────────────────────────────────────────────────────
i = FONTE.index("    def _escudo_do_clube(nome: str) -> str:")
j = FONTE.index("\n\n", FONTE.index("return (_escudos_liga.get(nome)", i))
LESAO = FONTE[i:j]
amb3 = {"_escudos_liga": {"Al-Nassr": "riade.png"},
        "_escudos_mundo": {"Al-Nassr": "dubai.png", "Chelsea": "chelsea.png"}}
exec("\n".join(l[4:] if l.startswith("    ") else l
               for l in LESAO.split("\n")), amb3)
_e = amb3["_escudo_do_clube"]

conferir(_e("Al-Nassr") == "riade.png",
         "com o clube nas DUAS tabelas, tem de valer o da liga — este é o "
         "caso do Al Nassr de Riade contra o Al Nasr de Dubai")
conferir(_e("Chelsea") == "chelsea.png",
         "clube de fora da liga só existe na tabela mundial; sem ela, "
         "lesionado no exterior ficaria sem escudo")
conferir(_e("") == "", "clube vazio não pode devolver escudo")
conferir(_e("Clube Que Não Existe") == "",
         "clube desconhecido devolve vazio — o card mostra o nome, que é "
         "melhor do que um escudo errado")

# E o `update` que dava falsa sensação de prioridade não pode voltar.
inicio = FONTE.index("import elos\n        import liga_spl")
bloco = FONTE[inicio:inicio + 2500]
conferir("_escudos.update(escudos_da_liga" not in bloco,
         "voltou o dicionário único com update — ele só dá prioridade à liga "
         "quando as duas tabelas escrevem o nome igual, que é justamente o "
         "que não acontece com Al-Nassr e Al Nasr")


# ─────────────────────────────────────────────────────────────────────────
# 4. "Completar agora" traz as outras competições
# ─────────────────────────────────────────────────────────────────────────
reler = FONTE[FONTE.index('@app.get("/api/escalacoes/reler")'):]
reler = reler[:reler.index("\n@app.")]

conferir("_calendario_de_todas_as_competicoes(" in reler,
         "o botão precisa atualizar o calendário de todas as competições — "
         "sem isso não há jogo de AFC no banco para ler")

# E ANTES de ler, não depois: ler primeiro e descobrir depois deixa as
# partidas novas para a próxima vez, e o Vini clicaria duas vezes sem saber.
pos_comp = reler.index("_calendario_de_todas_as_competicoes(")
pos_ler = reler.index("_ler_escalacoes(")
conferir(pos_comp < pos_ler,
         "a descoberta das competições tem de vir ANTES da leitura")

conferir('esquecer_escalacoes_lidas, "incompletas"' in reler,
         "relendo a temporada INTEIRA o botão gastaria mais de mil chamadas "
         "para reconfirmar o que já está certo; partida nova nem tem carimbo")

# A tela precisa dizer o que aconteceu.
conferir('"competicoes": comp.get("competicoes")' in reler,
         "a resposta tem de dizer quais competições entraram")
conferir("d.competicoes" in FONTE,
         "o botão deveria mostrar ao Vini quantas competições vieram")


# ─────────────────────────────────────────────────────────────────────────
# 5. A tabela que colide continua marcada como perigosa
# ─────────────────────────────────────────────────────────────────────────
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
conferir("ATENÇÃO: inclui clube do mundo inteiro" in BANCO,
         "o aviso em escudos_por_clube saiu — ele é o que evita o próximo")
conferir(re.search(r"def escudo_de_af_id", BANCO) is not None,
         "escudo_de_af_id sumiu do database.py")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ escudo pelo id e competições no botão: tudo certo")
