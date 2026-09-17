"""
A ficha permanente no glossário, e as coletas com data e botão.

O PEDIDO (16/09/26)
    Depois de uma conversa inteira separando o que é ficha permanente do que é
    dado com prazo de validade, ele fechou:

        "pode ser uma rotina de atualização por periodo, e daí além da fonte
         você também define frequência (...) Nas configurações pode ficar
         armazenado o visto_em, e ter um botão pra rodar manualmente."

    E, no mesmo dia, relatou que as outras competições continuavam sem
    aparecer. Os dois assuntos se encontram aqui: o único jeito de buscá-las à
    mão era o "Completar agora" da ficha do jogador — que só existe quando há
    partida pela metade. O botão sumia exatamente quando estava tudo completo,
    que é quando ele foi procurar.

O QUE ESTE ARQUIVO VIGIA, em ordem de importância
    1. QUE COLETA NÃO SOBRESCREVE O QUE ELE CORRIGIU. O glossário é auditado à
       mão; se uma rotina noturna pudesse passar por cima, o trabalho dele
       teria validade de um dia — e ele não teria como saber.
    2. Que toda coleta grava a data, inclusive quando falha, e que "nunca
       rodou" e "rodou e falhou" não se confundem.
    3. Que as competições têm botão próprio, que não depende de nada.
    4. Que a consolidação da ficha permanente não vai à rede.
"""
import ast
import os
import sys
import types
from datetime import datetime, timedelta, timezone

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

import coletas                                           # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def funcao(texto, nome):
    i = texto.index(f"def {nome}(")
    return texto[i:texto.index("\ndef ", i + 10)]


# ─────────────────────────────────────────────────────────────────────────
# 1. COLETA NÃO SOBRESCREVE O QUE ELE CORRIGIU
# ─────────────────────────────────────────────────────────────────────────
# Este é o teste que importa. Se ele falhar, o trabalho de auditoria do Vini
# passa a ter prazo de validade de uma madrugada.
for nome in ("preencher_ficha_permanente", "consolidar_ficha_permanente"):
    corpo = funcao(BANCO, nome)
    ok("UPDATE" in corpo, f"{nome} deixou de escrever no glossário")
    # SÓ O SQL, sem os comentários: eu explico a regra por extenso logo acima
    # do código, e procurar "COALESCE" no texto todo acharia a explicação.
    sql = "\n".join(l for l in corpo.split("\n")
                    if not l.strip().startswith("#"))
    ok("COALESCE" in sql,
       f"{nome} parou de usar COALESCE. Sem ele o valor novo escreve por cima "
       f"do que já existia — inclusive por cima da correção dele")
    ok("IS NULL" in sql,
       f"{nome} parou de filtrar por campo vazio; ele passaria por todas as "
       f"linhas, inclusive as que já estão certas")

# E A ORDEM DO COALESCE IMPORTA: `COALESCE(tabela, novo)` preserva o que
# existe; `COALESCE(novo, tabela)` faz o contrário e parece igual de relance.
consolidar = funcao(BANCO, "consolidar_ficha_permanente")
# ESPAÇO NÃO PODE ESCONDER O DEFEITO. Eu comparava a linha crua, com um ou
# três espaços antes do "="; plantei o defeito numa linha alinhada com CINCO
# espaços (`pe     = COALESCE(...)`) e o teste nem olhou para ela. Agora a
# linha é normalizada antes de qualquer comparação.
def _juntar(linha):
    return " ".join(linha.split())

_achou = 0
for linha in consolidar.split("\n"):
    plana = _juntar(linha)
    for campo in ("altura", "peso", "pe", "pais_nascimento"):
        if plana.startswith(f"{campo} = COALESCE(") or \
                plana.startswith(f"SET {campo} = COALESCE("):
            _achou += 1
            depois = plana.split("COALESCE(", 1)[1]
            ok(depois.startswith("g."),
               f"em '{plana}' o COALESCE começa pelo valor NOVO. Assim ele "
               f"escreve POR CIMA do que já existe — a ordem certa é "
               f"COALESCE(o_que_ja_tem, o_novo), e as duas são idênticas de "
               f"relance")
ok(_achou >= 6,
   f"só achei {_achou} atribuições com COALESCE na consolidação; esperava ao "
   f"menos seis. Se o formato mudou, esta conferência parou de olhar para o "
   f"código que ela deveria estar vigiando")

preencher = funcao(BANCO, "preencher_ficha_permanente")
ok('linha.get(k) not in (None, "", 0)' in preencher,
   "a coleta voltou a gravar vazio e zero. 'Não sei' nunca pode virar escrita: "
   "um zero gravado em altura é pior que a altura faltando")


# ─────────────────────────────────────────────────────────────────────────
# 2. A CONSOLIDAÇÃO NÃO VAI À REDE
# ─────────────────────────────────────────────────────────────────────────
# É o que a torna imune a 403 e a cota. Se um dia ela passar a buscar algo,
# vira só mais uma coleta que pode falhar — e perde a razão de existir.
for proibido in ("httpx", "requests", "_af_get", "urlopen", "https://"):
    ok(proibido not in consolidar,
       f"a consolidação da ficha permanente passou a falar '{proibido}'. Ela "
       f"junta o que as fontes JÁ deixaram no banco; indo à rede, volta a "
       f"poder ser bloqueada")

# O DISTINCT ON no elenco congelado: quem trocou de clube no meio do ano tem
# duas linhas lá, e sem ele o UPDATE escolhe uma ao acaso.
# O DISTINCT ON SOZINHO NÃO RESOLVE: sem o ORDER BY que diz QUAL linha fica,
# ele escolhe uma ao acaso. Plantei a remoção só do ORDER BY e o teste passou,
# porque eu olhava apenas para o DISTINCT.
ok("DISTINCT ON (jogador_id)" in consolidar,
   "sumiu o DISTINCT ON do elenco congelado. Quem trocou de clube tem uma "
   "linha por clube, e o pé viria de uma delas ao acaso")
ok("ORDER BY jogador_id, congelado_em DESC" in consolidar,
   "o DISTINCT ON ficou sem ORDER BY. Ele até continua devolvendo uma linha "
   "por jogador, só que a escolha passa a ser arbitrária — e a diferença é "
   "o pé do clube antigo em vez do atual")


# ─────────────────────────────────────────────────────────────────────────
# 3. TODA COLETA GRAVA A DATA
# ─────────────────────────────────────────────────────────────────────────
for c in coletas.COLETAS:
    ok(f'marcar_coleta, "{c["chave"]}"' in FONTE,
       f"a coleta '{c['chave']}' não grava a data de quando rodou. Dado "
       f"guardado sem data é indistinguível de uma resposta errada")
    ok(c["rota"] in FONTE,
       f"a rota {c['rota']} da coleta '{c['chave']}' não existe no main.py — "
       f"o botão da tela chamaria um endereço que não responde")
    ok(c.get("metodo") in ("GET", "POST"),
       f"a coleta '{c['chave']}' não diz se é GET ou POST; a tela chamaria "
       f"com o verbo errado")
    ok(c.get("fonte") and c.get("cadencia") and c.get("ajuda"),
       f"a coleta '{c['chave']}' está sem fonte, cadência ou explicação — sem "
       f"isso a tela vira um painel de botões que ninguém sabe se deve apertar")

marcar = funcao(BANCO, "marcar_coleta")
ok("erro" in marcar and "resultado" in marcar,
   "a anotação da coleta parou de guardar o erro. 'Rodou e falhou' é "
   "diferente de 'nunca rodou', e as duas pedem ações diferentes")
# E O `except` PRECISA ENGOLIR, não relançar. Plantei um `except Exception:
# raise` e o teste passou, porque eu só procurava a palavra `except`.
_trecho = marcar[marcar.index("except Exception"):]
ok("except Exception" in marcar,
   "a anotação da coleta pode levantar. Uma anotação que derruba a coleta que "
   "ela anota é uma piada de mau gosto")
ok("raise" not in _trecho,
   "o `except` da anotação relança o erro. Com isso ela derruba justamente a "
   "coleta que acabou de dar certo, só porque não conseguiu escrever a data")
ok("print(" in _trecho,
   "a anotação engole o erro em silêncio; ao menos o log do Railway precisa "
   "saber que a data não foi gravada")


# ─────────────────────────────────────────────────────────────────────────
# 4. O VEREDITO DE CADA COLETA, EXECUTADO
# ─────────────────────────────────────────────────────────────────────────
agora = datetime.now(timezone.utc)


def quando(dias):
    return (agora - timedelta(days=dias)).isoformat()


casos = {
    "competicoes": ({"ultima_em": quando(5), "resultado": "x", "erro": ""},
                    "atrasada", "diário, e cinco dias atrás"),
    "escalacoes": ({"ultima_em": quando(0.2), "resultado": "x", "erro": ""},
                   "ok", "rodou hoje"),
    "ficha_permanente": ({"ultima_em": quando(400), "resultado": "", "erro": ""},
                         "uma_vez", "não se repete, então idade não importa"),
    "elencos_congelados": ({"ultima_em": quando(1), "resultado": "", "erro": "403"},
                           "erro", "rodou e falhou"),
}
lista = {c["chave"]: c for c in coletas.com_datas(
    {k: v[0] for k, v in casos.items()})}
for chave, (_, esperado, porque) in casos.items():
    ok(lista[chave]["estado"] == esperado,
       f"'{chave}' ({porque}) foi classificada como "
       f"'{lista[chave]['estado']}' e devia ser '{esperado}'")
ok(lista["cadastro_das_fontes"]["estado"] == "nunca",
   "coleta que nunca rodou não está sendo marcada como 'nunca'")

# ERRO GANHA DE TUDO: uma coleta que rodou ontem e falhou não pode aparecer
# como "em dia" só porque a data é recente.
so_erro = {c["chave"]: c for c in coletas.com_datas(
    {"escalacoes": {"ultima_em": quando(0.1), "resultado": "", "erro": "503"}})}
ok(so_erro["escalacoes"]["estado"] == "erro",
   "uma coleta recente que FALHOU apareceu como 'em dia'. A data recente "
   "esconderia o erro justamente onde ele importa")

# Data ilegível não pode derrubar a página.
estranho = coletas.com_datas({"competicoes": {"ultima_em": "não é data",
                                              "resultado": "", "erro": ""}})
ok(len(estranho) == len(coletas.COLETAS),
   "uma data ilegível no banco derrubou a lista de coletas")


# ─────────────────────────────────────────────────────────────────────────
# 5. AS COMPETIÇÕES GANHARAM BOTÃO QUE NÃO SOME
# ─────────────────────────────────────────────────────────────────────────
# Era o defeito por trás do "não apareceram": o único jeito de buscá-las à mão
# era o "Completar agora" da ficha, que só existe quando há partida pela
# metade. O botão sumia exatamente quando estava tudo completo.
ok("competicoes" in coletas.POR_CHAVE,
   "as competições saíram da lista de coletas — voltam a depender de um botão "
   "que só aparece quando há partida incompleta")
_js = FONTE[FONTE.index("async function carregarColetas()"):]
_js = _js[:_js.index("\nasync function carregarSaude")]
ok("c.rota" in _js and "c.metodo" in _js,
   "o botão de rodar deixou de usar a rota e o método que vêm do coletas.py")
ok("carregarColetas()" in FONTE.split("async function carregarColetas()")[0]
   or FONTE.count("carregarColetas()") >= 2,
   "a lista de coletas nunca é carregada")
ok("gaveta('coletas'" in FONTE,
   "a gaveta das coletas não é criada; a lista escreveria num elemento que "
   "não existe")

# A DATA APARECE SEMPRE, inclusive quando é "nunca".
ok("'Nunca rodou.'" in _js,
   "a tela deixou de dizer quando a coleta nunca rodou — some a diferença "
   "entre 'nunca' e 'não sei'")
ok("Última vez:" in _js, "a tela parou de mostrar a data da última coleta")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print(f"✅ {len(coletas.COLETAS)} coletas com data e botão; a ficha "
      f"permanente não sobrescreve o que ele corrigiu")
