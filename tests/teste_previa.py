"""
O que sustenta a prévia: a escalação deduzida e a conferência dos números.

As duas existem pelo mesmo motivo — um modelo escrevendo prévia de futebol
inventa estatística com naturalidade. A escalação provável é a parte que EU
deduzo, e por isso precisa dizer o quanto deduziu. A conferência é a rede
embaixo do que o modelo escreve.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import previa


def _jogador(nome, camisa="9", papel="Midfielder"):
    return {"shortName": nome, "bibNumber": camisa, "roleLabel": papel}


def _escala(time_id, nomes, formacao="4-3-3", lado="home"):
    outro = "away" if lado == "home" else "home"
    return {lado: {"teamId": time_id, "tacticalFormation": formacao,
                   "fielded": [_jogador(n) for n in nomes], "benched": []},
            outro: {"teamId": "outro", "tacticalFormation": "4-4-2",
                    "fielded": [], "benched": []}}


def testar():
    falhas = []

    def conferir(nome, deu, esperado):
        if deu != esperado:
            falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")

    # ─────────────────────────────────────── escalação provável
    T = "spl::Football_Team::hilal"
    base = [f"J{i}" for i in range(1, 12)]
    jogos = [{"matchId": f"m{i}"} for i in range(4)]
    escalas = {
        # m0 é o mais recente. "Novato" entrou no lugar de J11 nos dois últimos.
        "m0": _escala(T, base[:10] + ["Novato"]),
        "m1": _escala(T, base[:10] + ["Novato"], lado="away"),
        "m2": _escala(T, base),
        "m3": _escala(T, base),
    }
    p = previa.escalacao_provavel(jogos, escalas, T)
    conferir("olhou os quatro jogos", p["jogos_olhados"], 4)
    conferir("onze titulares", len(p["titulares"]), 11)
    conferir("marcado como dedução", p["origem"], "provavel")
    nomes = [t["nome"] for t in p["titulares"]]
    conferir("os dez de sempre estão", all(n in nomes for n in base[:10]), True)
    # J11 e Novato empatam em 2 aparições. Quem jogou mais recentemente entra:
    # um titular que voltou de lesão vale mais que um reserva com o mesmo total.
    conferir("desempate pelo mais recente", "Novato" in nomes, True)
    conferir("o que parou de jogar sai", "J11" in nomes, False)
    por_nome = {t["nome"]: t for t in p["titulares"]}
    conferir("conta de titularidades", por_nome["J1"]["vezes"], 4)
    conferir("conta do novato", por_nome["Novato"]["vezes"], 2)
    conferir("pegou a formação", p["formacao"], "4-3-3")

    # Time que aparece como visitante em todos os jogos tem que ser achado do
    # mesmo jeito — o lado no JSON é do JOGO, não do time.
    so_fora = {"m0": _escala(T, base, lado="away")}
    conferir("acha o time como visitante",
             len(previa.escalacao_provavel([{"matchId": "m0"}], so_fora, T)["titulares"]),
             11)
    # E jogo de OUTRO time não pode contaminar a contagem.
    conferir("ignora jogo de outro time",
             previa.escalacao_provavel([{"matchId": "m0"}],
                                       {"m0": _escala("spl::Football_Team::nassr", base)},
                                       T)["jogos_olhados"], 0)
    # Sem escalação nenhuma, devolve vazio em vez de inventar onze.
    vazio = previa.escalacao_provavel([{"matchId": "x"}], {}, T)
    conferir("sem dado, sem onze", vazio["titulares"], [])
    conferir("e diz que olhou zero", vazio["jogos_olhados"], 0)

    # ─────────────────────────────────────── escalação oficial
    of = previa.escalacao_oficial(_escala(T, base, "4-4-2"), "home")
    conferir("oficial marcada como oficial", of["origem"], "oficial")
    conferir("oficial com onze", len(of["titulares"]), 11)
    conferir("oficial pega a formação", of["formacao"], "4-4-2")

    # ─────────────────────────────── conferência dos números
    fatos = {
        "tabela": {"Al Hilal": {"posicao": 1, "pontos": 9, "gols_pro": 10},
                   "Al Nassr": {"posicao": 4, "pontos": 6, "gols_pro": 7}},
        "confronto_direto": {"empates": 2},
        "jogo": {"quando": "2026-08-28T18:00:00"},
    }
    conferir("número que existe passa",
             previa.conferir_numeros("O Hilal tem 9 pontos e 10 gols.", fatos), [])
    conferir("número inventado é pego",
             previa.conferir_numeros("Está há 27 jogos invicto.", fatos), ["27"])
    # Soma de dois números presentes é plausível (9+6=15) e não vira alarme —
    # aviso que grita demais é aviso que ninguém lê.
    conferir("soma dos dados passa",
             previa.conferir_numeros("Somam 15 gols na temporada.", fatos), [])
    conferir("números de futebol passam",
             previa.conferir_numeros("Aos 45 do segundo tempo, com 11 em campo.",
                                     fatos), [])
    conferir("pega vários de uma vez",
             previa.conferir_numeros("Foram 33 finalizações e 84% de posse.", fatos),
             ["33", "84"])
    conferir("data dos dados passa",
             previa.conferir_numeros("Jogo em 2026-08-28.", fatos), [])
    conferir("texto sem número não acusa",
             previa.conferir_numeros("Jogo duro pela frente.", fatos), [])
    conferir("texto vazio não acusa", previa.conferir_numeros("", fatos), [])

    # ─────────────────────────────── não escrever sem dado
    # Chamar o modelo com JSON vazio produz um texto bonito e inteiramente
    # inventado. É o pior resultado possível, e por isso é barrado antes.
    conferir("sem tabela nem forma, recusa",
             bool(previa.sem_dados_suficientes(
                 {"tabela": {"A": {}, "B": {}}, "forma_recente": {}})), True)
    conferir("com tabela, segue",
             previa.sem_dados_suficientes(
                 {"tabela": {"A": {"pontos": 3}}, "forma_recente": {}}), "")
    conferir("só com forma, segue",
             previa.sem_dados_suficientes(
                 {"tabela": {}, "forma_recente": {"A": ["W", "D"]}}), "")

    # ─────────────────────────────── montagem dos fatos
    fatos2 = previa.montar_fatos(
        {"casa": "Al Hilal", "fora": "Al Nassr", "quando": "2026-08-28T18:00",
         "competicao": "Liga Saudita", "canais": ["Band"]},
        {"rank": 1, "points": 9, "forma": ["W", "W", "W"]}, {"rank": 4, "points": 6},
        {"home": {"form": ["W", "D"]}, "away": {"form": ["L"]},
         "headToHead": {"winsHome": 3, "draws": 1, "winsAway": 2}},
        of, of, [{"papel": "Referee", "nome": "X"}], [], [], [])
    conferir("tabela achatada", fatos2["tabela"]["Al Hilal"]["pontos"], 9)
    conferir("forma do lado certo", fatos2["forma_recente"]["Al Hilal"], ["W", "D"])
    conferir("transmissão entra nos fatos", fatos2["jogo"]["transmissao"], ["Band"])
    # E o número da tabela tem que ser aceito pela conferência — se montar_fatos
    # e conferir_numeros discordarem, o aviso acusa o próprio dado da fonte.
    conferir("fatos e conferência combinam",
             previa.conferir_numeros("São 9 pontos, 3 vitórias no confronto.", fatos2),
             [])

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ prévia: escalação provável, oficial e conferência de números")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
