"""
A hora do jogo tem que ser a hora de quem está olhando, não a da Arábia.

O QUE ACONTECEU (09/09/26)
    A guia Escalações mostrava "18:30" num jogo que no Brasil começava 12:30,
    e listava como "jogo de hoje" partidas que já tinham acontecido ontem.

    A causa é o calendário da liga trazer DOIS campos de horário:

        matchDateUtc    2026-09-09T15:30:00Z
        matchDateLocal  2026-09-09T18:30:00     ← sem fuso escrito

    O `local` é local DA ARÁBIA. Sem fuso escrito, quem lê tende a tratá-lo
    como hora de casa — e era o que a rota fazia. Três horas à frente de UTC,
    SEIS à frente de Brasília: erro grande o bastante para trocar o dia de um
    jogo noturno, e foi isso que encheu a agenda de partidas de ontem.

COMO FICOU RESOLVIDO
    `_instante_do_jogo` devolve um INSTANTE absoluto (datetime com fuso):
    prefere o UTC; sem ele, carimba o `local` com o fuso da Arábia, que é o
    que ele significa. `_jogos_do_dia_brasilia` decide o "hoje" convertendo
    esse instante para -03:00. E a rota manda `quando` em UTC para a tela,
    onde o navegador converte para o fuso do aparelho.

    O servidor NÃO formata hora. Ele roda em UTC no Railway e não sabe onde o
    Vini está — formatar ali seria chutar.

O QUE ESTE ARQUIVO VIGIA
    Que o instante saia certo das duas fontes, que o `local` sem fuso nunca
    seja lido como hora de casa, que o corte do dia seja em Brasília, e que
    `quando` chegue à tela com fuso escrito (senão o `new Date()` do
    JavaScript o lê como hora local e o erro volta pelo outro lado).
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

BRASILIA = timezone(timedelta(hours=-3))
ARABIA = timezone(timedelta(hours=3))

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _importar_main():
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


def testar():
    falhas.clear()
    main = _importar_main()

    # ── 1. o UTC manda quando existe ────────────────────────────────────
    q = main._instante_do_jogo({"matchDateUtc": "2026-09-09T15:30:00Z",
                                "matchDateLocal": "2026-09-09T18:30:00"})
    ok(q is not None and q.tzinfo is not None,
       "o instante do jogo veio sem fuso — datetime ingênuo é justamente o "
       "que deixa cada camada chutar um fuso diferente")
    if q:
        ok(q == datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc),
           f"o campo UTC do calendário não foi respeitado: {q!r}")
        ok(q.astimezone(BRASILIA).strftime("%H:%M") == "12:30",
           f"em Brasília este jogo é 12:30, virou {q.astimezone(BRASILIA):%H:%M}")

    # ── 2. sem UTC, o `local` é da ARÁBIA — nunca de casa ────────────────
    q = main._instante_do_jogo({"matchDateLocal": "2026-09-09T18:30:00"})
    ok(q is not None and q.tzinfo is not None,
       "o `matchDateLocal` sem fuso ficou sem carimbo — lido como hora de "
       "casa, ele adianta o jogo em seis horas")
    if q:
        ok(q == datetime(2026, 9, 9, 18, 30, tzinfo=ARABIA),
           f"o `local` deveria ser carimbado com +03:00 (Arábia): {q!r}")
        ok(q.astimezone(BRASILIA).strftime("%H:%M") == "12:30",
           f"deu {q.astimezone(BRASILIA):%H:%M} em Brasília, e não 12:30")

    # `local` já com fuso escrito não pode ser recarimbado.
    q = main._instante_do_jogo({"matchDateLocal": "2026-09-09T18:30:00+03:00"})
    ok(q == datetime(2026, 9, 9, 18, 30, tzinfo=ARABIA),
       f"o fuso que já vinha escrito no `local` foi trocado: {q!r}")

    # ── 3. lixo não vira hora ────────────────────────────────────────────
    for entrada in ({}, {"matchDateUtc": "", "matchDateLocal": ""},
                    {"matchDateUtc": "ontem"},
                    {"matchDateUtc": "ontem", "matchDateLocal": "amanhã"}):
        ok(main._instante_do_jogo(entrada) is None,
           f"data impossível virou instante: {entrada!r}. O card tem que "
           "aparecer sem hora, e não com uma hora inventada")

    # UTC ilegível com `local` bom: cai para o `local`, não para None.
    q = main._instante_do_jogo({"matchDateUtc": "??",
                                "matchDateLocal": "2026-09-09T18:30:00"})
    ok(q == datetime(2026, 9, 9, 18, 30, tzinfo=ARABIA),
       f"com o UTC ilegível deveria valer o `local`: {q!r}")

    # ── 4. a virada do dia é em Brasília ─────────────────────────────────
    # Jogo das 22h da Arábia = 16h em Brasília, MESMO dia.
    # Jogo das 02h da Arábia (dia 10) = 20h de Brasília do dia 9.
    tarde = main._instante_do_jogo({"matchDateUtc": "2026-09-09T19:00:00Z"})
    madruga = main._instante_do_jogo({"matchDateUtc": "2026-09-09T23:00:00Z"})
    ok(tarde.astimezone(BRASILIA).strftime("%Y-%m-%d") == "2026-09-09",
       "o jogo da tarde saiu do dia 09 em Brasília")
    ok(madruga.astimezone(BRASILIA).strftime("%Y-%m-%d") == "2026-09-09",
       "o jogo que na Arábia já é dia 10 tem que contar como dia 09 aqui — "
       "é a noite de quem assiste no Brasil")
    # E o corte do dia, exercitado de verdade. A primeira versão deste teste
    # procurava `astimezone(...hours=-3...)` no arquivo — e passava mesmo com
    # o bug plantado, porque essa mesma linha aparece em outros quatro pontos
    # do main.py. Teste que procura texto no arquivo confere que alguém
    # ESCREVEU a linha, não que ela roda.
    calendario = [
        # 22h da Arábia do dia 09 = 16h de Brasília do dia 09 → entra
        {"nome": "tarde", "matchDateUtc": "2026-09-09T19:00:00Z"},
        # 02h da Arábia do dia 10 = 20h de Brasília do dia 09 → entra
        {"nome": "noite", "matchDateUtc": "2026-09-09T23:00:00Z"},
        # 09h da Arábia do dia 09 = 03h de Brasília do dia 09 → entra
        {"nome": "manhã", "matchDateUtc": "2026-09-09T06:00:00Z"},
        # 20h da Arábia do dia 08 = 14h de Brasília do dia 08 → fica de fora
        {"nome": "ontem", "matchDateUtc": "2026-09-08T17:00:00Z"},
        # 22h de Brasília do dia 09 é 04h da Arábia do dia 10 → entra
        {"nome": "tarde da noite", "matchDateUtc": "2026-09-10T01:00:00Z"},
    ]
    liga = __import__("liga_spl")
    guardado = (liga.temporada, liga.jogos_da_temporada, main._dia_de_brasilia)
    try:
        liga.temporada = lambda *a, **k: 1
        liga.jogos_da_temporada = lambda *a, **k: calendario
        main._dia_de_brasilia = lambda *a, **k: "2026-09-09"
        saiu = [j["nome"] for j in main._jogos_do_dia_brasilia()]
    finally:
        liga.temporada, liga.jogos_da_temporada, main._dia_de_brasilia = guardado

    ok("ontem" not in saiu,
       f"o jogo de ONTEM entrou na agenda de hoje: {saiu}. Foi exatamente a "
       "reclamação do Vini — a lista abria com partidas já jogadas")
    ok("noite" in saiu and "tarde da noite" in saiu,
       f"sumiu um jogo que em Brasília é hoje à noite: {saiu}. Contado pelo "
       "calendário da Arábia ele já é de amanhã, e é aí que ele some")
    ok(len(saiu) == 4, f"deveriam sobrar 4 jogos do dia, sobraram {len(saiu)}: {saiu}")
    ok(saiu == ["manhã", "tarde", "noite", "tarde da noite"],
       f"a agenda saiu fora de ordem: {saiu} — ela é para olhar em sequência")

    # ── 5. `quando` chega à tela em UTC, com fuso escrito ────────────────
    jogos = [{"home": {"shortName": "Al-Hilal"}, "away": {"shortName": "Al Nassr"},
              "matchDateUtc": "2026-09-09T15:30:00Z",
              "matchDateLocal": "2026-09-09T18:30:00"}]
    cards = main._cards_de_escalacao(jogos, [])
    quando = cards[0]["quando"]
    ok(quando.endswith("+00:00") or quando.endswith("Z"),
       f"`quando` foi para a tela sem fuso escrito ({quando!r}). O "
       "`new Date()` do navegador lê um ISO sem fuso como hora LOCAL: o erro "
       "das seis horas volta, agora pelo lado do cliente")
    ok(quando.startswith("2026-09-09T15:30"),
       f"`quando` não está em UTC: {quando!r}")
    ok("18:30" not in quando,
       f"a hora da Arábia vazou para a tela: {quando!r}")

    # Jogo sem data nenhuma continua virando card, só que sem hora.
    cards = main._cards_de_escalacao(
        [{"home": {"shortName": "Al-Hilal"}, "away": {"shortName": "Al Nassr"}}], [])
    ok(len(cards) == 1 and cards[0]["quando"] == "",
       f"jogo sem data quebrou o card em vez de sair sem hora: {cards!r}")

    # ── 6. quem formata a hora é o navegador ─────────────────────────────
    corpo = FONTE[FONTE.find("function soHora(iso)"):]
    corpo = corpo[:corpo.find("\n}}")]
    ok("new Date(iso)" in corpo and "toLocaleTimeString" in corpo,
       "`soHora` voltou a fatiar o texto do ISO. Fatiar string exibe a hora "
       "escrita, não a hora de quem olha — e a hora escrita é UTC")
    ok("slice(" not in corpo and "substring(" not in corpo,
       "`soHora` está recortando pedaços do ISO de novo")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ fuso das escalações: instante absoluto, dia contado em "
          "Brasília, hora formatada no navegador")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
