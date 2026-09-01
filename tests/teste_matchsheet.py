"""
A leitura do matchsheet oficial da SPL (PDF do mediahub) — separar titular de
reserva, achar goleiro e capitão, sem gastar token de IA.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    A primeira versão de `matchsheet.extrair()` parecia certa isolada (testada
    à mão, palavra por palavra, contra o PDF real) e saiu errada rodando como
    módulo, por dois motivos que só aparecem com o arquivo inteiro:

    1. Nome e número do MESMO jogador podem sair com "top" (posição vertical)
       a menos de 1px de diferença um do outro — fonte de número tem linha de
       base diferente da fonte de nome. Arredondar pra inteiro (`round(top)`)
       cruza essa fronteira às vezes sim, às vezes não: "THEO" (165.43) e
       "19" (165.92) caíam em linhas DIFERENTES (165 e 166), quebrando o
       jogador em dois pedaços incompletos — um sem número, outro sem nome —
       e os dois eram descartados. O goleiro nunca ficava marcado pelo mesmo
       motivo: "BONO" (152.41) e o "GK" dele (152.9) caindo em buckets
       diferentes.

    2. O rótulo lateral do template ("STARTING"/"SUBSTITUTE"), girado 90°,
       vira letras soltas (P, U, E, N, IL...) espalhadas entre as linhas de
       jogador. Um filtro ingênuo por posição x fixa (testado à mão só contra
       o time da casa) quebrava no time visitante, porque a faixa x do rótulo
       muda de lado. E usar o MENOR x0 entre os números pra achar essa faixa
       quebrava de novo: teve diagrama de formação tática (mesma camisa
       numerada de novo, solta mais abaixo na página) com x0 menor que a
       coluna de número de verdade, puxando o corte errado.

    A correção: agrupar linha por PROXIMIDADE (não por arredondamento) e
    achar a faixa do rótulo pela MEDIANA dos x0 dos números (não o mínimo) —
    ver `_linhas_por_coluna` e `_sem_ruido_lateral` em matchsheet.py.

Fixture real, não inventada
    tests/fixtures/matchsheet_al_hilal_al_ahli.pdf é o PDF oficial que você
    baixou do mediahub.spl.media: Al Hilal x Al Ahli, MD3, temporada 26/27,
    Kingdom Arena. A escalação abaixo foi conferida à mão contra ele, campo a
    campo, incluindo o "CGK" colado do Mendy (capitão E goleiro do Al Ahli).
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import matchsheet  # noqa: E402

PDF = os.path.join(RAIZ, "tests", "fixtures", "matchsheet_al_hilal_al_ahli.pdf")

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


# Números de camisa esperados, na ordem que o PDF lista — é o dado mais
# fácil de conferir de cabo a rabo sem transcrever nome por nome nas
# checagens de ordem/contagem abaixo.
HILAL_TITULARES = ["37", "19", "78", "3", "2", "38", "6", "8", "22", "75", "27"]
HILAL_RESERVAS = ["33", "11", "18", "24", "28", "55", "72", "77", "87"]
AHLI_TITULARES = ["16", "2", "3", "28", "5", "8", "6", "30", "13", "17", "7"]
AHLI_RESERVAS = ["1", "9", "11", "21", "29", "31", "46", "47", "66"]


def testar():
    falhas.clear()
    r = matchsheet.extrair(PDF)

    # ── 1. cabeçalho ─────────────────────────────────────────────────────
    ok(r["temporada"] == "26/27", f"temporada: esperava 26/27, veio {r['temporada']!r}")
    ok(r["rodada"] == "3", f"rodada: esperava 3, veio {r['rodada']!r}")
    ok(r["estadio"] == "Kingdom Arena", f"estádio: veio {r['estadio']!r}")
    ok(r["data"] == "1 September 2026", f"data: veio {r['data']!r}")
    ok(r["hora"] == "21:00", f"hora: veio {r['hora']!r}")
    print("  cabeçalho: temporada, rodada, estádio, data e hora corretos")

    # ── 2. nome dos times e técnicos ────────────────────────────────────
    ok(r["casa"]["time"] == "AL HILAL", f"time da casa: veio {r['casa']['time']!r}")
    ok(r["fora"]["time"] == "AL AHLI", f"time de fora: veio {r['fora']['time']!r}")
    ok(r["casa"]["tecnico"] == "SIMONE INZAGHI",
       f"técnico da casa: veio {r['casa']['tecnico']!r}")
    ok(r["fora"]["tecnico"] == "MARINO PUŠIĆ",
       f"técnico de fora: veio {r['fora']['tecnico']!r}")
    print("  times e técnicos: AL HILAL/SIMONE INZAGHI, AL AHLI/MARINO PUŠIĆ")

    # ── 3. titulares e reservas, na ordem certa e com a contagem certa ──
    for lado, esperado_tit, esperado_res in (
            ("casa", HILAL_TITULARES, HILAL_RESERVAS),
            ("fora", AHLI_TITULARES, AHLI_RESERVAS)):
        tit = [j["numero"] for j in r[lado]["titulares"]]
        res = [j["numero"] for j in r[lado]["reservas"]]
        ok(tit == esperado_tit,
           f"{lado}: titulares esperados {esperado_tit}, veio {tit}")
        ok(res == esperado_res,
           f"{lado}: reservas esperadas {esperado_res}, veio {res}")
        ok(len(r[lado]["titulares"]) == 11,
           f"{lado}: titular tem que ser 11, veio {len(r[lado]['titulares'])}")
        # Nenhum nome pode ter sobrado vazio nem carregado lixo do rótulo
        # lateral (letra solta colada, tipo "U ZAKARIA HAWSAWI").
        for j in r[lado]["titulares"] + r[lado]["reservas"]:
            ok(j["nome"], f"{lado} #{j['numero']}: nome veio vazio")
            ok(len(j["nome"].split()[0]) > 1 or j["nome"].split()[0] == j["nome"],
               f"{lado} #{j['numero']}: nome com cara de lixo do rótulo colado — {j['nome']!r}")
    print("  titulares/reservas: 11 + 9 por time, na ordem do PDF, sem lixo colado no nome")

    # ── 4. goleiro e capitão ─────────────────────────────────────────────
    bono = r["casa"]["titulares"][0]
    ok(bono["numero"] == "37" and bono["goleiro"],
       f"Bono (#37, titular) deveria estar marcado goleiro — veio {bono}")
    alowais = r["casa"]["reservas"][0]
    ok(alowais["numero"] == "33" and alowais["goleiro"],
       f"Alowais (#33, reserva) deveria estar marcado goleiro — veio {alowais}")
    nasser = next(j for j in r["casa"]["titulares"] if j["numero"] == "6")
    ok(nasser["capitao"], f"Nasser Aldawsari (#6) deveria estar marcado capitão — veio {nasser}")

    # Edouard Mendy: "CGK" colado — capitão E goleiro no mesmo token.
    mendy = r["fora"]["titulares"][0]
    ok(mendy["numero"] == "16" and mendy["goleiro"] and mendy["capitao"],
       f"Mendy (#16) tem marca colada CGK — deveria ser goleiro E capitão, veio {mendy}")
    ok("MENDY" in mendy["nome"], f"titular #16 do Al Ahli deveria ser Mendy, veio {mendy['nome']!r}")
    print("  goleiro/capitão: Bono, Alowais e Nasser Aldawsari certos; "
          "Mendy com marca colada CGK (capitão + goleiro) reconhecida")

    # ── 5. nomes por extenso batem com o PDF (amostra) ──────────────────
    nomes_hilal = {j["numero"]: j["nome"] for j in r["casa"]["titulares"]}
    ok(nomes_hilal["19"] == "THEO HERNANDEZ", f"#19 Al Hilal: veio {nomes_hilal.get('19')!r}")
    ok(nomes_hilal["3"] == "KALIDOU KOULIBALY", f"#3 Al Hilal: veio {nomes_hilal.get('3')!r}")
    ok(nomes_hilal["8"] == "RUBEN NEVES", f"#8 Al Hilal: veio {nomes_hilal.get('8')!r}")
    nomes_ahli = {j["numero"]: j["nome"] for j in r["fora"]["titulares"]}
    ok(nomes_ahli["3"] == "ROGER IBAÑEZ", f"#3 Al Ahli: veio {nomes_ahli.get('3')!r}")
    ok(nomes_ahli["7"] == "ANTONIO TRINCÃO", f"#7 Al Ahli: veio {nomes_ahli.get('7')!r}")
    print("  nomes por extenso: amostra dos dois times bate com o PDF")

    # ── 6. cruzar_com_elenco: casa por camisa, não some dado do PDF ─────
    elenco_falso = [
        {"camisa": "37", "nome": "Yassine Bono", "nome_curto": "BONO",
         "nacionalidade": "Morocco", "foto": "http://x/bono.jpg"},
        {"camisa": "19", "nome": "Théo Hernández", "nome_curto": "T. HERNÁNDEZ",
         "nacionalidade": "France", "foto": ""},
    ]
    cruzado = matchsheet.cruzar_com_elenco(r["casa"]["titulares"], elenco_falso)
    por_numero = {j["numero"]: j for j in cruzado}
    ok(por_numero["37"]["nome"] == "Yassine Bono",
       f"cruzamento não trouxe o nome acentuado do elenco: {por_numero['37']}")
    ok(por_numero["37"]["nacionalidade"] == "Morocco",
       f"cruzamento não trouxe a nacionalidade: {por_numero['37']}")
    ok(por_numero["78"]["nome"] == "ALI LAJAMI",
       "jogador sem casamento no elenco deveria manter o nome do PDF, "
       f"veio {por_numero['78']['nome']!r}")
    ok(por_numero["78"]["nacionalidade"] == "",
       "jogador sem casamento não deveria ter nacionalidade inventada, "
       f"veio {por_numero['78']['nacionalidade']!r}")
    ok(len(cruzado) == len(r["casa"]["titulares"]),
       "cruzar_com_elenco não pode ganhar nem perder jogador")
    print("  cruzar_com_elenco: casa por camisa, mantém o do PDF quando não acha no elenco")

    # ── 7. texto_titulares: bandeira só quando cruzou nacionalidade ─────
    texto = matchsheet.texto_titulares("Al Hilal", cruzado)
    linhas = texto.split("\n")
    ok(linhas[0] == "AL HILAL", f"primeira linha deveria ser o nome do time, veio {linhas[0]!r}")
    linha_bono = next(l for l in linhas if "BONO" in l)
    ok(linha_bono.startswith("🇲🇦"), f"Bono (Marrocos cruzado) deveria sair com bandeira: {linha_bono!r}")
    linha_lajami = next(l for l in linhas if "LAJAMI" in l)
    ok(not any(ord(c) > 0x1F1E5 for c in linha_lajami.split()[0]) or linha_lajami.startswith("78"),
       f"Lajami (sem cruzamento) não deveria sair com bandeira chutada: {linha_lajami!r}")
    print("  texto_titulares: bandeira aparece só quando a nacionalidade veio do cruzamento")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ matchsheet: PDF real lido certo — titulares, reservas, GK, capitão, cruzamento")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
