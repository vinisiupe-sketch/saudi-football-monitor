"""
Nenhuma tela pode depender de uma fonte só.

O QUE ACONTECEU (14/09/26)
    A guia Campinho abriu assim:

        Não consegui carregar a lista de clubes agora:
        RuntimeError: Transfermarkt HTTP 403 em saudi-professional-league/...

    Sem clube nenhum. Sem escudo, sem elenco, sem campo para montar. O
    Transfermarkt responde 403 quando acha que está sendo consultado demais, e
    a lista de clubes vinha só de lá — raspada ao vivo, a cada abertura.

    O Vini: "isso aqui é um erro que não podemos mais passar. Agora temos
    glossário. Não podemos depender do Transfermarkt. Use a API da SPL pra
    preencher esse campo de clubes. Tudo que o Transfermarkt não conseguir
    pegar tem que ter um backup de outra fonte."

A ORDEM, e cada degrau resolve a falha do anterior
    CLUBES:  SPL (oficial, sem raspagem) → elenco congelado (nosso banco, sem
             rede) → Transfermarkt.
    ELENCO:  Transfermarkt ao vivo (o mais completo) → elenco congelado →
             glossário (sabe QUEM joga em cada clube, ainda que com menos
             campos).

    A SPL vem primeiro nos clubes porque é a fonte OFICIAL da competição: quem
    está na liga esta temporada é ela quem diz. O Transfermarkt é uma boa
    cópia disso, não o original.

O QUE ESTE ARQUIVO VIGIA
    Que a reserva entra quando precisa, que ela NÃO entra quando não precisa,
    e que a tela diz de onde veio. Reserva calada esconde que a principal está
    fora do ar — e o defeito só aparece quando falta algo que só ela tinha.
"""
import os
import sys
import types
from unittest.mock import MagicMock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    _t = types.ModuleType("psycopg2")
    _t.extras = types.ModuleType("psycopg2.extras")
    _t.extras.RealDictCursor = object
    _t.Error = Exception
    sys.modules["psycopg2"] = _t
    sys.modules["psycopg2.extras"] = _t.extras

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


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
    fastapi = sys.modules["fastapi"]
    app = fastapi.FastAPI.return_value
    for metodo in ("get", "post", "put", "patch", "delete", "middleware",
                   "on_event", "exception_handler", "websocket"):
        getattr(app, metodo).side_effect = lambda *a, **k: (lambda f: f)
    if "main" in sys.modules:
        return sys.modules["main"]
    import main
    return main


CONGELADO = [
    {"clube_id": 20, "clube": "Al-Hilal SFC", "jogador_id": 111,
     "nome": "Guardado Um", "numero": 1, "posicao": "Goleiro", "idade": 30,
     "altura": 190, "pe": "direito", "nacionalidades": "Brasil",
     "foto": "tm/um.png", "valor": "€1m"},
    {"clube_id": 20, "clube": "Al-Hilal SFC", "jogador_id": 222,
     "nome": "Guardado Dois", "numero": 9, "posicao": "Centroavante",
     "idade": 25, "altura": 182, "pe": "esquerdo",
     "nacionalidades": "Portugal", "foto": "tm/dois.png", "valor": "€2m"},
]

GLOSSARIO = [
    {"id": 1, "spl_id": "s1", "af_id": 101, "tm_id": "901",
     "nome_principal": "Do Glossario Um", "clube": "Al Hilal",
     "posicao": "Goalkeeper", "camisa": "1", "nacionalidade": "Arábia Saudita",
     "nascimento": "2000-01-01", "foto": "spl/g1.png"},
    {"id": 2, "spl_id": "s2", "af_id": 102, "tm_id": "902",
     "nome_principal": "Do Glossario Dois", "clube": "Al Hilal",
     "posicao": "Left Winger", "camisa": "11", "nacionalidade": "Brasil",
     "nascimento": "1999-06-06", "foto": "spl/g2.png"},
    {"id": 3, "spl_id": "s3", "af_id": 103, "tm_id": "903",
     "nome_principal": "De Outro Clube", "clube": "Al Nassr",
     "posicao": "Defender", "camisa": "4", "nacionalidade": "França",
     "nascimento": "1998-03-03", "foto": "spl/g3.png"},
]


def testar():
    falhas.clear()
    main = _importar_main()
    import asyncio
    import database
    import glossario

    database.glossario_completo = lambda: ([dict(g) for g in GLOSSARIO], [])
    database.valor_de_ajuste = lambda c: "melhor disponível"
    glossario.recarregar()

    # ── 1. O SETOR SAI DA POSIÇÃO, NAS DUAS LÍNGUAS ──────────────────────
    # As reservas escrevem diferente: o elenco congelado guardou o que o
    # Transfermarkt brasileiro dizia, o glossário guarda o rótulo da SPL, em
    # inglês. Sem as duas, metade do elenco cairia fora dos filtros do
    # campinho — e cairia em silêncio, que é pior.
    for pos, esperado in (("Goleiro", "G"), ("Goalkeeper", "G"),
                          ("Zagueiro", "D"), ("Centre-Back", "D"),
                          ("Lateral-direito", "D"), ("Defender", "D"),
                          ("Volante", "M"), ("Midfielder", "M"),
                          ("Meia-atacante", "M"), ("Centroavante", "A"),
                          ("Left Winger", "A"), ("Forward", "A"),
                          ("Centre-Forward", "A")):
        conferir(f"setor de {pos!r}", main._grupo_da_posicao(pos), esperado)
    conferir("posição desconhecida fica sem setor",
             main._grupo_da_posicao("Coringa"), "")
    conferir("posição vazia fica sem setor", main._grupo_da_posicao(""), "")

    # ── 2. O ELENCO CONGELADO É A PRIMEIRA RESERVA ───────────────────────
    database.elenco_congelado = lambda cid=None: (
        [dict(j) for j in CONGELADO] if cid in (None, 20) else [])
    linhas, fonte, avisos = main._elenco_de_reserva(20, "Al Hilal")
    conferir("a primeira reserva é o banco", fonte, "congelado")
    conferir("e traz o elenco inteiro", len(linhas), 2)
    conferir("com o setor derivado da posição",
             [j["grupo"] for j in linhas], ["G", "A"])
    conferir("e com o que o TM ao vivo daria de cadastro",
             linhas[0]["pe"], "direito")
    ok(any("congelado" in a for a in avisos),
       "a reserva entrou calada. Sem dizer, ninguém descobre que o "
       "Transfermarkt está fora do ar — e os números da temporada somem sem "
       "explicação")

    # ── 3. SEM BANCO, O GLOSSÁRIO ────────────────────────────────────────
    # Ele tem menos campos, mas tem as PESSOAS certas — e é isso que o
    # campinho precisa para montar uma escalação.
    database.elenco_congelado = lambda cid=None: []
    linhas, fonte, avisos = main._elenco_de_reserva(20, "Al Hilal")
    conferir("a última reserva é o glossário", fonte, "glossario")
    conferir("com quem joga NAQUELE clube", len(linhas), 2)
    ok(all("Glossario" in j["nome"] for j in linhas),
       f"veio gente de outro clube: {[j['nome'] for j in linhas]}")
    conferir("o setor sai do rótulo em inglês da SPL",
             sorted(j["grupo"] for j in linhas), ["A", "G"])
    # O QUE ELE NÃO TEM FICA VAZIO. Preencher altura por semelhança seria
    # inventar um dado que ninguém mediu.
    conferir("altura que o glossário não tem fica vazia",
             linhas[0]["altura"], None)
    conferir("pé que o glossário não tem fica vazio", linhas[0]["pe"], None)
    ok(any("glossário" in a for a in avisos),
       "o glossário entrou sem avisar que traz menos campos")

    # E o nome do clube é obrigatório aqui: sem ele eu não sei quem procurar.
    linhas, fonte, avisos = main._elenco_de_reserva(0, "")
    conferir("sem clube não inventa elenco", linhas, [])
    linhas, fonte, _ = main._elenco_de_reserva(0, "Clube Que Nao Existe")
    conferir("clube desconhecido não inventa elenco", linhas, [])

    # ── 3b. A QUEDA, EXECUTADA ───────────────────────────────────────────
    # Conferir a ORDEM no código não bastava: eu podia trocar a primeira fonte
    # por uma lista vazia e o teste passava, porque as três continuavam
    # escritas na ordem certa. Aqui cada fonte é derrubada de verdade.
    import elenco_tm as _tm
    guardados = (main._clubes_da_liga_spl, main._clubes_do_congelado, _tm.clubes)

    async def _tm_caiu(*a, **k):
        raise RuntimeError("Transfermarkt HTTP 403")

    try:
        # Tudo no ar: vem da SPL, e sem aviso nenhum.
        main._clubes_da_liga_spl = lambda: [{"id": 20, "nome": "Al Hilal",
                                             "sigla": "HIL", "escudo": "spl.png"}]
        main._clubes_do_congelado = lambda: {"al hilal": (20, "Al-Hilal SFC")}
        _tm.clubes = _tm_caiu
        r = asyncio.run(main.api_elencos_times())
        conferir("com tudo no ar, a lista vem da SPL", r.get("fonte"), "spl")
        conferir("e o escudo é o da SPL", r["times"][0]["escudo"], "spl.png")
        conferir("sem aviso quando a fonte principal responde", r["avisos"], [])

        # A SPL CAI. É o caso do 403 que o Vini viu — só que agora do outro
        # lado. A lista tem que continuar aparecendo.
        def _spl_caiu():
            raise RuntimeError("SPL fora do ar")
        main._clubes_da_liga_spl = _spl_caiu
        r = asyncio.run(main.api_elencos_times())
        conferir("com a SPL fora, a lista vem do banco", r.get("fonte"), "congelado")
        conferir("e ainda tem clube", len(r.get("times") or []), 1)
        ok(any("SPL" in a for a in r.get("avisos") or []),
           "a queda da SPL entrou calada. A tela precisa dizer que está numa "
           "reserva, senão ninguém descobre que a fonte oficial caiu")

        # SPL fora E banco vazio: sobra o Transfermarkt, que também está fora.
        # Aí sim é erro — mas um erro que DIZ que as três foram tentadas.
        main._clubes_do_congelado = lambda: {}
        r = asyncio.run(main.api_elencos_times())
        ok(r.get("erro"), "com as três fontes fora, a rota tinha que dizer que "
                          "falhou em vez de devolver lista vazia")
        ok(len(r.get("avisos") or []) >= 2,
           "o erro final não conta o que foi tentado. Sem isso, o Vini não "
           "sabe se o problema é de uma fonte ou de todas")

        # E com o Transfermarkt de pé, ele ainda é a última saída.
        async def _tm_ok(*a, **k):
            return [{"id": 20, "nome": "Al-Hilal SFC", "escudo": "tm.png"}], None
        _tm.clubes = _tm_ok
        r = asyncio.run(main.api_elencos_times())
        conferir("a última saída ainda é o Transfermarkt",
                 r.get("fonte"), "transfermarkt")
    finally:
        main._clubes_da_liga_spl, main._clubes_do_congelado, _tm.clubes = guardados

    # ── 4. A LISTA DE CLUBES NÃO DEPENDE MAIS DO TRANSFERMARKT ───────────
    import ast
    fonte_txt = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    times = next((ast.get_source_segment(fonte_txt, n)
                  for n in ast.walk(ast.parse(fonte_txt))
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "api_elencos_times"), "")
    ok(times.find("_clubes_da_liga_spl") < times.find("_clubes_do_congelado")
       < times.find("elenco_tm.clubes"),
       "a ordem das fontes de clube mudou. Tem que ser SPL → banco → "
       "Transfermarkt: a SPL é a fonte OFICIAL de quem está na liga, e o TM "
       "responde 403 quando quer")
    ok('"fonte": "spl"' in times and '"fonte": "congelado"' in times,
       "a rota parou de dizer de qual fonte a lista veio")

    spl = next((ast.get_source_segment(fonte_txt, n)
                for n in ast.walk(ast.parse(fonte_txt))
                if isinstance(n, ast.FunctionDef)
                and n.name == "_clubes_da_liga_spl"), "")
    ok("liga_spl.jogos_da_temporada" in spl,
       "a lista de clubes deixou de sair do calendário oficial da SPL")
    ok("_clubes_do_congelado()" in spl,
       "os clubes da SPL pararam de receber o id do Transfermarkt — sem ele o "
       "elenco ao vivo não é buscável")
    ok('d["id"] = tm[0] if tm else 0' in spl,
       "clube sem cruzamento com o Transfermarkt sumiu da lista. Ele tem que "
       "aparecer assim mesmo: a busca de elenco aceita o NOME como chave")

    # ── 5. A BUSCA DE ELENCO ACEITA O NOME ───────────────────────────────
    # É o que mantém clicável o clube que a SPL conhece e o Transfermarkt não.
    jog = next((ast.get_source_segment(fonte_txt, n)
                for n in ast.walk(ast.parse(fonte_txt))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "api_elencos_jogadores"), "")
    ok("async def api_elencos_jogadores(team: int = 0, clube: str = \"\")" in jog,
       "a busca de elenco voltou a exigir o id do Transfermarkt")
    ok("_elenco_de_reserva, team, clube)" in jog,
       "a busca de elenco parou de cair para as reservas")
    ok(jog.find("elenco_tm.elenco(team)") < jog.find("_elenco_de_reserva"),
       "as reservas passaram a vir ANTES do Transfermarkt ao vivo. Ele é o "
       "mais completo — pé, altura, valor e números da temporada — e tem que "
       "continuar sendo a primeira escolha")
    ok('"fonte": fonte' in jog,
       "a resposta do elenco parou de dizer de onde ele veio")
    for tela, texto in (("campinho", open(os.path.join(RAIZ, "public", "campinho.html"), encoding="utf-8").read()),
                        ("elencos", fonte_txt)):
        ok("'&clube=' + encodeURIComponent(TIME_NOME || '')" in texto,
           f"a guia {tela} parou de mandar o nome do clube junto — sem ele, "
           "clube sem id do Transfermarkt aparece na barra e não abre nada")
        ok("data-nome=" in texto,
           f"a guia {tela} parou de guardar o nome do clube no escudo")

    for f_ in falhas:
        print("  ✗", f_)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ fontes de reserva: SPL primeiro, e nada depende só do Transfermarkt")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
