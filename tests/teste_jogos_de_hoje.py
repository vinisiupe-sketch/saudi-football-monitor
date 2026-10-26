"""
/api/diag/jogos-de-hoje — a data certa (Arábia, não Brasília) e a conta de
UTC que a rotina agendada da escalação por PDF depende para saber quando
abrir a janela de 1h30 antes do pontapé.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    A primeira versão da tarefa agendada fazia as três chamadas
    (competitions → seasons → matches) direto na API da liga, de dentro da
    própria tarefa. Rodando sem o Vini presente (madrugada, sem ninguém pra
    aprovar site novo), só a primeira chamada — a única escrita LITERAL no
    texto da tarefa — passou; as outras duas, montadas em tempo de execução,
    foram recusadas. Essa rota tira as três chamadas de dentro da tarefa e
    põe aqui, no servidor, que já sabe falar com a API da liga sem pedir
    licença — a tarefa passa a fazer UMA chamada, com endereço fixo.

    Continua existindo motivo pra errar a data: matchDateLocal vem SEM fuso,
    já na hora local da Arábia Saudita — se alguém comparar isso direto com
    a data em UTC (sem somar as 3 horas), um jogo às 21h locais some da
    lista de "hoje" quando ainda são 20h UTC do mesmo dia (a data em UTC já
    seria a mesma, mas a hora do pontapé em UTC sairia errada de qualquer
    jeito se a conta for feita ao contrário — e é essa conta que decide
    quando a janela de pré-jogo abre).
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


class _Dublê(types.ModuleType):
    def __getattr__(self, nome):
        v = MagicMock(name=f"{self.__name__}.{nome}")
        setattr(self, nome, v)
        return v


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
        sys.modules.setdefault(nome, _Dublê(nome))
    # Os decoradores de rota devolvem a PRÓPRIA função: este arquivo chama a
    # rota de verdade (26/10/26), e um decorador falso a trocaria por um dublê.
    app = sys.modules["fastapi"].FastAPI.return_value
    for metodo in ("get", "post", "put", "patch", "delete", "middleware",
                   "on_event", "exception_handler", "websocket"):
        getattr(app, metodo).side_effect = lambda *a, **k: (lambda f: f)
    sys.modules.pop("main", None)
    import main
    return main


def testar():
    falhas.clear()
    main = _importar_main()

    ok("/api/diag/" in main.LIVRES,
       "/api/diag/ saiu de LIVRES — a rota jogos-de-hoje ficaria atrás de "
       "login, e a tarefa agendada não tem sessão de navegador nenhuma")

    # ── O HORÁRIO DO JOGO É O DO matchDateUtc (26/10/26) ───────────────
    #
    # Este teste dizia que o matchDateLocal da liga vem na hora da Arábia e
    # conferia que a rota tirava 3 horas dele. O log do monitor desmentiu:
    # em 24/10 ele foi buscar a escalação de NEOM x Abha às 09:45 UTC, para
    # um jogo das 14:00 UTC — o "local" já vinha com o relógio do UTC, e as
    # 3 horas tiradas jogaram o jogo para as 11:00. As escalações pararam de
    # chegar. O registro abaixo é o desse jogo, como a liga o publicou.
    neom_abha = {"matchDateUtc": "2026-10-24T14:00:00Z",
                 "matchDateLocal": "2026-10-24T14:00:00",
                 "home": {"shortName": "NEOM SC"}, "away": {"shortName": "Abha"}}
    quando, dia = main._pontape_e_dia_na_arabia(neom_abha)
    ok(quando is not None and quando.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-24T14:00:00Z",
       f"NEOM x Abha saiu às {quando} e era às 14:00 UTC. Três horas a menos "
       "foi o que fez o monitor buscar a escalação antes de ela existir")
    ok(dia == "2026-10-24", f"o dia na Arábia saiu {dia!r}")

    # A VIRADA DO DIA: 21:30 UTC já é 00:30 do dia seguinte na Arábia. É a
    # data da Arábia que o Media Hub usa para filtrar os PDFs.
    tarde = {"matchDateUtc": "2026-10-26T21:30:00Z",
             "matchDateLocal": "2026-10-26T21:30:00"}
    ok(main._pontape_e_dia_na_arabia(tarde)[1] == "2026-10-27",
       "um jogo às 21:30 UTC ficou no dia errado; na Arábia já é o dia seguinte")

    # Sem UTC, o local entra COM o fuso da Arábia carimbado (é o que ele
    # significa quando vem sozinho) — a mesma regra do card de Escalações.
    so_local = {"matchDateLocal": "2026-10-24T17:00:00"}
    ok(main._pontape_e_dia_na_arabia(so_local)[0].strftime("%H:%M") == "14:00",
       "sem matchDateUtc, o local não foi lido como hora da Arábia")
    ok(main._pontape_e_dia_na_arabia({}) == (None, ""),
       "sem data nenhuma, a função inventou um horário")
    ok(main._pontape_e_dia_na_arabia({"matchDateUtc": "lixo"}) == (None, ""),
       "com data ilegível, a função inventou um horário em vez de desistir")

    # ── A ROTA INTEIRA, COMO O MONITOR A CONSULTA ───────────────────────
    import liga_spl
    from datetime import datetime as _dt, timezone as _tz
    guard = (liga_spl.temporada, liga_spl.jogos_da_temporada, main.datetime)

    class _Agora(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 10, 24, 9, 0, tzinfo=_tz.utc)

    try:
        liga_spl.temporada = lambda dia, cli: 99
        liga_spl.jogos_da_temporada = lambda sid, cli: [
            neom_abha,
            # O jogo de ONTEM na Arábia não pode entrar na agenda de hoje.
            {"matchDateUtc": "2026-10-23T18:00:00Z", "matchDateLocal": "2026-10-23T18:00:00",
             "home": {"shortName": "Al Qadsiah"}, "away": {"shortName": "Al Hilal"}}]
        main.datetime = _Agora
        import asyncio
        agenda = asyncio.run(main.diag_jogos_de_hoje())
    finally:
        liga_spl.temporada, liga_spl.jogos_da_temporada, main.datetime = guard
    jogos = (agenda or {}).get("jogos") or []
    ok(len(jogos) == 1 and jogos[0]["casa"] == "NEOM SC",
       f"a agenda de 24/10 saiu com {[(j.get('casa'), j.get('fora')) for j in jogos]}")
    ok(jogos and jogos[0]["pontape_utc"] == "2026-10-24T14:00:00Z",
       f"a agenda que o monitor lê diz {jogos[0].get('pontape_utc') if jogos else '-'} "
       "para NEOM x Abha; o jogo era às 14:00 UTC. É esse número que decide a "
       "hora dos pontos de checagem")
    ok(jogos and jogos[0]["pontape_local_arabia"] == "2026-10-24T17:00:00",
       "o horário da Arábia na agenda não é o UTC mais 3 horas")

    # E A CONTA ERRADA NÃO VOLTA: nenhuma parte do app tira 3 horas do
    # matchDateLocal por conta própria.
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    ok("def _pontape_utc_de_local" not in fonte,
       "a conta que tirava 3 horas do matchDateLocal voltou ao main.py")
    # Os três lugares que fazem conta de HORÁRIO com o jogo da liga — a
    # agenda do monitor, o coletor que mede a escalação da liga e o
    # diagnóstico — passam pela mesma função. (Comparar só a DATA pelo
    # matchDateLocal, como outras partes fazem, só erra em jogo depois das
    # 21h UTC, que esta liga praticamente não tem.)
    for marco in ('async def diag_jogos_de_hoje', 'escala_do_jogo(sid, j.get("matchId"), cli)'):
        i = fonte.find(marco)
        ok(i > 0 and "_pontape_e_dia_na_arabia(j)" in fonte[max(0, i - 2500):i + 2500],
           f"perto de '{marco[:40]}' a conta do horário do jogo não passa mais "
           "pela função única — é por esse caminho que as 3 horas voltam")
    print("  horário do jogo: matchDateUtc, e o dia pela Arábia")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ jogos-de-hoje: rota livre de login, pontapé pelo matchDateUtc")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
