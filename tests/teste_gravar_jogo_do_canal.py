"""
O botão "Gravar" tem que aparecer para o jogo que está no ar AGORA.

O QUE ACONTECEU (12/09/26)
    O Vini: "não está aparecendo a opção de gravar o jogo do Al Nassr que está
    acontecendo neste momento". O canal estava transmitindo, o gravador estava
    ligado, e a tela dizia "O canal não está transmitindo nada agora".

    A guia esconde as transmissões que não casam com o calendário da Saudi Pro
    League — o canal cobre outras competições, e a guia é sobre o campeonato.
    Escondidas, nunca descartadas: eu tinha escrito um botão "+N fora da liga
    saudita" e um comentário dizendo que "esconder sem porta de saída é como
    se perde uma final".

    E então escondi sem porta de saída. O `return` que desiste quando não
    sobrou nenhum jogo visível vinha ANTES do trecho que desenha aquele botão.
    Resultado: a escapatória só existia quando havia OUTRO jogo reconhecido na
    tela — ou seja, nunca no caso em que ela é a única saída. Um jogo só, não
    reconhecido, e a tela ficava muda.

POR QUE O TESTE QUE EU JÁ TINHA NÃO PEGOU
    Porque ele conferia o SERVIDOR. A rota devolvia `escondidas: 1`
    corretamente, a asserção passava, e o dado chegava à tela — onde ninguém
    desenhava nada com ele. Eu testei que a informação existia, não que ela
    era ALCANÇÁVEL.

    Por isso este arquivo EXECUTA a função no Node, com um DOM de mentira, e
    pergunta o que apareceu na tela. É a única forma de responder "dá para
    clicar?", que é a pergunta que o Vini fez.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo_py(nome: str) -> str:
    """O código-fonte de uma função Python do main.py."""
    import ast
    mod = ast.parse(FONTE)
    for n in ast.walk(mod):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == nome:
            return ast.get_source_segment(FONTE, n) or ""
    return ""


def _funcao_js(nome: str) -> str:
    """O corpo de uma função JavaScript escrita dentro do main.py.

    Recorta contando chaves, e não por expressão regular: o corpo tem chaves
    dentro de strings e de objetos, e um `}` no fim da linha não quer dizer
    fim de função.
    """
    i = FONTE.find("function " + nome + "(")
    if i < 0:
        return ""
    j = FONTE.find("{", i)
    nivel, k = 0, j
    while k < len(FONTE):
        if FONTE[k] == "{":
            nivel += 1
        elif FONTE[k] == "}":
            nivel -= 1
            if nivel == 0:
                return FONTE[i:k + 1]
        k += 1
    return ""


# O DOM de mentira é pequeno de propósito: ele responde só o que a função
# usa — createElement, appendChild, innerHTML, textContent — e no fim conta o
# que foi parar dentro do alvo. Um DOM completo traria comportamento que eu
# não controlo e faria o teste passar ou falhar por motivo errado.
MOLDE = r"""
function Elemento(tag) {
  this.tag = tag; this.filhos = []; this.style = {}; this.dataset = {};
  this.className = ''; this.textContent = ''; this._html = '';
  this.disabled = false; this.title = '';
}
Object.defineProperty(Elemento.prototype, 'innerHTML', {
  get: function () { return this._html; },
  set: function (v) { this._html = v; this.filhos = []; }
});
Elemento.prototype.appendChild = function (f) { this.filhos.push(f); return f; };
Elemento.prototype.querySelector = function () { return null; };
Elemento.prototype.querySelectorAll = function () { return []; };

var ALVO = new Elemento('div');
var TITULO = new Elemento('h2');
var document = {
  createElement: function (t) { return new Elemento(t); },
  getElementById: function (id) {
    if (id === 'disponiveis') return ALVO;
    if (id === 'tituloDisp') return TITULO;
    return null;
  }
};
function carregar() { RECARREGOU = true; }
// O onclick do "Gravar" é só guardado, nunca disparado aqui: o que este teste
// pergunta é se o botão EXISTE e está clicável.
function adicionarJogo() {}
function placarDoJogo(x) { var e = new Elemento('div'); e.textContent = x.titulo || ''; return e; }
function esc(t) { return String(t == null ? '' : t); }
var RECARREGOU = false;
var _verTodas = VER_TODAS;
var _escondidas = ESCONDIDAS;
var _semCalendario = SEM_CALENDARIO;

__FUNCOES__

pintarDisponiveis(DISPONIVEIS, LIVES, MAX, ONLINE);

// O que a tela mostra, na linguagem da pergunta: quantos botões de gravar
// existem, e se sobrou algum caminho para ver o que foi escondido.
function texto(e) {
  var t = (e._html || '') + ' ' + (e.textContent || '');
  e.filhos.forEach(function (f) { t += ' ' + texto(f); });
  return t;
}
function achar(e, saida) {
  if (e.tag === 'button') saida.push({classe: e.className, texto: e.textContent,
                                      desabilitado: !!e.disabled});
  e.filhos.forEach(function (f) { achar(f, saida); });
  return saida;
}
var botoes = achar(ALVO, []);
console.log(JSON.stringify({
  gravar: botoes.filter(function (b) { return b.texto === 'Gravar'; }).length,
  gravar_ativos: botoes.filter(function (b) {
    return b.texto === 'Gravar' && !b.desabilitado; }).length,
  ver_todas: botoes.filter(function (b) { return b.classe === 'ver-todas'; }).length,
  texto: texto(ALVO).replace(/\s+/g, ' ').trim()
}));
"""


def _rodar(disponiveis, lives, escondidas, ver_todas=False,
           online=True, maximo=4, sem_calendario="") -> dict:
    """Executa pintarDisponiveis de verdade e devolve o que apareceu na tela."""
    js = (MOLDE
          .replace("__FUNCOES__",
                   _funcao_js("pintarDisponiveis") + "\n"
                   + _funcao_js("botaoVerTodas") + "\n"
                   + _funcao_js("new_vazio"))
          .replace("SEM_CALENDARIO", json.dumps(sem_calendario))
          .replace("DISPONIVEIS", json.dumps(disponiveis))
          .replace("LIVES", json.dumps(lives))
          .replace("ESCONDIDAS", str(escondidas))
          .replace("VER_TODAS", "true" if ver_todas else "false")
          .replace("ONLINE", "true" if online else "false")
          .replace("MAX", str(maximo)))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        caminho = f.name
    try:
        r = subprocess.run(["node", caminho], capture_output=True, text=True,
                           timeout=30)
        if r.returncode != 0:
            return {"erro": (r.stderr or "")[-400:]}
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(caminho)


JOGO_DA_LIGA = {"id": "aaa", "titulo": "AL HILAL X AL NASSR", "da_liga": True,
                "jogo": {"casa": "Al Hilal", "fora": "Al Nassr"}}
JOGO_DE_FORA = {"id": "bbb", "titulo": "AL NASSR X ISTIKLOL — AFC",
                "da_liga": False, "jogo": None}


def testar():
    falhas.clear()

    ok(_funcao_js("pintarDisponiveis"), "não achei pintarDisponiveis no main.py")
    ok(_funcao_js("botaoVerTodas"),
       "sumiu botaoVerTodas. Enquanto ela vivia dentro de pintarDisponiveis, "
       "só era desenhada num dos dois caminhos — e não no que importava")

    # ── 1. O CASO DO AL NASSR ────────────────────────────────────────────
    # O canal transmite UM jogo, e ele não casou com o calendário da liga.
    # A lista visível fica vazia. Antes, a tela desistia aqui e dizia que o
    # canal não estava transmitindo nada — com o jogo no ar.
    r = _rodar(disponiveis=[], lives=[], escondidas=1)
    ok(not r.get("erro"), f"o JavaScript quebrou: {r.get('erro')}")
    ok(r.get("ver_todas") == 1,
       "com o único jogo do canal escondido pelo filtro, a tela NÃO oferece "
       "como vê-lo. É o caso do Al Nassr: jogo no ar, nenhum botão, e a "
       "escapatória que eu escrevi inalcançável justamente quando é a única")
    ok("não está transmitindo nada" not in r.get("texto", ""),
       "a tela afirma que o canal não está transmitindo nada quando o que eu "
       "sei é outra coisa: que nada casou com o calendário da liga. É uma "
       "afirmação sobre o canal feita a partir de uma falha de reconhecimento")
    ok("calendário da liga" in r.get("texto", ""),
       "a tela parou de explicar POR QUE não há nada para gravar. Sem o "
       "motivo, o Vini não sabe se é o canal, o gravador ou o filtro")

    # E o caminho tem que levar ao jogo: ao tocar, a tela recarrega pedindo
    # todas — e aí o botão Gravar aparece.
    r = _rodar(disponiveis=[JOGO_DE_FORA], lives=[], escondidas=0,
               ver_todas=True)
    ok(r.get("gravar") == 1,
       "com 'ver todas' ligado, o jogo de fora da liga continua sem botão de "
       "gravar — a porta de saída não leva a lugar nenhum")

    # ── 2. o caminho normal não pode ter regredido ───────────────────────
    r = _rodar(disponiveis=[JOGO_DA_LIGA], lives=[], escondidas=0)
    ok(r.get("gravar") == 1,
       "o jogo da liga perdeu o botão de gravar")
    ok(r.get("ver_todas") == 0,
       "apareceu 'ver todas' sem nada escondido")

    # Lista visível E escondidas: os dois têm que conviver. Este era o único
    # caminho em que o botão existia antes.
    r = _rodar(disponiveis=[JOGO_DA_LIGA], lives=[], escondidas=2)
    ok(r.get("gravar") == 1 and r.get("ver_todas") == 1,
       "com um jogo visível e outros escondidos, sumiu uma das duas coisas")

    # ── 3. o que já está gravando não reaparece na lista de escolher ─────
    r = _rodar(disponiveis=[JOGO_DA_LIGA], lives=[{"id": "aaa"}], escondidas=0)
    ok(r.get("gravar") == 0,
       "o jogo que já está sendo gravado voltou a aparecer como opção — dois "
       "botões para a mesma partida, e o de baixo não faz nada")

    # ── 4. o teto de jogos simultâneos ───────────────────────────────────
    # O botão fica visível e DESABILITADO, com o motivo no title. Sumir com
    # ele faria parecer que o jogo não está no ar.
    r = _rodar(disponiveis=[JOGO_DA_LIGA], lives=[{"id": "x"}, {"id": "y"}],
               escondidas=0, maximo=2)
    ok(r.get("gravar") == 1,
       "no limite de jogos simultâneos o botão sumiu em vez de desabilitar — "
       "sumir esconde que a transmissão existe")
    ok(r.get("gravar_ativos") == 0,
       "no limite de jogos simultâneos o botão continua clicável. O toque "
       "iria ao servidor para voltar com um erro — e num intervalo de jogo "
       "isso é tempo gasto descobrindo o que a tela já sabia")
    # E fora do limite ele tem que estar mesmo clicável, senão a asserção de
    # cima passaria com o botão morto sempre.
    r = _rodar(disponiveis=[JOGO_DA_LIGA], lives=[], escondidas=0, maximo=4)
    ok(r.get("gravar_ativos") == 1,
       "o botão de gravar nasceu desabilitado fora do limite")

    # ── 5. o silêncio legítimo continua legítimo ─────────────────────────
    # Nada disponível, nada escondido, gravador online: aí sim o canal não
    # está transmitindo, e dizer isso é correto.
    r = _rodar(disponiveis=[], lives=[], escondidas=0)
    ok("não está transmitindo nada" in r.get("texto", ""),
       "com o canal realmente sem transmitir, a tela deixou de dizer isso")
    # Com o gravador desligado eu NÃO afirmo nada sobre o canal: quem olha o
    # canal é o gravador, e ele está fora do ar. O aviso do gravador
    # desligado já está no topo da guia.
    r = _rodar(disponiveis=[], lives=[], escondidas=0, online=False)
    ok("não está transmitindo nada" not in r.get("texto", ""),
       "com o gravador desligado a tela afirma que o canal não transmite "
       "nada. Ela não tem como saber: quem olha o canal é o gravador")

    # ── 6. SEM CALENDÁRIO NÃO SE CULPA O CANAL ──────────────────────────
    # Se a API da liga não responde, NENHUMA transmissão é reconhecida e todas
    # caem no filtro. O efeito na tela é idêntico ao de "não tem jogo hoje" —
    # e a causa é o oposto. Dizer "o canal não está transmitindo nada" aqui
    # mandaria o Vini procurar defeito no canal no meio da rodada.
    r = _rodar(disponiveis=[], lives=[], escondidas=0,
               sem_calendario="o calendário da liga voltou vazio")
    ok(not r.get("erro"), f"o JavaScript quebrou: {r.get('erro')}")
    ok("calendário da liga" in r.get("texto", ""),
       "com o calendário da liga fora do ar, a tela não diz isso")
    ok("não está transmitindo nada" not in r.get("texto", ""),
       "sem o calendário, a tela culpa o canal por uma falha minha")
    ok(r.get("ver_todas") == 1,
       "sem o calendário, some o caminho para ver o que o canal transmite — "
       "e é exatamente aí que ele é a ÚNICA forma de gravar o jogo")

    # ── 7. NO SERVIDOR: TODA LISTA VAZIA TEM QUE DIZER POR QUÊ ──────────
    # `_calendario_de_hoje` tem vários caminhos que devolvem lista vazia — API
    # fora do ar, temporada não encontrada, calendário vazio — e ANTES todos
    # saíam iguais, como um `return []` mudo. É a mesma armadilha de sempre:
    # "não tem" e "não consegui saber" viram a mesma tela.
    #
    # Confiro pela ÁRVORE do código, e não procurando texto: assim um caminho
    # novo acrescentado amanhã sem motivo também é pego.
    import ast
    arvore = ast.parse(FONTE)
    alvo_fn = next((n for n in ast.walk(arvore)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "_calendario_de_hoje"), None)
    ok(alvo_fn, "sumiu _calendario_de_hoje")
    mudos = []
    for n in ast.walk(alvo_fn or ast.parse("")):
        if not isinstance(n, ast.Return) or not isinstance(n.value, ast.Tuple):
            continue
        lista, motivo = n.value.elts[0], n.value.elts[1]
        vazia = isinstance(lista, ast.List) and not lista.elts
        if not vazia:
            continue
        # Motivo tem que ser texto não vazio (literal ou f-string).
        tem = (isinstance(motivo, ast.JoinedStr)
               or (isinstance(motivo, ast.Constant)
                   and isinstance(motivo.value, str) and motivo.value.strip()))
        if not tem:
            mudos.append(n.lineno)
    ok(not mudos,
       f"há saída sem jogo nenhum e sem motivo nas linhas {mudos} de "
       "_calendario_de_hoje. Sem motivo, a guia não distingue 'não tem jogo "
       "hoje' de 'não consegui saber quais são os jogos'")

    # E o motivo tem que CHEGAR à tela pelas duas rotas que a guia usa.
    for fn in ("api_clipes", "api_clipe_lives"):
        corpo = _corpo_py(fn)
        ok("_calendario_de_hoje()" in corpo,
           f"{fn}: parou de pedir o motivo junto com o calendário")
        ok('"sem_calendario": sem_calendario' in corpo,
           f"{fn}: o motivo não chega mais à tela")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ gravar jogo do canal: a porta de saída existe quando é a única saída")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
