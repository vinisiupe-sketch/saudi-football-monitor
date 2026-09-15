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
     "capitao": True, "posicao": "F", "rodada": "4", "status": "FT"},
    {"fixture_id": 2, "minutos": 45, "titular": False, "gols": 0,
     "assistencias": 0, "amarelos": 0, "vermelhos": 1, "nota": 5.8,
     "clube": "Al Nassr", "data": "2026-09-01", "casa": "Al Hilal",
     "fora": "Al Nassr", "em_casa": False, "adversario": "Al Hilal",
     "capitao": False, "posicao": "F", "rodada": "3", "status": "FT"},
    # Partida SEM nota: acontece quando a API não publica. A média não pode
    # contá-la como zero.
    {"fixture_id": 3, "minutos": 67, "titular": True, "gols": 1,
     "assistencias": 0, "amarelos": 0, "vermelhos": 0, "nota": None,
     "clube": "Al Nassr", "data": "2026-08-26", "casa": "Al Nassr",
     "fora": "Abha", "em_casa": True, "adversario": "Abha",
     "capitao": False, "posicao": "F", "rodada": "2", "status": "FT"},
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

    # E o Campinho tem tudo que saiu de lá.
    for preciso in ("salvarEscalacao", "renderCampo", "aplicarFormacao",
                    'id="campo"', "baixarArte", "voltarEscalacao"):
        ok(preciso in CAMPINHO,
           f"'{preciso}' não chegou na guia Campinho — ela precisa fazer tudo "
           "que a de Elencos fazia com o campo")
    ok('@app.get("/campinho"' in FONTE, "sumiu a rota da guia Campinho")
    ok('("/campinho"' in FONTE, "a guia Campinho não está no menu")

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
saida.aviso = _els['vagaAviso'].textContent;

// Tocar num jogador com a vaga escolhida escala ele ali.
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
        conferir("na vaga de goleiro sobra só o goleiro",
                 s["na_vaga_de_goleiro"], ["Goleiro Um"])
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
