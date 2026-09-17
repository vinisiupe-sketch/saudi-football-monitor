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
ok('nome = f.get("nome_principal") or nome' in rota,
   "o nome da lista parou de vir do glossário")
ok('"nome": nome,' in rota,
   "a lista não está publicando o nome resolvido")

# E a ORDEM importa: o nome do glossário tem de ser calculado ANTES de entrar
# no dicionário de saída, senão a atribuição não chega a lugar nenhum.
ok(rota.index('nome = f.get("nome_principal")') < rota.index('"nome": nome,'),
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
