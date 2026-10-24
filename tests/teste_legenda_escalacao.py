"""A legenda das escalações: o texto padrão dele, pronto para copiar.

O QUE ELE PEDIU (24/10/26)
    "Quero que consiga um botão pra montar esse texto padrão:

     🔴🔵📋 Escalações de Al-Qadsiah e Al-Hilal para a partida de logo mais,
     às 15h, pela 11ª rodada da Saudi Pro League.
     🔴➡️ Koen Casteels, (...) são os estrangeiros titulares de Brendan Rodgers.
     (...)
     🖥️ Transmissão: CANAL GOAT 🐐 e Xsports.

     De acordo com os confrontos, estrangeiros (não sauditas), e transmissões
     (que já tem nos agendamentos programados). O ideal é um botão pra copiar
     já pronto. Não precisa ser o nome completo dos jogadores, pode ser o
     mesmo que vai pra arte."

AS AMOSTRAS SÃO AS FOLHAS DE VERDADE: os textos de Al Ahli x Al Khaleej e
Al Qadsiah x Al Hilal abaixo foram copiados de /api/escalacao-pdf/recentes,
no ar, em 23/10/26 — os mesmos jogos do exemplo dele.
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


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
    app = sys.modules["fastapi"].FastAPI.return_value
    for metodo in ("get", "post", "put", "patch", "delete", "middleware",
                   "on_event", "exception_handler", "websocket"):
        getattr(app, metodo).side_effect = lambda *a, **k: (lambda f: f)
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


main = _importar_main()
import database                                             # noqa: E402
import elenco_tm                                            # noqa: E402

AHLI = ("🇸🇦 01 AL SANBI\n🇸🇦 31 SAAD YASLAM\n🇧🇷 03 IBAÑEZ\n🇸🇦 05 SULAIMAN\n"
        "🇸🇦 15 SAEED BAATTIA\n🇦🇲 08 E. SPERTSYAN\n🇺🇦 19 A. BONDARENKO\n"
        "🇫🇷 06 V. ATANGANA\n🇸🇦 09 AL BURAIKAN\n🇬🇧 17 I. TONEY\n🇵🇹 07 TRINCÃO")
KHALEEJ = ("🇸🇦 96 MARWAN AL HAIDARI\n🇸🇦 17 ABDULLAH AL HAFITH\n🇸🇦 03 KHUBRANI\n"
           "🇸🇦 13 AHMED ASIRI\n🇸🇦 27 AL SOQOUR\n🇵🇹 05 REBOCHO\n"
           "🇬🇶 08 OMAR MASCARELL\n🇸🇦 12 MAJED KANABAH\n🇬🇲 99 M. BARROW\n"
           "🇦🇷 09 BENEGAS\n🇳🇴 07 J. KING")
QADSIAH = ("🇧🇪 01 K. CASTEELS\n🇺🇾 08 N. NÁNDEZ\n🇺🇾 17 G. ÁLVAREZ\n"
           "🇸🇦 04 JEHAD THIKRI\n🇬🇭 22 C. BONSU BAAH\n🇸🇦 10 MUSAB AL JUWAYR\n"
           "🇩🇪 05 J. WEIGL\n🇳🇱 14 RIJNDERS\n🇸🇦 02 MOHAMMED ABU AL SHAMAT\n"
           "🇲🇽 33 J. QUIÑONES\n🇮🇹 32 M. RETEGUI")
HILAL = ("🇲🇦 37 BONO\n🇫🇷 19 T. HERNÁNDEZ\n🇸🇦 87 HASSAN TAMBAKTI\n"
         "🇸🇳 03 K. KOULIBALY\n🇸🇦 02 MOHAMMED MAHZARI\n🇳🇱 38 SUMMERVILLE\n"
         "🇸🇦 06 NASSER AL DAWSARI\n🇵🇹 08 RÚBEN NEVES\n"
         "🇷🇸 22 S. MILINKOVIĆ-SAVIĆ\n🇬🇧 11 O. WATKINS\n🇧🇷 07 GABRIEL MARTINELLI")

# A lista de clubes do campinho como ela é no ar: SPL + id do Transfermarkt.
TIMES = {"fonte": "spl", "times": [
    {"id": 18487, "nome": "Al Ahli", "escudo": "https://spl/ahli.webp"},
    {"id": 2928, "nome": "Al Khaleej", "escudo": "https://spl/khaleej.webp"},
    {"id": 2010, "nome": "Al Qadsiah", "escudo": "https://spl/qad.webp"},
    {"id": 1114, "nome": "Al Hilal", "escudo": "https://spl/hilal.webp"},
]}
TECNICOS = {18487: ("Marino Pušić", ["Holanda"]), 2928: ("José Gomes", ["Portugal"]),
            2010: ("Brendan Rodgers", ["Irlanda do Norte"]),
            1114: ("Simone Inzaghi", ["Itália"])}
# O calendário da API-Football guardado no banco, com os nomes de LÁ.
PARTIDAS = [
    {"fixture_id": 1603062, "data": "2026-10-23T18:00:00+00:00",
     "casa": "Al-Ahli Jeddah", "fora": "Al Khaleej Saihat"},
    {"fixture_id": 1603063, "data": "2026-10-23T18:00:00+00:00",
     "casa": "Al-Qadisiyah FC", "fora": "Al-Hilal Saudi FC"},
    # O returno do mesmo confronto, meses depois: não pode ser confundido.
    {"fixture_id": 1609999, "data": "2027-03-10T18:00:00+00:00",
     "casa": "Al-Ahli Jeddah", "fora": "Al Khaleej Saihat"},
]
CANAIS = {1603062: ["Canal GOAT 🐐"], 1603063: ["Canal GOAT 🐐", "XSports"]}


class Pedido:
    def __init__(self, corpo):
        self._c = corpo

    async def json(self):
        return self._c


class Resposta:
    def __init__(self, conteudo=None, status_code=200, **k):
        self.dados, self.status_code = conteudo, status_code


def legenda(corpo, elencos=None, canais=CANAIS, partidas=PARTIDAS, times=TIMES):
    guard = (main.api_elencos_jogadores, main.api_elencos_times, elenco_tm.tecnico,
             database.partidas_da_liga, database.transmissao_do_jogo,
             main.JSONResponse, main._af_get)

    async def jog(clube="", **k):
        return {"jogadores": (elencos or {}).get(clube, [])}

    async def tim(**k):
        return times

    async def tec(clube_id):
        nome, paises = TECNICOS.get(int(clube_id), ("", []))
        return ({"nome": nome, "nacionalidades": paises} if nome else {}), None

    async def af(path, params, ttl=None):
        return None, "sem API no teste"

    main.api_elencos_jogadores, main.api_elencos_times = jog, tim
    elenco_tm.tecnico = tec
    database.partidas_da_liga = lambda season, liga_id=307, todas=False: list(partidas)
    database.transmissao_do_jogo = lambda fid: (canais or {}).get(int(fid))
    main.JSONResponse = Resposta
    main._af_get = af
    try:
        r = asyncio.run(main.api_escalacao_legenda(Pedido(corpo)))
        return r if isinstance(r, dict) else {"erro": getattr(r, "dados", r)}
    finally:
        (main.api_elencos_jogadores, main.api_elencos_times, elenco_tm.tecnico,
         database.partidas_da_liga, database.transmissao_do_jogo,
         main.JSONResponse, main._af_get) = guard


JOGO_AHLI = {"quando": "2026-10-23T18:00:00+00:00", "rodada": "11",
             "casa": {"nome": "Al Ahli", "time": "AL AHLI", "tecnico": "MARINO PUŠIĆ",
                      "texto": AHLI},
             "fora": {"nome": "Al Khaleej", "time": "AL KHALEEJ", "tecnico": "JOSE GOMES",
                      "texto": KHALEEJ}}

# ── O EXEMPLO DELE, PALAVRA POR PALAVRA ─────────────────────────────────
# Sem elenco do campinho, os nomes são os da folha sem a inicial — os mesmos
# da arte nessas condições.
r = legenda(JOGO_AHLI)
ESPERADO = (
    "🟢🟡📋 Escalações de Al Ahli e Al Khaleej para a partida de logo mais, às "
    "15h, pela 11ª rodada da Saudi Pro League.\n\n"
    "🟢➡️ Ibañez, Spertsyan, Bondarenko, Atangana, Toney e Trincão são os "
    "estrangeiros titulares de Marino Pušić.\n\n"
    "🟡➡️ Rebocho, Omar Mascarell, Barrow, Benegas e King são os estrangeiros "
    "titulares de José Gomes.\n\n"
    "🖥️ Transmissão: CANAL GOAT 🐐")
ok(r.get("texto") == ESPERADO,
   "a legenda de Al Ahli x Al Khaleej não saiu no formato dele.\n"
   f"      SAIU:\n{r.get('texto')}\n      ESPERADO:\n{ESPERADO}")

# AS CORES: Ahli 🟢 e Khaleej 🟡. A primeira cor do Khaleej também é verde —
# e o visitante passa para a segunda, como ele fez à mão.
ok((r.get("texto") or "").startswith("🟢🟡📋"),
   "as bolinhas saíram iguais para os dois times; o visitante tem de passar "
   "para a segunda cor dele")

# ── O OUTRO JOGO: duas transmissões, e o técnico com dois nomes ─────────
r2 = legenda({"quando": "2026-10-23T18:00:00+00:00", "rodada": "11",
              "casa": {"nome": "Al Qadsiah", "time": "AL QADSIAH",
                       "tecnico": "BRENDAN RODGERS", "texto": QADSIAH},
              "fora": {"nome": "Al Hilal", "time": "AL HILAL",
                       "tecnico": "SIMONE INZAGHI", "texto": HILAL}})
t2 = r2.get("texto") or ""
ok(t2.startswith("🔴🔵📋 Escalações de Al Qadsiah e Al Hilal"),
   f"a abertura de Qadsiah x Hilal saiu: {t2[:60]!r}")
ok("🖥️ Transmissão: CANAL GOAT 🐐 e XSports." in t2,
   f"as duas transmissões marcadas não saíram certas: {t2.splitlines()[-1]!r}")
ok("Casteels, Nández, Álvarez, Bonsu Baah, Weigl, Rijnders, Quiñones e Retegui "
   "são os estrangeiros titulares de Brendan Rodgers." in t2,
   "os estrangeiros do Qadsiah não saíram na ordem da folha, sem os sauditas "
   f"(Thikri, Al Juwayr, Abu Al Shamat): {t2}")
ok("Bono, Hernández, Koulibaly, Summerville, Rúben Neves, Milinković-Savić, "
   "Watkins e Gabriel Martinelli são os estrangeiros titulares de Simone "
   "Inzaghi." in t2,
   f"os estrangeiros do Hilal saíram errados: {t2}")
ok("Tambakti" not in t2 and "Mahzari" not in t2 and "Dawsari" not in t2,
   "um saudita entrou na lista de estrangeiros")

# ── OS NOMES SÃO OS DA ARTE: com o campinho, a placa ────────────────────
ELENCO_HILAL = [{"numero": 37, "nome": "Yassine Bounou", "pais_bandeira": "🇲🇦"},
                {"numero": 22, "nome": "Sergej Milinković-Savić", "pais_bandeira": "🇷🇸"},
                {"numero": 87, "nome": "Hassan Tambakti", "pais_bandeira": "🇸🇦"}]
r3 = legenda({"quando": "2026-10-23T18:00:00+00:00", "rodada": "11",
              "casa": {"nome": "Al Qadsiah", "time": "AL QADSIAH", "tecnico": "",
                       "texto": QADSIAH},
              "fora": {"nome": "Al Hilal", "time": "AL HILAL", "tecnico": "",
                       "texto": HILAL}},
             elencos={"AL HILAL": ELENCO_HILAL})
t3 = r3.get("texto") or ""
ok("Bounou, Hernández" in t3,
   f"com o campinho, o 'BONO' da folha devia virar 'Bounou' — o nome da "
   f"placa, o mesmo da arte. Saiu: {t3}")

# ── QUEM NÃO TEM NACIONALIDADE NÃO É CHUTADO ────────────────────────────
r4 = legenda(dict(JOGO_AHLI, casa=dict(JOGO_AHLI["casa"],
                                        texto=AHLI.replace("🇬🇧 17 I. TONEY", "17 I. TONEY"))))
ok("Toney" not in (r4.get("texto") or "").split("\n\n")[1],
   "um jogador sem nacionalidade entrou como estrangeiro. Sem bandeira não "
   "se sabe — pode ser saudita")
ok(any("Toney" in a for a in r4.get("avisos") or []),
   "o jogador sem nacionalidade sumiu sem aviso; ele tem de saber para "
   "conferir antes de postar")

# ── TRANSMISSÃO NÃO MARCADA ≠ SEM TRANSMISSÃO ───────────────────────────
r5 = legenda(JOGO_AHLI, canais={})
ok((r5.get("texto") or "").endswith("🖥️ Transmissão: a confirmar"),
   "transmissão nunca marcada saiu como se fosse 'sem transmissão'")
ok(any("não foi marcada" in a for a in r5.get("avisos") or []),
   "a falta da transmissão nos posts não foi avisada")
r6 = legenda(JOGO_AHLI, canais={1603062: []})
ok((r6.get("texto") or "").endswith("❌ Sem transmissão"),
   "jogo marcado SEM transmissão não saiu como 'Sem transmissão'")

# ── O RETURNO NÃO PODE ROUBAR A TRANSMISSÃO DO TURNO ────────────────────
r7 = legenda(JOGO_AHLI, canais={1609999: ["Band"], 1603062: ["Canal GOAT 🐐"]})
ok("Band" not in (r7.get("texto") or ""),
   "a transmissão saiu do jogo de março, o returno do mesmo confronto")
# E quando o jogo de HOJE nem está no calendário guardado, o returno não
# assume o lugar dele: sem jogo achado, a transmissão fica "a confirmar".
r7b = legenda(JOGO_AHLI, canais={1609999: ["Band"]},
              partidas=[p for p in PARTIDAS if p["fixture_id"] != 1603062])
ok("Band" not in (r7b.get("texto") or "")
   and (r7b.get("texto") or "").endswith("a confirmar"),
   "sem o jogo de hoje no calendário, a transmissão do returno, de março, "
   f"entrou na legenda: {(r7b.get('texto') or '').splitlines()[-1:]}")

# ── SINGULAR E NENHUM ───────────────────────────────────────────────────
r8 = legenda(dict(JOGO_AHLI, fora=dict(JOGO_AHLI["fora"],
                                       texto="🇸🇦 01 A\n🇸🇦 02 B\n🇵🇹 05 REBOCHO")))
ok("🟡➡️ Rebocho é o estrangeiro titular de José Gomes." in (r8.get("texto") or ""),
   f"com um estrangeiro só a frase não foi para o singular: {r8.get('texto')}")
r9 = legenda(dict(JOGO_AHLI, fora=dict(JOGO_AHLI["fora"], texto="🇸🇦 01 A\n🇸🇦 02 B")))
ok("🟡➡️ Nenhum estrangeiro entre os titulares de José Gomes." in (r9.get("texto") or ""),
   f"sem estrangeiros a frase saiu errada: {r9.get('texto')}")

# ── O HORÁRIO É O DE BRASÍLIA, COM OS MINUTOS QUANDO HÁ ─────────────────
ok(main._hora_do_jogo("2026-10-23T18:00:00+00:00") == "15h",
   "18h UTC devia ser 15h em Brasília")
ok(main._hora_do_jogo("2026-10-23T15:30:00+00:00") == "12h30",
   "o jogo das 12h30 saiu sem os minutos")

# ── E O BOTÃO NA TELA ───────────────────────────────────────────────────
FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ok("📝 Copiar legenda" in FONTE and "/api/escalacao/legenda" in FONTE,
   "o botão da legenda sumiu da guia de Escalações")
_js = FONTE[FONTE.find("async function copiarLegenda"):]
ok("campoCasa.value" in _js[:2500] and "campoFora.value" in _js[:2500],
   "a legenda não lê os campos de escalação da tela — correção feita ali não "
   "entraria no texto")
ok("_lado_da_escalacao(" in FONTE[FONTE.find("async def _montar_legenda"):
                                  FONTE.find("async def api_escalacao_legenda")]
   and "_montar_legenda(" in FONTE[FONTE.find("async def api_escalacao_legenda"):
                                   FONTE.find("def escalacao_arte_iso")],
   "a legenda resolve os times por um caminho próprio, e não pela mesma "
   "função da arte")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ legenda das escalações no formato dele, pronta para copiar")
