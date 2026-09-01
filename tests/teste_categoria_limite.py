"""
get_recent_articles filtrando por categoria DENTRO do SQL.

O DEFEITO QUE ISTO CORRIGE
    /mercado/noticias, /aspas e /noticias saem da mesma busca, e essa busca
    não sabia filtrar por categoria — trazia os N mais recentes de TODAS as
    categorias, e o filtro de categoria rodava depois, em Python. Um `limit`
    que precisava cobrir a Arábia inteira de uma vez virou, na prática, um
    teto COMPARTILHADO: um dia de muito volume numa categoria (fechamento de
    janela de transferências, por exemplo) enchia esse teto antes da guia de
    Mercado — ou qualquer categoria de menor volume — ver artigo nenhum.

    A correção certa não é subir o número (isso só adia o dia em que ele
    aperta de novo) — é o próprio SQL filtrar por categoria, para o `limit`
    valer DEPOIS do filtro, individual por guia.

    Este teste roda a consulta de verdade contra SQLite (via
    tests/banco_de_teste.py) — não confere só se o texto do SQL "parece"
    certo, confere o RESULTADO de rodar a consulta.
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

TABELAS = ("articles",)
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _artigo(id_, categoria, minutos_atras=1, is_duplicate=0, title_pt="ok"):
    from datetime import datetime, timedelta, timezone
    # Formato de datetime('now') do SQLite: espaço, sem fuso, sem
    # microssegundo. published_at é comparado como TEXTO puro (SQLite não
    # tem tipo de data) — semear em outro formato (ISO com 'T', por
    # exemplo) compararia errado, já que 'T' (0x54) ordena depois de
    # espaço (0x20) em qualquer posição.
    quando = (datetime.now(timezone.utc)
              - timedelta(minutes=minutos_atras)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": id_, "source_name": "fonte", "source_tier": "A", "source_type": "twitter",
        "url": f"https://x.com/{id_}", "title_orig": id_, "title_pt": title_pt,
        "body_orig": "", "body_pt": "", "image_url": None, "category": categoria,
        "language": "en", "published_at": quando, "collected_at": quando,
        "is_duplicate": is_duplicate, "relevance_score": 0.9,
    }


def _semear(banco, artigos):
    cols = ["id", "source_name", "source_tier", "source_type", "url", "title_orig",
            "title_pt", "body_orig", "body_pt", "image_url", "category", "language",
            "published_at", "collected_at", "is_duplicate", "relevance_score"]
    marcadores = ", ".join(["?"] * len(cols))
    for a in artigos:
        banco.conn.execute(
            f"INSERT INTO articles ({', '.join(cols)}) VALUES ({marcadores})",
            [a[c] for c in cols])
    banco.conn.commit()


def com_banco(banco, fn, *a, **k):
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

    # ── 1. categoria filtra, e o limite vale DEPOIS do filtro ──────────────
    # 5 artigos de "geral" mais recentes que os 2 de "mercado" — um `limit`
    # aplicado ANTES do filtro perderia os de mercado. Aplicado depois, não.
    banco = Banco(TABELAS)
    artigos = (
        [_artigo(f"geral{i}", "geral", minutos_atras=i) for i in range(5)]
        + [_artigo(f"mercado{i}", "mercado", minutos_atras=10 + i) for i in range(2)]
    )
    _semear(banco, artigos)
    so_mercado = com_banco(banco, database.get_recent_articles,
                            hours=48, limit=10, categoria="mercado")
    conferir("categoria='mercado' traz só mercado",
             sorted(a["id"] for a in so_mercado), ["mercado0", "mercado1"])

    # Com limit MENOR que o total de "geral" só, mercado ainda aparece —
    # é exatamente o caso que quebrava antes: o limite não pode ser
    # consumido pelos artigos de OUTRA categoria.
    banco2 = Banco(TABELAS)
    artigos2 = (
        [_artigo(f"geral{i}", "geral", minutos_atras=i) for i in range(20)]
        + [_artigo("mercado_unico", "mercado", minutos_atras=50)]
    )
    _semear(banco2, artigos2)
    resultado = com_banco(banco2, database.get_recent_articles,
                           hours=48, limit=3, categoria="mercado")
    conferir("mercado sobrevive a um dia cheio de 'geral' com limit apertado",
             [a["id"] for a in resultado], ["mercado_unico"])

    # ── 2. excluir_categorias tira mercado/entrevista, mantém o resto ──────
    banco3 = Banco(TABELAS)
    artigos3 = [
        _artigo("g1", "geral", minutos_atras=1),
        _artigo("m1", "mercado", minutos_atras=2),
        _artigo("e1", "entrevista", minutos_atras=3),
        _artigo("l1", "lesao", minutos_atras=4),
    ]
    _semear(banco3, artigos3)
    resto = com_banco(banco3, database.get_recent_articles,
                       hours=48, limit=10, excluir_categorias=["mercado", "entrevista"])
    conferir("excluir_categorias tira mercado e entrevista",
             sorted(a["id"] for a in resto), ["g1", "l1"])

    # Artigo com categoria NULL (nunca classificado) precisa continuar
    # aparecendo em "notícias" — excluir não pode, por acidente, também
    # excluir quem não tem categoria nenhuma.
    banco4 = Banco(TABELAS)
    sem_categoria = _artigo("sem_cat", None, minutos_atras=1)
    _semear(banco4, [sem_categoria])
    com_null = com_banco(banco4, database.get_recent_articles,
                          hours=48, limit=10, excluir_categorias=["mercado", "entrevista"])
    conferir("categoria NULL não some quando excluir_categorias está ativo",
             [a["id"] for a in com_null], ["sem_cat"])

    # ── 3. sem categoria nem exclusão — comportamento antigo preservado ────
    banco5 = Banco(TABELAS)
    _semear(banco5, [_artigo("x1", "mercado", 1), _artigo("x2", "geral", 2)])
    tudo = com_banco(banco5, database.get_recent_articles, hours=48, limit=10)
    conferir("sem filtro nenhum, continua trazendo tudo",
             sorted(a["id"] for a in tudo), ["x1", "x2"])

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ categoria filtra dentro do SQL, e o limite passa a valer por guia")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
