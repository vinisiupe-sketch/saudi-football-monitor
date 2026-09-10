"""
Quem está pendurado, quem está fora e quem já cumpriu.

A REGRA, E DE ONDE ELA VEIO
    Na Saudi Pro League o jogador fica de fora da partida seguinte ao QUARTO
    amarelo, em jogos diferentes da mesma competição. Confirmei na imprensa
    saudita: a federação mudou de três para quatro para alinhar com o formato
    do Roshn. Como já mudou uma vez, o número mora nos Ajustes — e este
    arquivo testa a regra com o limite VARIÁVEL, porque um teste que só
    conhece o 4 não protege o dia em que virar 5.

O DEFEITO QUE DEU ORIGEM À SEGUNDA VERSÃO
    O Vini achou com um caso concreto, e é o teste 5 aqui embaixo:

        O Bento foi expulso contra o Al-Ettifaq em 25/08.
        Cumpriu a suspensão contra o Al-Taawoun em 28/08.
        Voltou ao banco contra o Al-Ittihad em 05/09.
        Foi titular em 09/09.
        E continuava na tela como suspenso.

    A causa: eu decidia a suspensão comparando com o "último jogo em que o
    jogador levou cartão". Como o Bento não levou mais nenhum, esse jogo
    seguiu sendo o de 25/08 para sempre — e ele seguiu suspenso para sempre.

    A punição não é sobre o jogo do cartão. É sobre O JOGO SEGUINTE DO CLUBE.
    Para saber qual é, e se já aconteceu, é preciso o calendário. Por isso a
    função agora recebe o calendário e a data de hoje: são eles que fazem o
    recorte, e recebê-los como argumento é o que permite testar o caso inteiro
    sem banco e sem rede.

POR QUE A CONTAGEM É CARTÃO A CARTÃO
    O caminho barato seria o total da temporada, numa chamada só. Ele erra de
    um jeito que não aparece: o total NÃO zera depois da suspensão cumprida,
    então quem pegou quatro e cumpriu ficaria pendurado para sempre. Numa guia
    que responde "quem eu não posso escalar", esse erro só se descobre no ar.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _carregar_regra():
    """Só as funções da regra, sem subir o main.py inteiro.

    São puras de propósito: é isso que permite imaginar aqui a rodada que eu
    preciso imaginar — o expulso que já cumpriu, o que cumpre no jogo que
    ainda vem, o pendurado às vésperas do clássico.
    """
    mod = ast.parse(FONTE)
    alvos = {"_classificar_cartao", "_e_amarelo", "_e_segundo_amarelo",
             "_e_vermelho", "_situacao_dos_cartoes", "_jogos_do_clube",
             "_adversario", "_ja_aconteceu", "_gancho_pode_ser_maior"}
    corpo = [n for n in mod.body
             if isinstance(n, ast.FunctionDef) and n.name in alvos]
    achadas = {n.name for n in corpo}
    corpo += [n for n in mod.body if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "id", "")
              in ("_JOGO_ENCERRADO", "MOTIVOS_DE_GANCHO_MAIOR")]
    ns = {}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), "<regra>", "exec"), ns)
    return ns, achadas


AMARELO = "Yellow Card"
VERMELHO = "Red Card"
# O QUE A API ESCREVE DE VERDADE. Eu tinha suposto "Second Yellow card"; ela
# manda "Yellow-Red Card". O rótulo que eu procurava não existia, e o defeito
# foi silencioso e DUPLO: "yellow" está nesse texto (contei um amarelo) e
# "red card" também (contei um vermelho). O mesmo lance entrava nas duas
# contas. Este teste usa o rótulo real como padrão; o antigo vira só um
# apelido a mais no teste 0.
SEGUNDO = "Yellow-Red Card"

NASSR, ETTIFAQ, TAAWOUN, ITTIHAD, HILAL = 2939, 2934, 2936, 2938, 2932
NOMES = {NASSR: "Al-Nassr", ETTIFAQ: "Al-Ettifaq", TAAWOUN: "Al-Taawoun",
         ITTIHAD: "Al-Ittihad", HILAL: "Al-Hilal"}


def jogo(fid, data, casa, fora, status="FT"):
    return {"fixture_id": fid, "data": data, "status": status, "rodada": "x",
            "casa_id": casa, "casa": NOMES[casa],
            "fora_id": fora, "fora": NOMES[fora]}


def cartao(fixture, jogador, detalhe, data, minuto=10, clube=NASSR):
    return {"fixture_id": fixture, "jogador_id": jogador,
            "jogador": f"J{jogador}", "clube": NOMES[clube], "clube_id": clube,
            "detalhe": detalhe, "minuto": minuto, "jogo_em": data,
            "tipo": "vermelho" if "Red" in detalhe or "Second" in detalhe
                    else "amarelo"}


# O calendário, com as datas do caso real do Bento.
#
# Três decisões de propósito, e cada uma existe porque a primeira versão deste
# teste passava com um defeito plantado:
#
#   · tem jogos de OUTROS clubes no meio. Sem isso, "pegar os jogos do clube"
#     e "pegar a liga inteira" davam o mesmo resultado, e a peneira por clube
#     podia sumir sem ninguém ver;
#   · a lista chega FORA DE ORDEM em alguns testes. Um calendário já ordenado
#     faz o `sorted` parecer decorativo, e é ele que define "o jogo seguinte";
#   · há um jogo ADIADO — data no passado, status "NS". É o caso em que a data
#     e o estado discordam, e ele diz qual dos dois manda.
CAL = [
    jogo(1, "2026-08-25", ETTIFAQ, NASSR),
    jogo(2, "2026-08-28", NASSR, TAAWOUN),
    jogo(3, "2026-09-05", ITTIHAD, NASSR),
    jogo(4, "2026-09-09", NASSR, HILAL),
    jogo(5, "2026-09-16", TAAWOUN, NASSR, "NS"),
    jogo(6, "2026-09-23", NASSR, ETTIFAQ, "NS"),
    # Outros clubes, para a peneira por clube ter o que peneirar.
    jogo(70, "2026-08-26", HILAL, ITTIHAD),
    jogo(71, "2026-08-29", TAAWOUN, ETTIFAQ),
    jogo(72, "2026-09-06", HILAL, TAAWOUN),
    jogo(73, "2026-09-12", ITTIHAD, ETTIFAQ, "NS"),
]

# Embaralhado de propósito: a ordem tem que sair do código, não da entrada.
CAL_FORA_DE_ORDEM = [CAL[i] for i in (3, 8, 0, 5, 6, 2, 9, 1, 7, 4)]


def _calendario_em(dia: str):
    """O calendário como ele estaria naquele dia: jogado o que já passou."""
    return [dict(p, status=("FT" if p["data"] < dia else "NS")) for p in CAL]


def _sem_status(cal):
    """O mesmo calendário sem o campo de estado.

    Acontece de verdade: o jogo entra no calendário antes de a API publicar o
    status. Aí quem decide se ele já aconteceu é a data — e é o único caminho
    em que a comparação de datas é exercitada.
    """
    return [dict(p, status="") for p in cal]


def testar():
    falhas.clear()
    ns, achadas = _carregar_regra()
    esperadas = {"_classificar_cartao", "_e_amarelo", "_e_segundo_amarelo",
                 "_e_vermelho", "_situacao_dos_cartoes", "_jogos_do_clube",
                 "_adversario", "_ja_aconteceu", "_gancho_pode_ser_maior"}
    ok(achadas == esperadas,
       f"sumiu alguma função da regra: falta {esperadas - achadas}")
    if achadas != esperadas:
        for f in falhas:
            print("  ✗", f)
        return len(falhas)
    situacao = ns["_situacao_dos_cartoes"]
    classificar = ns["_classificar_cartao"]

    # ── 0. cada cartão vira UMA categoria ────────────────────────────────
    # É aqui que o defeito de setembro nasceu. Eu perguntava três coisas
    # independentes ("é amarelo?", "é segundo amarelo?", "é vermelho?") e
    # "Yellow-Red Card" respondia SIM a duas delas — porque o nome dele contém
    # o nome das outras duas. Uma função só, com ordem explícita, é o que
    # impede isso de voltar.
    CATEGORIAS = {
        "Yellow Card": "amarelo",
        "Red Card": "vermelho",
        # O rótulo que a API-Football usa de verdade para o segundo amarelo:
        "Yellow-Red Card": "amarelo_vermelho",
        # Apelidos que outras fontes (e a documentação) usam. Custam nada e
        # evitam que a mesma armadilha volte por outro nome.
        "Second Yellow card": "amarelo_vermelho",
        "2nd Yellow Card": "amarelo_vermelho",
        "yellow_red_card": "amarelo_vermelho",
        "YELLOW-RED CARD": "amarelo_vermelho",
    }
    for texto, esperado in CATEGORIAS.items():
        obtido = classificar(texto)
        ok(obtido == esperado,
           f'"{texto}" foi classificado como {obtido!r} e deveria ser '
           f"{esperado!r}")

    # E o que eu não reconheço não vira palpite.
    for texto in ("", None, "Card", "Missing Fixture", "Questionable"):
        ok(classificar(texto) == "",
           f'"{texto}" virou uma categoria de cartão sem ser um')

    # A prova direta de que o mesmo evento não entra em duas contas.
    ok(not (ns["_e_amarelo"]("Yellow-Red Card")
            and ns["_e_vermelho"]("Yellow-Red Card")),
       "'Yellow-Red Card' voltou a contar como amarelo E como vermelho ao "
       "mesmo tempo. Foi assim que o Dion Lopy ganhou dois amarelos que o "
       "regulamento tinha cancelado")
    ok(not ns["_e_amarelo"]("Yellow-Red Card"),
       "'Yellow-Red Card' voltou a contar como amarelo simples")
    ok(ns["_e_vermelho"]("Yellow-Red Card"),
       "'Yellow-Red Card' deixou de ser expulsão — o jogador saiu de campo")

    def de(cartoes, limite=4, cal=None, hoje="2026-09-10"):
        cal = CAL if cal is None else cal
        return {d["jogador_id"]: d for d in situacao(cartoes, limite, cal, hoje)}

    # ── 1. o pendurado é o que está a UM do limite ───────────────────────
    tres = [cartao(f, 1, AMARELO, d)
            for f, d in ((1, "2026-08-25"), (2, "2026-08-28"), (3, "2026-09-05"))]
    d = de(tres)[1]
    ok(d["estado"] == "pendurado", f"três amarelos com limite 4: {d['estado']!r}")
    ok(d["faltam"] == 1, f"deveria faltar 1 amarelo, faltam {d['faltam']}")
    # E a tela precisa saber CONTRA QUEM é o risco.
    ok(d["proximo_jogo"] == "Al-Taawoun" and d["proximo_em"] == "2026-09-16",
       f"o próximo jogo do clube saiu errado: {d['proximo_jogo']!r} "
       f"em {d['proximo_em']!r} — era o Al-Taawoun em 16/09")

    d = de(tres[:2])[1]
    ok(d["estado"] == "", "dois amarelos com limite 4 não penduram ninguém")

    # ── 2. o limite é configurável, e a regra o obedece ──────────────────
    ok(de(tres, limite=3)[1]["estado"] in ("fora", "retornando"),
       "com limite 3, o terceiro amarelo tem que punir — a regra ignorou o "
       "limite recebido")
    ok(de(tres, limite=5)[1]["estado"] == "",
       "com limite 5, três amarelos não penduram ninguém")
    ok(de(tres, limite=4)[1]["estado"] == "pendurado",
       "com limite 4, três amarelos penduram")

    # ── 3. quarto amarelo: fora do JOGO SEGUINTE, com nome e data ────────
    # Quarto amarelo em 09/09; o jogo seguinte do Nassr é 16/09, contra o
    # Al-Taawoun, e ele ainda não aconteceu em 10/09.
    quatro = tres + [cartao(4, 1, AMARELO, "2026-09-09")]
    d = de(quatro)[1]
    ok(d["estado"] == "fora" and d["suspenso"],
       f"quarto amarelo tem que deixar o jogador fora: {d['estado']!r}")
    ok(d["jogo_da_pena"] == "Al-Taawoun" and d["jogo_da_pena_em"] == "2026-09-16",
       f"a suspensão apontou para o jogo errado: {d['jogo_da_pena']!r} em "
       f"{d['jogo_da_pena_em']!r}")
    ok("4" in d["motivo"], f"o motivo não diz qual amarelo foi: {d['motivo']!r}")
    # Quem já está fora não é also pendurado: a segunda etiqueta só tiraria
    # espaço da que importa.
    ok(not d["pendurado"],
       "o suspenso apareceu também como pendurado")

    # E o ciclo RECOMEÇA — o erro que o total da temporada cometeria.
    cinco = quatro + [cartao(5, 1, AMARELO, "2026-09-16")]
    d = de(cinco, hoje="2026-09-17", cal=_calendario_em("2026-09-17"))[1]
    ok(d["amarelos"] == 5 and d["no_ciclo"] == 1,
       f"o ciclo não recomeçou depois da suspensão: {d}")

    # ── 4. dois amarelos na mesma partida ────────────────────────────────
    expulso = [cartao(4, 2, AMARELO, "2026-09-09", 10),
               cartao(4, 2, SEGUNDO, "2026-09-09", 70)]
    d = de(expulso)[2]
    ok(d["amarelos"] == 0,
       f"os dois amarelos da expulsão entraram no acúmulo: {d['amarelos']}")
    ok(d["dois_amarelos"] == 1 and d["vermelhos"] == 1,
       f"a expulsão por dois amarelos não foi contada: {d}")
    ok(d["estado"] == "fora",
       "O ERRO DA PRIMEIRA VERSÃO: o expulso por dois amarelos aparecia como "
       "não suspenso, porque o `continue` que tira os cartões do acúmulo "
       "pulava também a anotação do jogo. O jogador mais obviamente fora de "
       "campo era o único que a tela não marcava")

    # ── 5. O CASO DO BENTO, dia a dia ────────────────────────────────────
    # Expulso contra o Ettifaq em 25/08 (fixture 1). O jogo seguinte do Nassr
    # é 28/08, contra o Al-Taawoun: é esse que ele perde.
    bento = [cartao(1, 3, VERMELHO, "2026-08-25", 44)]

    d = de(bento, hoje="2026-08-26", cal=_calendario_em("2026-08-26"))[3]
    ok(d["estado"] == "fora",
       f"no dia seguinte à expulsão ele tem que estar fora: {d['estado']!r}")
    ok(d["jogo_da_pena"] == "Al-Taawoun",
       f"a pena apontou para {d['jogo_da_pena']!r} e era o Al-Taawoun")

    # No próprio dia do jogo, ANTES de ele acontecer, continua fora. Tratar
    # 'hoje' como passado tiraria da lista justamente no dia em que ela é lida.
    d = de(bento, hoje="2026-08-28", cal=_calendario_em("2026-08-28"))[3]
    ok(d["estado"] == "fora",
       "no dia do jogo da suspensão, antes de ele ser jogado, o jogador "
       "sumiu da lista — que é exatamente o dia em que o Vini a consulta")

    # Cumprida. No dia seguinte ele é notícia como quem volta.
    d = de(bento, hoje="2026-08-29", cal=_calendario_em("2026-08-29"))[3]
    ok(d["estado"] == "retornando",
       f"depois de cumprir, o estado devia ser 'retornando': {d['estado']!r}")
    ok("cumpriu" in d["motivo"], f"motivo pouco claro: {d['motivo']!r}")

    # Duas rodadas depois não é mais notícia: ele saiu da lista.
    for dia in ("2026-09-06", "2026-09-10"):
        d = de(bento, hoje=dia, cal=_calendario_em(dia))[3]
        ok(d["estado"] == "" and not d["suspenso"],
           f"em {dia} o Bento ainda aparecia como {d['estado']!r}. Ele foi "
           "expulso em 25/08, cumpriu em 28/08, voltou ao banco em 05/09 e "
           "foi titular em 09/09 — é o caso que derrubou a primeira versão")

    # ── 5b. O CASO DO DION LOPY ──────────────────────────────────────────
    # O segundo caso real que o Vini trouxe, e o que revelou o rótulo errado.
    #
    #   21/08  expulso por dois amarelos contra o Al-Qadsiah
    #   24/08  cumpre a suspensão (não joga contra o Al-Hazem)
    #   29/08  volta contra o Al-Fateh, e leva amarelo
    #   01/09  leva outro amarelo contra o Al-Nassr
    #
    # Ele tem DOIS amarelos no ciclo, não quatro: os dois de 21/08 foram
    # cancelados junto com a expulsão. Com o defeito, a conta chegava a quatro
    # e a tela inventava uma segunda suspensão — dizendo que ele cumpriria
    # contra o Al-Fayha em 08/09 e voltaria contra o Al-Faisaly.
    ITT, QAD, HAZ, FATEH, FAYHA, FAISALY = 2938, 2933, 2945, 2931, 2944, 2930
    nomes_ITT = {ITT: "Al-Ittihad", QAD: "Al-Qadsiah", HAZ: "Al-Hazem",
                 FATEH: "Al-Fateh", NASSR: "Al-Nassr", FAYHA: "Al-Fayha",
                 FAISALY: "Al-Faisaly FC"}

    def jITT(fid, data, casa, fora, status="FT"):
        return {"fixture_id": fid, "data": data, "status": status, "rodada": "x",
                "casa_id": casa, "casa": nomes_ITT[casa],
                "fora_id": fora, "fora": nomes_ITT[fora]}

    cal_itt = [jITT(101, "2026-08-21", ITT, QAD),
               jITT(102, "2026-08-24", HAZ, ITT),
               jITT(103, "2026-08-29", ITT, FATEH),
               jITT(104, "2026-09-01", NASSR, ITT),
               jITT(105, "2026-09-08", ITT, FAYHA),
               jITT(106, "2026-09-15", FAISALY, ITT, "NS")]

    def cITT(fid, detalhe, data, minuto):
        return {"fixture_id": fid, "jogador_id": 77, "jogador": "D. Lopy",
                "clube": "Al-Ittihad", "clube_id": ITT, "detalhe": detalhe,
                "minuto": minuto, "jogo_em": data}

    lopy = [cITT(101, AMARELO, "2026-08-21", 30),
            cITT(101, "Yellow-Red Card", "2026-08-21", 68),
            cITT(103, AMARELO, "2026-08-29", 55),
            cITT(104, AMARELO, "2026-09-01", 77)]
    d = situacao(lopy, 4, cal_itt, "2026-09-10")[0]

    ok(d["amarelos"] == 2,
       f"o Lopy ficou com {d['amarelos']} amarelos e são 2. Os dois de 21/08 "
       "foram cancelados junto com a expulsão — o regulamento saudita diz "
       "isso com todas as letras: إلغاء الإنذارين اللذين نتج عنهما البطاقة الحمراء")
    ok(d["no_ciclo"] == 2 and d["faltam"] == 2,
       f"o ciclo dele está errado: {d['no_ciclo']} no ciclo, faltam {d['faltam']}")
    ok(d["dois_amarelos"] == 1 and d["vermelhos"] == 1,
       f"a expulsão de 21/08 não foi contada como uma só: {d}")
    ok(d["jogo_da_pena"] == "Al-Hazem" and d["jogo_da_pena_em"] == "2026-08-24",
       f"a suspensão dele foi cumprida contra o {d['jogo_da_pena']} em "
       f"{d['jogo_da_pena_em']} — era o Al-Hazem em 24/08")
    ok(d["estado"] == "",
       f"em 10/09 o Lopy não pode estar em lista nenhuma: {d['estado']!r} "
       f"({d['motivo']!r}). Ele cumpriu em 24/08 e voltou em 29/08")
    ok(d["jogo_da_pena"] != "Al-Fayha",
       "voltou o defeito exato que o Vini viu: a tela dizia que ele cumpria "
       "contra o Al-Fayha em 08/09 e voltava contra o Al-Faisaly")

    # No dia seguinte à expulsão ele TEM que estar fora — a regra continua
    # valendo, o que mudou foi só a contagem dos amarelos.
    d = situacao(lopy[:2], 4,
                 [dict(p, status=("FT" if p["data"] < "2026-08-22" else "NS"))
                  for p in cal_itt], "2026-08-22")[0]
    ok(d["estado"] == "fora" and d["jogo_da_pena"] == "Al-Hazem",
       f"em 22/08 o Lopy devia estar fora do jogo contra o Al-Hazem: {d}")

    # ── 5c. O ACRÉSCIMO: 45+4 e 45+7 são dois cartões ────────────────────
    # Achado nos dados reais dele (Al-Ahli x Al-Hilal, 01/09):
    #
    #     45+4  Yellow Card  Merih Demiral
    #     45+7  Yellow Card  Merih Demiral
    #     45+7  Red Card     Merih Demiral
    #
    # Guardando só o `elapsed`, os dois amarelos viram "minuto 45" e o segundo
    # some pela chave única do banco. Com UM amarelo no jogo, a regra não
    # reconhece a expulsão por dois amarelos, trata o vermelho como direto e
    # deixa aquele amarelo no acúmulo — o estrago do caso do Lopy, por outro
    # caminho. Aqui a regra recebe os dois e tem que enxergar os dois.
    demiral = [cartao(4, 12, AMARELO, "2026-09-09", 45),
               cartao(4, 12, AMARELO, "2026-09-09", 45),
               cartao(4, 12, VERMELHO, "2026-09-09", 45)]
    for c in demiral:
        c["extra"] = 4 if c is demiral[0] else 7
    d = de(demiral)[12]
    ok(d["dois_amarelos"] == 1 and d["amarelos"] == 0,
       f"os dois amarelos em acréscimo não foram reconhecidos como expulsão "
       f"por dois amarelos: {d}. Se o banco tiver descartado um deles pela "
       "chave única, a conta fica com um amarelo a mais para sempre")
    ok(d["estado"] == "fora",
       "o expulso em acréscimo não ficou fora do jogo seguinte")

    # E o que garante que o banco não descarte: a chave única inclui o extra.
    bd = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    ok("ON CONFLICT (fixture_id, jogador_id, tipo, minuto, extra)" in bd,
       "a chave única dos cartões voltou a ignorar o acréscimo. 45+4 e 45+7 "
       "viram o mesmo cartão e o segundo é descartado em silêncio")
    ok("cartao_evento_unico" in bd and "ADD COLUMN IF NOT EXISTS extra" in bd,
       "sumiu a migração que acrescenta a coluna `extra` e troca a chave "
       "única — sem ela, o banco que já existe continua com a chave antiga")

    # ── 5d. O ALERTA DE GANCHO MAIOR ─────────────────────────────────────
    # A API preenche o `comments` do cartão: "Foul", "Argument", "Violent
    # conduct" (conferido nos jogos da liga em 10/09). O que ela NÃO dá é a
    # duração — o endpoint `injuries`, que traria "Suspended 3 matches", não
    # cobre esta liga (coverage.injuries = false, conferido).
    #
    # Então o alerta é um SINAL, não um número: quando o motivo sugere gancho
    # longo, o jogador fica em "confira" em vez de eu liberá-lo sozinho.
    gancho = ns["_gancho_pode_ser_maior"]
    ok(gancho("Violent conduct") == "conduta violenta",
       f'"Violent conduct" devia virar um alerta: {gancho("Violent conduct")!r}')
    ok(gancho("Serious foul play") and gancho("Spitting"),
       "sumiram motivos graves da tabela de alerta")
    for comum in ("Foul", "Argument", "", None, "Handball"):
        ok(gancho(comum) == "",
           f'"{comum}" virou alerta de gancho maior e não devia — alarme que '
           "toca em todo vermelho é alarme que se aprende a ignorar")

    # Um vermelho por conduta violenta em 09/09. O jogo seguinte do Nassr no
    # calendário é 16/09.
    violento = [dict(cartao(4, 13, VERMELHO, "2026-09-09", 88),
                     motivo="Violent conduct")]
    d = de(violento)[13]
    ok(d["estado"] == "fora" and "conduta violenta" in d["motivo"],
       f"o motivo da expulsão não apareceu enquanto ele está fora: {d}")
    ok("mais de um jogo" in d["motivo"],
       f"o aviso de gancho maior não apareceu: {d['motivo']!r}")

    # Depois de cumprir UM jogo ele NÃO é liberado: fica em "confira".
    d = de(violento, hoje="2026-09-17", cal=_calendario_em("2026-09-17"))[13]
    ok(d["estado"] == "indefinido",
       f"depois de um jogo cumprido, o expulso por conduta violenta foi dado "
       f"como liberado ({d['estado']!r}). Eu não sei de quantos jogos foi o "
       "gancho — liberar por conta própria põe em campo alguém suspenso")
    ok("conduta violenta" in d["motivo"],
       f"o alerta não diz o motivo: {d['motivo']!r}")

    # Mas o alerta EXPIRA. Um aviso que nunca some vira parte do cenário.
    longo = CAL + [jogo(20, "2026-09-30", NASSR, HILAL),
                   jogo(21, "2026-10-07", TAAWOUN, NASSR),
                   jogo(22, "2026-10-14", NASSR, ITTIHAD)]
    tarde = [dict(p, status=("FT" if p["data"] < "2026-10-20" else "NS"))
             for p in longo]
    d = situacao(violento, 4, tarde, "2026-10-20")[0]
    ok(d["estado"] == "",
       f"o alerta de gancho maior não expirou: {d['estado']!r}. Cinco rodadas "
       "depois, qualquer suspensão plausível já acabou — e um aviso "
       "permanente é um aviso que ninguém lê")

    # Vermelho comum continua saindo da lista depois de cumprir.
    comum = [dict(cartao(4, 14, VERMELHO, "2026-09-09", 70), motivo="Foul")]
    d = de(comum, hoje="2026-09-17", cal=_calendario_em("2026-09-17"))[14]
    ok(d["estado"] == "retornando",
       f"vermelho comum devia estar como 'retornando' e está {d['estado']!r}")

    # ── 6. vermelho direto, e vermelho antigo ────────────────────────────
    d = de([cartao(4, 4, VERMELHO, "2026-09-09", 30)])[4]
    ok(d["estado"] == "fora" and "expuls" in d["motivo"],
       f"vermelho no último jogo tem que deixar fora do seguinte: {d}")
    ok(d["amarelos"] == 0, "vermelho direto virou amarelo no acúmulo")

    # ── 7. punição fora do calendário: eu digo que não sei ───────────────
    # Cartão numa partida que não está no calendário que eu tenho. Marcar como
    # liberado seria afirmar sem ter conferido; marcar como suspenso tiraria
    # do Vini um jogador que talvez possa escalar. Então: "não sei".
    solto = [cartao(999, 5, VERMELHO, "2026-09-09", 30)]
    d = de(solto)[5]
    ok(d["estado"] == "indefinido",
       f"cartão em jogo que não está no calendário virou {d['estado']!r} — o "
       "certo é dizer que não consegui conferir")
    ok("calendário" in d["motivo"],
       f"o motivo não explica o que faltou: {d['motivo']!r}")

    # Sem calendário nenhum, ninguém é declarado suspenso por dedução.
    d = de(quatro, cal=[])[1]
    ok(not d["suspenso"],
       "sem calendário a regra voltou a declarar suspensão no escuro")

    # ── 7b. o calendário chega bagunçado, e a ordem sai do código ────────
    d = de(quatro, cal=CAL_FORA_DE_ORDEM)[1]
    ok(d["jogo_da_pena"] == "Al-Taawoun" and d["jogo_da_pena_em"] == "2026-09-16",
       f"com o calendário fora de ordem a pena foi parar em "
       f"{d['jogo_da_pena']!r} ({d['jogo_da_pena_em']!r}). Quem ordena tem "
       "que ser o código: a API não promete ordem nenhuma")
    ok(d["proximo_jogo"] == "Al-Taawoun",
       f"o próximo jogo saiu errado com o calendário bagunçado: "
       f"{d['proximo_jogo']!r}")

    # ── 7a-bis. dois amarelos sem rótulo de expulsão ─────────────────────
    # A segunda rede de segurança: se a fonte inventar um terceiro nome para
    # a expulsão indireta, DOIS amarelos na mesma partida continuam sendo
    # expulsão — não existe outro final para isso. Aqui a fonte manda só dois
    # "Yellow Card" e nenhum vermelho.
    dois_crus = [cartao(4, 11, AMARELO, "2026-09-09", 20),
                 cartao(4, 11, AMARELO, "2026-09-09", 66)]
    d = de(dois_crus)[11]
    ok(d["amarelos"] == 0 and d["dois_amarelos"] == 1,
       f"dois amarelos na mesma partida, sem rótulo de expulsão, não foram "
       f"reconhecidos como expulsão: {d}")
    ok(d["estado"] == "fora",
       "dois amarelos na mesma partida não deixaram o jogador fora do jogo "
       "seguinte. Não existe outro desfecho para dois amarelos num jogo")

    # ── 7c. só os jogos DAQUELE clube contam ─────────────────────────────
    # O calendário tem partidas de Hilal, Ittihad e Taawoun entre as do Nassr.
    # Se elas entrarem na conta, "o jogo seguinte do clube" vira "o jogo
    # seguinte da liga" — e a suspensão é cumprida por um time que não é o
    # dele.
    d = de([cartao(1, 8, VERMELHO, "2026-08-25", 44)],
           hoje="2026-08-26", cal=_calendario_em("2026-08-26"))[8]
    ok(d["jogo_da_pena"] == "Al-Taawoun",
       f"a pena caiu no jogo {d['jogo_da_pena']!r}. Entre 25/08 e 28/08 há um "
       "Hilal x Ittihad no calendário: se ele entrou na conta, a peneira por "
       "clube sumiu e a suspensão está sendo cumprida pelo time errado")

    # ── 7d. status e data discordando ────────────────────────────────────
    # Sem status publicado, quem decide é a data — e 'hoje' NÃO é passado.
    d = de(bento, hoje="2026-08-28", cal=_sem_status(CAL))[3]
    ok(d["estado"] == "fora",
       "sem status publicado, o jogo de HOJE foi tratado como já realizado e "
       "o suspenso sumiu da lista justamente no dia em que ela é lida")
    d = de(bento, hoje="2026-08-29", cal=_sem_status(CAL))[3]
    ok(d["estado"] == "retornando",
       "sem status publicado, a data deixou de servir para saber que o jogo "
       "de ontem já aconteceu")

    # Jogo ADIADO: a data já passou, mas ele não foi jogado. Quem manda é o
    # status — tratar como cumprido liberaria um jogador que ainda deve.
    adiado = [dict(p, status=("NS" if p["fixture_id"] == 2 else p["status"]))
              for p in CAL]
    d = de(bento, hoje="2026-09-10", cal=adiado)[3]
    ok(d["estado"] == "fora",
       "o jogo da suspensão foi ADIADO (data no passado, status NS) e o "
       "jogador foi dado como liberado. Quando data e estado discordam, quem "
       "manda é o estado")

    # ── 7e. suspenso não vira pendurado também ───────────────────────────
    # Três amarelos (a um do limite) MAIS uma expulsão no último jogo. As duas
    # coisas são verdade ao mesmo tempo; a etiqueta que importa é uma só.
    os_dois = tres + [cartao(4, 7, VERMELHO, "2026-09-09", 30)]
    os_dois = [dict(c, jogador_id=7) for c in os_dois]
    d = de(os_dois)[7]
    ok(d["no_ciclo"] == 3 and d["estado"] == "fora",
       f"esperava 3 amarelos e estado 'fora': {d['no_ciclo']}, {d['estado']!r}")
    ok(not d["pendurado"],
       "o jogador apareceu como suspenso E pendurado ao mesmo tempo. Ele está "
       "fora do próximo jogo; a etiqueta de pendurado só tira espaço da que "
       "decide a escalação")

    # ── 8. lixo não derruba a conta ──────────────────────────────────────
    sujo = [{"fixture_id": 1, "jogador_id": None, "detalhe": AMARELO,
             "jogo_em": "2026-08-25", "minuto": 5}] + tres
    ok(len(situacao(sujo, 4, CAL, "2026-09-10")) == 1,
       "cartão sem jogador identificado entrou na lista ou quebrou a conta")
    ok(situacao([], 4, CAL, "2026-09-10") == [],
       "lista vazia devia dar lista vazia")
    for limite in (0, 1, -3):
        d = de(tres, limite=limite)[1]
        ok(isinstance(d["no_ciclo"], int) and d["no_ciclo"] >= 0,
           f"limite {limite} produziu conta inválida: {d}")

    # ── 9. a ordem da tela ───────────────────────────────────────────────
    mistura = quatro + [cartao(f, 9, AMARELO, dia)
                        for f, dia in ((1, "2026-08-25"), (2, "2026-08-28"),
                                       (3, "2026-09-05"))]
    lista = situacao(mistura, 4, CAL, "2026-09-10")
    ok(lista[0]["estado"] == "fora",
       "a lista não começa pelos suspensos — é a informação que decide a "
       "escalação e ela tem que estar no topo")

    # ── 10. o ajuste existe e tem o valor certo ──────────────────────────
    aj = open(os.path.join(RAIZ, "ajustes.py"), encoding="utf-8").read()
    ok('"chave": "cartoes_para_suspender"' in aj,
       "sumiu o ajuste do número de amarelos que suspende — ele existe para "
       "o Vini corrigir sozinho quando a federação mudar a regra de novo")
    bloco = aj[aj.find('"cartoes_para_suspender"'):]
    bloco = bloco[:bloco.find("},")]
    ok('"padrao": 4' in bloco,
       "o padrão do limite deixou de ser 4, que é a regra saudita de hoje")

    # ── 11. a tela mostra contra quem ────────────────────────────────────
    ok("Fora do jogo contra o " in FONTE and "Pendurado para o jogo contra o " in FONTE,
       "a tela voltou a dizer só 'suspenso' sem o adversário. 'Fulano está "
       "suspenso' não ajuda a montar nada; 'fora do jogo contra o Al-Hilal' é "
       "a frase que serve no ar")
    ok("Voltando de suspensão" in FONTE,
       "sumiu a seção de quem acabou de cumprir")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ pendurados: pena amarrada ao jogo seguinte do clube, cumprida "
          "sai da lista, e o caso do Bento fecha em todas as datas")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
