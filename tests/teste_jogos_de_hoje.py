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
    sys.modules.pop("main", None)
    import main
    return main


def testar():
    falhas.clear()
    main = _importar_main()

    ok("/api/diag/" in main.LIVRES,
       "/api/diag/ saiu de LIVRES — a rota jogos-de-hoje ficaria atrás de "
       "login, e a tarefa agendada não tem sessão de navegador nenhuma")

    # ── a conversão de hora local (Arábia) pra UTC ──────────────────────
    # 21:00 na Arábia (UTC+3) é 18:00 em UTC, no MESMO dia.
    ok(main._pontape_utc_de_local("2026-09-01T21:00:00") == "2026-09-01T18:00:00Z",
       "pontapé às 21h local da Arábia deveria virar 18h UTC do mesmo dia")
    # Perto da virada: 01:00 local (Arábia) é 22:00 UTC do dia ANTERIOR —
    # o dia muda na conta, não só a hora. Se alguém trocar o sinal (somar em
    # vez de subtrair 3h), o dia sai errado pro lado contrário.
    ok(main._pontape_utc_de_local("2026-09-02T01:00:00") == "2026-09-01T22:00:00Z",
       "pontapé à 01h local da Arábia deveria virar 22h UTC do dia ANTERIOR "
       "— a data muda, não só a hora; um sinal trocado (+3h em vez de -3h) "
       "não pega esse caso")
    ok(main._pontape_utc_de_local("") == "",
       "sem matchDateLocal, tem que devolver vazio — nunca inventar horário")
    ok(main._pontape_utc_de_local("data quebrada") == "",
       "matchDateLocal ilegível tem que devolver vazio, não estourar erro")
    print("  _pontape_utc_de_local: Arábia (UTC+3) -> UTC, com troca de dia na virada")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ jogos-de-hoje: rota livre de login, conversão de fuso Arábia->UTC certa")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
