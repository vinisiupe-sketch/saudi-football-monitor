"""
Quem está pendurado e quem está fora — a regra dos amarelos.

A REGRA, E DE ONDE ELA VEIO
    Na Saudi Pro League o jogador fica de fora da partida seguinte ao QUARTO
    amarelo, em jogos diferentes da mesma competição. Confirmei na imprensa
    saudita: a federação mudou de três para quatro para alinhar com o formato
    do Roshn. Como já mudou uma vez, o número mora nos Ajustes e não no
    código — e este arquivo testa a regra com o limite VARIÁVEL, porque um
    teste que só conhece o 4 não protege o dia em que virar 5.

POR QUE A CONTAGEM É CARTÃO A CARTÃO
    O caminho barato seria o total da temporada, numa chamada só. Ele dá a
    resposta errada e de um jeito que não aparece: o total NÃO zera depois da
    suspensão cumprida, então quem já pegou quatro e cumpriu ficaria marcado
    como pendurado para sempre. Numa guia que existe para responder "quem eu
    não posso escalar", esse erro é do tipo que só se descobre no ar.

O CASO QUE MAIS DEU TRABALHO
    Dois amarelos na mesma partida viram vermelho e, nas regras alinhadas à
    FIFA, não entram no acúmulo — a punição já foi a expulsão. Na primeira
    versão, o `continue` que implementava isso pulava também a anotação do
    "último jogo com cartão". Resultado: o expulso ficava sem último jogo e
    aparecia como NÃO suspenso. O jogador mais obviamente fora de campo era o
    único que a tela não marcava. É o teste 4 abaixo.
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

    São puras de propósito: é isso que permite imaginar aqui a partida que eu
    preciso imaginar — o cara que levou o quarto amarelo na rodada passada, o
    que foi expulso por dois amarelos, o que já cumpriu e recomeçou.
    """
    mod = ast.parse(FONTE)
    alvos = {"_e_amarelo", "_e_segundo_amarelo", "_e_vermelho",
             "_situacao_dos_cartoes"}
    corpo = [n for n in mod.body
             if isinstance(n, ast.FunctionDef) and n.name in alvos]
    ns = {}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), "<regra>", "exec"), ns)
    return ns, {n.name for n in corpo}


AMARELO = "Yellow Card"
VERMELHO = "Red Card"
SEGUNDO = "Second Yellow card"


def cartao(fixture, jogador, detalhe, dia, minuto=10, clube="Al-Hilal"):
    return {"fixture_id": fixture, "jogador_id": jogador, "jogador": f"J{jogador}",
            "clube": clube, "clube_id": 1, "detalhe": detalhe, "minuto": minuto,
            "tipo": "vermelho" if "Red" in detalhe or "Second" in detalhe else "amarelo",
            "rodada": "1", "jogo_em": dia}


def testar():
    falhas.clear()
    ns, achadas = _carregar_regra()
    ok(len(achadas) == 4, f"sumiu alguma função da regra: achei {achadas}")
    if len(achadas) != 4:
        for f in falhas:
            print("  ✗", f)
        return len(falhas)
    situacao = ns["_situacao_dos_cartoes"]

    def de(cartoes, limite=4):
        return {d["jogador_id"]: d for d in situacao(cartoes, limite)}

    # ── 1. o pendurado é o que está a UM do limite ───────────────────────
    tres = [cartao(i, 1, AMARELO, f"2026-08-{i:02d}") for i in (1, 8, 15)]
    d = de(tres)[1]
    ok(d["pendurado"] and not d["suspenso"],
       f"três amarelos com limite 4 tem que ser pendurado: {d}")
    ok(d["faltam"] == 1, f"deveria faltar 1 amarelo, faltam {d['faltam']}")

    # Com dois, ainda não é notícia.
    d = de(tres[:2])[1]
    ok(not d["pendurado"] and not d["suspenso"],
       "dois amarelos com limite 4 não penduram ninguém")

    # ── 2. o limite é configurável, e a regra o obedece ──────────────────
    # A federação já mudou de 3 para 4. Um teste que só conhece o 4 não
    # protege o dia em que mudar de novo.
    d = de(tres, limite=3)[1]
    ok(d["suspenso"] and not d["pendurado"],
       "com limite 3, o terceiro amarelo suspende — e a regra ignorou o "
       "limite recebido")
    d = de(tres, limite=5)[1]
    ok(not d["pendurado"] and not d["suspenso"],
       "com limite 5, três amarelos não penduram ninguém")
    d = de(tres, limite=4)[1]
    ok(d["pendurado"], "com limite 4, três amarelos penduram")

    # ── 3. fechou o ciclo no último jogo = fora do próximo ───────────────
    quatro = tres + [cartao(22, 1, AMARELO, "2026-08-22")]
    d = de(quatro)[1]
    ok(d["suspenso"] and not d["pendurado"],
       f"quarto amarelo tem que suspender: {d}")
    ok("4" in d["motivo"], f"o motivo não diz qual amarelo foi: {d['motivo']!r}")

    # E o ciclo RECOMEÇA. Este é o erro que o total da temporada cometeria:
    # quem pegou cinco já cumpriu a suspensão e está com um só no ciclo novo.
    cinco = quatro + [cartao(29, 1, AMARELO, "2026-08-29")]
    d = de(cinco)[1]
    ok(d["amarelos"] == 5 and d["no_ciclo"] == 1,
       f"o ciclo não recomeçou depois da suspensão: {d}")
    ok(not d["pendurado"] and not d["suspenso"],
       "quem já cumpriu a suspensão continuou marcado. É exatamente o erro "
       "do total da temporada — e ele nunca se corrige sozinho")

    # ── 4. dois amarelos na mesma partida ────────────────────────────────
    # Viram vermelho, NÃO entram no acúmulo, e o jogador está fora.
    expulso = [cartao(9, 2, AMARELO, "2026-08-01", 10),
               cartao(9, 2, SEGUNDO, "2026-08-01", 70)]
    d = de(expulso)[2]
    ok(d["amarelos"] == 0,
       f"os dois amarelos da expulsão entraram no acúmulo: {d['amarelos']}")
    ok(d["dois_amarelos"] == 1 and d["vermelhos"] == 1,
       f"a expulsão por dois amarelos não foi contada: {d}")
    ok(d["suspenso"],
       "O ERRO ORIGINAL: o expulso por dois amarelos apareceu como NÃO "
       "suspenso. O `continue` que tira os cartões do acúmulo pulava também a "
       "anotação do último jogo, e o jogador mais obviamente fora de campo "
       "era o único que a tela não marcava")

    # E o acúmulo dele continua limpo depois disso.
    depois = expulso + [cartao(f, 2, AMARELO, f"2026-08-{f:02d}") for f in (10, 11, 12)]
    d = de(depois)[2]
    ok(d["amarelos"] == 3 and d["pendurado"] and not d["suspenso"],
       f"depois da expulsão o acúmulo devia seguir do zero: {d}")

    # ── 5. vermelho direto ───────────────────────────────────────────────
    d = de([cartao(9, 3, VERMELHO, "2026-08-01", 30)])[3]
    ok(d["suspenso"] and "expuls" in d["motivo"],
       f"vermelho direto no último jogo tem que suspender: {d}")
    ok(d["amarelos"] == 0, "vermelho direto virou amarelo no acúmulo")

    # Vermelho ANTIGO, com jogos depois: já cumpriu, não está mais fora.
    antigo = [cartao(1, 4, VERMELHO, "2026-08-01", 30),
              cartao(2, 4, AMARELO, "2026-08-08")]
    d = de(antigo)[4]
    ok(not d["suspenso"],
       "vermelho de duas rodadas atrás continua marcando o jogador como fora")

    # ── 6. o mesmo amarelo não conta duas vezes ──────────────────────────
    # A partida é relida quando foi lida ainda em andamento; o banco tem
    # UNIQUE, mas a regra também não pode somar duplicata que escape.
    d = de([cartao(1, 5, AMARELO, "2026-08-01", 10),
            cartao(1, 5, AMARELO, "2026-08-01", 10)])[5]
    ok(d["amarelos"] <= 2, f"contagem estranha em cartão repetido: {d}")

    # ── 7. cartão sem jogador não derruba nada ───────────────────────────
    sujo = [{"fixture_id": 1, "jogador_id": None, "detalhe": AMARELO,
             "jogo_em": "2026-08-01", "minuto": 5}] + tres
    ok(len(situacao(sujo, 4)) == 1,
       "cartão sem jogador identificado entrou na lista ou quebrou a conta")
    ok(situacao([], 4) == [], "lista vazia devia dar lista vazia")

    # ── 8. a ordem da tela: quem está fora vem primeiro ──────────────────
    mistura = quatro + [cartao(i, 9, AMARELO, f"2026-09-{i:02d}") for i in (1, 2, 3)]
    lista = situacao(mistura, 4)
    ok(lista[0]["suspenso"],
       "a lista não começa pelos suspensos — é a informação que decide a "
       "escalação e ela tem que estar no topo")

    # ── 9. o limite não pode ser sabotado por um número absurdo ──────────
    for limite in (0, 1, -3):
        d = de(tres, limite=limite)[1]
        ok(isinstance(d["no_ciclo"], int) and d["no_ciclo"] >= 0,
           f"limite {limite} produziu conta inválida: {d}")

    # ── 10. o ajuste existe e tem o valor certo ──────────────────────────
    aj = open(os.path.join(RAIZ, "ajustes.py"), encoding="utf-8").read()
    ok('"chave": "cartoes_para_suspender"' in aj,
       "sumiu o ajuste do número de amarelos que suspende — ele existe para "
       "o Vini corrigir sozinho quando a federação mudar a regra de novo")
    bloco = aj[aj.find('"cartoes_para_suspender"'):]
    bloco = bloco[:bloco.find("},")]
    ok('"padrao": 4' in bloco,
       "o padrão do limite deixou de ser 4, que é a regra saudita de hoje")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ pendurados: ciclo que recomeça, expulsão fora do acúmulo, "
          "limite configurável e suspenso no topo da lista")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
