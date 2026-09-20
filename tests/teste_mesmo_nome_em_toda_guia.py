"""O mesmo jogador, o mesmo nome — em lesões, pendurados, mercado e elenco.

O PEDIDO, depois de eu consertar o sintoma três vezes (20/09/26)
    "O exemplo do escudo foi apenas uma forma de ilustrar o problema. O que eu
     quero corrigir é a falta de padronização entre todas as guias. Se um
     jogador aparece em lesões, pendurados, notícias, mercado, elenco ou
     qualquer outra guia, o nome exibido precisa ser exatamente o mesmo em
     todas elas. Não quero que cada guia use o nome vindo diretamente da fonte
     que alimentou aquele dado. (...) Quero que o star schema seja realmente o
     centro da aplicação."

POR QUE ESTE ARQUIVO EXISTE, SENDO QUE JÁ HÁ UM TESTE DE GLOSSÁRIO
    Porque o outro lê o CÓDIGO e prova que a rota encosta no glossário. Este
    aqui olha o DADO e prova outra coisa, que é a que ele pediu: que o nome
    que sai é o mesmo. Plantei `f = {} if True else glossario.quem(...)` e o
    teste estático passou verde — a chamada continuava escrita, morta.

    Três guias guardam o nome como TEXTO na própria tabela: mercado
    (`negociacao.jogador`), lesões (`injuries.player_name`) e pendurados
    (`cartao.jogador`). Cada uma nasceu de uma fonte diferente e escreve a
    grafia daquela fonte. Consultar a dimensão e exibir o texto guardado é o
    defeito, e ele é invisível no código: a consulta está lá.

O QUE ESTE ARQUIVO VIGIA
    1. Que a medição ACUSA quando duas guias mostram nomes diferentes para o
       mesmo `jogador_id_interno` — se ela não acusar, não serve de nada.
    2. Que ela distingue "não identificado" de "identificado e divergente".
    3. Que as guias que guardam texto realmente trocam pelo nome da dimensão.
"""
import os
import sys
import types

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

import database                                           # noqa: E402
import glossario                                          # noqa: E402

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# ─────────────────────────────────────────────────────────────────────────
# O GLOSSÁRIO DE MENTIRA — e as três guias com as grafias DELAS
# ─────────────────────────────────────────────────────────────────────────
FICHAS = [
    {"id": 1, "spl_id": "s1", "af_id": 101, "tm_id": "201",
     "nome_principal": "Yassine Bounou", "nome_curto": "Bono",
     "clube": "Al Hilal", "posicao": "Goleiro", "foto": "f1.png"},
    {"id": 2, "spl_id": "s2", "af_id": 102, "tm_id": "202",
     "nome_principal": "Mohammed Meïté", "nome_curto": "Meïté",
     "clube": "Al Hilal", "posicao": "Atacante", "foto": "f2.png"},
]
GRAFIAS = [
    # As grafias que cada fonte usa para a MESMA pessoa. É por elas que a
    # medição consegue resolver o texto guardado até o id interno.
    {"jogador_id": 1, "fonte": "noticia", "idioma": "lat", "tipo": "variacao",
     "nome": "Yassine Bono", "nome_normalizado": "", "confirmado": True},
    {"jogador_id": 2, "fonte": "noticia", "idioma": "lat", "tipo": "variacao",
     "nome": "Kader Meite", "nome_normalizado": "", "confirmado": True},
]
for g in GRAFIAS:
    g["nome_normalizado"] = glossario._chave(g["nome"])

database.glossario_completo = lambda: ([dict(f) for f in FICHAS],
                                       [dict(g) for g in GRAFIAS])
database.valor_de_ajuste = lambda c: "melhor disponível"
glossario.recarregar()

# O CANÔNICO, para comparar contra.
CANONICO = {f["spl_id"]: glossario.ficha(
    glossario.por_spl_id(f["spl_id"])).get("nome") for f in FICHAS}
ok(CANONICO["s1"] == "Yassine Bounou",
   f"o glossário de teste não está montado: {CANONICO}")


def _medir(lesoes, cartoes, mercado, lesoes_resolve=True):
    """Roda a medição de verdade, recortada do main.py.

    Recorto e executo em vez de reescrever a lógica aqui: se eu refizesse a
    conta, estaria conferindo a minha cópia contra ela mesma — o engano que
    esta suíte já cometeu quatro vezes.
    """
    i = FONTE.index("    def _juntar():")
    corpo = FONTE[i:FONTE.index("\n    linhas = [", i)]
    corpo = "\n".join(l[4:] if l.startswith("    ") else l
                      for l in corpo.split("\n"))
    database.get_injuries = lambda incluir=False: lesoes
    database.cartoes_da_temporada = lambda t: cartoes
    database.negociacoes = lambda a=60, b=45: mercado
    # A MEDIÇÃO AGORA APLICA A RESOLUÇÃO DE CADA GUIA, e não lê o texto cru.
    # Então o ambiente precisa das duas funções que as guias usam: o contexto
    # de elenco e o identificador. Eles entram como o app os tem — o
    # `_identificar_jogador` de verdade seria melhor, mas ele puxa meio
    # main.py; aqui basta que a medição CHAME quem resolve, e o que se mede é
    # se ela compara o exibido.
    amb = {"glossario": glossario, "_af_temporada_corrente": lambda: 2026,
           "_contexto_de_elenco": lambda: {},
           # `lesoes_resolve=False` simula a guia cuja resolução é mais
           # FRACA que a da medição: ela não acha o jogador e exibe o nome
           # cru, enquanto o elenco exibe o da dimensão. É essa a divergência
           # que interessa agora — a guia que vaza a grafia da fonte para a
           # tela. Quando NINGUÉM acha, o caso é outro: vira "não
           # identificado", que é a terceira seção do relatório.
           "_identificar_jogador": (
               (lambda nome, clube, ctx:
                glossario.quem(nome=nome, clube=clube) or {})
               if lesoes_resolve else (lambda nome, clube, ctx: {}))}
    exec(corpo, amb)
    por_id, desconhecidos, _grafias = amb["_juntar"]()
    return por_id, desconhecidos


# ── 1. A MEDIÇÃO ACUSA A DIVERGÊNCIA ────────────────────────────────────
#
# O cenário é o real: cada guia guardou a grafia da fonte que a alimentou.
# A guia de Lesões não resolve; as outras resolvem. Ela exibe "Yassine Bono",
# o elenco exibe "Yassine Bounou", e a MESMA pessoa aparece com dois nomes.
por_id, desconhecidos = _medir(
    lesoes=[{"player_name": "Yassine Bono", "club": "Al Hilal"}],
    cartoes=[{"jogador": "Kader Meite", "jogador_id": 102,
              "clube": "Al Hilal"}],
    mercado=[{"jogador": "Yassine Bono", "spl_id": "s1", "af_id": 101}],
    lesoes_resolve=False)

divergentes = {k: v for k, v in por_id.items() if len(v["vistos"]) > 1}
ok(len(divergentes) == 1,
   f"a medição achou {len(divergentes)} divergências e o cenário tem uma: a "
   f"guia de Lesões exibe 'Yassine Bono' e o elenco exibe 'Yassine Bounou'. "
   f"Se ela não acusa isso, ela não serve para nada — e foi para eu parar de "
   f"apontar o lugar errado que ela existe")
# E O MERCADO E OS PENDURADOS, QUE RESOLVEM, NÃO PODEM APARECER: eles guardam
# a grafia da fonte na tabela e exibem a da dimensão. Acusá-los seria alarme
# falso — foi o que a primeira versão desta medição fez com 108 linhas.
# Elas PODEM aparecer — mas só sob o nome canônico, que é onde estar é
# elogio. O que não pode é uma guia que traduz aparecer sob a grafia da fonte.
_erradas = {g for d in divergentes.values()
            for nome, guias in d["vistos"].items() if nome != d["canonico"]
            for g in guias}
ok(_erradas == {"lesões"},
   f"as guias exibindo grafia que não é a da dimensão são {_erradas}; só a de "
   f"Lesões deveria estar, porque só ela não resolveu neste cenário. Acusar "
   f"quem traduz é alarme falso — foi o que a primeira versão desta medição "
   f"fez em 108 linhas, e foi por isso que o número assustou à toa")

_bono = por_id.get("s1") or {}
ok(_bono.get("canonico") == "Yassine Bounou",
   f"o nome canônico do Bounou saiu {_bono.get('canonico')!r}; ele tem de vir "
   f"da DIM_JOGADOR, que é a referência contra a qual tudo é comparado")
ok(set(_bono.get("vistos", {}).keys()) == {"Yassine Bounou", "Yassine Bono"},
   f"as grafias vistas do Bounou saíram {set(_bono.get('vistos', {}))}")
ok(_bono.get("vistos", {}).get("Yassine Bono") == {"lesões"},
   f"a medição não diz QUAIS guias mostram a grafia divergente: "
   f"{_bono.get('vistos', {}).get('Yassine Bono')}. Sem isso ela vira um "
   f"número sem endereço, e eu volto a consertar por adivinhação")
ok("elenco" in (_bono.get("vistos", {}).get("Yassine Bounou") or set()),
   "a medição perdeu o elenco como referência")

# ── 2. TUDO PADRONIZADO NÃO ACUSA NADA ──────────────────────────────────
por_id2, _ = _medir(
    lesoes=[{"player_name": "Yassine Bounou", "club": "Al Hilal"}],
    cartoes=[{"jogador": "Mohammed Meïté", "jogador_id": 102,
              "clube": "Al Hilal"}],
    mercado=[{"jogador": "Yassine Bounou", "spl_id": "s1", "af_id": 101}])
ok(not [v for v in por_id2.values() if len(v["vistos"]) > 1],
   f"com todas as guias mostrando o nome da dimensão, a medição ainda acusou "
   f"divergência: {[(k, list(v['vistos'])) for k, v in por_id2.items()]}. "
   f"Alarme falso treina a gente a ignorar o alarme")

# ── 3. NÃO IDENTIFICADO É OUTRA COISA, e não some calado ────────────────
por_id3, desc3 = _medir(
    lesoes=[{"player_name": "Jogador Do Liverpool", "club": "Liverpool"}],
    cartoes=[], mercado=[])
ok(not [v for v in por_id3.values() if len(v["vistos"]) > 1],
   "quem o glossário não conhece entrou na contagem de divergência")
ok("lesões" in desc3 and "Jogador Do Liverpool" in desc3["lesões"],
   f"o nome que o glossário não identificou sumiu do relatório: {desc3}. "
   f"'Não identificado' e 'padronizado' são coisas diferentes: o primeiro é "
   f"jogador de fora da liga (certo) ou grafia que falta no glossário (a "
   f"arrumar), e sem aparecer ninguém sabe qual dos dois")


# ─────────────────────────────────────────────────────────────────────────
# 4. AS GUIAS QUE GUARDAM TEXTO TROCAM PELO NOME DA DIMENSÃO
# ─────────────────────────────────────────────────────────────────────────
def _sem_comentario(txt, marca="#"):
    return "\n".join(l for l in txt.split("\n")
                     if not l.strip().startswith(marca))


_merc = FONTE[FONTE.index("async def api_mercado("):]
_merc = _sem_comentario(_merc[:_merc.index("\n@app.")])
ok("glossario.quem(" in _merc,
   "a guia de Mercado parou de perguntar à dimensão")
ok('c["jogador"] = f["nome"]' in _merc,
   "a guia de Mercado consulta o glossário e continua exibindo o nome que a "
   "extração guardou no dia em que o card nasceu — a grafia da notícia. Era "
   "o caso mais gritante: ela já usava a resposta para a FOTO e ignorava o "
   "nome, dois campos da mesma pessoa vindos de autoridades diferentes no "
   "mesmo card")

_les = FONTE[FONTE.index("async def _page_lesoes_impl("):]
_les = _sem_comentario(_les[:_les.index("\n@app.")])
ok('player = (do_elenco.get("nome") or "").strip() or bruto' in _les,
   "a guia de Lesões voltou a exibir o `player_name` da notícia em vez do "
   "nome resolvido")

_pend = FONTE[FONTE.index("async def api_pendurados("):]
_pend = _sem_comentario(_pend[:_pend.index("\n@app.")])
ok('d["jogador"] = f.get("nome")' in _pend,
   "a guia de Pendurados voltou a exibir o nome que veio do cartão")

# ── A REFERÊNCIA É A DIMENSÃO, E A ORDEM É O QUE SUSTENTA ISSO ──────────
#
# Plantei `canonico = nome` (o nome da guia) no lugar de `f.get("nome")` (o da
# dimensão) e NADA falhou. Não é buraco do teste: é mutante equivalente. O
# elenco é medido primeiro e o nome que ele exibe JÁ é o da dimensão, então os
# dois caminhos dão no mesmo valor.
#
# Só que ele deixa de dar no mesmo no dia em que alguém trocar a ordem ou tirar
# o elenco da conta — e aí a referência passa a ser "o primeiro que chegou",
# que é exatamente o modelo errado. Então é a invariante que eu guardo aqui, em
# vez de fingir que a conferência de valor cobriria isso.
_j = FONTE[FONTE.index("    def _juntar():"):]
_j = _sem_comentario(_j[:_j.index("\n    linhas = [")])
ok('"canonico": f.get("nome")' in _j,
   "a referência da comparação deixou de sair da DIM_JOGADOR. Ela vira 'o "
   "nome da primeira guia que chegou', e aí a medição nunca acusa nada")
ok(_j.index('_anotar("elenco"') < _j.index('_anotar("lesões"'),
   "o elenco deixou de ser medido primeiro. Ele é a referência — a guia que "
   "exibe a dimensão sem intermediário — e medir depois das outras faz a "
   "comparação depender de quem chegou antes")

ok('@app.get("/api/diag/padronizacao"' in FONTE,
   "sumiu a página que mede a padronização. É ela que responde à pergunta "
   "dele com dado em vez de promessa")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ a medição acusa nome divergente entre guias, e as três que guardam "
      "texto usam a dimensão")
