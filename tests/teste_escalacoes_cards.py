"""
A escalação tem que aparecer no card do jogo CERTO.

POR QUE ISTO PRECISA DE TESTE
    A guia Escalações passou a listar os jogos do dia, cada um com a
    escalação dele quando ela chega (09/09/26). Antes ela mostrava só o que
    já tinha sido lido, numa pilha sem contexto: não dava para saber quantos
    jogos faltavam.

    O casamento entre o jogo e a escalação é por nome de clube, e nome de
    clube é escrito diferente em cada fonte — o calendário da liga diz
    "Al-Hilal", o matchsheet diz "AL HILAL SFC". Errar aqui não dá erro
    nenhum: aparece uma escalação embaixo do jogo errado, com onze nomes
    plausíveis, e ninguém confere antes de publicar.

    Três jeitos de isso quebrar, e os três estão cobertos abaixo:
    1. casar pelo texto cru em vez de pelo glossário — e nunca casar nada;
    2. deixar UMA escalação servir a dois jogos parecidos no mesmo dia;
    3. sumir com a escalação que não bate com nenhum jogo do dia (a de
       ontem, a de outra competição) — trabalho que a rotina fez e some.
"""
import os
import sys
import types
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _importar_main():
    """main.py com os módulos pesados trocados por dublês.

    Mesmo truque dos outros testes que precisam do main de verdade: o que eu
    quero exercitar aqui é uma função pura, mas ela mora num arquivo que
    importa fastapi e psycopg2 no topo.
    """
    for nome in ("fastapi", "fastapi.responses", "fastapi.staticfiles",
                 "fastapi.middleware", "fastapi.middleware.cors",
                 "fastapi.templating", "httpx", "feedparser", "bs4", "dotenv",
                 "psycopg2", "psycopg2.extras", "psycopg2.extensions",
                 "apscheduler", "apscheduler.schedulers",
                 "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                 "apscheduler.triggers.cron", "apscheduler.triggers.interval",
                 "apscheduler.jobstores", "apscheduler.executors",
                 "apscheduler.schedulers.background", "starlette",
                 "starlette.middleware", "starlette.middleware.base",
                 "starlette.responses", "starlette.requests", "lxml"):
        sys.modules.setdefault(nome, MagicMock(name=nome))
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


def _jogo(casa, fora, quando="2026-09-09T18:00:00"):
    return {"home": {"shortName": casa}, "away": {"shortName": fora},
            "matchDateLocal": quando}


def _escalacao(casa, fora, marca=""):
    return {"casa": {"time": casa, "texto": "11 " + (marca or casa)},
            "fora": {"time": fora, "texto": "11 " + fora},
            "jogo": f"{casa} x {fora}"}


def testar():
    falhas.clear()
    main = _importar_main()

    # ── 1. casa mesmo com as fontes escrevendo diferente ─────────────────
    jogos = [_jogo("Al-Hilal", "Al Nassr", "2026-09-09T16:45:00"),
             _jogo("Al-Ittihad", "Al Ahli", "2026-09-09T19:00:00")]
    lidas = [_escalacao("AL NASSR FC", "AL HILAL SFC")]   # ordem trocada também
    cards = main._cards_de_escalacao(jogos, lidas)

    ok(len(cards) == 2, f"deveriam sair 2 cards, saíram {len(cards)}")
    ok(cards[0]["escalacao"] is not None,
       "a escalação do Hilal x Nassr não casou com o jogo — o casamento tem "
       "que passar pelo glossário, e não pelo texto cru")
    ok(cards[1]["escalacao"] is None,
       "a escalação foi parar no card do Ittihad x Ahli também")

    # A ordem casa/fora não pode importar: o matchsheet lista o mandante do
    # jeito dele, e o calendário do jeito dele.
    ok(cards[0]["jogo"].startswith("Al-Hilal"),
       f"o card deveria manter o nome do calendário: {cards[0]['jogo']!r}")

    # ── 2. jogo sem escalação continua aparecendo ────────────────────────
    cards = main._cards_de_escalacao(jogos, [])
    ok(len(cards) == 2 and all(c["escalacao"] is None for c in cards),
       "jogo sem escalação sumiu da lista — é justamente o que o Vini "
       "precisa ver ANTES do jogo: o que ainda falta")
    ok(all(c.get("quando") for c in cards),
       "o card perdeu a hora do jogo")

    # ── 3. uma escalação não serve a dois jogos ──────────────────────────
    dois_iguais = [_jogo("Al-Hilal", "Al Nassr"), _jogo("Al-Hilal", "Al Nassr")]
    cards = main._cards_de_escalacao(dois_iguais, [_escalacao("Al Hilal", "Al Nassr")])
    com = [c for c in cards if c["escalacao"]]
    ok(len(com) == 1,
       f"a mesma escalação apareceu em {len(com)} cards — cada uma vale por "
       "um jogo só")

    # ── 4. escalação de rodada antiga não invade a rodada atual ──────────
    cards = main._cards_de_escalacao(
        [_jogo("Al-Hilal", "Al Nassr")],
        [_escalacao("Al Hilal", "Al Nassr"), _escalacao("Al Taawoun", "Al Fayha")])
    ok(len(cards) == 1,
       f"uma escalação antiga apareceu como jogo da rodada atual: {len(cards)} cards")
    ok(cards[0]["escalacao"] is not None,
       "o jogo da rodada ficou sem a escalação que era dele")

    # ── 5. a rodada que começou substitui a anterior inteira ─────────────
    def da_md(numero, dia, status="Scheduled"):
        j = _jogo(f"Casa {numero}", f"Fora {numero}", dia + "T18:00:00")
        j["matchSet"] = {"matchSetId": f"md-{numero}", "shortName": f"MD {numero}",
                         "matchdayStatus": status}
        return j
    temporada = [da_md(6, "2026-09-09", "Played") for _ in range(9)]
    temporada += [da_md(7, "2026-09-11", "Playing") for _ in range(9)]
    nome, rodada = main._selecionar_rodada(temporada, "2026-09-11")
    ok(nome == "MD 7" and len(rodada) == 9,
       f"deveria mostrar somente os 9 jogos da MD 7: {nome!r}, {len(rodada)}")

    # ── 6. confronto degenerado não casa com nada ────────────────────────
    # Dois nomes que viram o mesmo clube (ou um vazio) não formam jogo. Sem
    # esta guarda, um par degenerado casaria com qualquer outro igualmente
    # degenerado e a escalação cairia no card errado.
    cards = main._cards_de_escalacao([_jogo("Al-Hilal", "")],
                                     [_escalacao("Al Nassr", "")])
    ok(cards[0]["escalacao"] is None,
       "um jogo sem os dois clubes casou com alguma escalação")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ cards da guia Escalações: somente a rodada atual, com cada "
          "escalação no jogo certo e uma vez só")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
