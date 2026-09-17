"""
O glossário responde também pelos CAMPOS, e não só por quem é.

A PERGUNTA DELE (16/09/26)
    A guia de Configurações mostrava "183 com id do Transfermarkt, 434 com id
    da API-Football", e ele estranhou: "eu mapeei 595 no TM e 595 no
    Api-Football. Tá pareado no glossário. Você continua não usando?".

    Fui ver. Eram duas coisas:

    1. Aquela contagem lia `FROM jogador` — a tabela da varredura antiga, de
       antes do glossário. Os 595 dele estavam intactos em
       `glossario_lab_jogador`; a tela é que olhava para o lugar errado,
       embaixo de um título que eu mesmo escrevi dizendo "a base de nomes,
       ids e nascimentos".

    2. Pior: em `_identificar_jogador` estava escrito

           return por_id.get(spl) or _ficha_como_elenco(achado)

       ou seja, o glossário decidia QUEM era e eu ia buscar os DADOS na tabela
       antiga, caindo no glossário só se não achasse lá. Como a configuração
       de fonte por campo mora em `glossario.ficha()`, ela não passava por
       aquele caminho — e para todo jogador que existe nas duas bases (quase
       todos) escolher a foto da SPL em Ajustes não mudava nada.

       É o mesmo sintoma que ele já tinha relatado meses antes, com outra
       causa: "setei as fotos vindo da SPL e continua vindo a do Transfermarkt".

O QUE ESTE ARQUIVO VIGIA
    Que o glossário ganha campo a campo; que vazio nos três campos
    configuráveis é RESPOSTA e não lacuna; que o registro antigo continua
    preenchendo o que o glossário não tem; e que a contagem da tela é a do
    glossário.
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

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# 1. A MISTURA, EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
# Recorto a função do main.py e rodo de verdade, com um `_ficha_como_elenco`
# de mentira. Conferir que a linha certa está escrita não diz nada sobre qual
# valor sai — e o valor que sai É a coisa toda.
i = FONTE.index("def _glossario_com_reserva(g: dict, antigo: dict) -> dict:")
j = FONTE.index("\n\n\n", i)
CORPO = FONTE[i:j]

FICHA = {}


def _ficha_falsa(g):
    return dict(FICHA)


# A LISTA DE CAMPOS CONFIGURÁVEIS SAI DO main.py, e não daqui.
#
# Eu tinha escrito a tupla à mão neste ambiente. Plantei o defeito que tira a
# "foto" da lista no main.py e o teste passou — claro: ele estava usando a
# CÓPIA que eu mesmo injetei. Um teste que fornece o valor que deveria estar
# conferindo não confere nada.
_i2 = FONTE.index("_CAMPOS_COM_FONTE = (")
_amb2 = {}
exec(FONTE[_i2:FONTE.index("\n", _i2)], _amb2)
CAMPOS_COM_FONTE = _amb2["_CAMPOS_COM_FONTE"]

ambiente = {"_ficha_como_elenco": _ficha_falsa,
            "_CAMPOS_COM_FONTE": CAMPOS_COM_FONTE}
exec(CORPO, ambiente)
misturar = ambiente["_glossario_com_reserva"]

ANTIGO = {"spl_id": "abc", "nome": "Nome Velho", "nome_curto": "Velho",
          "clube": "Clube Velho", "foto": "foto-velha.png",
          "posicao": "Posicao Velha", "nacionalidade": "Pais Velho",
          "altura": 181, "nascimento": "1999-11-10", "tm_id": "111"}

# ── O GLOSSÁRIO GANHA onde ele sabe ──────────────────────────────────────
FICHA = {"spl_id": "abc", "nome": "Nome do Glossário",
         "nome_curto": "Glossário", "clube": "Clube do Glossário",
         "foto": "foto-do-glossario.png", "posicao": "Posicao Nova",
         "nacionalidade": "Pais Novo", "tm_id": "999", "af_id": 42}
r = misturar({"spl_id": "abc"}, ANTIGO)
for campo in ("nome", "nome_curto", "clube", "foto", "posicao",
              "nacionalidade", "tm_id"):
    ok(r[campo] == FICHA[campo],
       f"o campo '{campo}' saiu da tabela antiga ({r[campo]!r}) em vez do "
       f"glossário ({FICHA[campo]!r}). É o defeito que o Vini pegou: o "
       f"glossário diz quem é, mas os dados vinham da base velha")
ok(r.get("do_glossario") is True,
   "o registro não sai marcado como vindo do glossário")

# ── A TABELA ANTIGA PREENCHE O QUE O GLOSSÁRIO NÃO TEM ───────────────────
ok(r.get("altura") == 181,
   "a altura sumiu. O glossário ainda não guarda altura, e enquanto não "
   "guardar a base antiga é quem tem — apagar seria perder dado por causa "
   "de uma reorganização")
ok(r.get("nascimento") == "1999-11-10",
   "o nascimento sumiu junto com o resto da base antiga")

# ── VAZIO NOS TRÊS CAMPOS CONFIGURÁVEIS É RESPOSTA, NÃO LACUNA ───────────
#
# Este é o teste mais fino do arquivo. Quando o Vini escolhe "foto da SPL" e
# aquele jogador não tem foto na SPL, `glossario.ficha()` devolve vazio DE
# PROPÓSITO — "vazio é honesto". Se eu preenchesse com a base antiga, a
# escolha dele pareceria ignorada, que é exatamente o defeito de origem.
FICHA = {"spl_id": "abc", "nome": "Nome do Glossário", "foto": "",
         "posicao": "", "nacionalidade": ""}
r2 = misturar({"spl_id": "abc"}, ANTIGO)
for campo in ("foto", "posicao", "nacionalidade"):
    ok(campo in CAMPOS_COM_FONTE,
       f"'{campo}' saiu da lista de campos cuja fonte ele escolhe em Ajustes. "
       f"Fora dela, o vazio dele volta a ser preenchido pela base antiga e a "
       f"configuração parece ignorada")
    ok(r2[campo] == "",
       f"'{campo}' vazio no glossário foi preenchido com "
       f"{r2[campo]!r} da base antiga. Vazio ali quer dizer 'a fonte que "
       f"você escolheu não tem isso' — preencher desfaz a escolha dele em "
       f"silêncio")
# Mas os OUTROS campos vazios continuam sendo preenchidos: ali vazio é falta
# de dado, não escolha.
ok(r2.get("nome_curto") == "Velho",
   "um campo comum vazio no glossário deixou de ser preenchido pela base "
   "antiga; aí vazio é lacuna, não resposta")
ok(r2.get("altura") == 181, "a altura sumiu no caso de campo vazio")

# ── SEM REGISTRO ANTIGO, A FICHA SOZINHA BASTA ───────────────────────────
FICHA = {"spl_id": "novo", "nome": "Contratado Ontem", "foto": "f.png"}
r3 = misturar({"spl_id": "novo"}, {})
ok(r3.get("nome") == "Contratado Ontem" and r3.get("do_glossario") is True,
   "jogador que está no glossário e não na base antiga parou de existir para "
   "as telas — é o caso do contratado ontem")
r4 = misturar({"spl_id": "novo"}, None)
ok(r4.get("nome") == "Contratado Ontem",
   "com `None` no lugar do registro antigo a mistura quebrou")


# ─────────────────────────────────────────────────────────────────────────
# 2. A ORDEM NA IDENTIFICAÇÃO
# ─────────────────────────────────────────────────────────────────────────
ident = FONTE[FONTE.index("def _identificar_jogador("):]
ident = ident[:ident.index("\ndef _e_nome_de_clube_da_liga")
              if "\ndef _e_nome_de_clube_da_liga" in ident else 6000]
# PROCURO O `return`, e não só a expressão: o comentário logo acima CITA o
# código antigo para explicar o que mudou, e procurar a expressão solta
# encontrava a minha própria explicação. Foi a primeira coisa que este teste
# acusou, e não era defeito nenhum.
ok("return por_id.get(spl) or" not in ident,
   "voltou o `return por_id.get(spl) or _ficha_como_elenco(achado)`. Nessa "
   "ordem o glossário decide quem é e a tabela antiga entrega os dados — e a "
   "configuração de fonte por campo deixa de valer")
ok("_glossario_com_reserva(achado, por_id.get(spl)" in ident,
   "a identificação parou de misturar o glossário por cima do registro antigo")


# ─────────────────────────────────────────────────────────────────────────
# 3. A CONTAGEM DA TELA É A DO GLOSSÁRIO
# ─────────────────────────────────────────────────────────────────────────
ok("def contar_glossario()" in BANCO,
   "sumiu a contagem do glossário")
_i = BANCO.index("def contar_glossario()")
_conta = BANCO[_i:BANCO.index("\ndef ", _i + 10)]
# SÓ O SQL, e não o texto todo: a explicação da função CITA o `FROM jogador`
# antigo para contar de onde veio o problema, e procurar no texto inteiro
# encontrava a citação. Segunda vez no mesmo arquivo.
_sql = _conta[_conta.index("c.execute("):_conta.index('""")')]
ok("FROM glossario_lab_jogador" in _sql,
   "a contagem do glossário lê outra tabela")
ok("FROM jogador" not in _sql,
   "a contagem do glossário voltou a ler a tabela antiga — foi exatamente "
   "isso que fez ele ver 183 onde tinha mapeado 595")
ok("revisado" in _sql,
   "sumiu a contagem de fichas revisadas por ele; é o número que mede o "
   "trabalho que só ele pode fazer")

rota = FONTE[FONTE.index('@app.get("/api/jogadores")'):]
rota = rota[:rota.index("\nasync def congelar_elencos_do_tm")]
ok('"resumo": contar_glossario()' in rota,
   "o resumo da tela voltou a ser o da tabela antiga")
ok('"antiga": contar_jogadores()' in rota,
   "a base antiga sumiu da resposta. Ela ainda existe e ainda é usada como "
   "índice de quem não é da liga; esconder não resolve, dizer o que é resolve")

_js = FONTE[FONTE.index("async function carregarElenco()"):]
_js = _js[:_js.index("\nasync function varrer(")]
ok("'Glossario: '" in _js,
   "o painel voltou a mostrar um número sem dizer de qual base ele é. Foi "
   "assim que ele leu 183 achando que era o glossário dele")
ok("d.antiga" in _js,
   "o painel parou de mostrar a base antiga separada")
ok("revisados" in _js,
   "o painel não mostra quantas fichas ele já revisou")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ o glossário manda nos campos, e a tela conta a base certa")
