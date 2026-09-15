"""
A guia Elencos vira ficha de jogador, e o campinho ganha guia própria.

O PEDIDO (14/09/26)
    O Vini mandou duas imagens: a ficha do Cristiano Ronaldo no Sofascore e o
    montador de escalação do oGol. A guia de Elencos passa a avaliar jogador —
    ficha à esquerda, lista à direita — e o campinho sai de lá para uma guia
    "Campinho", com o campo à esquerda e o elenco em cartões à direita.

POR QUE SEPARAR ERA O CERTO
    As duas telas respondiam perguntas diferentes no mesmo lugar. Elencos é
    "como este jogador está?" — número ao lado de número, para comparar. O
    campinho é "quem eu ponho nesta vaga?" — e isso se responde pelo rosto e
    pela posição. Juntas, cada uma atrapalhava a outra: o campo comia metade
    da largura da tabela, e a tabela dava doze colunas a quem só queria achar
    um lateral.

O QUE ESTE ARQUIVO VIGIA
    Que a ficha soma o que mostra, que ela não inventa nota, que o campinho
    filtra pela vaga escolhida, e que a escalação NÃO ficou nas duas telas —
    o Vini foi explícito: ela vive só no Campinho.
"""
import json
import os
import subprocess
import sys
import tempfile
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

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
CAMPINHO = open(os.path.join(RAIZ, "public", "campinho.html"),
                encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _tem_node() -> str:
    for nome in ("node", "nodejs"):
        try:
            if subprocess.run([nome, "--version"], capture_output=True,
                              timeout=20).returncode == 0:
                return nome
        except Exception:
            continue
    return ""


def _elencos_html() -> str:
    i = FONTE.find('_ELENCOS_HTML = """')
    j = FONTE.find('\n"""', i + 25)
    return FONTE[i:j]


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


# Um jogador e três partidas dele. Os números são escolhidos para que a soma
# não coincida por acaso com nenhum deles — se a ficha somasse errado, ou
# copiasse um totalzinho de outro lugar, o resultado seria diferente.
PARTIDAS = [
    {"fixture_id": 1, "minutos": 90, "titular": True, "gols": 2,
     "assistencias": 1, "amarelos": 1, "vermelhos": 0, "nota": 8.5,
     "clube": "Al Nassr", "data": "2026-09-11", "casa": "Al Nassr",
     "fora": "Al Hazem", "em_casa": True, "adversario": "Al Hazem",
     "capitao": True, "posicao": "F", "rodada": "4", "status": "FT",
     "liga_id": 307, "liga_nome": "Saudi Pro League",
     "liga_logo": "https://media.api-sports.io/football/leagues/307.png"},
    {"fixture_id": 2, "minutos": 45, "titular": False, "gols": 0,
     "assistencias": 0, "amarelos": 0, "vermelhos": 1, "nota": 5.8,
     "clube": "Al Nassr", "data": "2026-09-01", "casa": "Al Hilal",
     "fora": "Al Nassr", "em_casa": False, "adversario": "Al Hilal",
     "capitao": False, "posicao": "F", "rodada": "3", "status": "FT",
     "liga_id": 307, "liga_nome": "Saudi Pro League",
     "liga_logo": "https://media.api-sports.io/football/leagues/307.png"},
    # Partida SEM nota: acontece quando a API não publica. A média não pode
    # contá-la como zero.
    {"fixture_id": 3, "minutos": 67, "titular": True, "gols": 1,
     "assistencias": 0, "amarelos": 0, "vermelhos": 0, "nota": None,
     "clube": "Al Nassr", "data": "2026-08-26", "casa": "Al Nassr",
     "fora": "Abha", "em_casa": True, "adversario": "Abha",
     "capitao": False, "posicao": "F", "rodada": "2", "status": "FT",
     # Outra competição, de propósito: é ela que faz o filtro ter o que
     # filtrar, e o seletor ter mais de uma opção para aparecer.
     "liga_id": 504, "liga_nome": "King Cup",
     "liga_logo": "https://media.api-sports.io/football/leagues/504.png"},
]

FICHA_GLOSSARIO = {
    "id": 7, "spl_id": "s7", "af_id": 874, "tm_id": "8198",
    "nome_principal": "Cristiano Ronaldo", "nome_curto": "Ronaldo",
    "nome_ar": "كريستيانو رونالدو", "clube": "Al Nassr", "posicao": "Atacante",
    "camisa": "7", "nacionalidade": "Portugal", "nascimento": "1985-02-05",
    "foto": "spl/cr7.png",
}


def testar():
    falhas.clear()
    main = _importar_main()
    import asyncio
    import database
    import glossario

    # ── 1. A FICHA SOMA O QUE MOSTRA ─────────────────────────────────────
    # Os totais saem da soma das partidas, e não de uma tabela de agregados.
    # Assim eles nunca discordam da lista logo abaixo — um total dizendo 8
    # jogos com 7 na lista obriga a escolher em qual acreditar, sem dar pista
    # nenhuma de qual está certo.
    glossario.recarregar()
    database.glossario_completo = lambda: ([dict(FICHA_GLOSSARIO)], [])
    database.valor_de_ajuste = lambda c: "melhor disponível"
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in PARTIDAS]
    glossario.recarregar()

    d = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    t = d["totais"]
    conferir("jogos", t["jogos"], 3)
    conferir("começou", t["comecou"], 2)
    conferir("minutos", t["minutos"], 202)
    conferir("gols", t["gols"], 3)
    conferir("assistências", t["assistencias"], 1)
    conferir("amarelos", t["amarelos"], 1)
    conferir("vermelhos", t["vermelhos"], 1)
    # MÉDIA SÓ DO QUE TEM NOTA. Contar a partida sem nota como zero puxaria a
    # média para 4,77 — uma avaliação péssima que ninguém deu, ao lado de um
    # jogador que fez três gols.
    conferir("média das notas ignora quem não tem nota", t["nota_media"], 7.15)

    # ── 1b. ZERO E "NÃO SEI" NÃO SÃO A MESMA COISA ───────────────────────
    #
    # O João Félix apareceu com 0 gols e 0 assistências na ficha enquanto a
    # tabela AO LADO, vinda do Transfermarkt, mostrava os números certos. Uma
    # contradição na mesma tela, e a ficha era a que mentia com mais confiança.
    #
    # A causa: as partidas lidas antes de 14/09 guardaram só minutos e titular,
    # então gols e assistências ficaram NULOS — e eu somava com `or 0`. Eu
    # passei semanas caçando exatamente este erro em outras telas e o cometi
    # aqui.
    INCOMPLETAS = [dict(p, gols=None, assistencias=None, amarelos=None,
                        vermelhos=None, nota=None) for p in PARTIDAS]
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in INCOMPLETAS]
    meia = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    tm_ = meia["totais"]
    conferir("sem nenhum dado de gol, o total é 'não sei' e não zero",
             tm_["gols"], None)
    conferir("o mesmo para assistências", tm_["assistencias"], None)
    conferir("e para os cartões", tm_["amarelos"], None)
    # Minutos e jogos CONTINUAM contando: esses sempre foram guardados, e
    # apagá-los junto seria jogar fora o que está certo.
    conferir("minutos continuam somando", tm_["minutos"], 202)
    conferir("jogos continuam contando", tm_["jogos"], 3)
    conferir("e a tela sabe quantas partidas estão pela metade",
             meia["incompletas"], 3)

    # Com UMA partida completa, a soma é dela — e não some por causa das outras.
    MISTO = [dict(INCOMPLETAS[0], gols=2, assistencias=1, amarelos=1,
                  vermelhos=0)] + INCOMPLETAS[1:]
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in MISTO]
    mx = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    conferir("uma partida completa já dá total", mx["totais"]["gols"], 2)
    conferir("e as outras continuam sendo contadas como pendentes",
             mx["incompletas"], 2)
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in PARTIDAS]
    conferir("com tudo lido, não sobra pendência",
             asyncio.run(main.api_jogador_ficha(tm_id="8198"))["incompletas"], 0)

    # ── 1b2. E O APP SE COMPLETA SOZINHO ─────────────────────────────────
    #
    # "Eu vou ter que clicar em LER AGORA em todos os jogadores, todas as
    # vezes?" — não, e o botão só existia porque eu tinha deixado o conserto
    # na mão dele. A rotina de madrugada desmarca as partidas pela metade e as
    # relê, até não sobrar nenhuma.
    import ast as _ast
    sched = open(os.path.join(RAIZ, "scheduler.py"), encoding="utf-8").read()
    ret = next((_ast.get_source_segment(sched, n)
                for n in _ast.walk(_ast.parse(sched))
                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                and n.name == "run_retornos"), "")
    # A LINHA EXATA: o nome da função também aparece no import e no balanço
    # do fim, então procurá-lo solto deixava passar um `incompletas = 0`.
    ok("incompletas = await asyncio.to_thread(partidas_com_atuacao_incompleta)"
       in ret,
       "a rotina de madrugada não pergunta se há partidas pela metade — o "
       "conserto volta a depender de alguém clicar num botão")
    ok('esquecer_escalacoes_lidas, "incompletas"' in ret,
       "a rotina desmarca TODAS as partidas em vez de só as incompletas. "
       "Reler a temporada inteira toda noite é uma chamada por partida para "
       "reconfirmar o que já está certo")
    ok("if incompletas:" in ret,
       "a releitura deixou de ser condicional — ela passa a rodar todo dia "
       "mesmo quando não há nada a completar")
    # E O NÚMERO DE PASSADAS, não só a existência do laço: `range(1)` é um
    # laço que não repete, e passava na versão anterior desta asserção.
    import re as _re
    _m = _re.search(r"for _ in range\((\d+)\)", ret)
    ok(_m and int(_m.group(1)) > 1,
       "a rotina lê uma passada só. Uma temporada não cabe numa passada, e o "
       "teto por passada existe porque cada partida custa uma chamada")

    banco = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    esq = next((_ast.get_source_segment(banco, n)
                for n in _ast.walk(_ast.parse(banco))
                if isinstance(n, _ast.FunctionDef)
                and n.name == "esquecer_escalacoes_lidas"), "")
    ok('WHERE fixture_id IN (' in esq and "gols IS NULL" in esq,
       "o modo 'incompletas' deixou de escolher pelas partidas sem números")
    inc = next((_ast.get_source_segment(banco, n)
                for n in _ast.walk(_ast.parse(banco))
                if isinstance(n, _ast.FunctionDef)
                and n.name == "partidas_com_atuacao_incompleta"), "")
    ok("COUNT(DISTINCT fixture_id)" in inc and "gols IS NULL" in inc,
       "a contagem de partidas pela metade mudou de critério")

    # E A TELA DIZ QUE É AUTOMÁTICO. Um aviso que não diz isso transforma um
    # conserto automático numa tarefa recorrente na cabeça de quem lê.
    ok("completa isso sozinho" in _elencos_html(),
       "o aviso não diz que o app se completa sozinho — foi exatamente o que "
       "fez o Vini achar que teria de clicar em cada jogador, toda vez")
    ok("todos os jogadores de uma vez" in _elencos_html(),
       "o aviso não diz que a releitura vale para o elenco inteiro")

    # E A TELA OFERECE O CONSERTO, em vez de só mostrar "—".
    el_ = _elencos_html()
    # A LINHA EXATA, e não o nome da função: um `return ''` posto na frente
    # deixa os dois textos no arquivo e mata o aviso. Já caí nessa antes.
    ok("function avisoIncompleto(d){\n  if (!d.incompletas) return '';" in el_,
       "a ficha não avisa que faltam números por partida")
    # Dentro do avisoIncompleto, e não em qualquer lugar do arquivo.
    _aviso = el_.split("function avisoIncompleto(d){")[-1].split("\n}")[0]
    ok('onclick="relerEscalacoes(this)"' in _aviso,
       "o aviso não oferece a releitura. 'Ainda não li' tem conserto, e não se "
       "conserta o que não parece quebrado")
    ok("'/api/escalacoes/reler'" in el_, "o botão de reler não chama a rota")

    # ── 1c. O PLACAR DO PONTO DE VISTA DELE ──────────────────────────────
    #
    # É onde um sinal trocado passa despercebido: o jogo fica com o placar
    # certo e a vitória vira derrota, e a tela não tem como denunciar — quem
    # olha vê "2 - 1 D" e acredita.
    from database import placar_do_jogador as _pj
    conferir("em casa, vitória", _pj(3, 1, True), ("3 - 1", "V"))
    conferir("em casa, derrota", _pj(1, 3, True), ("1 - 3", "D"))
    conferir("FORA, o placar inverte", _pj(3, 1, False), ("1 - 3", "D"))
    conferir("fora, vitória", _pj(1, 3, False), ("3 - 1", "V"))
    conferir("empate em casa", _pj(2, 2, True), ("2 - 2", "E"))
    conferir("empate fora", _pj(2, 2, False), ("2 - 2", "E"))
    conferir("0 a 0 é empate, não ausência", _pj(0, 0, True), ("0 - 0", "E"))
    # Jogo sem placar guardado fica VAZIO. Um "0 - 0" inventado para partida
    # que não aconteceu seria pior que a coluna em branco.
    conferir("sem placar, nada é inventado", _pj(None, None, True), ("", ""))
    conferir("com metade do placar, também não", _pj(2, None, True), ("", ""))

    # ── 2. IDENTIDADE PELO GLOSSÁRIO, E PELOS TRÊS IDENTIFICADORES ───────
    # Cada tela tem um id em mãos: Elencos sabe o do Transfermarkt, o Mercado
    # sabe o da API-Football, o campinho sabe o da liga.
    for chave, valor in (("tm_id", "8198"), ("af_id", 874), ("spl_id", "s7")):
        r = asyncio.run(main.api_jogador_ficha(**{chave: valor}))
        conferir(f"acha pelo {chave}", (r.get("jogador") or {}).get("id"), 7)
    r = asyncio.run(main.api_jogador_ficha(tm_id="99999"))
    ok(r.get("sem_glossario"),
       "jogador fora do glossário devia ser dito em voz alta, e não virar uma "
       "ficha vazia que parece erro de carregamento")

    conferir("a idade sai calculada no servidor",
             main._idade_em_anos("1985-02-05") >= 40, True)
    conferir("nascimento vazio não vira idade", main._idade_em_anos(""), None)
    conferir("nascimento curto demais não vira idade",
             main._idade_em_anos("ontem"), None)
    # Dez caracteres, formato certo, data impossível: é o caso que chega ao
    # `strptime` e levanta. "ontem" nem chega lá — morre na conferência de
    # tamanho —, então sozinho ele deixava a outra saída sem teste.
    conferir("data impossível não vira idade",
             main._idade_em_anos("2026-13-45"), None)

    # ── 3. SEM PARTIDA, A TELA PRECISA SABER POR QUÊ ─────────────────────
    # "Ele não jogou" e "eu ainda não li as escalações" são a mesma tela vazia,
    # e a segunda tem conserto. É a mesma armadilha da guia de Clipes.
    database.jogo_a_jogo = lambda af, season=0, teto=60: []
    vazia = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    ok(vazia.get("sem_leitura"),
       "ficha sem partidas não avisa que pode ser falta de leitura")
    ok('sem_leitura' in _elencos_html(),
       "a tela não usa o aviso de que as escalações ainda não foram lidas")
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in PARTIDAS]

    # ── 4. OS NÚMEROS JOGO A JOGO SÃO GUARDADOS ──────────────────────────
    # A chamada fixtures/players já trazia gols, assistências, cartões e nota;
    # eu guardava só minutos e titular e pagava a chamada inteira do mesmo
    # jeito. Não é fonte nova: é parar de desperdiçar a que estava aberta.
    import ast
    ler = next((ast.get_source_segment(FONTE, n) for n in ast.walk(ast.parse(FONTE))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "_ler_escalacoes"), "")
    for campo in ('"gols"', '"assistencias"', '"amarelos"', '"vermelhos"',
                  '"nota"', '"capitao"'):
        ok(campo in ler, f"a leitura de escalações parou de guardar {campo}")
    ok('nota = round(float(nota), 2) if nota not in (None, "") else None' in ler,
       "a nota deixou de ser convertida com cuidado. A API manda texto; sem "
       "isso, ou quebra, ou entra como string e a média não fecha")
    ok("except (TypeError, ValueError):" in ler and "nota = None" in ler,
       "nota ilegível passou a virar um número qualquer. Prefiro sem nota a "
       "com nota inventada")

    # ── 5. A ESCALAÇÃO SAIU DE ELENCOS ───────────────────────────────────
    # Decisão do Vini, e é o que impede duas telas de salvarem por cima uma da
    # outra sem ninguém ver.
    el = _elencos_html()
    for proibido in ("salvarEscalacao", "renderCampo", "aplicarFormacao",
                     'id="campo"', "SLOTS"):
        ok(proibido not in el,
           f"'{proibido}' continua na guia de Elencos. O campinho e a "
           "escalação foram para a guia Campinho — ficar nos dois lugares é "
           "ter duas telas gravando por cima uma da outra")
    ok("irAoCampinho" in el,
       "sumiu o atalho de Elencos para o Campinho, levando o clube junto")
    ok("verFicha" in el and "jogosFicha" in el,
       "a ficha do jogador não está na guia de Elencos")

    # ── 5b. OS ELEMENTOS VISUAIS QUE ELE CIRCULOU NO PRINT ───────────────
    # Cada um faz o mesmo trabalho: deixar o olho pousar no lugar certo sem
    # ler. Numa ficha de quarenta números, é a diferença entre consultar e
    # decifrar.
    for peca, porque in (
        ("function atributo(icone, texto)",
         "a linha de atributos perdeu os ícones — vira seis informações "
         "separadas por ponto, que se leem todas ou nenhuma"),
        ("escudo-ficha",
         "sumiu o escudo ao lado do clube. Numa liga em que 15 dos 18 nomes "
         "começam com 'Al-', o escudo é o que se reconhece"),
        ("cel(t.amarelos, 'Cartões amarelos', {icone: ICO.amarelo})",
         "sumiu o cartão ao lado do número de amarelos"),
        ("cel(t.vermelhos, 'Cartões vermelhos', {icone: ICO.vermelho})",
         "sumiu o cartão ao lado do número de vermelhos"),
        ("p.escudo_adversario ? '<img class=\"escudo-jg\"",
         "sumiu o escudo do adversário na lista de partidas"),
        ("res-V",
         "sumiu o V/D/E colorido. É ele que deixa varrer a campanha sem ler"),
        ("jg-placar", "sumiu o placar da partida"),
        ('<th title="Avaliação"><i class="ico">',
         "o cabeçalho da tabela voltou a ser letra. Em nove colunas estreitas, "
         "'G' e 'A' não se distinguem de relance; a bola e o cartão sim"),
    ):
        ok(peca in el, porque)
    # ── 5c. OS AJUSTES DE 15/09 ──────────────────────────────────────────
    #
    # A ficha aberta no celular vinha CORTADA e sem como arrastar. A lista do
    # elenco rolava; esta não, porque o corte acontecia no cartão da ficha, que
    # esconde o que transborda por causa das bordas arredondadas.
    ok('<div class="rolagem-jogos">' in el and ".rolagem-jogos{overflow-x:auto" in el,
       "a tabela de partidas voltou a não rolar de lado — no celular ela fica "
       "cortada e metade das colunas some sem jeito de alcançar")
    ok(".ficha-caixa{overflow:visible" in el,
       "a ficha voltou a esconder o que transborda no celular. É isso que "
       "corta a tabela e impede o arraste")
    ok(".rolagem-jogos .tab-jogos{min-width:" in el,
       "a tabela perdeu a largura mínima — sem ela as colunas se espremem em "
       "vez de rolar, e os números ficam ilegíveis")

    # A data curta, para sobrar largura ao nome do adversário.
    ok("function dataCurta(iso){" in el and "MESES_CURTOS" in el,
       "sumiu a data curta (dd mmm) da lista de partidas")
    ok("dataCurta(p.data)" in el,
       "a lista de partidas voltou à data por extenso, que come a largura do "
       "nome do adversário")

    # Casa e avião em vez da palavra "fora".
    ok("(p.em_casa ? ICO.casa : ICO.aviao)" in el,
       "voltou a palavra 'fora' no lugar dos ícones de casa e avião — numa "
       "coluna que se repete dez vezes, a palavra rouba o nome do adversário")
    ok('title="' + "' + (p.em_casa ? 'Em casa' : 'Fora de casa') + '" in el,
       "os ícones de casa e avião ficaram sem explicação ao passar o mouse")

    # Competição, placar e resultado na mesma linha.
    ok('class="jg-comp"' in el and "ICO.trofeu" in el,
       "sumiu a coluna de competição da lista de partidas")
    ok("'<span class=\"jg-placar\">' + (p.placar || '')" in el,
       "o placar saiu da linha da partida")

    # Ícones no cabeçalho de minutos, gols e assistências.
    for icone, coluna in ((("ICO.relogio"), "minutos"), ("ICO.bola", "gols"),
                          ("ICO.passe", "assistências")):
        ok(icone in el, f"o cabeçalho de {coluna} voltou a ser letra")

    # O cabeçalho quebra em duas linhas, e a camisa vai para o lado do nome.
    ok('class="ficha-linha ficha-cadastro"' in el,
       "a linha de atributos voltou a ser uma só. No celular as seis "
       "informações viram um bloco de texto corrido que ninguém lê")
    ok("<h2>' + nome + numero + '</h2>" in el,
       "a camisa saiu de junto do nome. Ela não é dado de cadastro como "
       "altura ou pé — é como o jogador é chamado em campo")
    ok("atributo(ICO.camisa" not in el,
       "a camisa continua na lista de atributos, repetida")

    # A bandeira é IMAGEM, não emoji: no Windows o emoji de bandeira sai como
    # duas letras, e é no Windows que ele abre isto.
    ok('p["escudo_adversario"] = _escudo(p.get("adversario") or "")' in FONTE,
       "o servidor parou de preencher o escudo do adversário — a tela tem o "
       "lugar dele e nada para pôr lá")
    ok("flagcdn.com/w40/" in el,
       "a bandeira da ficha voltou a ser emoji — no Windows ela vira um par "
       "de letras")

    # E o Campinho tem tudo que saiu de lá.
    for preciso in ("salvarEscalacao", "renderCampo", "aplicarFormacao",
                    'id="campo"', "baixarArte", "voltarEscalacao"):
        ok(preciso in CAMPINHO,
           f"'{preciso}' não chegou na guia Campinho — ela precisa fazer tudo "
           "que a de Elencos fazia com o campo")
    ok('@app.get("/campinho"' in FONTE, "sumiu a rota da guia Campinho")

    # A LISTA DE FORMAÇÕES tem que existir antes de qualquer clube. Ao separar
    # as páginas eu levei as funções e esqueci o trecho que preenche o seletor
    # — a guia abria com o campo vazio e só a formação do último jogo, que vem
    # depois, junto com a escalação.
    ok("Object.keys(FORMACOES).map(function(f){" in CAMPINHO,
       "o seletor de formações não é preenchido no Campinho — sobra só a "
       "formação do último jogo, que chega junto com a escalação")
    ok("aplicarFormacao(FORM);" in CAMPINHO.split("// ── início ──")[-1],
       "o Campinho não monta um campo antes de o clube ser escolhido")

    # E O COLUNAS É DE ELENCOS, não do Campinho. Ele morava no fim do bloco do
    # `soltarEm` — código do campo — e o meu corte por função levou o vizinho
    # junto. A guia abriu com "COLUNAS is not defined".
    ok("const COLUNAS = [" in el,
       "sumiu a lista de colunas da tabela de Elencos — é o 'COLUNAS is not "
       "defined' que o Vini viu")
    ok("const COLUNAS = [" not in CAMPINHO,
       "o COLUNAS continua no Campinho, que não tem tabela nenhuma")
    for coluna in ("'numero'", "'nome'", "'nacionalidade'", "'idade'",
                   "'altura'", "'pe'", "'posicao'", "'jogos'", "'gols'",
                   "'assistencias'", "'amarelos'", "'vermelhos'", "'minutos'"):
        ok(coluna in el.split("const COLUNAS = [")[-1].split("];")[0],
           f"a coluna {coluna} sumiu da tabela de Elencos — ele pediu "
           "exatamente as que estavam antes")
    ok('("/campinho"' in FONTE, "a guia Campinho não está no menu")

    # ── 5e. O FILTRO DE COMPETIÇÃO REFAZ O CARD ──────────────────────────
    #
    # "Inclua aquele filtro de competição que altera todo o card do jogador."
    # A palavra é "altera todo o card": escolher a Copa do Rei tem de mudar os
    # GOLS, os minutos e a média — não só esconder linhas da lista. Um filtro
    # que mexesse só na tabela deixaria o cabeçalho falando da temporada
    # inteira enquanto a lista fala de outra coisa, e a tela se contradiria.
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in PARTIDAS]
    dc = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    comps = {c["nome"]: c for c in dc["competicoes"]}
    conferir("as competições saem das partidas DELE", sorted(comps), 
             ["King Cup", "Saudi Pro League"])
    conferir("com a contagem de jogos em cada uma",
             comps["Saudi Pro League"]["jogos"], 2)
    conferir("e com o emblema para a tela desenhar",
             comps["King Cup"]["logo"],
             "https://media.api-sports.io/football/leagues/504.png")
    conferir("a competição chega em cada partida",
             dc["partidas"][0]["competicao"], "Saudi Pro League")
    # Partida antiga, lida antes de eu guardar o nome da liga, não fica sem
    # competição: ela cai na liga que o app lê, que é a única que existe hoje.
    database.jogo_a_jogo = lambda af, season=0, teto=60: [
        dict(p, liga_nome=None) for p in PARTIDAS]
    antiga = asyncio.run(main.api_jogador_ficha(tm_id="8198"))
    conferir("sem nome de liga, a partida não fica órfã",
             antiga["partidas"][0]["competicao"], "Saudi Pro League")
    database.jogo_a_jogo = lambda af, season=0, teto=60: [dict(p) for p in PARTIDAS]

    # A CONSULTA tem de trazer as colunas da liga. Este é dos poucos pontos
    # que eu confiro no texto do SQL e não executando: o teste troca o
    # `jogo_a_jogo` inteiro por um dublê, então a consulta de verdade não roda
    # aqui. Digo isso em voz alta porque conferir texto é o tipo de teste que
    # eu já vi passar com o defeito plantado — aqui ele cobre só a lista de
    # colunas, que é o que mudou.
    import ast as _ast2
    _banco = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    _jaj = next((_ast2.get_source_segment(_banco, n)
                 for n in _ast2.walk(_ast2.parse(_banco))
                 if isinstance(n, _ast2.FunctionDef) and n.name == "jogo_a_jogo"), "")
    for _col in ("p.liga_id", "p.liga_nome", "p.liga_logo",
                 "p.gols_casa", "p.gols_fora"):
        ok(_col in _jaj,
           f"a consulta jogo a jogo parou de trazer {_col} — a tela tem o "
           "lugar dele e nada para pôr lá")
    _sal = next((_ast2.get_source_segment(_banco, n)
                 for n in _ast2.walk(_ast2.parse(_banco))
                 if isinstance(n, _ast2.FunctionDef)
                 and n.name == "salvar_partidas_liga"), "")
    # As DUAS pontas: a coluna no INSERT e o valor vindo de quem chama. Só a
    # coluna passava com os nomes trocados aos pares.
    ok('l.get("liga_nome"), l.get("liga_logo")' in _sal,
       "o calendário parou de guardar o nome e o emblema da competição — eles "
       "vêm na MESMA resposta que já pagamos")
    ok("liga_nome = COALESCE(EXCLUDED.liga_nome" in _sal,
       "a atualização do calendário apaga a competição já guardada em vez de "
       "manter o que existe")
    ok('"liga_nome": (f.get("league") or {}).get("name")' in FONTE,
       "a leitura do calendário parou de tirar o nome da competição da "
       "resposta da API")
    ok('"liga_logo": (f.get("league") or {}).get("logo")' in FONTE,
       "a leitura do calendário parou de tirar o emblema da resposta da API")

    el2 = _elencos_html()
    ok("function seletorCompeticao(d){" in el2 and "comps.length < 2" in el2,
       "sumiu o seletor de competição — ou ele passou a aparecer com uma "
       "opção só, que é um botão que não faz nada")
    ok("function somarPartidas(ps){" in el2,
       "o filtro voltou a só esconder linhas. Os totais têm de ser refeitos "
       "com o recorte, senão o cabeçalho e a lista falam de coisas diferentes")
    ok("numerosFicha(d, ps)" in el2 and "jogosFicha(d, ps)" in el2,
       "os números e a lista deixaram de receber as partidas filtradas")
    ok("COMP_ESCOLHIDA = '';\n    FICHA_DADOS" in el2,
       "a competição escolhida sobrevive à troca de jogador — a ficha do "
       "próximo abriria pela metade sem ninguém ter pedido")
    ok("p.liga_logo ? '<img class=\"logo-comp\"" in el2,
       "a lista de partidas parou de usar o emblema real da competição")

    # ── 5f. A SOMA DO NAVEGADOR TEM DE BATER COM A DO SERVIDOR ───────────
    # Duas contas para o mesmo número é como elas divergem. Aqui a do
    # navegador é EXECUTADA contra as mesmas partidas, e o resultado é
    # comparado com o que o servidor devolveu.
    node = _tem_node()
    if not node:
        print("PULAR: o Node nao esta instalado nesta maquina")
        return 1
    _som = el2[el2.find("function somarPartidas(ps){"):el2.find("function escolherCompeticao")]
    _prova = _som + "\nconsole.log(JSON.stringify(somarPartidas(" + \
             json.dumps(PARTIDAS) + ")));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(_prova)
        _c2 = f.name
    try:
        _r2 = subprocess.run([node, _c2], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(_c2)
    if _r2.returncode != 0:
        falhas.append("a soma do navegador quebrou: " + (_r2.stderr or "")[-300:])
    else:
        _js = json.loads(_r2.stdout.strip().splitlines()[-1])
        _py = asyncio.run(main.api_jogador_ficha(tm_id="8198"))["totais"]
        for campo in ("jogos", "comecou", "minutos", "gols", "assistencias",
                      "amarelos", "vermelhos", "nota_media"):
            conferir(f"navegador e servidor concordam em {campo}",
                     _js[campo], _py[campo])
        # E a regra do "não sei" também tem de ser a mesma nos dois lados.
        _prova2 = _som + "\nconsole.log(JSON.stringify(somarPartidas(" + \
                  json.dumps([dict(p, gols=None) for p in PARTIDAS]) + ")));"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(_prova2)
            _c3 = f.name
        try:
            _r3 = subprocess.run([node, _c3], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(_c3)
        conferir("sem nenhum gol sabido, o navegador também diz 'não sei'",
                 json.loads(_r3.stdout.strip().splitlines()[-1])["gols"], None)

    # ── 5d. A DATA CURTA, EXECUTADA ──────────────────────────────────────
    # Procurar o nome da função no arquivo prova que eu a escrevi, não que ela
    # converte certo. Um mês fora da faixa, ou o índice trocado, sai como uma
    # data plausível e errada — "12 out" onde era setembro.
    node = _tem_node()
    if not node:
        print("PULAR: o Node nao esta instalado nesta maquina")
        return 1
    _dc = el[el.find("const MESES_CURTOS"):el.find("function jogosFicha")]
    _prova = _dc + """
var casos = ['2026-09-12','2026-01-01','2026-12-31','2026-08-05',
             '2026-09-12T20:00:00Z','','2026-13-01','ontem'];
console.log(JSON.stringify(casos.map(dataCurta)));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(_prova)
        _cam = f.name
    try:
        _r = subprocess.run([node, _cam], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, OSError):
        print("PULAR: o Node nao esta instalado nesta maquina")
        return 1
    finally:
        os.unlink(_cam)
    if _r.returncode != 0:
        falhas.append("a data curta quebrou: " + (_r.stderr or "")[-300:])
    else:
        _saiu = json.loads(_r.stdout.strip().splitlines()[-1])
        conferir("setembro vira 'set'", _saiu[0], "12 set")
        conferir("janeiro é o primeiro mês, não o zero", _saiu[1], "01 jan")
        conferir("dezembro é o último, e não estoura a lista", _saiu[2], "31 dez")
        conferir("agosto", _saiu[3], "05 ago")
        conferir("data com hora também", _saiu[4], "12 set")
        conferir("vazio não vira data", _saiu[5], "")
        # Mês impossível NÃO pode virar um mês plausível: melhor mostrar o
        # número cru do que dizer outubro onde era outra coisa.
        conferir("mês fora da faixa mostra o número", _saiu[6], "01 13")
        conferir("texto que não é data passa inteiro", _saiu[7], "ontem")

    # ── 6. O CAMPINHO FILTRA PELA VAGA — a ideia do Vini ─────────────────
    # "Clicar no vazio no campinho e ele filtrar a lista de acordo com a
    # posição disponível". É o caminho contrário do arrastar: em vez de achar
    # o jogador e levá-lo até a vaga, você aponta a vaga.
    node = _tem_node()
    if not node:
        print("PULAR: o Node nao esta instalado nesta maquina")
        return 1

    import formacoes
    js = CAMPINHO[CAMPINHO.find("<script>") + 8: CAMPINHO.rfind("</script>")]
    js = js.replace("__FORMACOES__", json.dumps(
        {k: [{"x": x, "y": y, "g": g} for x, y, g in v]
         for k, v in formacoes.QUADROS.items()}))
    MOLDE = """
var _els = {};
// O elemento de mentira responde só o que o código da página usa. Tem
// `style.setProperty` porque o campinho define a escala de cada casa por
// variável de CSS, e `filhos` porque é assim que eu leio o que apareceu.
function _novo(){ var e = {_html:'', textContent:'', dataset:{},
  className:'', value:'', checked:false, draggable:false, filhos:[],
  style:{setProperty:function(){}, removeProperty:function(){}},
  appendChild:function(f){ this.filhos.push(f); return f; },
  insertBefore:function(f){ this.filhos.unshift(f); return f; },
  addEventListener:function(){}, querySelectorAll:function(){ return []; },
  querySelector:function(){ return null; }, remove:function(){},
  closest:function(){ return null; }, focus:function(){},
  classList:{toggle:function(){}, add:function(){}, remove:function(){},
             contains:function(){ return false; }} };
  // ZERAR innerHTML TEM QUE ZERAR OS FILHOS, como no navegador de verdade.
  // Sem isto o meu elemento de mentira acumulava, e o teste do filtro passou
  // a "ver" 20 jogadores num elenco de 5 — acusando o código por um defeito
  // do próprio teste.
  Object.defineProperty(e, 'innerHTML', {
    get:function(){ return this._html; },
    set:function(v){ this._html = v; this.filhos = []; }
  });
  return e; }
var document = {
  getElementById:function(id){ if(!_els[id]) _els[id]=_novo(); return _els[id]; },
  createElement:function(){ return _novo(); },
  querySelectorAll:function(){ return []; }
};
// O `carregarTimes()` do fim da página dispara sozinho ao carregar. Devolvo
// uma lista vazia de clubes para ele terminar em paz — quem este teste
// exercita é o filtro, não a busca de escudos.
function fetch(){ return Promise.resolve({json:function(){ return {times:[]}; }}); }
process.on('unhandledRejection', function(){});
function alert(){}
var location = {href:''};
__JS__
// O elenco de mentira: um por setor, para a vaga distinguir.
ELENCO = [
  {id:1, nome:'Goleiro Um',  grupo:'G', posicao:'Goalkeeper',   numero:1, foto:null},
  {id:2, nome:'Zagueiro Um', grupo:'D', posicao:'Centre-Back',  numero:4, foto:null},
  {id:3, nome:'Meia Um',     grupo:'M', posicao:'Midfielder',   numero:8, foto:null},
  {id:4, nome:'Atacante Um', grupo:'A', posicao:'Centre-Forward',numero:9, foto:null},
  {id:5, nome:'Atacante Dois',grupo:'A',posicao:'Left Winger',  numero:11,foto:null}
];
aplicarFormacao('4-3-3');
function _nomes(){
  return _els['lista'].filhos.map(function(c){
    var m = /<strong[^>]*>([^<]*)</.exec(c.innerHTML); return m ? m[1] : '?'; });
}
var saida = {};
renderElenco();
saida.sem_filtro = _nomes().length;

// A vaga do goleiro: a lista tem que sobrar só o goleiro.
var iGol = -1;
SLOTS.forEach(function(s, i){ if (s.g === 'G' && iGol < 0) iGol = i; });
escolherVaga(iGol);
saida.na_vaga_de_goleiro = _nomes();
saida.primeiro_na_vaga = _nomes()[0];
saida.aviso = _els['vagaAviso'].textContent;

// A VAGA DE ATAQUE é o caso que distingue ordenar de não ordenar.
// Na ordem natural o goleiro vem primeiro (G, D, M, A). Se a vaga não
// ordenasse, o atacante continuaria lá embaixo — e o teste do goleiro não via
// diferença nenhuma, porque ele já era o primeiro de qualquer jeito.
var iAta = -1;
SLOTS.forEach(function(s, i){ if (s.g === 'A' && iAta < 0) iAta = i; });
escolherVaga(iGol);            // desfaz a do goleiro
escolherVaga(iAta);
saida.primeiro_na_vaga_de_ataque = _nomes()[0];
saida.total_na_vaga_de_ataque = _nomes().length;
saida.ordem_na_vaga_de_ataque = _nomes();
escolherVaga(iAta);            // desfaz
saida.primeiro_sem_vaga = _nomes()[0];

// Tocar num jogador com a vaga escolhida escala ele ali.
escolherVaga(iGol);
escalarNaVaga(1);
saida.escalado_no_gol = SLOTS[iGol].id;
saida.vaga_apos_escalar = VAGA;

// Busca por nome, sem vaga escolhida.
_els['busca'].value = 'atacante';
renderElenco();
saida.busca_atacante = _nomes().length;
_els['busca'].value = '';

// Chip de setor.
filtrarGrupo('D');
saida.chip_defesa = _nomes();
filtrarGrupo('D');   // de novo: desliga
saida.chip_desligado = _nomes().length;
console.log(JSON.stringify(saida));
"""
    script = MOLDE.replace("__JS__", js)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        caminho = f.name
    try:
        r = subprocess.run([node, caminho], capture_output=True, text=True,
                           timeout=40)
    except (FileNotFoundError, OSError):
        print("PULAR: o Node nao esta instalado nesta maquina")
        return 1
    finally:
        os.unlink(caminho)

    if r.returncode != 0:
        falhas.append("o JS do campinho quebrou ao rodar: "
                      + (r.stderr or "")[-400:])
    else:
        s = json.loads(r.stdout.strip().splitlines()[-1])
        conferir("sem filtro, o elenco inteiro aparece", s["sem_filtro"], 5)
        # A VAGA SUGERE, NÃO LIMITA. O Vini cortou a primeira versão: "se eu
        # quiser colocar um DEF lá, eu posso; o filtro não pode ser
        # limitante". Zagueiro improvisado de volante e lateral subindo na ala
        # são comuns demais para a lista escondê-los.
        conferir("na vaga de goleiro, o goleiro vem PRIMEIRO",
                 s["primeiro_na_vaga"], "Goleiro Um")
        conferir("mas o elenco inteiro continua alcançável",
                 len(s["na_vaga_de_goleiro"]), 5)
        # A vaga de ataque prova que a ORDEM muda: sem ela, o goleiro seria o
        # primeiro (a ordem natural é G, D, M, A).
        conferir("na vaga de ataque, o atacante sobe para o topo",
                 s["primeiro_na_vaga_de_ataque"], "Atacante Um")
        conferir("e ninguém é escondido por isso",
                 s["total_na_vaga_de_ataque"], 5)
        # A ORDEM INTEIRA, e não só o primeiro. Conferir só o topo deixava
        # passar um comparador meio quebrado: ele ainda punha um atacante na
        # frente, e o resto embaralhava sem ninguém ver.
        conferir("os dois atacantes vêm primeiro, e o resto na ordem natural",
                 s["ordem_na_vaga_de_ataque"],
                 ["Atacante Um", "Atacante Dois", "Goleiro Um",
                  "Zagueiro Um", "Meia Um"])
        conferir("desfeita a vaga, volta a ordem natural",
                 s["primeiro_sem_vaga"], "Goleiro Um")
        ok("GOL" in (s["aviso"] or ""),
           "a tela não diz de que posição é a vaga escolhida — sem isso o "
           "filtro encolhe a lista e ninguém sabe por quê")
        conferir("tocar num jogador com a vaga escolhida escala ele",
                 s["escalado_no_gol"], 1)
        conferir("e a vaga se desfaz depois de preenchida",
                 s["vaga_apos_escalar"], None)
        conferir("a busca por nome filtra", s["busca_atacante"], 2)
        conferir("o chip de setor filtra", s["chip_defesa"], ["Zagueiro Um"])
        conferir("e tocar no mesmo chip desliga o filtro",
                 s["chip_desligado"], 5)

    for f_ in falhas:
        print("  ✗", f_)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ ficha do jogador e campinho: somas conferem, vaga filtra a lista")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
