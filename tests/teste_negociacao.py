"""
A gravação do card de mercado.

O QUE ESTE ARQUIVO VIGIA
    O card é reescrito a cada rodada; os PASSOS não. Essa assimetria é a razão
    de existirem duas tabelas, e é o que mais tem chance de se perder numa
    refatoração distraída.

    Uma negociação que foi de 'Acerto' para 'Melou' tem que continuar
    mostrando que um dia foi Acerto — é isso que ele narra no ar. Se o
    histórico fosse regravado junto com o estado, o card ficaria sempre
    contando só o presente, que é justamente o que ele já tem na timeline do
    Twitter e não precisa de mim para ver.

    E a mesma notícia lida duas vezes não pode virar dois passos. Isso não
    pode depender de ninguém lembrar de não reprocessar: depende da chave.
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

from banco_de_teste import Banco

TABELAS = ("negociacao", "negociacao_fonte")

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def com_banco(banco, fn, *a, **k):
    """Roda a função de produção contra o banco de teste."""
    import database
    original = database.get_conn
    database.get_conn = banco
    try:
        return fn(*a, **k)
    finally:
        database.get_conn = original


def testar():
    falhas.clear()
    import database

    def passo(aid, quando, status, fonte="Romano"):
        return {"article_id": aid, "quando": quando, "status": status,
                "fonte": fonte, "titulo": f"t{aid}", "url": f"u{aid}"}

    banco = Banco(TABELAS)
    card = {"chave": "watkins|al hilal", "jogador": "Ollie Watkins",
            "clube_origem": "Aston Villa", "clube_destino": "Al Hilal",
            "status": "Acerto", "valor": "58 milhões", "foto": "",
            "passos": [passo("a1", "2026-08-25", "Negociação"),
                       passo("a2", "2026-08-26", "Acerto")]}

    # ── 1. a primeira gravação ─────────────────────────────────────────────
    conferir("card novo", com_banco(banco, database.salvar_negociacao, card), "nova")
    conferir("um card", banco.quantos("negociacao"), 1)
    conferir("dois passos", banco.quantos("negociacao_fonte"), 2)
    guardado = banco.linhas("negociacao")[0]
    conferir("primeira data", guardado["primeira_em"], "2026-08-25")
    conferir("última data", guardado["ultima_em"], "2026-08-26")
    conferir("o clube foi padronizado", guardado["clube_destino"], "Al Hilal")

    # ── 2. rodar de novo não duplica passo ─────────────────────────────────
    # Não pode depender de ninguém lembrar de não reprocessar.
    conferir("segunda vez atualiza", com_banco(banco, database.salvar_negociacao, card),
             "atualizada")
    conferir("continua com dois passos", banco.quantos("negociacao_fonte"), 2)
    conferir("continua com um card", banco.quantos("negociacao"), 1)

    # ── 3. a negociação anda — e o que passou não some ─────────────────────
    # É o coração do card: 'Acerto' virou 'Melou' e os dois têm que aparecer.
    virou = dict(card, status="Melou",
                 passos=[passo("a3", "2026-08-28", "Melou", "Ornstein")])
    com_banco(banco, database.salvar_negociacao, virou)
    conferir("o status do card acompanha o mais recente",
             banco.linhas("negociacao")[0]["status"], "Melou")
    conferir("mas o Acerto continua no histórico", banco.quantos("negociacao_fonte"), 3)
    ok(any(f["status"] == "Acerto" for f in banco.linhas("negociacao_fonte")),
       "o passo 'Acerto' sumiu quando a negociação melou — é justamente o que "
       "ele precisa para contar a história")
    conferir("a data mais antiga não anda para a frente",
             banco.linhas("negociacao")[0]["primeira_em"], "2026-08-25")

    # ── 4. vazio não apaga o que já estava ─────────────────────────────────
    # A nota curta não repete valor nem clube de origem. Se ela sobrescrevesse,
    # o card perderia informação a cada notícia magra que chegasse.
    magra = dict(card, valor="", clube_origem="", foto="",
                 passos=[passo("a4", "2026-08-29", "Oficial")])
    com_banco(banco, database.salvar_negociacao, magra)
    g = banco.linhas("negociacao")[0]
    conferir("o valor continua lá", g["valor"], "58 milhões")
    conferir("a origem continua lá", g["clube_origem"], "Aston Villa")

    # ── 5. o que não é card não vira card ──────────────────────────────────
    for ruim, porque in (
            ({"chave": "", "jogador": "X", "clube_destino": "Al Hilal"}, "sem chave"),
            ({"chave": "k", "jogador": "", "clube_destino": "Al Hilal"}, "sem jogador"),
            ({"chave": "k", "jogador": "X", "clube_destino": ""}, "sem destino")):
        conferir(porque, com_banco(Banco(TABELAS), database.salvar_negociacao, ruim),
                 "descartada")

    # ── 6. passo sem notícia de origem é ignorado ──────────────────────────
    # Um passo sem article_id não tem como ser conferido depois nem como
    # evitar duplicata. Ele não entra.
    b2 = Banco(TABELAS)
    r2 = com_banco(b2, database.salvar_negociacao,
                   dict(card, passos=[{"quando": "2026-08-25", "status": "Acerto"}]))
    # O passo torto é IGNORADO, não é um erro. Sem a guarda, a gravação
    # estoura no meio e o card inteiro se perde por causa de um passo ruim.
    conferir("o card salva mesmo assim", r2, "nova")
    conferir("passo sem id de notícia não entra", b2.quantos("negociacao_fonte"), 0)
    conferir("mas o card existe", b2.quantos("negociacao"), 1)

    # ── 7. marcar como lido ────────────────────────────────────────────────
    # A gravação em si usa `= ANY(%s)`, que é do Postgres e o SQLite não tem.
    # Testo aqui só a guarda de lista vazia; o resto está coberto pelo teste
    # de ORDEM abaixo, que é onde mora o defeito que importa.
    conferir("lista vazia não faz nada",
             com_banco(Banco(TABELAS), database.marcar_mercado_lido, []), 0)

    # ── 8. a marca cobre também o que NÃO era negociação ───────────────────
    # Se eu marcasse só o que virou card, as outras voltariam para a fila em
    # toda rodada e ele pagaria de novo, para sempre, pela mesma resposta.
    import ast
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    fn = next((n for n in ast.walk(ast.parse(fonte))
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "processar_mercado"), None)
    ok(fn is not None, "não achei processar_mercado")
    if fn:
        corpo = "\n".join(fonte.split("\n")[fn.lineno - 1:fn.end_lineno])
        descarte = corpo.find("if not d:")
        marca = corpo.find("lidos.append")
        falhou = corpo.find("isinstance(d, Exception)")
        ok(0 < marca < descarte,
           "o artigo passou a ser marcado como lido DEPOIS do descarte — "
           "quem não era negociação volta para a fila e é repago toda rodada")
        # A ORDEM entre os dois é o que importa, e é o que eu quase não testei:
        # a primeira versão só conferia que a linha do `isinstance` existia, e
        # ela continua existindo mesmo depois de eu movê-la para o lugar
        # errado. Erro de rede não é "li e não era nada": é não ter lido.
        ok(0 < falhou < marca,
           "erro de rede está sendo marcado como lido — a notícia se perde "
           "calada, porque eu não perguntei, eu falhei em perguntar")

    # ── 9. a lista antiga não pode desaparecer ─────────────────────────────
    # A guia nova só tem o que mostrar depois que o extrator rodou. Enquanto
    # isso não acontece — ou quando o coletor está seco, como ficou por dois
    # dias — o card não tem o que compilar. Trocar a lista crua por uma tela
    # vazia seria piorar a guia em nome de melhorá-la.
    for rota in ('@app.get("/mercado", response_class=HTMLResponse)',
                 '@app.get("/mercado/noticias", response_class=HTMLResponse)',
                 '@app.get("/api/mercado")',
                 '@app.post("/api/mercado/processar")'):
        ok(rota in fonte, f"sumiu a rota: {rota}")
    # O que importa não é a rota que ela passa para o cabeçalho — isso mudou
    # quando ela virou guia própria — e sim que a lista crua de mercado
    # continue existindo e continue alcançável.
    ok('_pagina_de_noticias("mercado"' in fonte,
       "a lista de notícias soltas de mercado deixou de existir")
    ok('href="/mercado/noticias"' in fonte,
       "a lista crua existe mas não há como chegar nela pela guia de cards")
    ok('("/mercado/noticias", _ICO_MERCADO' in fonte,
       "a lista crua saiu do menu — só se chega nela por dentro da outra guia")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ negociação: o card acompanha o presente, o histórico não se reescreve")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
