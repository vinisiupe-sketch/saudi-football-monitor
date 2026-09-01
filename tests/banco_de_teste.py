"""
Um banco de verdade, pequeno, para os testes que gravam.

POR QUE ISTO EXISTE
    Eu tinha escrito um banco falso que reimplementava em Python o que o SQL
    faz: o ON CONFLICT, o COALESCE(NULLIF(...)), o LEAST/GREATEST. Parecia
    razoável e era inútil. Quando fui conferir se os testes pegavam defeito —
    apagando de propósito o `ON CONFLICT ... DO NOTHING`, trocando
    `COALESCE(NULLIF(x,''), y)` por `x` — SETE de nove mutações passaram
    verdes. Claro: o falso não lia o SQL, ele imitava a minha intenção. O
    teste estava conferindo a si mesmo.

    Aqui o SQL é EXECUTADO. As instruções de CREATE TABLE são lidas do próprio
    database.py, então uma coluna renomeada lá quebra aqui, e as cláusulas de
    conflito rodam de verdade.

O QUE PRECISA SER TRADUZIDO, E POR QUE É POUCO
    SQLite não é Postgres, mas a distância nas partes que me interessam é
    pequena: `%s` vira `?`, `NOW()` vira CURRENT_TIMESTAMP, `LEAST/GREATEST`
    viram `MIN/MAX` (que no SQLite são escalares quando recebem dois
    argumentos). O ON CONFLICT, o COALESCE e o NULLIF são iguais nos dois — e
    são justamente o que os testes estão vigiando.

    Os tipos (TIMESTAMPTZ, SERIAL) o SQLite aceita e ignora. Isso é uma
    limitação real e eu registro: este banco não pega erro de TIPO, só de
    lógica.
"""
import ast
import os
import re
import sqlite3

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _instrucoes_de_criacao(tabelas):
    """Os CREATE TABLE de verdade, tirados do database.py.

    Escrever o schema aqui à mão seria repetir o mesmo erro do banco falso:
    o teste passaria a conferir a minha cópia, e uma coluna renomeada no
    código de produção não quebraria nada.
    """
    fonte = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    achados = {}
    for no in ast.walk(ast.parse(fonte)):
        if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
            continue
        for t in tabelas:
            alvo = f"CREATE TABLE IF NOT EXISTS {t} ("
            if alvo in no.value:
                i = no.value.find("CREATE TABLE")
                achados.setdefault(t, no.value[i:].strip())
    faltando = [t for t in tabelas if t not in achados]
    if faltando:
        raise AssertionError(f"não achei o CREATE TABLE de: {faltando}")
    return [achados[t] for t in tabelas]


def _para_sqlite(sql: str) -> str:
    sql = sql.replace("%s", "?")
    # A janela "artigo dos últimos N horas" é escrita em Postgres com
    # INTERVAL e AT TIME ZONE, que o SQLite não tem. Vira uma chamada a
    # datetime() com modificador de horas — texto puro, comparável de
    # verdade com o que os testes semeiam no mesmo formato (sem 'T', sem
    # fuso: ver o comentário sobre isso nos testes que usam esta função).
    sql = re.sub(
        r"NOW\(\) AT TIME ZONE 'UTC' - \(INTERVAL '1 hour' \* \?\)",
        "datetime('now', '-' || ? || ' hours')",
        sql)
    sql = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", sql)
    sql = re.sub(r"\bLEAST\(", "MIN(", sql)
    sql = re.sub(r"\bGREATEST\(", "MAX(", sql)
    # O cast `coluna::TIPO` é sintaxe do Postgres; SQLite não entende os dois
    # pontos. Some primeiro (na comparação de datas), e só depois trata o
    # `TIMESTAMPTZ` que sobra sozinho, como parte de um CREATE TABLE.
    sql = re.sub(r"::\w+", "", sql)
    sql = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", sql)
    sql = re.sub(r"\bSERIAL\b", "INTEGER", sql)
    return sql


class _Cursor:
    def __init__(self, cur):
        self._c = cur

    def execute(self, sql, args=None):
        return self._c.execute(_para_sqlite(sql), list(args or []))

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @property
    def rowcount(self):
        return self._c.rowcount


class Banco:
    """Serve de `get_conn`: é chamado, e é usado como `with ... as conn`."""

    def __init__(self, tabelas, extras=()):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for instrucao in _instrucoes_de_criacao(tabelas):
            self.conn.execute(_para_sqlite(instrucao))
        for instrucao in extras:
            self.conn.execute(instrucao)

    def __call__(self, *a, **k):
        return self

    def cursor(self, *a, **k):
        return _Cursor(self.conn.cursor())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.conn.commit()
        return False

    # ── para o teste espiar ─────────────────────────────────────────────
    def linhas(self, tabela):
        return [dict(r) for r in
                self.conn.execute(f"SELECT * FROM {tabela}").fetchall()]

    def quantos(self, tabela):
        return self.conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
