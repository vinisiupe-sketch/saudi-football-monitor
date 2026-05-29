"""
Banco de dados SQLite — armazena artigos coletados, resumos e logs.
"""
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/monitor.db")


def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            source_type TEXT NOT NULL,
            url         TEXT UNIQUE,
            title_orig  TEXT,
            title_pt    TEXT,
            body_orig   TEXT,
            body_pt     TEXT,
            language    TEXT,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            is_duplicate INTEGER DEFAULT 0,
            relevance_score REAL DEFAULT 0.0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end   TEXT NOT NULL,
            summary_pt   TEXT NOT NULL,
            article_ids  TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS collection_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ran_at       TEXT NOT NULL,
            sources_ok   INTEGER DEFAULT 0,
            sources_fail INTEGER DEFAULT 0,
            articles_new INTEGER DEFAULT 0,
            articles_dup INTEGER DEFAULT 0,
            error_msg    TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("✅ Banco de dados inicializado.")


def make_article_id(url: str, title: str) -> str:
    raw = f"{url}|{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def article_exists(article_id: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone()
    conn.close()
    return row is not None


def save_article(article: dict) -> bool:
    if article_exists(article["id"]):
        return False
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO articles
              (id, source_name, source_tier, source_type, url,
               title_orig, title_pt, body_orig, body_pt,
               language, published_at, collected_at, relevance_score)
            VALUES
              (:id, :source_name, :source_tier, :source_type, :url,
               :title_orig, :title_pt, :body_orig, :body_pt,
               :language, :published_at, :collected_at, :relevance_score)
        """, article)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_recent_articles(hours: int = 24, tier: str = None, limit: int = 100):
    conn = get_conn()
    query = """
        SELECT * FROM articles
        WHERE collected_at >= datetime('now', ?)
          AND is_duplicate = 0
    """
    params = [f"-{hours} hours"]
    if tier:
        query += " AND source_tier = ?"
        params.append(tier)
    query += " ORDER BY source_tier ASC, relevance_score DESC, collected_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_summary(summary: dict):
    import json
    conn = get_conn()
    conn.execute("""
        INSERT INTO summaries (generated_at, period_start, period_end, summary_pt, article_ids)
        VALUES (:generated_at, :period_start, :period_end, :summary_pt, :article_ids)
    """, {**summary, "article_ids": json.dumps(summary["article_ids"])})
    conn.commit()
    conn.close()


def get_latest_summary():
    conn = get_conn()
    row = conn.execute("SELECT * FROM summaries ORDER BY generated_at DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def log_collection(log: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO collection_logs (ran_at, sources_ok, sources_fail, articles_new, articles_dup, error_msg)
        VALUES (:ran_at, :sources_ok, :sources_fail, :articles_new, :articles_dup, :error_msg)
    """, log)
    conn.commit()
    conn.close()


def get_collection_logs(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM collection_logs ORDER BY ran_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
