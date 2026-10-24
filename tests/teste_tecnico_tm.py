"""O técnico da arte vem do Transfermarkt: nome completo e bandeira.

O QUE ELE PEDIU (24/10/26)
    "CONTINUA NÃO VINDO a bandeira do técnico. Pq o técnico você não puxa
     direto da api-spl ou do scrap do transfermkt? Estão atualizados e não
     muda. Seta no time correspondente e pega de lá. Vai vir certo. (...)
     Bruno Lage além de estar vindo sem bandeira tá vindo só 'Bruno'."

    O log do ar mostrou por que a API-Football não servia: o Jens Wissing
    voltou SEM nacionalidade, e para o Diriyah ela não tinha técnico nenhum.

O QUE ESTE ARQUIVO NÃO CONSEGUE PROVAR
    Que o HTML abaixo é igual ao do Transfermarkt de verdade: o TM é bloqueado
    para mim, e eu escrevi o parser e estas amostras pelas convenções que o
    próprio app já lê no elenco (tabela `items`, tabela pequena aninhada com
    nome e cargo, bandeira `flaggenrahmen` com o país no `title`). Quem prova
    isso é /api/diag/tecnicos, rodando no ar. O que este arquivo prova é a
    REGRA: o principal e não o adjunto, a bandeira certa, a reserva da ficha.
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# O httpx não é usado aqui (as páginas do TM são de mentira), e a máquina que
# roda os testes não precisa tê-lo instalado. bs4 e lxml são os de verdade:
# é o parser que está sendo testado.
sys.modules.setdefault("httpx", MagicMock(name="httpx"))
for _mod in ("psycopg2", "psycopg2.extras", "psycopg2.extensions", "dotenv",
             "feedparser"):
    sys.modules.setdefault(_mod, MagicMock(name=_mod))

from bs4 import BeautifulSoup                               # noqa: E402

import elenco_tm                                            # noqa: E402

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def _sopa(html):
    return BeautifulSoup(html, "lxml")


def _linha(nome, tid, cargo, paises):
    bandeiras = "".join(f'<img class="flaggenrahmen" title="{p}" alt="{p}">'
                        for p in paises)
    return f"""
<tr class="odd">
  <td><table class="inline-table">
    <tr><td rowspan="2"><img class="bilderrahmen-fixed" title="{nome}"></td>
        <td class="hauptlink"><a title="{nome}" href="/x/profil/trainer/{tid}">{nome}</a></td></tr>
    <tr><td>{cargo}</td></tr>
  </table></td>
  <td class="zentriert">49</td>
  <td class="zentriert">{bandeiras}</td>
  <td class="zentriert">01/07/2025</td>
</tr>"""


def _pagina(*linhas):
    return ('<div class="responsive-table"><table class="items"><thead><tr>'
            '<th>Nome</th></tr></thead><tbody>' + "".join(linhas)
            + "</tbody></table></div>")


# ── O CASO DELE: "BRUNO" NA FOLHA, BRUNO LAGE NO TM ─────────────────────
f = elenco_tm._parse_tecnico(_sopa(_pagina(
    _linha("Bruno Lage", 12345, "Treinador", ["Portugal"]),
    _linha("Fulano Adjunto", 999, "Treinador adjunto", ["Espanha"]))))
ok(f.get("nome") == "Bruno Lage",
   f"o técnico saiu {f.get('nome')!r}. É o nome completo do TM que entra na "
   "arte — a folha escreve só 'BRUNO'")
ok(f.get("nacionalidades") == ["Portugal"],
   f"a nacionalidade saiu {f.get('nacionalidades')}; a bandeira do técnico "
   "depende dela")
ok(f.get("trainer_id") == 12345, "o id do treinador não foi lido")

# O ADJUNTO LISTADO PRIMEIRO não pode virar técnico da arte.
f2 = elenco_tm._parse_tecnico(_sopa(_pagina(
    _linha("Fulano Adjunto", 999, "Treinador adjunto", ["Espanha"]),
    _linha("Treinador de Goleiros", 998, "Treinador de goleiros", ["Brasil"]),
    _linha("Simone Inzaghi", 2392, "Treinador", ["Itália"]))))
ok(f2.get("nome") == "Simone Inzaghi",
   f"saiu {f2.get('nome')!r}: o adjunto ou o de goleiros virou o técnico "
   "da arte. O cargo tem de ser o do principal — por igualdade, e não por "
   "'contém Treinador'")

# Sem cargo reconhecível, a ordem do TM decide: o primeiro da comissão.
f3 = elenco_tm._parse_tecnico(_sopa(_pagina(
    _linha("Arthur Papas", 777, "Coach", ["Austrália"]),
    _linha("Outro", 778, "Analista", ["Grécia"]))))
ok(f3.get("nome") == "Arthur Papas",
   "sem cargo reconhecido, o primeiro da comissão devia ser o técnico")

ok(elenco_tm._parse_tecnico(_sopa("<html><body>sem tabela</body></html>")) == {},
   "página sem treinador devolveu alguém")

# DUAS NACIONALIDADES: a primeira é a que o TM considera esportiva.
f4 = elenco_tm._parse_tecnico(_sopa(_pagina(
    _linha("Ange Postecoglou", 555, "Treinador", ["Austrália", "Grécia"]))))
ok(f4.get("nacionalidades") == ["Austrália", "Grécia"],
   f"as nacionalidades saíram {f4.get('nacionalidades')} — a ordem do TM "
   "tem de ser mantida, a primeira é a que vale")


# ── A RESERVA: A FICHA DO TREINADOR ─────────────────────────────────────
ficha = _sopa("""
<div class="info-table">
  <span class="info-table__content info-table__content--regular">Nacionalidade:</span>
  <span class="info-table__content info-table__content--bold">
    <img title="Austrália" alt="Austrália" class="flaggenrahmen"> Austrália
  </span>
</div>""")
ok(elenco_tm._parse_nacionalidade_perfil(ficha) == ["Austrália"],
   "a nacionalidade da ficha do treinador não foi lida; é a reserva para "
   "quando a comissão vem sem bandeira")
ok(elenco_tm._parse_nacionalidade_perfil(_sopa("<p>nada</p>")) == [],
   "ficha sem nacionalidade devolveu algum país")


# ── O CAMINHO INTEIRO NO TM: comissão sem bandeira → ficha ──────────────
paginas = {
    "x/mitarbeiter/verein/1114": _pagina(_linha("Simone Inzaghi", 2392, "Treinador", [])),
    "x/profil/trainer/2392": """<span class="info-table__content">Nacionalidade:</span>
        <span class="info-table__content"><img class="flaggenrahmen" title="Itália"></span>""",
}
pedidas = []


async def _sopa_falsa(caminho, tentativas=3):
    pedidas.append(caminho)
    return _sopa(paginas[caminho])


_real = elenco_tm._sopa
elenco_tm._CACHE.clear()
try:
    elenco_tm._sopa = _sopa_falsa
    ficha_tec, aviso = asyncio.run(elenco_tm.tecnico(1114))
    # Segunda vez: do cache, sem bater no TM.
    asyncio.run(elenco_tm.tecnico(1114))
finally:
    elenco_tm._sopa = _real
ok(ficha_tec.get("nacionalidades") == ["Itália"],
   f"com a comissão sem bandeira, a ficha do treinador não foi consultada "
   f"({ficha_tec})")
ok(pedidas.count("x/mitarbeiter/verein/1114") == 1,
   f"a comissão foi pedida {pedidas.count('x/mitarbeiter/verein/1114')} "
   "vezes. O TM bloqueia quem pede demais; tem de vir do cache")


# ── E A BANDEIRA SAI PELO MESMO CAMINHO DOS JOGADORES DO CAMPINHO ───────
def _importar_main():
    for nome in ("fastapi", "fastapi.responses", "fastapi.staticfiles",
                 "fastapi.middleware", "fastapi.middleware.cors",
                 "fastapi.templating", "httpx", "feedparser", "dotenv",
                 "psycopg2", "psycopg2.extras", "psycopg2.extensions",
                 "apscheduler", "apscheduler.schedulers",
                 "apscheduler.schedulers.asyncio", "apscheduler.triggers",
                 "apscheduler.triggers.cron", "apscheduler.triggers.interval",
                 "apscheduler.jobstores", "apscheduler.executors",
                 "apscheduler.schedulers.background", "starlette",
                 "starlette.middleware", "starlette.middleware.base",
                 "starlette.responses", "starlette.requests"):
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

# As grafias do TM em português, as que os técnicos desta liga têm.
for pais, emoji in (("Portugal", "🇵🇹"), ("Itália", "🇮🇹"), ("Alemanha", "🇩🇪"),
                    ("Austrália", "🇦🇺"), ("Croácia", "🇭🇷"), ("Marrocos", "🇲🇦"),
                    ("Brasil", "🇧🇷"), ("Tunísia", "🇹🇳"), ("Holanda", "🇳🇱"),
                    ("Espanha", "🇪🇸")):
    got = main._elenco_pais([pais]).get("pais_bandeira")
    ok(got == emoji,
       f"'{pais}' do Transfermarkt virou {got!r} e não {emoji}. É a mesma "
       "tradução que dá a bandeira dos jogadores no campinho")


def _rodar(ficha=None, aviso=None, erro=None, af=("", "reserva não usada")):
    _t, _e = elenco_tm.tecnico, main._emoji_do_tecnico

    async def tecnico(clube_id):
        if erro:
            raise erro
        return dict(ficha or {}), aviso

    async def emoji_af(clube, nome):
        return af

    elenco_tm.tecnico, main._emoji_do_tecnico = tecnico, emoji_af
    try:
        return asyncio.run(main._tecnico_do_clube({"id": 1114, "nome": "Diriyah"},
                                                  "BRUNO", "DIRIYAH CLUB"))
    finally:
        elenco_tm.tecnico, main._emoji_do_tecnico = _t, _e


nome, emoji, motivo = _rodar({"nome": "Bruno Lage", "nacionalidades": ["Portugal"]})
ok(nome == "Bruno Lage" and emoji == "🇵🇹",
   f"saiu ({nome!r}, {emoji!r}) — devia ser Bruno Lage com a bandeira de "
   "Portugal, o nome do TM no lugar do 'BRUNO' da folha")
ok("Transfermarkt" in motivo, "o motivo não diz que veio do Transfermarkt")

# O TM bloqueou: a folha e a API-Football seguram, e o motivo diz por quê.
nome, emoji, motivo = _rodar(erro=RuntimeError("Transfermarkt HTTP 403"),
                             af=("🇵🇹", "pelo clube: B. Lage (Portugal)"))
ok(nome == "BRUNO" and emoji == "🇵🇹" and "403" in motivo,
   f"com o TM fora a reserva não funcionou ou o motivo se perdeu: "
   f"({nome!r}, {emoji!r}, {motivo!r})")

# Clube sem id do TM na lista: direto para a reserva, sem perguntar ao TM.
_t = elenco_tm.tecnico
chamado = []


async def _nao_chame(clube_id):
    chamado.append(clube_id)
    return {}, None
try:
    elenco_tm.tecnico = _nao_chame
    _e = main._emoji_do_tecnico

    async def _af(clube, nome_):
        return "", "nada"
    main._emoji_do_tecnico = _af
    asyncio.run(main._tecnico_do_clube({"nome": "X"}, "FULANO", "X"))
finally:
    elenco_tm.tecnico, main._emoji_do_tecnico = _t, _e
ok(chamado == [], "o TM foi consultado sem id de clube")

# A ARTE USA O NOME DO TM, e não o da folha.
FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ok('"tecnico": {"nome": tecnico, "bandeira": band_tec}' in FONTE,
   "a arte voltou a desenhar o nome do técnico da FOLHA ('BRUNO') em vez do "
   "nome do Transfermarkt ('BRUNO LAGE')")
ok("await _tecnico_do_clube(" in FONTE[FONTE.find("async def _lado_da_escalacao"):
                                      FONTE.find("async def api_elencos_card")],
   "a rota da arte não pergunta mais o técnico ao Transfermarkt")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f_ in falhas:
        print("   - " + f_)
    sys.exit(1)
print("✅ técnico pelo Transfermarkt: nome completo, o principal e a bandeira")
