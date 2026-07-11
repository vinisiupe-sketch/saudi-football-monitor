"""
Banco de dados PostgreSQL — armazena artigos coletados, resumos e logs.
Usa DATABASE_URL do ambiente (fornecido automaticamente pelo Railway).
"""
import os
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
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
    init_injuries()
    init_entity_tables()
    print("✅ Banco de dados PostgreSQL inicializado.")


def make_article_id(url: str, title: str) -> str:
    """Gera ID unico para um artigo a partir da URL (fallback para title)."""
    src = (url or title or "").strip().encode("utf-8")
    return hashlib.md5(src).hexdigest()[:16]


def save_article(art: dict) -> bool:
    """Salva um artigo no banco. Retorna True se novo, False se duplicado (url ja existe)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO articles (
                    id, source_name, source_tier, source_type, url,
                    title_orig, title_pt, body_orig, body_pt, image_url,
                    category, language, published_at, collected_at,
                    is_duplicate, relevance_score
                ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s)
                ON CONFLICT (id) DO NOTHING
            """, (
                art["id"], art["source_name"], art["source_tier"], art["source_type"], art.get("url"),
                art.get("title_orig"), art.get("title_pt"), art.get("body_orig"), art.get("body_pt"),
                art.get("image_url"), art.get("category"), art.get("language"),
                art.get("published_at"), now,
                0, art.get("relevance_score", 0.0),
            ))
            return c.rowcount == 1
    except Exception:
        return False


def log_collection(log: dict):
    """Registra o resultado de uma execucao de coleta em collection_logs."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO collection_logs
                    (ran_at, sources_ok, sources_fail, articles_new, articles_dup, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                log.get("ran_at"), log.get("sources_ok", 0), log.get("sources_fail", 0),
                log.get("articles_new", 0), log.get("articles_dup", 0), log.get("error_msg"),
            ))
    except Exception:
        pass


def update_article_title(article_id: str, title_pt: str):
    """Atualiza o titulo traduzido de um artigo."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE articles SET title_pt = %s WHERE id = %s",
                (title_pt, article_id)
            )
    except Exception:
        pass


def update_article_body(article_id: str, body_orig: str, body_pt: str):
    """Atualiza o corpo original e traduzido de um artigo."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE articles SET body_orig = %s, body_pt = %s WHERE id = %s",
                (body_orig, body_pt, article_id)
            )
    except Exception:
        pass


def update_article_meta(article_id: str, category: str = None, relevance_score: float = None):
    """Atualiza category e/ou relevance_score de um artigo."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            if category is not None and relevance_score is not None:
                c.execute(
                    "UPDATE articles SET category = %s, relevance_score = %s WHERE id = %s",
                    (category, relevance_score, article_id)
                )
            elif category is not None:
                c.execute("UPDATE articles SET category = %s WHERE id = %s", (category, article_id))
            elif relevance_score is not None:
                c.execute("UPDATE articles SET relevance_score = %s WHERE id = %s", (relevance_score, article_id))
    except Exception:
        pass


def get_recent_articles(hours: int = 24, limit: int = 100, tier: str = None) -> list[dict]:
    """Retorna artigos recentes ordenados por published_at DESC."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if tier:
            c.execute(
                """
                SELECT * FROM articles
                WHERE is_duplicate = 0
                  AND published_at::TIMESTAMPTZ >= (NOW() AT TIME ZONE 'UTC' - (INTERVAL '1 hour' * %s))
                  AND source_tier = %s
                ORDER BY published_at DESC
                LIMIT %s
                """, (hours, tier, limit)
            )
        else:
            c.execute(
                """
                SELECT * FROM articles
                WHERE is_duplicate = 0
                  AND published_at::TIMESTAMPTZ >= (NOW() AT TIME ZONE 'UTC' - (INTERVAL '1 hour' * %s))
                ORDER BY published_at DESC
                LIMIT %s
                """, (hours, limit)
            )
        return [dict(r) for r in c.fetchall()]


def get_low_score_articles(hours: int = 24, limit: int = 200) -> list[dict]:
    """Retorna artigos com relevance_score baixo (para re-scoring)."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(
            """
            SELECT * FROM articles
            WHERE is_duplicate = 0
              AND relevance_score < 5.0
              AND published_at::TIMESTAMPTZ >= (NOW() AT TIME ZONE 'UTC' - (INTERVAL '1 hour' * %s))
            ORDER BY published_at DESC
            LIMIT %s
            """, (hours, limit)
        )
        return [dict(r) for r in c.fetchall()]


def get_collection_logs(limit: int = 10) -> list[dict]:
    """Retorna os ultimos N logs de colecao."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(
            "SELECT * FROM collection_logs ORDER BY ran_at DESC LIMIT %s", (limit,)
        )
        return [dict(r) for r in c.fetchall()]


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


TOKEN_STATUS_KEY = "twitter_token_status"


def get_token_status() -> dict:
    """Retorna {status: 'ok'|'broken', detail: str, checked_at: iso} do último check
    diário do token X/Twitter do RSSHub (rotina agendada twitter-token-check).
    {} se nunca checado — o front trata isso como 'desconhecido' (bolinha cinza)."""
    try:
        raw = get_state(TOKEN_STATUS_KEY)
        if raw is not None:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def set_token_status(status: str, detail: str = ""):
    """status = 'ok' | 'broken'. Chamado via POST /api/token-status pela rotina
    diária que verifica o token X/Twitter do RSSHub."""
    set_state(TOKEN_STATUS_KEY, json.dumps({
        "status": status,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False))



# ─────────────────────────────────────────────
#  MONITOR DE LESÕES
# ─────────────────────────────────────────────

def init_injuries():
    """Cria/migra a tabela injuries. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS injuries (
                id              TEXT PRIMARY KEY,
                player_name     TEXT NOT NULL,
                player_name_orig TEXT,
                club            TEXT NOT NULL,
                injury_date     TEXT,
                injury_type     TEXT,
                body_part       TEXT,
                expected_return TEXT,
                status          TEXT DEFAULT 'lesionado',
                first_reported  TEXT NOT NULL,
                last_updated    TEXT NOT NULL,
                sources         TEXT NOT NULL DEFAULT '[]',
                notes           TEXT
            )
        """)


def _normalize(s: str) -> str:
    """Normaliza string para comparação fuzzy (minúsculo, sem acentos)."""
    import unicodedata
    s = s.lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def upsert_injury(data: dict) -> str:
    """Insere ou atualiza registro de lesão.
    data keys: player_name, player_name_orig, club, injury_date, injury_type,
               body_part, expected_return, status, source_info (dict), notes.
    Matching: mesmo jogador + mesmo clube dentro de 60 dias → atualiza.
    Retorna 'created' | 'updated'."""
    from difflib import SequenceMatcher

    player_name = (data.get("player_name") or "").strip()
    club = (data.get("club") or "").strip()
    source_info = data.get("source_info") or {}
    now = datetime.now(timezone.utc).isoformat()

    if not player_name or not club:
        return "skipped"

    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Candidatos: mesmo clube, últimos 60 dias
        c.execute("""
            SELECT * FROM injuries
            WHERE LOWER(club) = LOWER(%s)
              AND last_updated::DATE >= (NOW() AT TIME ZONE 'UTC' - INTERVAL '60 days')::DATE
            ORDER BY last_updated DESC
        """, (club,))
        candidates = [dict(r) for r in c.fetchall()]

        # Fuzzy match por nome de jogador
        player_norm = _normalize(player_name)
        best_match, best_ratio = None, 0.0
        for cand in candidates:
            ratio = SequenceMatcher(None, player_norm, _normalize(cand["player_name"])).ratio()
            if ratio > best_ratio:
                best_ratio, best_match = ratio, cand

        existing = best_match if best_ratio >= 0.75 else None

        if existing:
            sources = json.loads(existing["sources"] or "[]")
            url = source_info.get("url", "")
            if url and url not in [s.get("url") for s in sources]:
                sources.append(source_info)

            c2 = conn.cursor()
            c2.execute("""
                UPDATE injuries SET
                    player_name     = COALESCE(NULLIF(%s,''), player_name),
                    injury_type     = COALESCE(NULLIF(%s,''), injury_type),
                    body_part       = COALESCE(NULLIF(%s,''), body_part),
                    expected_return = COALESCE(NULLIF(%s,''), expected_return),
                    status          = %s,
                    last_updated    = %s,
                    sources         = %s,
                    notes           = COALESCE(NULLIF(%s,''), notes)
                WHERE id = %s
            """, (
                player_name,
                data.get("injury_type") or "",
                data.get("body_part") or "",
                data.get("expected_return") or "",
                data.get("status") or existing["status"],
                now,
                json.dumps(sources, ensure_ascii=False),
                data.get("notes") or "",
                existing["id"],
            ))
            return "updated"
        else:
            injury_id = hashlib.sha256(
                f"{_normalize(player_name)}|{_normalize(club)}|{now[:10]}".encode()
            ).hexdigest()[:16]
            sources = [source_info] if source_info else []

            c2 = conn.cursor()
            c2.execute("""
                INSERT INTO injuries
                    (id, player_name, player_name_orig, club, injury_date, injury_type,
                     body_part, expected_return, status, first_reported, last_updated, sources, notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
            """, (
                injury_id,
                player_name,
                data.get("player_name_orig"),
                club,
                data.get("injury_date"),
                data.get("injury_type"),
                data.get("body_part"),
                data.get("expected_return"),
                data.get("status") or "lesionado",
                now, now,
                json.dumps(sources, ensure_ascii=False),
                data.get("notes"),
            ))
            return "created"


def get_injuries(include_recovered: bool = True) -> list[dict]:
    """Retorna lesões ordenadas: ativas primeiro, depois recuperadas.
    Se a tabela ainda não existir, chama init_injuries() e retorna []."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if include_recovered:
                c.execute("""
                    SELECT * FROM injuries
                    ORDER BY
                        CASE status
                            WHEN 'lesionado'      THEN 1
                            WHEN 'em_recuperacao' THEN 2
                            WHEN 'retornando'     THEN 3
                            WHEN 'recuperado'     THEN 4
                            ELSE 5
                        END,
                        last_updated DESC
                """)
            else:
                c.execute("""
                    SELECT * FROM injuries
                    WHERE status != 'recuperado'
                    ORDER BY last_updated DESC
                """)
            rows = [dict(r) for r in c.fetchall()]
            for r in rows:
                try:
                    r["sources"] = json.loads(r["sources"] or "[]")
                except Exception:
                    r["sources"] = []
            return rows
    except Exception as e:
        if "injuries" in str(e) and "does not exist" in str(e):
            init_injuries()
        return []


def get_lesao_articles() -> list[dict]:
    """Retorna todos os artigos com category='lesao' para reprocessamento retroativo."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT * FROM articles
            WHERE category = 'lesao'
            ORDER BY published_at ASC
        """)
        return [dict(r) for r in c.fetchall()]


# ─────────────────────────────────────────────
#  MONITOR DE TRANSFERÊNCIAS
# ─────────────────────────────────────────────

def init_entity_tables():
    """Cria tabelas de entity resolution. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS entity_resolutions (
                id              SERIAL PRIMARY KEY,
                entity_type     TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                ctx1            TEXT NOT NULL DEFAULT '',
                ctx2            TEXT NOT NULL DEFAULT '',
                af_id           TEXT,
                top_name        TEXT,
                status          TEXT NOT NULL DEFAULT 'unresolved',
                score           FLOAT,
                score_gap       FLOAT,
                score_log       TEXT,
                stale_after     TIMESTAMPTZ,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(entity_type, normalized_name, ctx1, ctx2)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS entity_aliases (
                id             SERIAL PRIMARY KEY,
                entity_type    TEXT NOT NULL,
                alias          TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                af_id          TEXT NOT NULL,
                notes          TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(entity_type, alias)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS entity_overrides (
                id             SERIAL PRIMARY KEY,
                entity_type    TEXT NOT NULL,
                raw_name       TEXT NOT NULL,
                canonical_name TEXT,
                af_id          TEXT NOT NULL,
                reason         TEXT,
                overridden_by  TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(entity_type, raw_name)
            )
        """)


def get_entity_resolution(entity_type: str, normalized_name: str,
                           ctx1: str = "", ctx2: str = "") -> dict | None:
    """Retorna resolução cacheada. None = nunca resolvido. Verifica stale_after."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT af_id, top_name, status, score, score_gap, score_log, stale_after
                FROM entity_resolutions
                WHERE entity_type = %s AND normalized_name = %s
                  AND ctx1 = %s AND ctx2 = %s
            """, (entity_type, normalized_name, ctx1 or "", ctx2 or ""))
            row = c.fetchone()
            if row is None:
                return None
            r = dict(row)
            # Marca como stale se expirou
            if r.get("stale_after") and r["stale_after"] < datetime.now(timezone.utc):
                r["status"] = "stale"
            return r
    except Exception:
        return None


def cache_entity_resolution(entity_type: str, normalized_name: str,
                              ctx1: str, ctx2: str, result) -> None:
    """Salva ou atualiza resultado de resolução no cache DB."""
    try:
        score_log = json.dumps([c.to_dict() for c in result.candidates]) if result.candidates else "[]"
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO entity_resolutions
                    (entity_type, normalized_name, ctx1, ctx2,
                     af_id, top_name, status, score, score_gap, score_log, stale_after, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (entity_type, normalized_name, ctx1, ctx2) DO UPDATE SET
                    af_id       = EXCLUDED.af_id,
                    top_name    = EXCLUDED.top_name,
                    status      = EXCLUDED.status,
                    score       = EXCLUDED.score,
                    score_gap   = EXCLUDED.score_gap,
                    score_log   = EXCLUDED.score_log,
                    stale_after = EXCLUDED.stale_after,
                    updated_at  = NOW()
            """, (
                entity_type, normalized_name, ctx1 or "", ctx2 or "",
                result.af_id, result.top_name, result.status,
                result.score, result.gap,
                score_log,
                result.stale_after,
            ))
    except Exception as e:
        print(f"   ⚠️  cache_entity_resolution error: {e}")


def get_entity_alias(entity_type: str, alias_norm: str) -> dict | None:
    """Retorna alias conhecido para entidade. None = não existe alias."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT af_id, canonical_name, notes
                FROM entity_aliases
                WHERE entity_type = %s AND alias = %s
            """, (entity_type, alias_norm))
            row = c.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def set_entity_alias(entity_type: str, alias: str, canonical_name: str,
                      af_id: str, notes: str = "") -> None:
    """Insere ou atualiza alias de entidade."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO entity_aliases (entity_type, alias, canonical_name, af_id, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (entity_type, alias) DO UPDATE SET
                    canonical_name = EXCLUDED.canonical_name,
                    af_id          = EXCLUDED.af_id,
                    notes          = EXCLUDED.notes
            """, (entity_type, alias, canonical_name, af_id, notes or ""))
    except Exception as e:
        print(f"   ⚠️  set_entity_alias error: {e}")


def get_entity_override(entity_type: str, raw_name: str) -> dict | None:
    """Retorna override manual para entidade. None = sem override."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT af_id, canonical_name, reason
                FROM entity_overrides
                WHERE entity_type = %s AND lower(raw_name) = lower(%s)
            """, (entity_type, raw_name))
            row = c.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def set_entity_override(entity_type: str, raw_name: str, af_id: str,
                         canonical_name: str = "", reason: str = "",
                         overridden_by: str = "admin") -> None:
    """Insere ou atualiza override manual."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO entity_overrides
                    (entity_type, raw_name, af_id, canonical_name, reason, overridden_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_type, raw_name) DO UPDATE SET
                    af_id          = EXCLUDED.af_id,
                    canonical_name = EXCLUDED.canonical_name,
                    reason         = EXCLUDED.reason,
                    overridden_by  = EXCLUDED.overridden_by,
                    created_at     = NOW()
            """, (entity_type, raw_name, af_id, canonical_name or "", reason or "", overridden_by))
    except Exception as e:
        print(f"   ⚠️  set_entity_override error: {e}")


def list_entity_overrides() -> list[dict]:
    """Lista todos os overrides manuais."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT entity_type, raw_name, af_id, canonical_name, reason, created_at
                FROM entity_overrides ORDER BY created_at DESC
            """)
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def list_entity_aliases() -> list[dict]:
    """Lista todos os aliases."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT entity_type, alias, canonical_name, af_id, notes, created_at
                FROM entity_aliases ORDER BY entity_type, alias
            """)
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def invalidate_entity_cache(entity_type: str | None = None) -> int:
    """Marca resoluções como stale para forçar re-resolução. Retorna nº afetados."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            if entity_type:
                c.execute("""
                    UPDATE entity_resolutions SET status = 'stale', stale_after = NOW()
                    WHERE entity_type = %s AND status NOT IN ('manually_resolved')
                """, (entity_type,))
            else:
                c.execute("""
                    UPDATE entity_resolutions SET status = 'stale', stale_after = NOW()
                    WHERE status NOT IN ('manually_resolved')
                """)
            return c.rowcount
    except Exception:
        return 0
# ─────────────────────────────────────────────
#  CACHE DE LOGOS DE CLUBES
# ─────────────────────────────────────────────
