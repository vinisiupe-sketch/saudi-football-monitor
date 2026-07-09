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
    init_transfer_meta()
    init_club_logos()
    init_player_photos()
    init_player_name_cache()
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


def get_transfer_articles_raw() -> list[dict]:
    """Retorna todos os artigos com category IN ('transferencia','sondagem') para reprocessamento."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT * FROM articles
            WHERE category IN ('transferencia', 'sondagem')
            ORDER BY published_at ASC
        """)
        return [dict(r) for r in c.fetchall()]


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

def init_transfer_meta():
    """Cria a tabela transfer_meta. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS transfer_meta (
                article_id         TEXT PRIMARY KEY,
                player_name        TEXT,
                player_position    TEXT,
                player_nationality TEXT,
                club_from          TEXT,
                club_to            TEXT,
                fee                TEXT,
                nego_type          TEXT,
                classified_at      TEXT NOT NULL
            )
        """)
        # Migra colunas ausentes em instâncias existentes (IF NOT EXISTS evita abort de transação)
        for col in ("player_position", "player_nationality",
                    "af_player_id", "af_team_from_id", "af_team_to_id"):
            c.execute(f"ALTER TABLE transfer_meta ADD COLUMN IF NOT EXISTS {col} TEXT")


def upsert_transfer_meta(article_id: str, data: dict):
    """Insere ou atualiza metadados de transferência para um artigo."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO transfer_meta (article_id, player_name, player_position, player_nationality,
                                       club_from, club_to, fee, nego_type, classified_at,
                                       af_player_id, af_team_from_id, af_team_to_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article_id) DO UPDATE SET
                player_name        = EXCLUDED.player_name,
                player_position    = EXCLUDED.player_position,
                player_nationality = EXCLUDED.player_nationality,
                club_from          = EXCLUDED.club_from,
                club_to            = EXCLUDED.club_to,
                fee                = EXCLUDED.fee,
                nego_type          = EXCLUDED.nego_type,
                classified_at      = EXCLUDED.classified_at,
                af_player_id       = COALESCE(EXCLUDED.af_player_id, transfer_meta.af_player_id),
                af_team_from_id    = COALESCE(EXCLUDED.af_team_from_id, transfer_meta.af_team_from_id),
                af_team_to_id      = COALESCE(EXCLUDED.af_team_to_id, transfer_meta.af_team_to_id)
        """, (
            article_id,
            data.get("player_name"),
            data.get("player_position"),
            data.get("player_nationality"),
            data.get("club_from"),
            data.get("club_to"),
            data.get("fee"),
            data.get("nego_type"),
            now,
            data.get("af_player_id") or None,
            data.get("af_team_from_id") or None,
            data.get("af_team_to_id") or None,
        ))


# ─────────────────────────────────────────────
#  CACHE DE LOGOS DE CLUBES
# ─────────────────────────────────────────────

def init_club_logos():
    """Cria tabela de cache de logos de clubes. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS club_logos (
                name_norm  TEXT PRIMARY KEY,
                logo_url   TEXT,
                fetched_at TEXT NOT NULL
            )
        """)


def get_club_logo(name_norm: str) -> str | None:
    """Retorna URL cacheada do logo.
    - str (url ou ''): já foi buscado antes
    - None: nunca buscado
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT logo_url FROM club_logos WHERE name_norm = %s", (name_norm,))
            row = c.fetchone()
            if row is None:
                return None
            return row[0] if row[0] else ""
    except Exception:
        return None


def set_club_logo(name_norm: str, logo_url: str):
    """Armazena URL do logo ('' se não encontrado)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO club_logos (name_norm, logo_url, fetched_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (name_norm) DO UPDATE SET
                    logo_url   = EXCLUDED.logo_url,
                    fetched_at = EXCLUDED.fetched_at
            """, (name_norm, logo_url, now))
    except Exception:
        pass


# ─────────────────────────────────────────────
#  CACHE DE FOTOS DE JOGADORES
# ─────────────────────────────────────────────

def init_player_photos():
    """Cria tabela de cache de fotos de jogadores. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS player_photos (
                name_norm  TEXT PRIMARY KEY,
                photo_url  TEXT,
                fetched_at TEXT NOT NULL
            )
        """)


def get_player_photo(name_norm: str) -> str | None:
    """Retorna URL cacheada da foto.
    - str (url ou ''): já foi buscado antes
    - None: nunca buscado
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT photo_url FROM player_photos WHERE name_norm = %s", (name_norm,))
            row = c.fetchone()
            if row is None:
                return None
            return row[0] if row[0] else ""
    except Exception:
        return None


def set_player_photo(name_norm: str, photo_url: str):
    """Armazena URL da foto ('' se não encontrado)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO player_photos (name_norm, photo_url, fetched_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (name_norm) DO UPDATE SET
                    photo_url  = EXCLUDED.photo_url,
                    fetched_at = EXCLUDED.fetched_at
            """, (name_norm, photo_url, now))
    except Exception:
        pass

# ── Player name cache (normalização via Transfermarkt) ────────────────────────

def init_player_name_cache():
    """Cria tabela de cache de nomes canônicos. Chamado por init_db()."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS player_name_cache (
                name_query TEXT PRIMARY KEY,
                tm_name    TEXT,
                tm_id      TEXT,
                fetched_at TEXT NOT NULL
            )
        """)


def get_player_name_cache(name_query: str) -> str | None:
    """Retorna nome canônico cacheado.
    - None : nunca consultado
    - ''   : consultado mas não encontrado no Transfermarkt
    - str  : nome canônico encontrado
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT tm_name FROM player_name_cache WHERE name_query = %s",
                (name_query,)
            )
            row = c.fetchone()
            if row is None:
                return None
            return row[0] if row[0] is not None else ""
    except Exception:
        return None


def set_player_name_cache(name_query: str, tm_name: str, tm_id: str = ""):
    """Armazena nome canônico ('' se não encontrado no Transfermarkt)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO player_name_cache (name_query, tm_name, tm_id, fetched_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name_query) DO UPDATE SET
                    tm_name    = EXCLUDED.tm_name,
                    tm_id      = EXCLUDED.tm_id,
                    fetched_at = EXCLUDED.fetched_at
            """, (name_query, tm_name, tm_id, now))
    except Exception:
        pass


def get_transfer_articles() -> list[dict]:
    """Retorna artigos de transferência/sondagem de julho de 2026 com metadados classificados pela IA.
    LEFT JOIN — artigos sem classificação ainda são retornados (nego_type=None).
    Se a tabela transfer_meta não existir, cria e retorna lista vazia."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT
                    a.id, a.source_name, a.source_tier, a.url,
                    a.title_pt, a.title_orig, a.body_pt, a.body_orig,
                    a.published_at, a.collected_at, a.relevance_score,
                    tm.player_name, tm.player_position, tm.player_nationality,
                    tm.club_from, tm.club_to,
                    tm.fee, tm.nego_type, tm.classified_at,
                    tm.af_player_id, tm.af_team_from_id, tm.af_team_to_id
                FROM articles a
                LEFT JOIN transfer_meta tm ON a.id = tm.article_id
                WHERE a.category IN ('transferencia', 'sondagem')
                  AND a.published_at >= '2026-07-01'
                ORDER BY a.published_at DESC NULLS LAST
            """)
            return [dict(r) for r in c.fetchall()]
    except Exception as e:
        if "transfer_meta" in str(e) and "does not exist" in str(e):
            init_transfer_meta()
        return []


def make_article_id(url: str, title: str) -> str:
    raw = f"{url}|{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def save_article(article: dict) -> bool:
    with get_conn() as conn:
        c = conn.cursor()
        try:
            article.setdefault("image_url", None)
            article.setdefault("category", None)
            c.execute("""                INSERT INTO articles
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


def update_article_meta(article_id: str, category: str = None, relevance_score: float = None):
    """Atualiza category e/ou relevance_score de um artigo existente."""
    if category is None and relevance_score is None:
        return
    with get_conn() as conn:
        c = conn.cursor()
        if category is not None and relevance_score is not None:
            c.execute(
                "UPDATE articles SET category = %s, relevance_score = %s WHERE id = %s",
                (category, relevance_score, article_id)
            )
        elif category is not None:
            c.execute("UPDATE articles SET category = %s WHERE id = %s", (category, article_id))
        else:
            c.execute("UPDATE articles SET relevance_score = %s WHERE id = %s", (relevance_score, article_id))


def get_low_score_articles(hours: int = 24, limit: int = 200):
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""            SELECT * FROM articles
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
        c.execute("""            INSERT INTO summaries (generated_at, period_start, period_end, summary_pt, article_ids)
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
        c.execute("""            INSERT INTO collection_logs (ran_at, sources_ok, sources_fail, articles_new, articles_dup, error_msg)
            VALUES (%(ran_at)s, %(sources_ok)s, %(sources_fail)s, %(articles_new)s, %(articles_dup)s, %(error_msg)s)
        """, log)


def get_collection_logs(limit: int = 20):
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM collection_logs ORDER BY ran_at DESC LIMIT %s", (limit,))
        return [dict(r) for r in c.fetchall()]
