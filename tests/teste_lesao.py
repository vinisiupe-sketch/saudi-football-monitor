"""
Quando uma notícia vira lesão — e, principalmente, quando não vira.

O DEFEITO QUE ISTO CORRIGE
    A guia encheu de gente que não estava machucada. O extrator recebia
    "Fulano fica fora do jogo contra o Al-Hilal" e devolvia uma lesão, porque
    ausência e lesão andam juntas no texto e o modelo completou o resto.

    Ausência não é lesão. Não relacionado, suspenso, poupado, negociando
    saída, motivo pessoal, decisão técnica — tudo isso tira o jogador do jogo
    e nada disso é problema físico.

POR QUE A REGRA É DE CÓDIGO, E NÃO SÓ DE PEDIDO
    O pedido ao modelo ficou explícito, e isso ajuda. Mas pedido é pedido: ele
    pode responder is_injury=true assim mesmo, e respondia. A peneira daqui
    não depende de ninguém se comportar — se o texto não tem NENHUMA palavra
    que fale de corpo, a notícia nem chega ao modelo.

    Ela é grossa de propósito. Não decide quem está lesionado; só barra o que
    nem fala de lesão.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# O injury_processor importa o processor, que importa o database e o httpx.
# Nada disso é usado aqui: este teste não fala com banco nem faz requisição.
if "psycopg2" not in sys.modules:
    talo = types.ModuleType("psycopg2")
    talo.extras = types.ModuleType("psycopg2.extras")
    talo.extras.RealDictCursor = object
    talo.Error = Exception
    sys.modules["psycopg2"] = talo
    sys.modules["psycopg2.extras"] = talo.extras
for nome in ("httpx", "bs4", "feedparser"):
    try:
        __import__(nome)
    except ImportError:
        sys.modules[nome] = types.ModuleType(nome)

import injury_processor as ip

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


# Casos reais do tipo que enchia a guia. Nenhum deles é lesão.
NAO_E_LESAO = [
    "Fulano fica fora da partida contra o Al-Hilal",
    "O técnico não relacionou Ciclano para o clássico",
    "Beltrano está suspenso pelo terceiro cartão amarelo",
    "Jogador foi poupado e não viajou com a delegação",
    "Atacante fica de fora por decisão técnica",
    "Meia deixa a concentração por motivo pessoal",
    "Zagueiro não entra em campo por causa da negociação com o Al-Nassr",
    "Al Hilal anuncia a saída do lateral por empréstimo",
    "لن يشارك اللاعب في مباراة الغد",          # não vai jogar amanhã
    "الفريق يستبعد اللاعب من قائمة المباراة",   # excluído da lista
]

# Estes falam de corpo, e por isso passam pela peneira.
E_LESAO = [
    "Fulano sofreu uma lesão muscular na coxa direita",
    "Ciclano passará por cirurgia no joelho na próxima semana",
    "Beltrano segue em tratamento no departamento médico",
    "Jogador sente dores e vai fazer exame médico",
    "Lateral tem ruptura de ligamento e desfalca o time",
    "Player suffered a hamstring injury during training",
    "Striker to undergo surgery after fracture",
    "تعرض اللاعب إلى إصابة عضلية في التمرين",  # sofreu lesão muscular
    "اللاعب يخضع للعلاج الطبي بعد الإصابة",     # tratamento médico após lesão
]


def testar():
    falhas.clear()

    # ── 1. ausência sozinha não passa ──────────────────────────────────────
    for t in NAO_E_LESAO:
        ok(not ip.fala_de_lesao(t),
           f"passou como lesão sem falar de corpo: {t[:60]}")

    # ── 2. o que fala de corpo passa ───────────────────────────────────────
    for t in E_LESAO:
        ok(ip.fala_de_lesao(t), f"barrou uma lesão de verdade: {t[:60]}")

    # ── 3. entradas estranhas não explodem ─────────────────────────────────
    for t in ("", None, "   ", "123", "!!!"):
        try:
            ok(not ip.fala_de_lesao(t), f"texto vazio virou lesão: {t!r}")
        except Exception as e:
            falhas.append(f"explodiu com {t!r}: {type(e).__name__}")

    # ── 4. a peneira roda ANTES de chamar o modelo ─────────────────────────
    # Se rodasse depois, cada desfalque continuaria custando uma chamada — e,
    # pior, o modelo continuaria tendo a chance de inventar a lesão.
    import ast
    fonte = open(os.path.join(RAIZ, "injury_processor.py"), encoding="utf-8").read()
    fn = next((n for n in ast.walk(ast.parse(fonte))
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "extract_injury_data"), None)
    ok(fn is not None, "não achei extract_injury_data")
    if fn:
        corpo = "\n".join(fonte.split("\n")[fn.lineno - 1:fn.end_lineno])
        peneira = corpo.find("fala_de_lesao")
        chamada = corpo.find("call_claude")
        ok(0 < peneira < chamada,
           "a peneira passou a rodar depois da chamada ao modelo — volta a "
           "pagar por notícia que nem fala de lesão, e volta a deixar o modelo "
           "inventar lesão a partir de desfalque")
        # `body_orig` aparece na linha de fallback do `body` também — contar
        # a ocorrência é o que distingue "a peneira olha o original" de "o
        # texto por acaso menciona a palavra". Foi assim que esta asserção
        # passou verde com a peneira olhando só a tradução.
        ok(corpo.count("body_orig") >= 2,
           "a peneira olha só o texto traduzido — notícia árabe sem tradução "
           "diz 'إصابة' e passaria batido")

    # ── 5. o pedido ao modelo continua dizendo a regra ─────────────────────
    # A peneira barra o que nem fala de lesão. Quem separa "lesionado" de
    # "fora por outro motivo" dentro de um texto que fala das duas coisas é o
    # modelo — e para isso ele precisa da instrução explícita.
    ok("AUSÊNCIA NÃO É LESÃO" in fonte,
       "o pedido ao modelo perdeu a regra de que ausência não é lesão")
    for termo in ("suspensão", "decisão técnica", "não foi relacionado"):
        ok(termo in fonte, f"o pedido não cita mais o caso: {termo}")
    ok("Na dúvida" in fonte,
       "sumiu a instrução de que a dúvida resolve em false")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ lesão: ausência não vira lesão, e a peneira é de código")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
