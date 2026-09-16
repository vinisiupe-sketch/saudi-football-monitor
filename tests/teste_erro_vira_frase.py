"""
Erro no servidor vira FRASE na tela, e não um "Internal Server Error" mudo.

O QUE ACONTECEU (16/09/26)
    O Vini abriu a guia de Elencos e viu:

        Erro: Unexpected token 'I', "Internal S"... is not valid JSON

    Essa mensagem é o navegador tentando ler como JSON a resposta padrão do
    servidor para um erro inesperado — o texto "Internal Server Error". Ou
    seja: alguma coisa estourou lá dentro e a tela não tinha como saber o quê.

    Eu procurei às cegas por quarenta minutos: li o diff inteiro, conferi nome
    por nome com a árvore sintática, procurei função apagada por engano. Nada.
    A procura teria durado um minuto se a resposta dissesse o nome do erro.

    ESSE é o defeito de verdade, e ele é mais velho que o erro que o revelou:
    toda rota deste app podia estourar, e todas estouravam em silêncio.

O QUE ESTE ARQUIVO VIGIA
    Que o tratador existe, que ele diz TIPO, MENSAGEM e ONDE, que rota de
    dados recebe JSON e página recebe HTML, e que o rastro inteiro vai para o
    log do Railway — que é onde cabe um traceback.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


ok("@app.exception_handler(Exception)" in FONTE,
   "sumiu o tratador de erro geral. Sem ele, qualquer exceção vira "
   "'Internal Server Error' e a tela mostra um erro de JSON que não tem nada "
   "a ver com o problema")

# ── EXECUTADO, e não lido ───────────────────────────────────────────────────
#
# Recorto o tratador do main.py e rodo de verdade, com uma exceção de mentira.
# Conferir que a função existe não diz nada sobre o que ela devolve — e o que
# ela devolve É a coisa toda.
i = FONTE.index("async def _erro_vira_frase(")
j = FONTE.index("\n\n\n", i)
CORPO = FONTE[i:j]


class _Resposta:
    def __init__(self, conteudo, status_code=200):
        self.conteudo = conteudo
        self.status_code = status_code


class _Url:
    def __init__(self, caminho):
        self.path = caminho


class _Pedido:
    def __init__(self, caminho):
        self.url = _Url(caminho)


_saida_do_log = []


def _print_de_mentira(*a, **k):
    _saida_do_log.append(" ".join(str(x) for x in a))


ambiente = {"JSONResponse": _Resposta, "HTMLResponse": _Resposta,
            "print": _print_de_mentira, "Request": object}
exec(CORPO, ambiente)
_tratar = ambiente["_erro_vira_frase"]


def _rodar(caminho, erro):
    """Roda o tratador com a saída de erro tapada.

    O tratador imprime o rastro inteiro no stderr de propósito — é o log do
    Railway. Aqui isso sujaria a saída da suíte com tracebacks que não são
    falha nenhuma, e um teste que parece ter quebrado é quase tão ruim quanto
    um que quebrou.
    """
    import asyncio
    import contextlib
    import io as _io
    with contextlib.redirect_stderr(_io.StringIO()):
        return asyncio.run(_tratar(_Pedido(caminho), erro))


# A exceção precisa ter rastro de verdade para o teste valer: uma exceção
# construída à mão tem __traceback__ vazio, e aí o "onde" sairia vazio sem que
# isso fosse defeito nenhum.
def _com_rastro(fabricar):
    try:
        fabricar()
    except Exception as e:
        return e
    raise AssertionError("a exceção de teste não estourou")


_erro_chave = _com_rastro(lambda: {"a": 1}["numero"])
_erro_tipo = _com_rastro(lambda: 1 + "dois")

r = _rodar("/api/elencos/jogadores", _erro_chave)
ok(r.status_code == 500, f"o tratador devolveu {r.status_code}, e não 500")
ok(isinstance(r.conteudo, dict),
   "rota de dados tem de receber JSON — a tela lê `d.erro`")
if isinstance(r.conteudo, dict):
    ok("KeyError" in r.conteudo.get("erro", ""),
       f"a resposta não diz o TIPO do erro: {r.conteudo.get('erro')!r}")
    ok("numero" in r.conteudo.get("erro", ""),
       "a resposta não diz a MENSAGEM do erro — 'KeyError' sozinho não diz "
       "qual chave faltou")
    ok(".py:" in r.conteudo.get("onde", ""),
       f"a resposta não diz ONDE aconteceu: {r.conteudo.get('onde')!r}. "
       f"Sem arquivo e linha, ainda se procura às cegas")

r2 = _rodar("/api/jogador/arte", _erro_tipo)
ok(isinstance(r2.conteudo, dict) and "TypeError" in r2.conteudo.get("erro", ""),
   "outro tipo de erro não foi relatado")

# PÁGINA RECEBE HTML. Se a página recebesse JSON, o navegador baixaria um
# arquivo em vez de mostrar uma tela — e ele veria um download misterioso no
# lugar de uma explicação.
r3 = _rodar("/elencos", _erro_chave)
ok(isinstance(r3.conteudo, str) and "<" in r3.conteudo,
   "quem pediu uma página recebeu JSON — o navegador baixaria o arquivo em "
   "vez de mostrar a tela")
ok(r3.status_code == 500, "a página de erro não veio com status 500")
ok("KeyError" in r3.conteudo,
   "a página de erro não diz qual foi o erro")

# E O RASTRO INTEIRO VAI PARA O LOG. A tela cabe uma frase; o traceback, não.
ok(any("/api/elencos/jogadores" in l for l in _saida_do_log),
   "o log do servidor não registrou qual rota estourou")
ok("traceback.print_exception" in CORPO,
   "o rastro completo parou de ir para o log do Railway — é lá que dá para "
   "ver a pilha inteira quando a frase da tela não basta")


# ── A RESERVA DO ELENCO TAMBÉM PRECISA DE REDE ──────────────────────────────
#
# Era a única chamada daquela rota sem proteção, e ela vai ao banco e ao
# glossário. Reserva que estoura derruba a guia inteira — que é exatamente o
# que a reserva existe para evitar.
rota = FONTE[FONTE.index('@app.get("/api/elencos/jogadores")'):]
rota = rota[:rota.index("\n_ELENCO_SALVA_CHAVE")]
i2 = rota.index("_elenco_de_reserva, team, clube)")
antes = rota[max(0, i2 - 400):i2]
ok("try:" in antes,
   "a chamada da reserva do elenco voltou a ficar sem try. Ela é a última "
   "linha de defesa quando o Transfermarkt bloqueia; se ela estoura, a guia "
   "inteira cai e a tela não diz por quê")
ok("a reserva também falhou" in rota,
   "sumiu o aviso de que a reserva falhou — a tela precisa distinguir "
   "'ninguém achou' de 'a busca quebrou'")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ erro do servidor vira frase na tela, com tipo, mensagem e lugar")
