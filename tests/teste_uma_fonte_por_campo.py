"""
A mesma pessoa não pode ter dois nomes na mesma tela.

O QUE ELE VIU (16/09/26)
    Guia de Elencos, Al-Hilal, camisa 75. Na lista da direita: "Kader Meïté",
    "Costa do Marfim". Na ficha da esquerda, do MESMO jogador: "Mohammed
    Meïté", "France".

        "Me diga por que na mesma página do Elenco, você bebe duas fontes
         diferentes? A nossa ficha fixa não deveria resolver isso? (...) A
         ficha do jogador sempre 'pisca' pra carregar de novo."

    Eram três defeitos empilhados:

    1. O NOME DA LISTA NUNCA PASSAVA PELO GLOSSÁRIO. O código lia
       `p["nome"]` — o do Transfermarkt — e só consultava o glossário para
       foto, posição e nacionalidade. O nome escapou quando eu liguei os
       outros três, e ninguém notou porque quase sempre eles coincidem.

    2. O PAÍS SAÍA EM DOIS IDIOMAS. A lista lê o Transfermarkt em português
       (o app raspa o .com.br); a ficha lê o glossário, cuja nacionalidade
       veio de fonte em inglês. E embaixo disso havia um defeito calado: o
       filtro "Só estrangeiros" compara com "arábia saudita" em PORTUGUÊS —
       um "Saudi Arabia" seria contado como estrangeiro, com uma contagem
       plausível na tela e nenhum erro em lugar nenhum.

    3. A "PISCADA" NÃO ERA CARREGAMENTO. O cabeçalho é desenhado logo com os
       dados da LISTA e redesenhado quando a ficha chega. Como os dois
       discordavam, ele via o valor TROCAR. A piscada era a contradição
       ficando visível — e some sozinha quando os dois lados concordam.

O QUE ESTE ARQUIVO VIGIA
    Que o nome vem do glossário nos dois lugares; que país sai em português
    num lugar só; e que o cabeçalho e a lista não têm como discordar.
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

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# 1. A TRADUÇÃO DO PAÍS, EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
# Recorto as duas funções do main.py e rodo de verdade. É o único jeito de
# saber o que SAI — e o que sai é a coisa toda.
_i = FONTE.index("JANELA_PAIS_EN_PT = {")
_j = FONTE.index("\n}", _i) + 2
ambiente = {}
exec(FONTE[_i:_j], ambiente)

_i2 = FONTE.index("def _pais_em_portugues(")
exec(FONTE[_i2:FONTE.index("\ndef ", _i2 + 10)], ambiente)
traduzir = ambiente["_pais_em_portugues"]

ok(traduzir("France") == "França",
   f"'France' saiu como {traduzir('France')!r}. A ficha mostrava isso cru ao "
   f"lado de uma lista em português")
ok(traduzir("Ivory Coast") == "Costa do Marfim",
   "'Ivory Coast' não virou 'Costa do Marfim'")
ok(traduzir("Costa do Marfim") == "Costa do Marfim",
   "o que já está em português foi estragado pela tradução")
ok(traduzir("") == "" and traduzir(None) == "",
   "país vazio devolveu alguma coisa; vazio tem de continuar vazio")
ok(traduzir("Paisdolândia") == "Paisdolândia",
   "um país que não está na tabela foi trocado por um palpite. Melhor exibir "
   "como veio do que inventar")

# ── E O FILTRO "SÓ ESTRANGEIROS" ─────────────────────────────────────────
# O defeito calado: ele compara com "arábia saudita", em português.
ambiente["_janela_bandeira"] = lambda p: "🇸🇦" if p else None
_i3 = FONTE.index("def _elenco_pais(")
exec(FONTE[_i3:FONTE.index("\ndef ", _i3 + 10)], ambiente)
elenco_pais = ambiente["_elenco_pais"]

r = elenco_pais(["Saudi Arabia"])
ok(r["estrangeiro"] is False,
   "um jogador com a nacionalidade escrita em inglês ('Saudi Arabia') foi "
   "contado como ESTRANGEIRO. O filtro compara com 'arábia saudita' em "
   "português — sem traduzir antes, ele erra calado e a contagem fica "
   "plausível")
ok(r["nacionalidade"] == "Arábia Saudita",
   "a nacionalidade não foi traduzida antes de ir para a tela")
ok(elenco_pais(["Arábia Saudita"])["estrangeiro"] is False,
   "o caso em português parou de funcionar")
ok(elenco_pais(["France"])["estrangeiro"] is True,
   "um francês deixou de ser estrangeiro")
ok(elenco_pais([])["nacionalidade"] is None,
   "sem nacionalidade nenhuma a função devia devolver None, e não inventar")
ok(elenco_pais(["Ivory Coast", "France"])["nacionalidades"]
   == ["Costa do Marfim", "França"],
   "as nacionalidades extras deixaram de ser traduzidas")
ok(elenco_pais(["", "France"])["nacionalidade"] == "França",
   "uma nacionalidade vazia na lista virou a principal")


# ─────────────────────────────────────────────────────────────────────────
# 2. O NOME DA LISTA VEM DO GLOSSÁRIO
# ─────────────────────────────────────────────────────────────────────────
rota = FONTE[FONTE.index('@app.get("/api/elencos/jogadores")'):]
rota = rota[:rota.index("\n_ELENCO_SALVA_CHAVE")]

ok('"nome": p["nome"]' not in rota,
   "a lista voltou a mostrar o nome do Transfermarkt direto. Foi assim que a "
   "mesma pessoa apareceu como 'Kader Meïté' na lista e 'Mohammed Meïté' na "
   "ficha, na mesma tela")
# E É O NOME RESOLVIDO PELA FONTE QUE ELE ESCOLHEU, não o `nome_principal`
# cru. Eu tinha fixado o `nome_principal` e ele me corrigiu: as grafias das
# três bases são todas válidas, e escolher qual usar é decisão dele.
ok('nome = f.get("nome") or nome' in rota,
   "o nome da lista parou de vir do glossário, ou voltou a ignorar a fonte "
   "que ele escolheu em Ajustes")
ok('f.get("nome_principal")' not in rota,
   "a lista voltou a fixar o `nome_principal`. Ele é a âncora do glossário, "
   "não a grafia que o Vini escolheu para ver na tela")
ok('"nome": nome,' in rota,
   "a lista não está publicando o nome resolvido")

# E a ORDEM importa: o nome tem de ser resolvido ANTES de entrar no dicionário
# de saída, senão a atribuição não chega a lugar nenhum.
ok(rota.index('nome = f.get("nome")') < rota.index('"nome": nome,'),
   "o nome é resolvido DEPOIS de ser publicado; a atribuição não teria efeito")

# O padrão continua sendo o do TM para quem o glossário não conhece — é o
# jogador de fora da liga, que não está lá e nem deveria estar.
ok('nome = p["nome"]' in rota,
   "quem o glossário não conhece ficou sem nome. A lista tem gente de fora "
   "da liga, e para essa o Transfermarkt continua sendo a fonte")


# E A FICHA TAMBÉM TRADUZ. Ela era o lado que mostrava "France"; se voltar a
# mandar o valor cru, a incoerência volta inteira — e o teste do cabeçalho
# sozinho não pega, porque a preferência continuaria certa.
ficha = FONTE[FONTE.index("async def _ficha_do_jogador("):]
ficha = ficha[:ficha.index("\ndef _idade_em_anos")]
ok('"nacionalidade": _pais_em_portugues(' in ficha,
   "a ficha do jogador voltou a mandar a nacionalidade como veio da fonte. "
   "Era este lado que dizia 'France' ao lado de uma lista que dizia 'Costa "
   "do Marfim'")


# ─────────────────────────────────────────────────────────────────────────
# 2b. O NOME É UMA ESCOLHA DELE, COMO A FOTO — e a escolha é EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
import glossario                                        # noqa: E402
import ajustes                                          # noqa: E402

ok("glossario_fonte_nome" in ajustes.POR_CHAVE,
   "sumiu o seletor de fonte do nome. Cada base escreve de um jeito e nenhuma "
   "está errada: 'Kader Meïté' no Transfermarkt, 'Mohammed Meïté' na SPL. "
   "Escolher qual padronizar é decisão dele")
ok("nome" in glossario._DE_ONDE,
   "o nome saiu do mapa de fontes do glossário")
for fonte in ("spl", "api_football", "transfermarkt"):
    ok(glossario._DE_ONDE["nome"].get(fonte),
       f"o nome não tem coluna para a fonte '{fonte}'")

# EXECUTADO: troco a fonte e confiro qual grafia sai.
_original = glossario._fonte_escolhida
LINHA = {"nome_principal": "Mohammed Meïté", "af_nome": "M. Meite",
         "tm_nome": "Kader Meïté", "foto": "", "posicao": "",
         "nacionalidade": ""}
try:
    for escolha, esperado in (("spl", "Mohammed Meïté"),
                              ("transfermarkt", "Kader Meïté"),
                              ("api_football", "M. Meite")):
        glossario._fonte_escolhida = lambda c, e=escolha: e
        ok(glossario.ficha(LINHA).get("nome") == esperado,
           f"com a fonte do nome em '{escolha}' saiu "
           f"{glossario.ficha(LINHA).get('nome')!r} e devia sair {esperado!r}")

    # A EXCEÇÃO QUE SÓ O NOME TEM: fonte escolhida sem o dado cai na âncora do
    # glossário. Nos outros campos vazio é resposta — mas card sem foto ainda
    # funciona, e card sem NOME vira uma linha em branco que não dá para
    # clicar nem procurar.
    glossario._fonte_escolhida = lambda c: "transfermarkt"
    sem_tm = dict(LINHA, tm_nome="")
    ok(glossario.ficha(sem_tm).get("nome") == "Mohammed Meïté",
       "um jogador sem nome na fonte escolhida ficou SEM NOME na tela. Ele "
       "some da lista sem sumir do elenco — o pior tipo de desaparecimento")

    # E o vazio dos outros campos continua sendo resposta, não lacuna.
    ok(glossario.ficha(dict(LINHA, tm_foto=""))["foto"] == "",
       "a exceção do nome vazou para a foto; ali vazio tem de continuar "
       "querendo dizer 'a fonte que você escolheu não tem isto'")
finally:
    glossario._fonte_escolhida = _original


# TODO MUNDO QUE MOSTRA NOME USA O RESOLVIDO. Plantei o `nome_principal` de
# volta em cada consumidor, um por um, e os que eu não estava vigiando
# passaram batidos — o defeito não some por estar consertado num lugar.
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
for trecho, quem in (
        (FONTE[FONTE.index("def _ficha_como_elenco("):
               FONTE.index("\ndef _e_nome_de_clube_da_liga")],
         "a ficha-como-elenco (Lesões, Mercado, campinho)"),
        (ficha, "a ficha do jogador"),
        (FONTE[FONTE.index("def _elenco_de_reserva("):
               FONTE.index("\ndef ", FONTE.index("def _elenco_de_reserva(") + 10)],
         "o elenco de reserva pelo glossário")):
    ok('"nome": f.get("nome_principal")' not in trecho,
       f"{quem} voltou a fixar o `nome_principal`. A escolha de fonte do nome "
       f"passa a valer numa tela e não na outra — que é exatamente a "
       f"incoerência que ele apontou")

# E AS COLUNAS PRECISAM CHEGAR. Oferecer uma fonte que sempre devolve vazio é
# uma armadilha com cara de opção — o próprio ajustes.py já diz isso sobre a
# posição da API-Football.
_i4 = BANCO.index("def glossario_completo(")
_sql = BANCO[_i4:BANCO.index("\ndef ", _i4 + 10)]
# A COLUNA DE ORIGEM PRECISA APARECER, e não só o apelido. Plantei
# `'' AS af_nome` — o apelido continua lá e o dado nunca chega — e o teste
# passou. Um alias sozinho não prova que alguma coisa é lida.
for origem, apelido, fonte in (("a.nome", "af_nome", "api_football"),
                               ("e.nome", "tm_nome", "transfermarkt")):
    plano = " ".join(_sql.split())
    ok(f"{origem} AS {apelido}" in plano,
       f"a consulta do glossário não lê mais {origem} para o {apelido}. A "
       f"opção '{fonte}' continuaria na tela e devolveria vazio sempre — "
       f"armadilha com cara de opção")
ok("jogador_id, nome, foto" in _sql,
   "o elenco congelado parou de entregar o nome; a opção 'transfermarkt' "
   "ficaria sem dado")


# ─────────────────────────────────────────────────────────────────────────
# 3. O CABEÇALHO E A LISTA NÃO PODEM DISCORDAR
# ─────────────────────────────────────────────────────────────────────────
cab = FONTE[FONTE.index("function cabecalhoFicha(j, d){"):]
cab = cab[:cab.index("\nfunction dataBr(")]
# SEM OS COMENTÁRIOS. Eu explico o código ANTIGO logo acima do novo, para
# quem ler daqui a seis meses saber o que mudou — e a busca encontrava a minha
# própria explicação. Foi a terceira vez que caí nisso hoje; agora o teste
# olha só para o código.
cab_codigo = "\n".join(l for l in cab.split("\n")
                       if not l.strip().startswith("//"))

ok("const nacionalidade = j.nacionalidade || g.nacionalidade;" in cab,
   "a nacionalidade do cabeçalho voltou a preferir a ficha. A lista é quem "
   "tem a ORDEM das nacionalidades do Transfermarkt, que distingue a "
   "esportiva da de nascimento — é o que faz o Bounou sair como Marrocos")
ok("g.nacionalidade || j.nacionalidade" not in cab_codigo,
   "sobrou a preferência antiga em algum lugar do cabeçalho")

# A BANDEIRA SEGUE O PAÍS. Se o nome vem de um lado e a bandeira do outro,
# sai a bandeira de um país com o nome de outro.
ok("isoBandeira(j.pais_bandeira || g.bandeira)" in cab,
   "a bandeira e o nome do país passaram a vir de lados diferentes; um dia "
   "eles vão discordar, e aí sai a bandeira errada com o nome certo")

# A POSIÇÃO já preferia a lista, e continua: é ela que tem a posição
# DETALHADA do Transfermarkt ("Centroavante" e não "Atacante").
ok("j.posicao || g.posicao" in cab,
   "a posição deixou de preferir a lista, que é a única com a posição "
   "detalhada")

# E O NOME, ao contrário, prefere a ficha — porque agora os dois lados tiram
# o nome do MESMO glossário, então não há como discordar.
ok("g.nome || j.nome" in cab,
   "o nome do cabeçalho deixou de preferir o glossário")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ uma fonte por campo: o nome vem do glossário, o país sai em "
      "português, e a lista e a ficha não têm como discordar")
