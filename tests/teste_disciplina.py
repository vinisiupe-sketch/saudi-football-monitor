"""
As decisões da Comissão de Disciplina da SAFF, lidas do HTML de verdade.

POR QUE ESTA FONTE EXISTE
    A API-Football conta que houve expulsão. Ela não conta o gancho: o
    endpoint que traria isso não cobre a liga saudita — conferido, com
    coverage.injuries = false e zero entradas. E a diferença importa: em
    07/09/26 o Óscar Rodríguez, do Diriyah, levou DOIS jogos, não um. Um app
    que supõe sempre um devolve o jogador ao campo uma rodada antes.

A ARMADILHA CENTRAL, E POR QUE ELA TEM TESTE PRÓPRIO
    As decisões vêm em duas formas, e trocá-las inverte o resultado:

        إيقاف ... (2) مباراتين بما في ذلك الإيقاف التلقائي
        "suspenso por (2) partidas, INCLUINDO a automática"   → total 2, extra 1

        بالإضافة إلى مباراة الإيقاف التلقائي ... غرامة
        "ALÉM da partida automática, multa"                    → total 1, extra 0

    Ler o (2) da primeira como "duas ALÉM da automática" daria três jogos, e o
    jogador ficaria fora de uma rodada em que podia jogar. É o mesmo tipo de
    erro por uma unidade que já apareceu duas vezes neste projeto.

O HTML É REAL
    tests/amostras/saff_disciplina_2026-09-07.html foi copiado da página no
    ar, sem retoque. Testar contra a marcação que o site entrega — e não
    contra a que eu imaginei que ele entregava — é o que fez este parser
    funcionar de primeira depois de eu ter errado a regex dos artigos: eu
    procurava "المادة" e o texto escreve "للمادة", com o prefixo grudado.
    Contra um fixture inventado por mim, aquele erro teria passado.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import disciplina

AMOSTRA = os.path.join(RAIZ, "tests", "amostras",
                       "saff_disciplina_2026-09-07.html")

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


# Os textos como a SAFF os publicou, em 07/09 e 10/09 de 2026.
COM_GANCHO = (
    "أولاً: ثبوت مخالفة لاعب نادي الدرعية/ أوسكار رودريغيز للمادة (48-1-2) من "
    "لائحة الانضباط والأخلاق.\n"
    "ثانياً: إيقاف لاعب نادي الدرعية/ أوسكار رودريغيز (2) مباراتين بما في ذلك "
    "الإيقاف التلقائي بموجب البطاقة الحمراء المباشرة.\n"
    "ثالثاَ: إلزام لاعب نادي الدرعية/ أوسكار رودريغيز بدفع غرامة مالية قدرها "
    "(20,000) عشرون ألف ريال.\n"
    "رابعاً: قرار غير قابل للاستئناف وفقاً للمادة (144)."
)
SO_AUTOMATICA = (
    "أولاً: ثبوت مخالفة لاعب نادي الطائي/ مهند حسين الحارثي للمادة (48-1-1).\n"
    "ثانياً: بالإضافة إلى مباراة الإيقاف التلقائي المترتب بموجب البطاقة الحمراء "
    "المباشرة، إلزام لاعب نادي الطائي/ مهند حسين الحارثي بدفع غرامة مالية "
    "قدرها (7,500) سبعة آلاف وخمسمائة ريال.\n"
    "ثالثاَ: قرار غير قابل للاستئناف وفقاً للمادة (144)."
)
QUATRO_JOGOS = (
    "أولاً: ثبوت مخالفة مترجم النادي الأهلي/ صلاح الدين دهيثم للمادة (49-2-2).\n"
    "ثانياً: إيقاف مترجم النادي الأهلي/ صلاح الدين دهيثم (4) أربع مباريات بما "
    "في ذلك الإيقاف التلقائي بموجب البطاقة الحمراء المباشرة.\n"
    "ثالثاَ: إلزام ... بدفع غرامة مالية قدرها (40,000) أربعون ألف ريال.\n"
    "رابعاً: قرار غير قابل للاستئناف وفقاً للمادة (144)."
)
SO_MULTA_CLUBE = (
    "أولاً: ثبوت مخالفة نادي الطائي للمادة (54-1).\n"
    "ثانياً: إلزام نادي الطائي بدفع غرامة مالية قدرها (7,500) ريال.\n"
    "ثالثاَ: قرار غير قابل للاستئناف وفقاً للمادة (144)."
)


def testar():
    falhas.clear()

    # ── 1. o total, e o extra derivado dele ──────────────────────────────
    ok(disciplina.jogos_de_suspensao(COM_GANCHO) == 2,
       f"o Óscar Rodríguez pegou 2 jogos no TOTAL e saiu "
       f"{disciplina.jogos_de_suspensao(COM_GANCHO)}")
    ok(disciplina.jogos_extras(COM_GANCHO) == 1,
       "o (2) da decisão inclui a partida automática, então sobra UM jogo "
       "além dela. Ler como 'dois além' tira o jogador de uma rodada a mais "
       "do que a SAFF mandou")
    ok(disciplina.jogos_de_suspensao(QUATRO_JOGOS) == 4
       and disciplina.jogos_extras(QUATRO_JOGOS) == 3,
       "os 4 jogos do tradutor do Al-Ahli saíram errados")

    # A outra forma: só a automática, mais multa.
    ok(disciplina.jogos_de_suspensao(SO_AUTOMATICA) == 1,
       '"بالإضافة إلى مباراة الإيقاف التلقائي" quer dizer que a pena é a '
       "partida automática mais a multa — total UM")
    ok(disciplina.jogos_extras(SO_AUTOMATICA) == 0,
       "esta decisão não tem gancho além do automático, e o app achou que tem")

    # Decisão sem suspensão nenhuma (multa a clube) não inventa número.
    ok(disciplina.jogos_de_suspensao(SO_MULTA_CLUBE) is None,
       "uma multa a clube virou suspensão de jogo")

    # ── 2. a multa não é confundida com o número de jogos ────────────────
    # As duas vêm entre parênteses. Ancorar na palavra "partida" é o que
    # separa (2) مباراتين de (20,000) ريال.
    ok(disciplina.multa_em_riais(COM_GANCHO) == 20000,
       f"multa errada: {disciplina.multa_em_riais(COM_GANCHO)}")
    ok(disciplina.multa_em_riais(QUATRO_JOGOS) == 40000, "multa errada")
    ok(disciplina.jogos_de_suspensao(SO_MULTA_CLUBE) is None,
       "o valor da multa foi lido como quantidade de jogos")

    # ── 3. artigos ───────────────────────────────────────────────────────
    # O texto escreve "للمادة" (com prefixo), não "المادة". Procurar a forma
    # com alif devolvia lista vazia em TODAS as decisões — e calado, porque
    # "nenhum artigo citado" é uma resposta plausível.
    ok(disciplina.artigos(COM_GANCHO) == ["48-1-2", "144"],
       f"artigos errados: {disciplina.artigos(COM_GANCHO)}")
    ok(disciplina.artigos("texto sem artigo nenhum") == [],
       "inventou artigo onde não há")

    # ── 4. recurso: a ordem dos testes é a regra ─────────────────────────
    # "غير قابل للاستئناف" (NÃO cabe) contém "قابل للاستئناف" (cabe). Testar o
    # segundo primeiro devolveria "cabe recurso" em toda decisão que diz o
    # contrário — a mesma armadilha do "Yellow-Red Card", que contém "Red
    # Card".
    ok(disciplina.cabe_recurso(COM_GANCHO) is False,
       "a decisão diz que NÃO cabe recurso e o app entendeu que cabe")
    ok(disciplina.cabe_recurso("قرار قابل للاستئناف خلال ثلاثة أيام") is True,
       "decisão recorrível não foi reconhecida")
    ok(disciplina.cabe_recurso("texto que não fala de recurso") is None,
       "inventou uma resposta sobre recurso onde a decisão não diz nada")

    # ── 5. contra quem é a decisão ───────────────────────────────────────
    a = disciplina.alvo_da_decisao("لاعب نادي الدرعية/ أوسكار رودريغيز")
    ok(a["tipo"] == "jogador" and a["nome"] == "أوسكار رودريغيز"
       and a["clube"] == "الدرعية",
       f"alvo lido errado: {a}")
    a = disciplina.alvo_da_decisao("نادي الطائي")
    ok(a["tipo"] == "clube" and a["clube"] == "نادي الطائي" and not a["nome"],
       f"decisão contra clube foi lida como pessoa: {a}")
    # Em 07/09 quem pegou quatro jogos foi o TRADUTOR do Al-Ahli. Não é
    # jogador, e continua sendo notícia.
    a = disciplina.alvo_da_decisao("مترجم النادي الأهلي/ صلاح الدين دهيثم")
    ok(a["tipo"] == "dirigente" and a["nome"] == "صلاح الدين دهيثم",
       f"o tradutor do Al-Ahli foi lido como {a}")
    ok(disciplina.alvo_da_decisao("")["tipo"] == "", "texto vazio virou alvo")

    # ── 6. é de cartão vermelho? ─────────────────────────────────────────
    ok(disciplina.por_vermelho("", COM_GANCHO) is True,
       "expulsão não reconhecida como decisão de vermelho")
    ok(disciplina.por_vermelho("", SO_MULTA_CLUBE) is False,
       "multa por conduta de torcida foi tratada como expulsão — só as de "
       "vermelho podem virar gancho de jogo")

    # ── 7. o HTML REAL, ponta a ponta ────────────────────────────────────
    ok(os.path.exists(AMOSTRA), f"sumiu a amostra real: {AMOSTRA}")
    if os.path.exists(AMOSTRA):
        html = open(AMOSTRA, encoding="utf-8").read()
        r = disciplina.ler_decisoes(html)
        ok(not r["erros"], f"erros ao ler a página real: {r['erros']}")
        ok(len(r["decisoes"]) == 2,
           f"a página de 07/09 tem 2 decisões da Roshn, saíram "
           f"{len(r['decisoes'])}")
        por_nome = {d["nome"]: d for d in r["decisoes"]}

        oscar = por_nome.get("أوسكار رودريغيز")
        ok(oscar is not None, f"não achei o Óscar: {list(por_nome)}")
        if oscar:
            ok(oscar["jogos_total"] == 2 and oscar["jogos_extras"] == 1,
               f"Óscar com jogos errados: {oscar['jogos_total']}/"
               f"{oscar['jogos_extras']}")
            ok(oscar["multa"] == 20000, "multa do Óscar errada")
            ok(oscar["tipo"] == "jogador", "Óscar não foi lido como jogador")
            ok(oscar["clube"] == "الدرعية", f"clube: {oscar['clube']}")
            # É este campo que casa com o cartão da API-Football: a data do
            # JOGO, não a da decisão. O cartão dele é de 03/09; a decisão saiu
            # em 07/09. Casar pela data errada não acha nada.
            ok(oscar["jogo_em"] == "2026-09-03",
               f"a data do JOGO saiu como {oscar['jogo_em']!r} — é ela que "
               "casa com o cartão, e não a data da decisão (2026-09-07)")
            ok(oscar["data"] == "2026-09-07",
               f"a data da decisão saiu como {oscar['data']!r}")
            ok(oscar["por_vermelho"] is True, "não marcado como de vermelho")
            ok(oscar["competicao_pt"] == "Roshn Saudi League",
               f"competição: {oscar['competicao_pt']!r}")
            ok(oscar["numero"] and "2026" in oscar["numero"],
               f"número da decisão: {oscar['numero']!r}")

        tradutor = por_nome.get("صلاح الدين دهيثم")
        ok(tradutor is not None and tradutor["jogos_total"] == 4
           and tradutor["tipo"] == "dirigente",
           f"o tradutor do Al-Ahli saiu errado: {tradutor}")

    # ── 8. o filtro de competição conta o que deixou de fora ─────────────
    # Mesmo princípio da guia de Arbitragem: num dia sem nada da Roshn, saber
    # que havia seis decisões e todas eram do sub-21 é uma informação
    # completamente diferente de "não saiu nada".
    fora = """<table><tr><th>رقم وتاريخ القرار</th><th>a</th><th>b</th>
      <th>c</th><th>d</th><th>e</th></tr>
      <tr><td>9/ ل ض / 2026<br>2026-09-01</td><td>دوري جوّي للنخبة تحت 21</td>
      <td>س - ص<br>(2026-08-30)</td><td>نادي س</td><td>x</td><td>y</td></tr>
      </table>"""
    r = disciplina.ler_decisoes(fora)
    ok(not r["decisoes"] and len(r["ignoradas"]) == 1,
       f"a decisão do sub-21 devia ser ignorada E contada: {r}")
    ok(r["ignoradas"][0]["competicao"] == "دوري جوّي للنخبة تحت 21",
       "a competição ignorada não voltou identificada — sem o nome, você não "
       "sabe SE valia a pena")

    # ── 9. lixo não derruba nada ─────────────────────────────────────────
    for entrada in ("", "<html><body>sem tabela</body></html>", "<table></table>"):
        r = disciplina.ler_decisoes(entrada)
        ok(isinstance(r.get("decisoes"), list),
           f"HTML inesperado quebrou a leitura: {entrada[:30]!r}")

    # ── 10. as datas publicadas saem do índice ───────────────────────────
    # A SAFF não publica todo dia, e não publica no dia do jogo: a decisão do
    # jogo de 08/09 saiu em 10/09. Varrer data por data seria chutar; a
    # própria página lista quais existem.
    d = disciplina.datas_publicadas(
        'a <a href="x&mdate=2026-09-10#new">1</a> b '
        '<a href="y&mdate=2026-09-10">2</a> <a href="z&mdate=2026-09-07">3</a>')
    ok(d == ["2026-09-10", "2026-09-07"],
       f"datas do índice erradas (ou repetidas): {d}")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ disciplina: total x extra sem trocar a unidade, HTML real "
          "lido, e o que fica de fora volta contado")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
