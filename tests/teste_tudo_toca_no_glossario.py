"""Toda tela que mostra jogador ou clube passa pelo glossário.

A ORDEM DELE (18/09/26)
    "O glossário não tem que responder sem nada. Ele é o grande unificador de
     links/bases. Preciso que entenda isso. Ele é o local onde vai conseguir
     fazer o de-para pra qualquer uma das 3 bases principais. Passe a limpo
     todas as guias. Todas as que tiverem jogadores/clubes precisa fazer link
     com o glossário, que aponta nome correto, fotos, clube correto (! a pouco
     vi um jogador no lesões com escudo do Al Nassr de dubai, isso a essa
     altura é uma vergonha). Passei horas conectando os nomes e criando um ID
     próprio pra unificar as três bases. Passe TUDO a limpo. Tudo tem que
     tocar no glossário em algum nível."

POR QUE UM TESTE, E NÃO UMA VARRIDA
    Porque eu já passei a limpo três vezes. Consertei o escudo por nome na
    ficha do jogador em setembro, e ele reapareceu na guia de Lesões. Liguei o
    glossário nos Elencos, e a caixa de busca de lesão continuou lendo a
    tabela antiga. Uma varrida conserta o que existe hoje; o que impede a
    quarta vez é uma regra que falha sozinha.

COMO ELE FUNCIONA
    Lê o main.py com a árvore sintática, acha toda rota que devolve campo de
    jogador ou de clube, e segue as chamadas dela — inclusive as funções
    passadas como ARGUMENTO, que foi por onde a primeira versão desta
    varredura deixou escapar metade do app, porque `asyncio.to_thread(f)` não
    é uma chamada a `f`.

    Rota que entrega nome, foto ou clube e não encosta no glossário em nível
    nenhum é falha. As exceções estão listadas aqui embaixo, uma a uma, com o
    motivo escrito — e a lista é curta de propósito: ela é a confissão do que
    ainda não passa pela porta.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ARVORE = ast.parse(FONTE)
FUNCOES = {n.name: n for n in ast.walk(ARVORE)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


# Os campos que denunciam uma tela de pessoa ou de clube.
CAMPOS = ("nome", "jogador", "player_name", "foto", "clube", "escudo",
          "nome_curto", "posicao", "nacionalidade")

# ── AS EXCEÇÕES, UMA A UMA E COM MOTIVO ─────────────────────────────────────
#
# Cada linha aqui é uma rota que entrega campo de gente ou de clube SEM passar
# pelo glossário. Nenhuma entra por conveniência: ou o "nome" não é de
# jogador, ou a rota é o próprio laboratório do glossário, ou ela é a fonte
# crua que alimenta a comparação e precisa continuar crua para a comparação
# fazer sentido.
DISPENSADAS = {
    # "nome" que não é de jogador nenhum.
    "/api/eu": "o nome é o DELE, do usuário logado",
    "/api/cadastrar": "nome de quem está criando conta",
    "/api/arbitragem/nome": "árbitro, e não jogador — o glossário é de atletas",
    "/api/clipe/pendentes": "nome do arquivo de clipe",
    "/api/clubes/extra": "cadastro MANUAL de escudo de clube; é ele escrevendo",
    "/api/jogador/apelido": "grava um apelido NO glossário; é a escrita, não a "
                            "leitura",

    # O próprio laboratório. Fazer ele consultar a si mesmo pela porta de
    # leitura esconderia justamente o que ele foi lá conferir: o dado cru de
    # cada fonte, lado a lado.
    "/api/glossario-lab/fontes/{fonte}/buscar": "é a busca NA fonte crua, para "
                                                "ele vincular",
    "/api/glossario-lab/nomes": "as grafias cruas de cada base",
    "/api/diag/nomes-arabes": "mede as grafias do próprio glossário",
    "/api/diag/nomes": "diagnóstico das grafias cruas",
    "/api/diag/elos": "diagnóstico dos vínculos entre bases",

    # Clube, e pelo ID.
    "/api/elencos/times": "lista de CLUBES, e o escudo sai do id do clube na "
                          "URL — nunca de casamento por nome",

    # Diagnósticos que existem para mostrar o cru.
    "/api/diag/congelado": "mostra o elenco congelado como ele está no banco",
    "/api/diag/escalacao": "mostra o que a API-Football respondeu, cru",
    "/api/diag/pendurado": "mostra a contagem de cartões por dentro",

    # Fonte crua de comparação.
    "/api/af-window-transfers": "a janela da API-Football, crua, para comparar "
                                "com a nossa",
    "/api/escalacao-pdf": "a súmula em PDF: o nome é o que está impresso no "
                          "papel, e o cruzamento com o elenco é feito pelo "
                          "matchsheet, que tem teste próprio",
}


def _rotas():
    achadas = []
    for n in ARVORE.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ("get", "post") and d.args
                    and isinstance(d.args[0], ast.Constant)):
                achadas.append((d.args[0].value, n.name))
    return achadas


def _mapear():
    """Uma passada só: quem cada função cita, e quem fala com o glossário.

    A PRIMEIRA VERSÃO ANDAVA A ÁRVORE A CADA VISITA e o teste levava vinte
    segundos — num arquivo de vinte mil linhas, `ast.walk` dentro de recursão
    é quadrático. Pior: ele estourou o tempo no meio de uma bateria de mutação
    e deixou um defeito plantado no código, que só não foi para o ar porque a
    rodada seguinte o acusou.

    Aqui o grafo é montado UMA vez e depois só se caminha por ele.
    """
    cita, fala = {}, set()
    for nome, no in FUNCOES.items():
        vizinhos = set()
        for n in ast.walk(no):
            if isinstance(n, ast.Name):
                vizinhos.add(n.id)
                # SEGUE TAMBÉM O QUE É PASSADO COMO ARGUMENTO. A primeira
                # versão desta varredura só seguia chamadas diretas e disse
                # que a guia de Lesões não tocava no glossário — mentira: ela
                # chama `asyncio.to_thread(_lesoes_do_tm)`, e o
                # `_lesoes_do_tm` é um ARGUMENTO, não uma chamada. Metade do
                # app saiu como falso positivo e eu quase fui consertar o que
                # já estava certo.
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "glossario"):
                fala.add(nome)
        cita[nome] = vizinhos
    return cita, fala


CITA, FALA_COM_GLOSSARIO = _mapear()


def _toca_no_glossario(nome):
    """Esta função, ou alguma que ela alcança, fala com o glossário?"""
    pilha, visto = [nome], set()
    while pilha:
        atual = pilha.pop()
        if atual in visto or atual not in CITA:
            continue
        visto.add(atual)
        if atual in FALA_COM_GLOSSARIO:
            return {"GLOSSARIO"}
        pilha.extend(CITA[atual])
    return set()


LINHAS = FONTE.split("\n")


def _corpo_de(nome: str) -> str:
    """O texto da função, por linha.

    O `ast.get_source_segment` relê o arquivo inteiro a cada chamada, e num
    main.py de vinte mil linhas isso são duzentas releituras — foi metade dos
    vinte segundos que este teste levava. O nó já sabe onde começa e onde
    acaba.
    """
    n = FUNCOES[nome]
    return "\n".join(LINHAS[n.lineno - 1:n.end_lineno])


vistoriadas, sem_glossario = 0, []
for url, fn in sorted(_rotas()):
    if not url.startswith("/api/"):
        continue
    corpo = _corpo_de(fn)
    if not any(f'"{c}"' in corpo for c in CAMPOS):
        continue
    vistoriadas += 1
    if "GLOSSARIO" in _toca_no_glossario(fn):
        # Rota que passou a tocar no glossário não pode continuar na lista de
        # dispensadas: lista de exceção que não encolhe vira decoração.
        ok(url not in DISPENSADAS,
           f"{url} agora toca no glossário e continua na lista de dispensadas "
           f"— tire de lá, senão a lista deixa de dizer o que ainda falta")
        continue
    if url in DISPENSADAS:
        continue
    sem_glossario.append(url)

ok(not sem_glossario,
   "estas rotas entregam jogador ou clube SEM passar pelo glossário: "
   + ", ".join(sem_glossario) +
   ". Ou elas passam a consultar o glossário, ou entram na lista de "
   "dispensadas com o motivo escrito — o que não pode é ficarem no meio, "
   "que é onde o Al Nasr de Dubai morou por dois meses")

ok(vistoriadas >= 20,
   f"olhei só {vistoriadas} rotas com campo de gente; a varredura está "
   f"pegando pouca coisa e passaria verde à toa")

# E AS DISPENSADAS TÊM DE EXISTIR. Uma rota que sumiu do app e continua na
# lista faz a lista parecer maior do que a dívida é.
_urls = {u for u, _ in _rotas()}
for url in DISPENSADAS:
    ok(url in _urls,
       f"a rota dispensada {url} não existe mais no app; tire da lista")


# ─────────────────────────────────────────────────────────────────────────
# CONTATO NÃO É USO — as rotas ligadas hoje, conferidas pelo que fazem
# ─────────────────────────────────────────────────────────────────────────
# A VARREDURA ACIMA PROVA QUE A ROTA ENCOSTA NO GLOSSÁRIO, e só isso. Plantei
# `f = {} if True else glossario.quem(...)` na guia de Pendurados e ela passou
# verde: a chamada continuava escrita na árvore, morta. É o limite de qualquer
# leitura estática, e fingir o contrário seria pior que não ter o teste.
#
# Então, para as rotas que passaram a consultar o glossário nesta virada, eu
# confiro o que importa: que o valor resolvido CHEGA no campo que vai à tela.
# Consultar e jogar fora é o mesmo que não consultar, com um ar melhor.
USOS = (
    ("api_pendurados", 'd["jogador"] = f.get("nome")',
     "a guia de Pendurados consulta o glossário e não usa o nome que ele "
     "devolve — o cartão continuaria mandando na grafia"),
    ("api_pendurados", 'd["foto"] = f.get("foto")',
     "a guia de Pendurados não leva a foto do glossário"),
    ("api_ausencias_af", '"jogador": _g.get("nome") or nome',
     "a comparação de ausências voltou a mostrar a transliteração da "
     "API-Football ao lado das telas que mostram a grafia dele"),
    ("api_ausencias_af", '"foto": _g.get("foto") or jogador.get("photo")',
     "as ausências não usam a foto do glossário"),
    ("api_disciplina", 'd["nome"] = f.get("nome")',
     "a guia de Disciplina consulta o glossário e ignora a resposta"),
)
for fn, trecho, queixa in USOS:
    ok(fn in FUNCOES, f"sumiu a rota {fn}")
    if fn in FUNCOES:
        corpo = "\n".join(l for l in _corpo_de(fn).split("\n")
                          if not l.strip().startswith("#"))
        ok(trecho in corpo, queixa)


# ─────────────────────────────────────────────────────────────────────────
# A PORTA ÚNICA DO DE-PARA
# ─────────────────────────────────────────────────────────────────────────
import types                                              # noqa: E402

if "psycopg2" not in sys.modules:
    _t = types.ModuleType("psycopg2")
    _t.extras = types.ModuleType("psycopg2.extras")
    _t.extras.RealDictCursor = object
    _t.Error = Exception
    sys.modules["psycopg2"] = _t
    sys.modules["psycopg2.extras"] = _t.extras

import database                                           # noqa: E402
import glossario                                          # noqa: E402

FICHAS = [
    {"id": 1, "spl_id": "s1", "af_id": 101, "tm_id": "201",
     "nome_principal": "Salem Al-Dawsari", "nome_curto": "Al-Dawsari",
     "nome_ar": "سالم الدوسري", "clube": "Al Hilal", "posicao": "Ponta",
     "nacionalidade": "Arábia Saudita", "foto": "spl/salem.png"},
    {"id": 2, "spl_id": "s2", "af_id": 102, "tm_id": "202",
     "nome_principal": "Cristiano Ronaldo", "nome_curto": "Ronaldo",
     "clube": "Al Nassr", "posicao": "Atacante",
     "nacionalidade": "Portugal", "foto": "spl/cr.png"},
]
database.glossario_completo = lambda: ([dict(f) for f in FICHAS], [])
database.valor_de_ajuste = lambda c: "melhor disponível"
glossario.recarregar()

# QUATRO CHAVES, UMA PERGUNTA. É isto que ele quis dizer com "o grande
# unificador": quem tem QUALQUER uma das três bases na mão consegue perguntar.
ok(glossario.quem(af_id=101).get("nome") == "Salem Al-Dawsari",
   "o de-para pelo id da API-Football parou de responder")
ok(glossario.quem(spl_id="s1").get("nome") == "Salem Al-Dawsari",
   "o de-para pelo id da SPL parou de responder")
ok(glossario.quem(tm_id="201").get("nome") == "Salem Al-Dawsari",
   "o de-para pelo id do Transfermarkt parou de responder")
ok(glossario.quem(nome="Salem Al-Dawsari").get("nome") == "Salem Al-Dawsari",
   "o de-para por nome parou de responder")
# A foto sai com o endereço completo da SPL: a `ficha` completa o prefixo,
# e é assim que ela chega na tela. Confiro o arquivo, e não a URL inteira.
ok("salem.png" in (glossario.quem(af_id=999,
                                  nome="Salem Al-Dawsari").get("foto") or ""),
   "com um id que não existe, a pergunta devia cair no nome — e ela devolve a "
   "FICHA, com foto, que é o que as telas precisam")
ok(glossario.quem() == {} and glossario.quem(nome="Ninguém") == {},
   "a porta respondeu por quem ela não conhece; adivinhar identidade é o que "
   "este projeto inteiro saiu de dentro")

# A ORDEM É A DA CONFIANÇA: identificador antes de nome.
ok(glossario.quem(af_id=102, nome="Salem Al-Dawsari").get("nome")
   == "Cristiano Ronaldo",
   "o NOME ganhou do id. Um id é um de-para que ele fez à mão; um nome é uma "
   "string que duas bases escrevem diferente — a ordem importa e é essa")

# ── O CLUBE DA LIGA, que é o que tranca o escudo errado ─────────────────
ok(glossario.e_da_liga("Al Nassr") and glossario.e_da_liga("Al Hilal"),
   "o glossário deixou de reconhecer os clubes que ele mesmo guarda. É essa "
   "resposta que impede a tabela mundial de emprestar o escudo do Al Nasr de "
   "Dubai para o Al-Nassr de Riade")
ok(not glossario.e_da_liga("Chelsea") and not glossario.e_da_liga(""),
   "o glossário passou a dizer que qualquer clube é da liga; aí o lesionado "
   "que joga no exterior fica sem escudo nenhum")

# ── A BUSCA sai do glossário, e não da tabela antiga ────────────────────
_achados = glossario.procurar("dawsari")
ok(len(_achados) == 1 and "salem.png" in (_achados[0].get("foto") or ""),
   f"a busca por pedaço de nome devolveu "
   f"{[a.get('nome') for a in _achados]}; ela tem de sair do "
   f"glossário e já vir com a ficha, para a lista mostrar o que o card vai "
   f"mostrar depois")
ok(glossario.procurar("a") == [],
   "uma letra só devolveu gente; a caixa de busca dispararia a cada tecla")

_busca = FONTE[FONTE.index("async def api_injuries_buscar_jogador("):]
_busca = _busca[:_busca.index("\n@app.")]
_sem_comentario = "\n".join(l for l in _busca.split("\n")
                            if not l.strip().startswith("#"))
ok("glossario.procurar" in _sem_comentario,
   "a busca de jogador do cadastro de lesão voltou a ler só a tabela antiga. "
   "Ele auditou seiscentas fichas à mão e a caixa oferecia a base velha")
ok(_sem_comentario.index("glossario.procurar")
   < _sem_comentario.index("listar_jogadores"),
   "a tabela antiga voltou a responder ANTES do glossário")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print(f"✅ {vistoriadas} rotas com campo de gente vistoriadas, "
      f"{len(DISPENSADAS)} dispensadas com motivo, e o de-para responde pelas "
      f"quatro chaves")
