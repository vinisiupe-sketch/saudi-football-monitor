"""
A deduplicação semântica, e por que ela não pode cruzar fontes.

O DEFEITO QUE ISTO CORRIGE
    `processor.deduplicate()` roda sobre o lote inteiro de um ciclo de
    coleta, comparando título contra título — sem olhar de QUAL FONTE cada
    um veio. Duas fontes diferentes noticiando a mesma negociação com
    palavras parecidas ("Al Ittihad agree deal to sign Richard Rios") caíam
    acima do limiar de similaridade uma da outra, e só a de maior
    relevance_score sobrevivia. A outra sumia antes mesmo de ser traduzida.

    Isso é o oposto do que a guia de Mercado precisa: ela existe para juntar
    VÁRIAS fontes cobrindo a MESMA negociação numa linha do tempo (ver
    mercado.py, elos.py) — cortar aqui, cedo demais, tira a fonte do jogo
    antes dela ter chance de virar mais uma entrada naquela negociação.
    Corroboração de fontes diferentes é sinal, não ruído.

    O que a deduplicação ainda precisa pegar: a MESMA fonte publicando o
    "mesmo" tweet duas vezes com o título cortado em ponto diferente entre
    dois ciclos — isso sim é ruído, e continua sendo removido.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# processor.py importa httpx e database (que importa psycopg2) no topo do
# arquivo, mas deduplicate()/titles_are_similar() não tocam em nenhum dos
# dois — só texto puro. Sem stub, testar essa função pura exigiria instalar
# a pilha inteira de rede e banco. Mesmo padrão de teste_lesao.py.
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
# call_claude() usa `httpx.AsyncClient` só como anotação de tipo — nunca
# instanciado por quem chama deduplicate()/titles_are_similar() — mas o
# módulo stub precisa do atributo só para o arquivo terminar de carregar.
if not hasattr(sys.modules["httpx"], "AsyncClient"):
    sys.modules["httpx"].AsyncClient = object

import processor

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _art(id_, fonte, titulo, score=0.9):
    return {"id": id_, "source_name": fonte, "title_orig": titulo, "relevance_score": score}


def testar():
    falhas.clear()

    # ── 1. mesmo texto, fontes DIFERENTES — as duas ficam ──────────────────
    titulo = "Al Ittihad agree deal to sign Richard Rios, here we go!"
    dois = [
        _art("fabrizio", "FabrizioRomano", titulo, score=0.95),
        _art("outro", "CLMerlo", titulo, score=0.80),
    ]
    resultado = processor.deduplicate(dois)
    conferir("fontes diferentes com título igual: as duas sobrevivem",
             sorted(a["id"] for a in resultado), ["fabrizio", "outro"])

    # ── 2. mesmo texto, MESMA fonte — cai a de menor relevância ────────────
    # Caso real: RSSHub trunca o título em ponto diferente entre dois
    # ciclos, ou a mesma fonte republica o furo reforçando.
    repetido = [
        _art("v1", "FabrizioRomano", titulo, score=0.95),
        _art("v2", "FabrizioRomano", titulo + " (updated)", score=0.70),
    ]
    resultado2 = processor.deduplicate(repetido)
    conferir("mesma fonte, título repetido: só a de maior relevância fica",
             [a["id"] for a in resultado2], ["v1"])

    # ── 3. textos DIFERENTES, mesma fonte — nenhum é cortado ───────────────
    diferentes = [
        _art("a", "FabrizioRomano", "Al Ittihad sign Richard Rios, here we go!"),
        _art("b", "FabrizioRomano", "Barcelona confirm signing of Gabriel Jesus"),
    ]
    resultado3 = processor.deduplicate(diferentes)
    conferir("mesma fonte, assuntos diferentes: os dois ficam",
             sorted(a["id"] for a in resultado3), ["a", "b"])

    # ── 4. três fontes, mesma notícia — nenhuma cai ────────────────────────
    tres = [
        _art("f1", "FabrizioRomano", titulo, score=0.95),
        _art("f2", "CLMerlo", titulo, score=0.90),
        _art("f3", "MatteMoretto", titulo, score=0.85),
    ]
    resultado4 = processor.deduplicate(tres)
    ok(len(resultado4) == 3,
       f"3 fontes cobrindo a mesma negociação deviam sobrar 3, sobrou "
       f"{len(resultado4)} — corroboração de fonte não é duplicata")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ dedup: só dentro da mesma fonte — corroboração entre fontes sobrevive")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
