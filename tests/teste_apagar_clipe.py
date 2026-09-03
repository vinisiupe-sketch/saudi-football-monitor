"""
Apagar um clipe: some agora, e não leva junto o que não devia.

POR QUE ISTO PRECISA DE TESTE
    É o único botão do app que destrói alguma coisa por vontade sua. Ele tem
    três jeitos de dar errado, e os três só aparecem depois:

    1. Apagar o clipe errado — são vários cards parecidos na tela, no meio do
       jogo, com o dedo. Por isso a confirmação mostra QUAL clipe, e não um
       "tem certeza?" seco.
    2. Apagar e não apagar — a linha sai do banco e o mp4 fica no disco para
       sempre, ou o contrário.
    3. Apagar o que é registro, não rascunho. Clipe publicado guarda o
       post_id do vídeo que está no ar em nome do acordo com o detentor dos
       direitos; apagar a linha não tira o vídeo do X, só apaga a memória de
       que ele existe. Esse a rota recusa.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    talo = types.ModuleType("psycopg2")
    talo.extras = types.ModuleType("psycopg2.extras")
    talo.extras.RealDictCursor = object
    talo.Error = Exception
    sys.modules["psycopg2"] = talo
    sys.modules["psycopg2.extras"] = talo.extras

from datetime import datetime, timezone

from banco_de_teste import Banco

import database

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def com_banco(banco, fn, *a, **k):
    original = database.get_conn
    database.get_conn = banco
    try:
        return fn(*a, **k)
    finally:
        database.get_conn = original


def testar():
    falhas.clear()
    banco = Banco(("clipe",))
    alvo = datetime(2026, 9, 3, 18, 0, 0, tzinfo=timezone.utc)

    comum = com_banco(banco, database.criar_pedido_clipe, alvo, 12, 10, "live1", "gol")
    guardado = com_banco(banco, database.criar_pedido_clipe, alvo, 12, 10, "live1", "gol")
    publicado = com_banco(banco, database.criar_pedido_clipe, alvo, 12, 10, "live1", "gol")
    banco.conn.execute("UPDATE clipe SET guardado = 1 WHERE id = ?", [guardado])
    banco.conn.execute("UPDATE clipe SET estado = 'publicado' WHERE id = ?", [publicado])

    # ── 1. o caso normal ──────────────────────────────────────────────────
    conferir("apaga um clipe comum",
             com_banco(banco, database.apagar_clipe, comum), (True, ""))
    ids = {r["id"] for r in banco.linhas("clipe")}
    ok(comum not in ids, "a linha do clipe apagado continuou no banco")

    # ── 2. apagar de novo não finge que deu certo ─────────────────────────
    de_novo, motivo = com_banco(banco, database.apagar_clipe, comum)
    conferir("apagar o que já sumiu devolve falso", de_novo, False)
    ok("não existe" in motivo, f"o motivo não explica o que houve: {motivo!r}")

    # ── 3. o marcado com ★ TAMBÉM sai ─────────────────────────────────────
    # Quem marcou foi você, e quem está apagando também. Recusar aqui seria
    # obrigar a desmarcar antes — dois cliques para a mesma decisão.
    conferir("clipe salvo com estrela também é apagado quando você manda",
             com_banco(banco, database.apagar_clipe, guardado), (True, ""))

    # ── 4. o publicado NÃO sai ────────────────────────────────────────────
    deu, motivo = com_banco(banco, database.apagar_clipe, publicado)
    conferir("clipe publicado é recusado", deu, False)
    ok("publicado" in motivo,
       f"o motivo da recusa não fala de publicação: {motivo!r}")
    ids = {r["id"] for r in banco.linhas("clipe")}
    ok(publicado in ids, "o clipe publicado foi apagado mesmo assim")

    # ── 5. a rota e a tela ────────────────────────────────────────────────
    import ast
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

    def _corpo(nome):
        for n in ast.walk(ast.parse(fonte)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
                return "\n".join(fonte.split("\n")[n.lineno - 1:n.end_lineno])
        return ""

    rota = _corpo("api_clipe_apagar")
    ok(rota, "sumiu a rota /api/clipe/{id}/apagar")
    ok("apagar_clipe(clipe_id)" in rota,
       "a rota parou de chamar a função que apaga de verdade")
    ok("409" in rota,
       "a rota deixou de devolver erro quando a recusa acontece — a tela "
       "mostraria 'apagado' para um clipe que continua lá")

    # A confirmação precisa DIZER qual clipe. Um "tem certeza?" genérico, com
    # quatro jogos e uma lista cheia, não protege de nada.
    ok("function apagarClipe" in fonte, "sumiu o apagarClipe da tela")
    ok("confirm('Apagar este clipe?" in fonte,
       "o botão de apagar parou de confirmar antes")
    ok("c.jogo ? c.jogo" in fonte and "hora(c.alvo_em)" in fonte,
       "a confirmação parou de dizer QUAL clipe está sendo apagado")
    ok("(c.guardado ? '  (este esta marcado com ★)' : '')" in fonte,
       "a confirmação parou de avisar quando o clipe apagado é um marcado ★")

    # E o botão precisa existir onde ele é útil: no card pronto, no de erro e
    # no pedido que ainda não virou vídeo.
    conferir("o botão aparece nos três estados", fonte.count("botaoApagar(c)"), 4)

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ apagar clipe: some agora, confirma qual, e não apaga o publicado")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
