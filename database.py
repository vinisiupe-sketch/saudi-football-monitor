"""
Banco de dados PostgreSQL — armazena artigos coletados, resumos e logs.
Usa DATABASE_URL do ambiente (fornecido automaticamente pelo Railway).
"""
import os
import hashlib
import json
from contextlib import contextmanager
import psycopg2
import psycopg2.extras

def _get_database_url():
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url
    # Fallback para variáveis individuais do Railway
    host = os.environ.get("PGHOST", "")
    if host:
        return (
            f"postgresql://{os.environ.get('PGUSER')}:{os.environ.get('PGPASSWORD')}"
            f"@{host}:{os.environ.get('PGPORT', 5432)}/{os.environ.get('PGDATABASE')}"
        )
    return ""


@contextmanager
def get_conn():
    url = _get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL não configurada.")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id              TEXT PRIMARY KEY,
                source_name     TEXT NOT NULL,
                source_tier     TEXT NOT NULL,
                source_type     TEXT NOT NULL,
                url             TEXT UNIQUE,
                title_orig      TEXT,
                title_pt        TEXT,
                body_orig       TEXT,
                body_pt         TEXT,
                image_url       TEXT,
                category        TEXT,
                language        TEXT,
                published_at    TEXT,
                collected_at    TEXT NOT NULL,
                is_duplicate    INTEGER DEFAULT 0,
                relevance_score REAL DEFAULT 0.0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id           SERIAL PRIMARY KEY,
                generated_at TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end   TEXT NOT NULL,
                summary_pt   TEXT NOT NULL,
                article_ids  TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS collection_logs (
                id           SERIAL PRIMARY KEY,
                ran_at       TEXT NOT NULL,
                sources_ok   INTEGER DEFAULT 0,
                sources_fail INTEGER DEFAULT 0,
                articles_new INTEGER DEFAULT 0,
                articles_dup INTEGER DEFAULT 0,
                error_msg    TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS article_flags (
                article_id  TEXT PRIMARY KEY,
                flag        TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Migrações
        c.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url TEXT")
        c.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS category TEXT")
        c.execute("ALTER TABLE article_flags ADD COLUMN IF NOT EXISTS comment TEXT")
    print("✅ Banco de dados PostgreSQL inicializado.")


def get_flagged_articles(flag: str) -> list[dict]:
    """Retorna artigos com a flag indicada (qualquer idade), com dados do artigo e comentário."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT a.*, af.updated_at AS flagged_at, af.comment AS flag_comment
            FROM articles a
            JOIN article_flags af ON a.id = af.article_id
            WHERE af.flag = %s
            ORDER BY af.updated_at DESC
        """, (flag,))
        return [dict(r) for r in c.fetchall()]


def get_trashed_articles() -> list[dict]:
    """Retorna artigos com flag='descartado' nas últimas 24h (com dados do artigo)."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT a.*, af.updated_at AS trashed_at
            FROM articles a
            JOIN article_flags af ON a.id = af.article_id
            WHERE af.flag = 'descartado'
              AND af.updated_at::TIMESTAMPTZ >= (NOW() AT TIME ZONE 'UTC' - INTERVAL '24 hours')
            ORDER BY af.updated_at DESC
        """)
        return [dict(r) for r in c.fetchall()]


def cleanup_old_trash():
    """Remove flags 'descartado' com mais de 7 dias (muito além da janela de 48h do dashboard)."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM article_flags
            WHERE flag = 'descartado'
              AND updated_at::TIMESTAMPTZ < (NOW() AT TIME ZONE 'UTC' - INTERVAL '7 days')
        """)
        return c.rowcount


def set_flag(article_id: str, flag: str | None, comment: str | None = None):
    """flag = 'naopublicado' | 'publicado' | 'descartado' | 'analise' | None (remove).
    comment: motivo informado pelo usuário (usado principalmente na flag 'analise')."""
    with get_conn() as conn:
        c = conn.cursor()
        if flag:
            c.execute("""
                INSERT INTO article_flags (article_id, flag, updated_at, comment)
                VALUES (%s, %s, NOW()::TEXT, %s)
                ON CONFLICT (article_id) DO UPDATE SET flag = EXCLUDED.flag, updated_at = EXCLUDED.updated_at, comment = EXCLUDED.comment
            """, (article_id, flag, comment))
        else:
            c.execute("DELETE FROM article_flags WHERE article_id = %s", (article_id,))


def get_all_flags() -> dict:
    """Retorna {article_id: flag}"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT article_id, flag FROM article_flags")
        return {row[0]: row[1] for row in c.fetchall()}


def get_state(key: str) -> str | None:
    """Lê um valor (string, geralmente JSON) salvo em app_state. None se não existir.
    Usado para dados que precisam sobreviver a redeploys (Railway não tem disco
    persistente), como exclusões aprendidas e overrides de fontes."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM app_state WHERE key = %s", (key,))
        row = c.fetchone()
        return row[0] if row else None


def set_state(key: str, value: str):
    """Salva/atualiza um valor em app_state (upsert)."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app_state (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, value))


SOURCE_OVERRIDE_KEY = "source_overrides"


def load_source_overrides() -> dict:
    """Retorna {handle: {tier, moon}} ou {handle: {deleted: True}} salvos via /fontes."""
    try:
        raw = get_state(SOURCE_OVERRIDE_KEY)
        if raw is not None:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def save_source_overrides(data: dict):
    set_state(SOURCE_OVERRIDE_KEY, json.dumps(data, ensure_ascii=False))


def get_effective_sources() -> list[dict]:
    """Combina sources.py (TIER_A/B/C) com os overrides salvos via /fontes — fontes
    adicionadas manualmente entram, fontes deletadas saem, tier/moon editados valem.

    Bug real (2026-06-24): essa lógica existia só dentro de main.py (pra exibir a
    página /fontes), e collector.py tinha sua PRÓPRIA leitura de overrides — de um
    arquivo local (sources_override.json) que a UI nunca escrevia (ela já salvava
    no Postgres há tempos). Resultado: adicionar ou excluir uma fonte em /fontes
    não tinha NENHUM efeito na coleta real — o coletor sempre rodava só com o que
    estava em sources.py, ignorando completamente os overrides. Agora main.py e
    collector.py chamam essa mesma função, então os dois sempre veem a lista
    efetiva idêntica."""
    from sources import TIER_A, TIER_B, TIER_C, SOURCE_MOON
    overrides = load_source_overrides()
    base: dict[str, dict] = {}
    for tier_label, tier_data in [("A", TIER_A), ("B", TIER_B), ("C", TIER_C)]:
        for h in tier_data.get("twitter_accounts", []):
            base[h] = {"handle": h, "tier": tier_label, "moon": SOURCE_MOON.get(h, "")}
    for h, ov in overrides.items():
        if ov.get("deleted"):
            base.pop(h, None)
        elif h in base:
            base[h].update(ov)
        else:
            base[h] = {"handle": h, "tier": ov.get("tier", "C"), "moon": ov.get("moon", "🌗")}
    return sorted(base.values(), key=lambda x: (x["tier"], x["handle"].lower()))


def make_article_id(url: str, title: str) -> str:
    raw = f"{url}|{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def save_article(article: dict) -> bool:
    with get_conn() as conn:
        c = conn.cursor()
        try:
            article.setdefault("image_url", None)
            article.setdefault("category", None)
            c.execute("""
                INSERT INTO articles
                  (id, source_name, source_tier, source_type, url,
                   title_orig, title_pt, body_orig, body_pt,
                   language, published_at, collected_at, relevance_score, image_url, category)
                VALUES
                  (%(id)s, %(source_name)s, %(source_tier)s, %(source_type)s, %(url)s,
                   %(title_orig)s, %(title_pt)s, %(body_orig)s, %(body_pt)s,
                   %(language)s, %(published_at)s, %(collected_at)s, %(relevance_score)s, %(image_url)s, %(category)s)
                ON CONFLICT (id) DO NOTHING
            """, article)
            return c.rowcount > 0
        except Exception:
            return False


def update_article_body(article_id: str, body_orig: str, body_pt: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE articles SET body_orig = %s, body_pt = %s WHERE id = %s",
            (body_orig, body_pt, article_id)
        )


def update_article_title(article_id: str, title_pt: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE articles SET title_pt = %s WHERE id = %s",
            (title_pt, article_id)
        )


def get_low_score_articles(hours: int = 24, limit: int = 200):
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT * FROM articles
            WHERE collected_at >= (NOW() AT TIME ZONE 'UTC' - INTERVAL '%s hours')::TEXT
              AND is_duplicate = 0
              AND relevance_score < 0.34
            ORDER BY relevance_score DESC, collected_at DESC LIMIT %s
        """, (hours, limit))
        return [dict(r) for r in c.fetchall()]


def get_recent_articles(hours: int = 24, tier: str = None, limit: int = 100):
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = """
            SELECT * FROM articles
            WHERE collected_at >= (NOW() AT TIME ZONE 'UTC' - INTERVAL '%s hours')::TEXT
              AND is_duplicate = 0
        """
        params = [hours]
        if tier:
            query += " AND source_tier = %s"
            params.append(tier)
        query += " ORDER BY source_tier ASC, relevance_score DESC, collected_at DESC LIMIT %s"
        params.append(limit)
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]


def save_summary(summary: dict):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO summaries (generated_at, period_start, period_end, summary_pt, article_ids)
            VALUES (%(generated_at)s, %(period_start)s, %(period_end)s, %(summary_pt)s, %(article_ids)s)
        """, {**summary, "article_ids": json.dumps(summary["article_ids"])})


def get_latest_summary():
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM summaries ORDER BY generated_at DESC LIMIT 1")
        row = c.fetchone()
        return dict(row) if row else None


def log_collection(log: dict):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO collection_logs (ran_at, sources_ok, sources_fail, articles_new, articles_dup, error_msg)
            VALUES (%(ran_at)s, %(sources_ok)s, %(sources_fail)s, %(articles_new)s, %(articles_dup)s, %(error_msg)s)
        """, log)


def get_collection_logs(limit: int = 20):
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM collection_logs ORDER BY ran_at DESC LIMIT %s", (limit,))
        return [dict(r) for r in c.fetchall()]
