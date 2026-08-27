"""
Banco de dados PostgreSQL — armazena artigos coletados, resumos e logs.
Usa DATABASE_URL do ambiente (fornecido automaticamente pelo Railway).
"""
import os
import time
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
        # Fila de posts das redes. Genérica de propósito: o tipo diz quem gerou
        # (bola_rolando, fim_de_jogo, janela...), então um formato novo é só um
        # gerador novo, não outra integração.
        #
        # chave_unica é o que impede republicação: um reinício do Railway no meio
        # de uma rodada repetiria os nove jogos sem ela. O UNIQUE está no banco, e
        # não só no código, porque duas instâncias podem tentar ao mesmo tempo.
        c.execute("""
            CREATE TABLE IF NOT EXISTS post_fila (
                id            SERIAL PRIMARY KEY,
                tipo          TEXT NOT NULL,
                chave_unica   TEXT NOT NULL UNIQUE,
                texto         TEXT NOT NULL,
                imagens       TEXT,
                agendado_para TIMESTAMPTZ,
                status        TEXT NOT NULL DEFAULT 'pendente',
                publicado_em  TIMESTAMPTZ,
                post_id       TEXT,
                erro          TEXT,
                criado_em     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_post_fila_status ON post_fila(status, agendado_para)")
        # Escudo e cores de clubes que não vieram no pacote inicial — típico das
        # competições asiáticas. Fica no BANCO, e não em arquivo: o disco do
        # Railway é efêmero e a imagem sumiria no deploy seguinte, sem aviso.
        # A linha nasce quando o gerador encontra um clube desconhecido, então a
        # própria tabela é a lista do que falta preencher.
        c.execute("""
            CREATE TABLE IF NOT EXISTS clubes_extra (
                chave         TEXT PRIMARY KEY,
                nome          TEXT NOT NULL,
                escudo        BYTEA,
                cores         TEXT,
                atualizado_em TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Estatísticas que a API-Football NÃO publica por jogador em certas competições
        # (ex: Super Cup em todas as edições; King's Cup a partir de 2025/26), mas que
        # dá pra apurar partida a partida via escalações + eventos. Guardamos o resultado
        # aqui pra não refazer a apuração a cada consulta — e pra que a competição apareça
        # mesmo quando o agregado do jogador nem menciona que ela existiu.
        # minutos e nota ficam de fora de propósito: não são apuráveis por esse caminho.
        c.execute("""
            CREATE TABLE IF NOT EXISTS stats_apuradas (
                league_id    INTEGER NOT NULL,
                season       INTEGER NOT NULL,
                player_id    INTEGER NOT NULL,
                team_id      INTEGER NOT NULL,
                league_name  TEXT,
                team_name    TEXT,
                player_name  TEXT,
                appearences  INTEGER DEFAULT 0,
                goals        INTEGER DEFAULT 0,
                assists      INTEGER DEFAULT 0,
                yellow_cards INTEGER DEFAULT 0,
                red_cards    INTEGER DEFAULT 0,
                updated_at   TEXT NOT NULL,
                PRIMARY KEY (league_id, season, player_id, team_id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_stats_apuradas_player
            ON stats_apuradas (player_id)
        """)
        # Controle da varredura: guarda quais partidas já foram apuradas, pra que a
        # atualização diária processe só o que é novo em vez de tudo de novo.
        c.execute("""
            CREATE TABLE IF NOT EXISTS partidas_apuradas (
                fixture_id  INTEGER PRIMARY KEY,
                league_id   INTEGER NOT NULL,
                season      INTEGER NOT NULL,
                status      TEXT,
                apurada_em  TEXT NOT NULL
            )
        """)
        # Quais jogos têm transmissão, e por onde.
        #
        # Isto NASCEU como uma linha de texto no fim do post de BOLA ROLANDO, e
        # por um tempo foi só isso. Funcionava para o post e para mais nada: uma
        # linha de texto não responde "quais jogos de amanhã eu comento?" sem
        # alguém sair lendo post por post e reconhecendo emoji. E se o post
        # fosse cancelado, a informação ia junto — apagada por um clique que
        # tinha outra intenção.
        #
        # Aqui a marcação é um fato sobre o JOGO, com vida própria. A linha do
        # post passa a ser um desenho desse fato, não o lugar onde ele mora.
        c.execute("""
            CREATE TABLE IF NOT EXISTS transmissao (
                fixture_id    INTEGER PRIMARY KEY,
                canais        TEXT NOT NULL DEFAULT '[]',
                atualizado_em TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # A escala de arbitragem de cada jogo.
        #
        # Guardar aqui não é cache: é a única cópia. O SAFF publica no dia e
        # depois tira do ar — em datas antigas não há apito em jogo nenhum. O
        # que não for capturado no dia não volta.
        c.execute("""
            CREATE TABLE IF NOT EXISTS arbitragem (
                mid          INTEGER PRIMARY KEY,
                dia          DATE NOT NULL,
                hora         TEXT,
                competicao   TEXT,
                casa         TEXT,
                fora         TEXT,
                papeis       TEXT NOT NULL,
                capturado_em TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_arbitragem_dia ON arbitragem(dia)")
        # Como o SAFF escreve o nome × como o canal escreve.
        #
        # A linha nasce na primeira vez que o árbitro aparece, com nome vazio.
        # Ou seja: a própria tabela é a lista do que falta traduzir, e ela se
        # preenche sozinha à medida que os árbitros aparecem. Não existe
        # cadastro inicial para fazer.
        c.execute("""
            CREATE TABLE IF NOT EXISTS arbitro_nome (
                chave     TEXT PRIMARY KEY,
                saff      TEXT NOT NULL,
                nome      TEXT,
                pais      TEXT,
                vezes     INTEGER NOT NULL DEFAULT 1,
                visto_em  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # A prévia de cada jogo com transmissão.
        #
        # Guarda os FATOS junto com o texto, e não só o texto. Assim dá para
        # conferir depois de onde saiu cada número, e para reescrever a prévia
        # sem consultar de novo uma API que talvez já tenha mudado a resposta.
        #
        # `numeros_suspeitos` é a lista dos números do texto que eu não achei
        # nos fatos. Fica gravada junto: um aviso que só existe na hora de
        # gerar é um aviso que some justamente quando você vai ler.
        c.execute("""
            CREATE TABLE IF NOT EXISTS previa (
                chave        TEXT PRIMARY KEY,
                dia          DATE NOT NULL,
                casa         TEXT,
                fora         TEXT,
                quando       TIMESTAMPTZ,
                competicao   TEXT,
                texto        TEXT NOT NULL,
                fatos        TEXT,
                suspeitos    TEXT,
                escalacao    TEXT,
                gerado_em    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_previa_dia ON previa(dia)")
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
    """Retorna artigos recentes ordenados por published_at DESC.

    Exige title_pt: artigos guardados sem tradução (fora das categorias ativas)
    ficam no banco mas não vão pra tela."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if tier:
            c.execute(
                """
                SELECT * FROM articles
                WHERE is_duplicate = 0
                  AND title_pt IS NOT NULL
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
                  AND title_pt IS NOT NULL
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
              AND relevance_score < 0.45
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


CATEGORIAS_ATIVAS_KEY = "categorias_ativas"
TODAS_CATEGORIAS = ["mercado", "lesao", "competicao", "entrevista", "treino", "financas", "geral"]


def get_categorias_ativas() -> list[str]:
    """Categorias que hoje merecem tradução. Lista vazia = todas (sem triagem).

    Fica no banco, não no código, pra você abrir e fechar a janela pelo botão da
    interface sem depender de deploy."""
    import json as _json
    try:
        raw = get_state(CATEGORIAS_ATIVAS_KEY)
        if not raw:
            return []
        cats = _json.loads(raw)
        return [c for c in cats if c in TODAS_CATEGORIAS] if isinstance(cats, list) else []
    except Exception:
        return []


def set_categorias_ativas(cats: list[str]) -> list[str]:
    """Grava as categorias ativas. Lista vazia (ou todas marcadas) desliga a triagem."""
    import json as _json
    validas = [c for c in (cats or []) if c in TODAS_CATEGORIAS]
    if len(validas) == len(TODAS_CATEGORIAS):
        validas = []  # todas marcadas = sem filtro, e sem custo de triagem
    set_state(CATEGORIAS_ATIVAS_KEY, _json.dumps(validas))
    return validas


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
        c.execute("""
            CREATE TABLE IF NOT EXISTS window_transfers (
                id              TEXT PRIMARY KEY,
                player_id       TEXT,
                player_name     TEXT NOT NULL,
                photo           TEXT,
                age             TEXT,
                position        TEXT,
                market_value    TEXT,
                fee             TEXT,
                team_in_name    TEXT,
                team_in_logo    TEXT,
                team_out_name   TEXT,
                team_out_logo   TEXT,
                direction       TEXT NOT NULL DEFAULT 'in',
                transfer_date   DATE,
                nationality     TEXT,
                scraped_at      TIMESTAMPTZ DEFAULT NOW(),
                first_seen_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("ALTER TABLE window_transfers ADD COLUMN IF NOT EXISTS transfer_date DATE")
        c.execute("ALTER TABLE window_transfers ADD COLUMN IF NOT EXISTS nationality TEXT")
        c.execute("ALTER TABLE window_transfers ADD COLUMN IF NOT EXISTS flag_url TEXT")
        c.execute("ALTER TABLE window_transfers ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ DEFAULT NOW()")
        c.execute("""
            CREATE TABLE IF NOT EXISTS janela_player_photos (
                player_id  TEXT PRIMARY KEY,
                photo_url  TEXT,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
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


# ── Window Transfers (Janela de Transferências) ──────────────────────────────

def clear_window_transfers() -> None:
    """Remove todos os registros da tabela (para re-scrape limpo)."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM window_transfers")


def upsert_window_transfers(transfers: list[dict]) -> tuple[int, list[str]]:
    """Insere/atualiza lista de transferências.

    Retorna (quantidade_upserted, lista_de_ids).
    first_seen_at só é definido no INSERT — nunca sobrescrito no UPDATE,
    para que a ordenação por 'mais recentes' reflita quando cada jogador
    apareceu pela primeira vez na janela do TM.
    """
    if not transfers:
        return 0, []
    import hashlib
    ids: list[str] = []
    with get_conn() as conn:
        c = conn.cursor()
        for t in transfers:
            key = f"{t.get('player_id','')}_{t.get('direction','')}_{t.get('team_in',{}).get('name','')}"
            tid = hashlib.md5(key.encode()).hexdigest()[:16]
            ids.append(tid)
            c.execute("""
                INSERT INTO window_transfers
                    (id, player_id, player_name, photo, age, position,
                     market_value, fee, team_in_name, team_in_logo,
                     team_out_name, team_out_logo, direction, transfer_date,
                     nationality, flag_url, scraped_at, first_seen_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                ON CONFLICT (id) DO UPDATE SET
                    player_name   = EXCLUDED.player_name,
                    photo         = EXCLUDED.photo,
                    age           = EXCLUDED.age,
                    position      = EXCLUDED.position,
                    market_value  = EXCLUDED.market_value,
                    fee           = EXCLUDED.fee,
                    team_in_name  = EXCLUDED.team_in_name,
                    team_in_logo  = EXCLUDED.team_in_logo,
                    team_out_name = EXCLUDED.team_out_name,
                    team_out_logo = EXCLUDED.team_out_logo,
                    transfer_date = EXCLUDED.transfer_date,
                    nationality   = EXCLUDED.nationality,
                    flag_url      = EXCLUDED.flag_url,
                    scraped_at    = NOW()
                    -- first_seen_at NÃO é atualizado: preserva data original
            """, [
                tid,
                t.get("player_id"), t.get("player_name", ""),
                t.get("photo"), t.get("age"), t.get("position"),
                t.get("market_value"), t.get("fee"),
                t.get("team_in", {}).get("name"), t.get("team_in", {}).get("logo"),
                t.get("team_out", {}).get("name"), t.get("team_out", {}).get("logo"),
                t.get("direction", "in"), t.get("transfer_date"),
                t.get("nationality"), t.get("flag_url"),
            ])
    return len(ids), ids


def delete_stale_window_transfers(current_ids: list[str]) -> int:
    """Remove transferências que não apareceram na raspagem atual (saíram do TM)."""
    if not current_ids:
        return 0
    with get_conn() as conn:
        c = conn.cursor()
        placeholders = ",".join(["%s"] * len(current_ids))
        c.execute(
            f"DELETE FROM window_transfers WHERE id NOT IN ({placeholders})",
            current_ids,
        )
        return c.rowcount


def get_window_transfers() -> list[dict]:
    """Retorna todas as transferências da janela — mais recentes primeiro (first_seen_at DESC)."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""
                SELECT id, player_id, player_name, photo, age, position,
                       market_value, fee, team_in_name, team_in_logo,
                       team_out_name, team_out_logo, direction,
                       transfer_date::text, nationality, flag_url,
                       scraped_at::text, first_seen_at::text
                FROM window_transfers
                ORDER BY first_seen_at DESC NULLS LAST, player_name
            """)
            rows = c.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_window_transfers_last_scraped() -> str | None:
    """Retorna o timestamp da última raspagem, ou None."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT MAX(scraped_at) FROM window_transfers")
            row = c.fetchone()
        return row[0].isoformat() if row and row[0] else None
    except Exception:
        return None


def get_janela_player_photos() -> dict:
    """Retorna mapa {player_id → photo_url} do cache de fotos."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT player_id, photo_url FROM janela_player_photos WHERE photo_url IS NOT NULL")
            return {row[0]: row[1] for row in c.fetchall()}
    except Exception:
        return {}


def upsert_janela_player_photo(player_id: str, photo_url: str) -> None:
    """Salva/atualiza foto de um jogador no cache."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO janela_player_photos (player_id, photo_url, fetched_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (player_id) DO UPDATE SET photo_url = EXCLUDED.photo_url, fetched_at = NOW()
            """, [player_id, photo_url])
    except Exception:
        pass


# ─── Estatísticas apuradas por nós (competições sem cobertura da API) ─────────

def salvar_stats_apuradas(linhas: list[dict]) -> int:
    """Grava/atualiza os totais apurados de uma competição.

    Sobrescreve o total do jogador naquela (liga, temporada, time) em vez de somar:
    a varredura recalcula sempre a partir de todas as partidas conhecidas, então o
    valor que chega aqui já é o total correto. Somar causaria inflação a cada rodada."""
    if not linhas:
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    gravadas = 0
    with get_conn() as conn:
        c = conn.cursor()
        for l in linhas:
            c.execute("""
                INSERT INTO stats_apuradas (
                    league_id, season, player_id, team_id, league_name, team_name,
                    player_name, appearences, goals, assists, yellow_cards, red_cards, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (league_id, season, player_id, team_id) DO UPDATE SET
                    league_name  = EXCLUDED.league_name,
                    team_name    = EXCLUDED.team_name,
                    player_name  = EXCLUDED.player_name,
                    appearences  = EXCLUDED.appearences,
                    goals        = EXCLUDED.goals,
                    assists      = EXCLUDED.assists,
                    yellow_cards = EXCLUDED.yellow_cards,
                    red_cards    = EXCLUDED.red_cards,
                    updated_at   = EXCLUDED.updated_at
            """, [
                l["league_id"], l["season"], l["player_id"], l["team_id"],
                l.get("league_name"), l.get("team_name"), l.get("player_name"),
                l.get("appearences", 0), l.get("goals", 0), l.get("assists", 0),
                l.get("yellow_cards", 0), l.get("red_cards", 0), agora,
            ])
            gravadas += 1
    return gravadas


def get_stats_apuradas_do_jogador(player_id: int) -> list[dict]:
    """Todas as linhas apuradas por nós para um jogador."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("SELECT * FROM stats_apuradas WHERE player_id = %s", [player_id])
            return [dict(r) for r in c.fetchall()]
    except Exception:
        return []


def get_partidas_ja_apuradas(league_id: int, season: int) -> dict:
    """{fixture_id: status} das partidas já processadas — permite varredura incremental."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT fixture_id, status FROM partidas_apuradas WHERE league_id = %s AND season = %s",
                [league_id, season],
            )
            return {row[0]: row[1] for row in c.fetchall()}
    except Exception:
        return {}


def marcar_partidas_apuradas(fixtures: list[tuple]) -> None:
    """fixtures = [(fixture_id, league_id, season, status), ...]"""
    if not fixtures:
        return
    agora = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        c = conn.cursor()
        for fid, lid, season, status in fixtures:
            c.execute("""
                INSERT INTO partidas_apuradas (fixture_id, league_id, season, status, apurada_em)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (fixture_id) DO UPDATE SET
                    status = EXCLUDED.status, apurada_em = EXCLUDED.apurada_em
            """, [fid, lid, season, status, agora])


def filtrar_artigos_ja_salvos(articles: list[dict]) -> tuple[list, int]:
    """Separa os artigos que já estão no banco, ANTES de gastar scraping e tradução.

    Motivo: a pipeline roda a cada 30 min com janela de algumas horas, então o mesmo
    tweet volta a ser coletado várias vezes. Antes, o descarte só acontecia no
    save_article — depois de já ter raspado o artigo e pago a tradução. Medido nos
    logs de 20 execuções reais: 19 artigos novos contra 186 duplicados, ou seja
    ~91% das traduções eram jogadas no lixo.

    Retorna (novos, quantidade_descartada)."""
    if not articles:
        return [], 0
    ids = [a["id"] for a in articles if a.get("id")]
    urls = [a["url"] for a in articles if a.get("url")]
    existentes_id, existentes_url = set(), set()
    try:
        with get_conn() as conn:
            c = conn.cursor()
            if ids:
                c.execute("SELECT id FROM articles WHERE id = ANY(%s)", [ids])
                existentes_id = {r[0] for r in c.fetchall()}
            if urls:
                c.execute("SELECT url FROM articles WHERE url = ANY(%s)", [urls])
                existentes_url = {r[0] for r in c.fetchall()}
    except Exception:
        # Se a consulta falhar, segue o fluxo antigo: melhor pagar a tradução do que
        # perder artigo novo por causa de um problema momentâneo no banco.
        return articles, 0
    novos = [
        a for a in articles
        if a.get("id") not in existentes_id and (a.get("url") or "") not in existentes_url
    ]
    return novos, len(articles) - len(novos)


# ─── Fila de posts das redes ──────────────────────────────────────────────────

def enfileirar_post(tipo: str, chave_unica: str, texto: str,
                    imagens: list[str] | None = None,
                    agendado_para=None) -> str:
    """Coloca um post na fila. Devolve 'novo', 'ja_existia' ou 'erro: ...'.

    Idempotente por chave_unica: chamar de novo com a mesma chave não duplica.
    É isso que permite o gerador rodar a cada poucos minutos sem medo.

    A única coisa que um reenvio atualiza é a lista de imagens, e só enquanto o
    post ainda está pendente ou aprovado. O texto nunca — ele pode ter sido
    editado por você, e sobrescrever apagaria a transmissão que você marcou.
    A exceção das imagens existe porque elas são dado derivado: posts montados
    antes de o cadastro de escudos existir ficaram com a lista incompleta, sem
    sequer a referência do escudo que faltava, e sem isso a tela não tem como
    saber que há um escudo a subir. Remontar o dia conserta.

    Devolve 'novo', 'escudos_atualizados' ou 'ja_existia'.
    """
    import json as _json
    try:
        with get_conn() as conn:
            c = conn.cursor()
            imgs = _json.dumps(imagens or [], ensure_ascii=False)
            c.execute("SELECT status FROM post_fila WHERE chave_unica = %s", [chave_unica])
            atual = c.fetchone()

            if atual is None:
                # DO NOTHING continua aqui por causa da corrida: se outro
                # processo inserir entre o SELECT acima e este INSERT, o certo
                # é não fazer nada, não estourar.
                c.execute("""
                    INSERT INTO post_fila (tipo, chave_unica, texto, imagens, agendado_para)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (chave_unica) DO NOTHING
                    RETURNING id
                """, [tipo, chave_unica, texto, imgs, agendado_para])
                return "novo" if c.fetchone() else "ja_existia"

            if atual[0] in ("pendente", "aprovado"):
                c.execute("""UPDATE post_fila SET imagens = %s
                              WHERE chave_unica = %s
                                AND imagens IS DISTINCT FROM %s""",
                          [imgs, chave_unica, imgs])
                if c.rowcount:
                    return "escudos_atualizados"
            return "ja_existia"
    except Exception as e:
        return f"erro: {type(e).__name__}: {e}"


def listar_posts(status: str | None = None, limite: int = 60) -> list[dict]:
    import json as _json
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if status:
                c.execute("""SELECT * FROM post_fila WHERE status = %s
                             ORDER BY agendado_para NULLS LAST, id LIMIT %s""", [status, limite])
            else:
                c.execute("""SELECT * FROM post_fila
                             ORDER BY agendado_para DESC NULLS LAST, id DESC LIMIT %s""", [limite])
            linhas = [dict(r) for r in c.fetchall()]
    except Exception:
        return []
    for l in linhas:
        try:
            l["imagens"] = _json.loads(l.get("imagens") or "[]")
        except Exception:
            l["imagens"] = []
        for campo in ("agendado_para", "publicado_em", "criado_em"):
            if l.get(campo):
                l[campo] = l[campo].isoformat()
    return linhas


def salvar_previa(p: dict) -> bool:
    """Grava (ou regrava) a prévia de um jogo.

    Regravar é o caso normal, não a exceção: a prévia nasce na véspera com
    escalação provável e é reescrita quando a oficial sai. Por isso o UPDATE
    troca tudo — inclusive o campo `escalacao`, que é como a tela sabe se está
    olhando uma dedução ou um fato.
    """
    import json as _json
    chave = (p.get("chave") or "").strip()
    if not chave or not (p.get("texto") or "").strip():
        return False
    try:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO previa (chave, dia, casa, fora, quando, competicao,
                                    texto, fatos, suspeitos, escalacao, gerado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (chave) DO UPDATE SET
                    dia=EXCLUDED.dia, casa=EXCLUDED.casa, fora=EXCLUDED.fora,
                    quando=EXCLUDED.quando, competicao=EXCLUDED.competicao,
                    texto=EXCLUDED.texto, fatos=EXCLUDED.fatos,
                    suspeitos=EXCLUDED.suspeitos, escalacao=EXCLUDED.escalacao,
                    gerado_em=NOW()
            """, [chave, p.get("dia"), p.get("casa") or "", p.get("fora") or "",
                  p.get("quando"), p.get("competicao") or "", p["texto"],
                  _json.dumps(p.get("fatos") or {}, ensure_ascii=False, default=str),
                  _json.dumps(p.get("suspeitos") or [], ensure_ascii=False),
                  p.get("escalacao") or ""])
        return True
    except Exception as e:
        print(f"⚠️ salvar_previa({chave}): {e}")
        return False


def previas_do_dia(dia: str) -> list[dict]:
    import json as _json
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("SELECT * FROM previa WHERE dia = %s ORDER BY quando NULLS LAST, casa",
                      [dia])
            linhas = [dict(r) for r in c.fetchall()]
    except Exception as e:
        print(f"⚠️ previas_do_dia({dia}): {e}")
        return []
    for l in linhas:
        for campo in ("fatos", "suspeitos"):
            try:
                l[campo] = _json.loads(l.get(campo) or ("[]" if campo == "suspeitos" else "{}"))
            except Exception:
                l[campo] = [] if campo == "suspeitos" else {}
        for campo in ("dia", "quando", "gerado_em"):
            if l.get(campo) is not None:
                l[campo] = l[campo].isoformat()
    return linhas


def dias_com_previa(limite: int = 30) -> list[dict]:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""SELECT dia, COUNT(*) FROM previa
                         GROUP BY dia ORDER BY dia DESC LIMIT %s""", [limite])
            return [{"dia": d.isoformat(), "jogos": n} for d, n in c.fetchall()]
    except Exception as e:
        print(f"⚠️ dias_com_previa: {e}")
        return []


def previa_com_escalacao(chave: str) -> str:
    """Se esta prévia já foi escrita com escalação oficial, não precisa refazer."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT escalacao FROM previa WHERE chave = %s", [chave])
            linha = c.fetchone()
            return (linha[0] or "") if linha else ""
    except Exception:
        return ""


def salvar_arbitragem(jogos: list[dict]) -> int:
    """Guarda a escala de cada jogo e registra os árbitros vistos.

    Reescreve por cima quando o mesmo jogo volta: o SAFF corrige escala em
    cima da hora, e a correção é que vale. O ON CONFLICT do glossário NÃO
    toca no campo `nome` — se sobrescrevesse, cada nova aparição do árbitro
    apagaria a grafia que você tinha acabado de definir.
    """
    import json as _json
    if not jogos:
        return 0
    gravados = 0
    try:
        with get_conn() as conn:
            c = conn.cursor()
            for j in jogos:
                if j.get("mid") is None:
                    continue
                c.execute("""
                    INSERT INTO arbitragem
                        (mid, dia, hora, competicao, casa, fora, papeis, capturado_em)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (mid) DO UPDATE SET
                        dia = EXCLUDED.dia, hora = EXCLUDED.hora,
                        competicao = EXCLUDED.competicao,
                        casa = EXCLUDED.casa, fora = EXCLUDED.fora,
                        papeis = EXCLUDED.papeis, capturado_em = NOW()
                """, [int(j["mid"]), j.get("dia"), j.get("hora") or "",
                      j.get("competicao") or "", j.get("casa") or "",
                      j.get("fora") or "",
                      _json.dumps(j.get("papeis") or [], ensure_ascii=False)])
                gravados += 1
                for p in (j.get("papeis") or []):
                    import arbitragem as _arb
                    bruto = " ".join((p.get("nome_saff") or "").split())
                    chave = _arb.chave_do_arbitro(bruto)
                    if not chave:
                        continue
                    c.execute("""
                        INSERT INTO arbitro_nome (chave, saff, pais, vezes, visto_em)
                        VALUES (%s, %s, %s, 1, NOW())
                        ON CONFLICT (chave) DO UPDATE SET
                            saff = EXCLUDED.saff, pais = EXCLUDED.pais,
                            vezes = arbitro_nome.vezes + 1, visto_em = NOW()
                    """, [chave, bruto, p.get("pais") or ""])
    except Exception as e:
        print(f"⚠️ salvar_arbitragem: {e}")
        return 0
    return gravados


def arbitragem_do_dia(dia: str) -> list[dict]:
    """A escala guardada para esta data, na ordem dos jogos."""
    import json as _json
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("""SELECT * FROM arbitragem WHERE dia = %s
                         ORDER BY hora NULLS LAST, mid""", [dia])
            linhas = [dict(r) for r in c.fetchall()]
    except Exception as e:
        print(f"⚠️ arbitragem_do_dia({dia}): {e}")
        return []
    for l in linhas:
        try:
            l["papeis"] = _json.loads(l.get("papeis") or "[]")
        except Exception:
            l["papeis"] = []
        for campo in ("dia", "capturado_em"):
            if l.get(campo) is not None:
                l[campo] = l[campo].isoformat()
    return linhas


def dias_com_arbitragem(limite: int = 30) -> list[dict]:
    """As datas que já foram capturadas, da mais nova para a mais velha."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""SELECT dia, COUNT(*) FROM arbitragem
                         GROUP BY dia ORDER BY dia DESC LIMIT %s""", [limite])
            return [{"dia": d.isoformat(), "jogos": n} for d, n in c.fetchall()]
    except Exception as e:
        print(f"⚠️ dias_com_arbitragem: {e}")
        return []


def nomes_de_arbitros(so_faltando: bool = False) -> list[dict]:
    """O glossário de árbitros. Os mais frequentes primeiro — traduzir esses
    primeiro é o que mais rende."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql = "SELECT chave, saff, nome, pais, vezes FROM arbitro_nome"
            if so_faltando:
                sql += " WHERE nome IS NULL OR nome = ''"
            sql += " ORDER BY vezes DESC, saff"
            c.execute(sql)
            return [dict(r) for r in c.fetchall()]
    except Exception as e:
        print(f"⚠️ nomes_de_arbitros: {e}")
        return []


def traducoes_de_arbitros() -> dict[str, str]:
    """Só o que já foi traduzido, pronto para consulta rápida na montagem."""
    return {r["chave"]: r["nome"] for r in nomes_de_arbitros()
            if (r.get("nome") or "").strip()}


def definir_nome_de_arbitro(chave: str, nome: str) -> bool:
    """Grava a grafia do canal para este árbitro. Nome vazio volta a pendente."""
    chave = (chave or "").strip()
    if not chave:
        return False
    nome = " ".join((nome or "").split())
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE arbitro_nome SET nome = %s WHERE chave = %s",
                      [nome or None, chave])
            return c.rowcount > 0
    except Exception as e:
        print(f"⚠️ definir_nome_de_arbitro: {e}")
        return False


def marcar_transmissao(fixture_id, canais: list[str]) -> bool:
    """Grava por onde este jogo passa. Lista vazia = marcado como sem transmissão.

    Repare que lista vazia NÃO é o mesmo que linha ausente. Linha ausente quer
    dizer "ninguém olhou este jogo ainda"; lista vazia quer dizer "olhei, e não
    tem transmissão". Quem for perguntar depois precisa dessa diferença — senão
    um jogo esquecido e um jogo sem transmissão viram a mesma coisa.
    """
    import json as _json
    try:
        fid = int(fixture_id)
    except (TypeError, ValueError):
        return False
    try:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO transmissao (fixture_id, canais, atualizado_em)
                VALUES (%s, %s, NOW())
                ON CONFLICT (fixture_id) DO UPDATE
                   SET canais = EXCLUDED.canais, atualizado_em = NOW()
            """, [fid, _json.dumps(list(canais or []), ensure_ascii=False)])
        return True
    except Exception as e:
        print(f"⚠️ marcar_transmissao({fixture_id}): {e}")
        return False


def transmissao_do_jogo(fixture_id) -> list[str] | None:
    """Os canais deste jogo, [] se marcado sem transmissão, None se nunca marcado."""
    import json as _json
    try:
        fid = int(fixture_id)
    except (TypeError, ValueError):
        return None
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT canais FROM transmissao WHERE fixture_id = %s", [fid])
            linha = c.fetchone()
    except Exception:
        return None
    if not linha:
        return None
    try:
        return list(_json.loads(linha[0] or "[]"))
    except Exception:
        return []


def transmissoes(fixture_ids: list) -> dict[int, list[str]]:
    """Vários de uma vez. Só devolve os que foram marcados."""
    import json as _json
    ids = []
    for f in (fixture_ids or []):
        try:
            ids.append(int(f))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT fixture_id, canais FROM transmissao "
                      "WHERE fixture_id = ANY(%s::int[])", [ids])
            linhas = c.fetchall()
    except Exception as e:
        print(f"⚠️ transmissoes: {e}")
        return {}
    saida = {}
    for fid, canais in linhas:
        try:
            saida[int(fid)] = list(_json.loads(canais or "[]"))
        except Exception:
            saida[int(fid)] = []
    return saida


def jogos_com_transmissao() -> list[int]:
    """Só os que têm ao menos um canal. Os marcados como sem transmissão ficam
    de fora — eles foram olhados, e a resposta foi não."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT fixture_id FROM transmissao "
                      "WHERE canais <> '[]' AND canais <> '' ORDER BY fixture_id")
            return [int(r[0]) for r in c.fetchall()]
    except Exception as e:
        print(f"⚠️ jogos_com_transmissao: {e}")
        return []


def obter_post(post_fila_id: int) -> dict | None:
    itens = [p for p in listar_posts(limite=500) if p["id"] == post_fila_id]
    return itens[0] if itens else None


def atualizar_texto_post(post_fila_id: int, texto: str) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            # Só mexe no que ainda não foi publicado: post no ar não se reescreve.
            c.execute("UPDATE post_fila SET texto = %s WHERE id = %s AND status = 'pendente'",
                      [texto, post_fila_id])
            return c.rowcount > 0
    except Exception:
        return False


def marcar_post(post_fila_id: int, status: str, post_id: str | None = None,
                erro: str | None = None) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE post_fila
                   SET status = %s,
                       post_id = COALESCE(%s, post_id),
                       erro = %s,
                       publicado_em = CASE WHEN %s = 'publicado' THEN NOW() ELSE publicado_em END
                 WHERE id = %s
            """, [status, post_id, erro, status, post_fila_id])
            return c.rowcount > 0
    except Exception:
        return False


def expirar_posts_vencidos(minutos: int = 30) -> int:
    """Descarta post cuja partida já começou e que continua parado na fila.

    Existe porque um BOLA ROLANDO de ontem não serve para nada e, pior, fica
    disputando atenção com os de hoje na tela de aprovação. Só toca em
    'pendente' e 'aprovado' — publicado, cancelado e falho ficam como estão,
    porque neles o status já é o registro do que aconteceu.

    A margem de 30 minutos vem depois da regra do publicador, não em cima
    dela: até 25 min de atraso ele ainda publica; passando disso ele devolve
    o post para 'pendente'; só a partir dos 30 é que esta varredura desiste.
    Com 20 min as duas regras se contradiziam entre o minuto 20 e o 25 — uma
    cancelando o que a outra ainda tentava publicar."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE post_fila
                   SET status = 'cancelado',
                       erro = 'a partida começou antes de o post sair'
                 WHERE status IN ('pendente', 'aprovado')
                   AND agendado_para IS NOT NULL
                   AND agendado_para < NOW() - (%s * INTERVAL '1 minute')
            """, [minutos])
            return c.rowcount
    except Exception:
        return 0


def reservar_post_para_publicar(post_fila_id: int, de: str = "pendente") -> bool:
    """Marca como 'publicando' só se ainda estiver 'pendente'.

    A condição no próprio UPDATE é o que evita publicação dupla: se dois cliques
    (ou duas instâncias) chegarem juntos, só um encontra o registro pendente.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""UPDATE post_fila SET status = 'publicando'
                          WHERE id = %s AND status = %s""", [post_fila_id, de])
            return c.rowcount == 1
    except Exception:
        return False


def contar_publicados_hoje() -> int:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""SELECT COUNT(*) FROM post_fila
                          WHERE status = 'publicado' AND publicado_em >= NOW() - INTERVAL '24 hours'""")
            return int(c.fetchone()[0])
    except Exception:
        return 0


# ─── Clubes sem escudo/cores no pacote inicial ────────────────────────────────

def salvar_clube_extra(chave: str, nome: str | None = None,
                       escudo: bytes | None = None, cores: str | None = None) -> bool:
    """Grava escudo e/ou cores. Campo não informado permanece como está."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO clubes_extra (chave, nome, escudo, cores)
                VALUES (%s, COALESCE(%s, %s), %s, %s)
                ON CONFLICT (chave) DO UPDATE SET
                    nome   = COALESCE(EXCLUDED.nome, clubes_extra.nome),
                    escudo = COALESCE(EXCLUDED.escudo, clubes_extra.escudo),
                    cores  = COALESCE(EXCLUDED.cores,  clubes_extra.cores),
                    atualizado_em = NOW()
            """, [chave, nome, chave,
                  psycopg2.Binary(escudo) if escudo else None, cores])
            return True
    except Exception:
        return False


def obter_escudo_extra(chave: str) -> bytes | None:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT escudo FROM clubes_extra WHERE chave = %s", [chave])
            linha = c.fetchone()
            return bytes(linha[0]) if linha and linha[0] else None
    except Exception:
        return None


def _cria_gol_visto(c) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS gol_visto (
            id           SERIAL PRIMARY KEY,
            fixture_af   BIGINT,
            fixture_sm   BIGINT,
            fonte        TEXT NOT NULL,
            chave_gol    TEXT NOT NULL,
            minuto       INTEGER,
            autor        TEXT,
            assistente   TEXT,
            placar       TEXT,
            texto        TEXT,
            visto_em     TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (fonte, chave_gol)
        )
    """)


def registrar_gol(fonte: str, chave_gol: str, minuto=None, autor=None,
                  assistente=None, placar=None, texto=None,
                  fixture_af=None, fixture_sm=None) -> bool:
    """Grava o PRIMEIRO instante em que uma fonte mostrou este gol.

    O UNIQUE em (fonte, chave_gol) é o que faz a medição valer: a segunda vez
    que a mesma fonte reportar o mesmo gol não sobrescreve o horário. Sem isso
    eu estaria medindo a hora da última consulta, não a da descoberta.

    Devolve True só quando é a primeira vez — ou seja, quando é notícia.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_gol_visto(c)
            c.execute("""
                INSERT INTO gol_visto (fonte, chave_gol, minuto, autor, assistente,
                                       placar, texto, fixture_af, fixture_sm)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fonte, chave_gol) DO NOTHING
                RETURNING id
            """, [fonte, chave_gol, minuto, autor, assistente, placar, texto,
                  fixture_af, fixture_sm])
            return c.fetchone() is not None
    except Exception:
        return False


def gols_vistos(desde_horas: int = 6) -> list[dict]:
    """Gols carimbados nas últimas horas, das duas fontes."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_gol_visto(c)
            c.execute("""
                SELECT * FROM gol_visto
                 WHERE visto_em > NOW() - (%s * INTERVAL '1 hour')
                 ORDER BY visto_em DESC
            """, [desde_horas])
            linhas = [dict(r) for r in c.fetchall()]
        for l in linhas:
            if l.get("visto_em"):
                l["visto_em"] = l["visto_em"].isoformat()
        return linhas
    except Exception:
        return []


def tem_escudo_extra(chave: str) -> bool:
    """Só diz SE existe escudo, sem trazer os bytes.

    A tela pergunta isso para cada clube de cada post; usar obter_escudo_extra
    aqui arrastaria centenas de KB de imagem por carregamento só para decidir
    se desenha um quadrado vazio."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT escudo IS NOT NULL FROM clubes_extra WHERE chave = %s", [chave])
            l = c.fetchone()
            return bool(l and l[0])
    except Exception:
        return False


def status_das_chaves(chaves: list[str]) -> dict[str, str]:
    """Status atual de cada chave_unica pedida. Serve para a agenda saber
    quais jogos da semana já estão na fila sem baixar a fila inteira."""
    if not chaves:
        return {}
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT chave_unica, status FROM post_fila WHERE chave_unica = ANY(%s)",
                      [list(chaves)])
            return {l[0]: l[1] for l in c.fetchall()}
    except Exception:
        return {}





# ══════════════════════════════════════════════════════════════════════════
# CLIPES DE GOL
#
# O fluxo tem três máquinas: você aperta GOL AGORA no celular, o agente que
# grava a live em casa consulta esta tabela e devolve o recorte, e o servidor
# publica. Nenhuma delas fala com a outra diretamente — o banco é o encontro.
#
# alvo_em é hora de RELÓGIO, absoluta, e não posição no vídeo. É de propósito:
# o agente sabe a que horas começou a gravar, então converte sozinho. Se eu
# mandasse posição, teria que saber o instante em que a gravação começou, que
# é justamente o que muda a cada partida.
# ══════════════════════════════════════════════════════════════════════════

ESTADOS_CLIPE = ("pedido", "cortando", "pronto", "publicando", "publicado", "erro")


# ══════════════════════════════════════════════════════════════════════════
# ONDE MORA O VÍDEO DO CLIPE
#
# Em disco, não no banco. A versão anterior guardava o mp4 numa coluna BYTEA:
# treze megabytes por clipe, atravessando o diário de transações do Postgres.
# Vinte e sete clipes num dia e o banco caiu, ficou meia hora refazendo o
# diário, e o app inteiro foi junto.
#
# Banco relacional não é lugar de vídeo. O que fica na tabela agora é o
# tamanho e o nome do arquivo; o conteúdo fica aqui.
#
# O disco do contêiner é EFÊMERO — um redeploy leva os arquivos embora. Para
# este uso serve: o clipe nasce, você olha, publica ou baixa, tudo em minutos.
# Se um redeploy pegar um clipe no meio do caminho, o pior que acontece é você
# apertar o botão de novo. Perder um clipe é bem melhor que derrubar o banco.
# Dá para apontar CLIPES_DIR para um volume do Railway se um dia isso pesar.
PASTA_CLIPES = os.environ.get("CLIPES_DIR", "").strip() or "/tmp/clipes"
HORAS_GUARDA_CLIPE = 12


def _caminho_do_clipe(clipe_id: int) -> str:
    return os.path.join(PASTA_CLIPES, f"clipe_{int(clipe_id)}.mp4")


def _limpar_clipes_velhos() -> None:
    """Apaga mp4 que ninguém vai mais querer. Nunca levanta."""
    try:
        limite = time.time() - HORAS_GUARDA_CLIPE * 3600
        for nome in os.listdir(PASTA_CLIPES):
            caminho = os.path.join(PASTA_CLIPES, nome)
            if nome.endswith(".mp4") and os.path.getmtime(caminho) < limite:
                os.remove(caminho)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# QUANTO O BANCO ESTÁ OCUPANDO
#
# O volume encheu e ninguém soube até tudo parar. Não foi só o vídeo dentro do
# banco que causou isso — foi não haver nenhum lugar dizendo "está em 80%".
# Tirar o vídeo impede a causa conhecida; este medidor é para a próxima, que
# vai ser outra coisa.
#
# O teto vem de variável porque quem sabe o tamanho do volume é o Railway, não
# o Postgres: de dentro do banco não dá para enxergar o disco.
# O volume foi de 500 MB para 5 GB depois que ele encheu e derrubou tudo.
LIMITE_BANCO_MB = int(os.environ.get("BANCO_LIMITE_MB", "5000") or 5000)
_CACHE_TAMANHO: dict = {"quando": 0.0, "mb": None}


def tamanho_do_banco_mb(ttl: int = 300) -> float | None:
    """Megabytes ocupados. None quando não deu para perguntar.

    Com cache porque isto é chamado no cabeçalho de toda página, e uma
    consulta por visita para uma informação que muda devagar seria desperdício.
    """
    agora = time.time()
    if _CACHE_TAMANHO["mb"] is not None and agora - _CACHE_TAMANHO["quando"] < ttl:
        return _CACHE_TAMANHO["mb"]
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT pg_database_size(current_database())")
            mb = round(c.fetchone()[0] / 1048576, 1)
        _CACHE_TAMANHO.update({"quando": agora, "mb": mb})
        return mb
    except Exception:
        return None


def _cria_usuario(c) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuario (
            id            SERIAL PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            nome          TEXT,
            senha         TEXT NOT NULL,
            temporaria    BOOLEAN NOT NULL DEFAULT FALSE,
            criado_em     TIMESTAMPTZ DEFAULT NOW(),
            ultimo_acesso TIMESTAMPTZ
        )
    """)
    # Papéis: adm (tudo), gerente (tudo menos Configurações), leitor (as guias,
    # sem a home de aprovação). O padrão é o mais fraco de propósito — coluna
    # nova em base antiga preenche com o padrão, e é melhor que um usuário
    # antigo acorde com menos acesso do que com mais.
    c.execute("ALTER TABLE usuario ADD COLUMN IF NOT EXISTS papel TEXT "
              "NOT NULL DEFAULT 'leitor'")


def _cria_convite(c) -> None:
    """Convites de uso único.

    O código é gerado por quem convida e nunca fica guardado em texto puro —
    o banco tem só o resumo (hash). Um convite vazado no banco não vira acesso,
    e eu não consigo ler o código de ninguém nem querendo.
    """
    c.execute("""
        CREATE TABLE IF NOT EXISTS convite (
            resumo     TEXT PRIMARY KEY,
            papel      TEXT NOT NULL DEFAULT 'leitor',
            criado_por TEXT,
            criado_em  TIMESTAMPTZ DEFAULT NOW(),
            expira_em  TIMESTAMPTZ,
            usado_em   TIMESTAMPTZ,
            usado_por  TEXT
        )
    """)


def criar_usuario(email: str, nome: str, senha_guardada: str,
                  papel: str = "leitor") -> tuple[bool, str]:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_usuario(c)
            c.execute("SELECT 1 FROM usuario WHERE email = %s", [email])
            if c.fetchone():
                return False, "já existe conta com esse e-mail"
            # O PRIMEIRO a se cadastrar é sempre adm. Sem isso, ligar o login
            # numa base vazia criaria um app sem nenhum administrador — e a
            # única saída seria mexer no banco à mão.
            c.execute("SELECT COUNT(*) FROM usuario")
            primeiro = (c.fetchone() or [0])[0] == 0
            c.execute("INSERT INTO usuario (email, nome, senha, papel) "
                      "VALUES (%s,%s,%s,%s)",
                      [email, nome or "", senha_guardada,
                       "adm" if primeiro else papel])
            return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def registrar_convite(resumo: str, papel: str, criado_por: str,
                      expira_em) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_convite(c)
            c.execute("""INSERT INTO convite (resumo, papel, criado_por, expira_em)
                         VALUES (%s,%s,%s,%s)""",
                      [resumo, papel, criado_por, expira_em])
        return True
    except Exception as e:
        print(f"⚠️ registrar_convite: {e}")
        return False


def convite_valido(resumo: str) -> dict | None:
    """O convite, se existir, não tiver sido usado e não tiver vencido."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_convite(c)
            c.execute("""SELECT * FROM convite WHERE resumo = %s
                         AND usado_em IS NULL
                         AND (expira_em IS NULL OR expira_em > NOW())""", [resumo])
            linha = c.fetchone()
            return dict(linha) if linha else None
    except Exception as e:
        print(f"⚠️ convite_valido: {e}")
        return None


def queimar_convite(resumo: str, email: str) -> bool:
    """Marca como usado. O UPDATE só pega quem ainda não foi usado, então dois
    cadastros simultâneos com o mesmo código não passam os dois."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""UPDATE convite SET usado_em = NOW(), usado_por = %s
                         WHERE resumo = %s AND usado_em IS NULL""",
                      [email, resumo])
            return c.rowcount > 0
    except Exception as e:
        print(f"⚠️ queimar_convite: {e}")
        return False


def listar_convites(limite: int = 50) -> list[dict]:
    """Nunca devolve o código — ele não existe aqui, só o resumo."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_convite(c)
            c.execute("""SELECT papel, criado_por, criado_em, expira_em,
                                usado_em, usado_por FROM convite
                         ORDER BY criado_em DESC LIMIT %s""", [limite])
            linhas = []
            for r in c.fetchall():
                d = dict(r)
                for campo in ("criado_em", "expira_em", "usado_em"):
                    if d.get(campo) is not None:
                        d[campo] = d[campo].isoformat()
                linhas.append(d)
            return linhas
    except Exception as e:
        print(f"⚠️ listar_convites: {e}")
        return []


def papel_do_usuario(email: str) -> str:
    """O papel de quem está logado. Na dúvida, o MENOS poderoso.

    Erro de leitura aqui vira 'leitor', nunca 'adm'. Falhar para o lado de
    menos acesso incomoda; falhar para o lado de mais acesso é incidente.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_usuario(c)
            c.execute("SELECT papel FROM usuario WHERE email = %s", [email])
            linha = c.fetchone()
            return (linha[0] or "leitor") if linha else "leitor"
    except Exception as e:
        print(f"⚠️ papel_do_usuario: {e}")
        return "leitor"


def mudar_papel(email: str, papel: str) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE usuario SET papel = %s WHERE email = %s",
                      [papel, email])
            return c.rowcount > 0
    except Exception as e:
        print(f"⚠️ mudar_papel: {e}")
        return False


def usuario_por_email(email: str) -> dict | None:
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_usuario(c)
            c.execute("SELECT * FROM usuario WHERE email = %s", [email])
            linha = c.fetchone()
            return dict(linha) if linha else None
    except Exception:
        return None


def marcar_acesso(email: str) -> None:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_usuario(c)
            c.execute("UPDATE usuario SET ultimo_acesso = NOW() WHERE email = %s",
                      [email])
    except Exception:
        pass


def trocar_senha(email: str, senha_guardada: str, temporaria: bool = False) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_usuario(c)
            c.execute("UPDATE usuario SET senha = %s, temporaria = %s WHERE email = %s",
                      [senha_guardada, temporaria, email])
            return c.rowcount == 1
    except Exception:
        return False


def listar_usuarios() -> list[dict]:
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_usuario(c)
            # A senha NÃO sai daqui. Nem o hash: ele não serve para nada na
            # tela e só cria a chance de vazar num log ou numa resposta.
            c.execute("""SELECT email, nome, papel, temporaria, criado_em,
                                 ultimo_acesso
                           FROM usuario ORDER BY criado_em""")
            linhas = [dict(r) for r in c.fetchall()]
        for l in linhas:
            for campo in ("criado_em", "ultimo_acesso"):
                if l.get(campo):
                    l[campo] = l[campo].isoformat()
        return linhas
    except Exception:
        return []


def tem_algum_usuario() -> bool:
    """Se ninguém se cadastrou ainda, o app continua aberto.

    É o que evita eu te trancar do lado de fora: enquanto não existir conta
    nenhuma, nada exige login. No instante em que a primeira conta nasce, o
    app passa a pedir senha — e quem criou a conta é quem tem a senha.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_usuario(c)
            c.execute("SELECT 1 FROM usuario LIMIT 1")
            return c.fetchone() is not None
    except Exception:
        # Banco fora do ar não pode trancar a porta: sem conseguir perguntar,
        # eu deixo passar. Trancar por falha de leitura seria trancar por engano.
        return False


def _cria_clipe(c) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS clipe (
            id            SERIAL PRIMARY KEY,
            pedido_em     TIMESTAMPTZ DEFAULT NOW(),
            alvo_em       TIMESTAMPTZ NOT NULL,
            antes_seg     INTEGER NOT NULL DEFAULT 20,
            depois_seg    INTEGER NOT NULL DEFAULT 8,
            estado        TEXT NOT NULL DEFAULT 'pedido',
            video         BYTEA,
            tamanho       INTEGER,
            texto         TEXT,
            gol_id        INTEGER,
            media_id      TEXT,
            post_id       TEXT,
            erro          TEXT,
            atualizado_em TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # CREATE TABLE IF NOT EXISTS não toca em tabela que já existe. Como a sua
    # já tem clipes dentro, as colunas novas precisam de ALTER — senão o código
    # novo consultaria coluna inexistente e tudo cairia no except, virando
    # "nenhum clipe" na tela, sem explicação.
    c.execute("ALTER TABLE clipe ADD COLUMN IF NOT EXISTS live_id TEXT")
    c.execute("ALTER TABLE clipe ADD COLUMN IF NOT EXISTS tipo TEXT "
              "NOT NULL DEFAULT 'gol'")
    # Clipe que você mandou guardar. O resto é descartável por regra, não por
    # esquecimento: some sozinho duas horas depois que o jogo sai do ar.
    c.execute("ALTER TABLE clipe ADD COLUMN IF NOT EXISTS guardado BOOLEAN "
              "NOT NULL DEFAULT FALSE")
    # O trecho escolhido na fita, em segundos DENTRO do arquivo. Guardar em
    # vez de recortar na hora: arrastar o punho fica instantâneo, e o corte
    # de verdade acontece só quando o vídeo vai sair — publicar ou baixar.
    c.execute("ALTER TABLE clipe ADD COLUMN IF NOT EXISTS corte_ini REAL")
    c.execute("ALTER TABLE clipe ADD COLUMN IF NOT EXISTS corte_fim REAL")


# Colunas de listagem. O BYTEA fica de fora de propósito: um clipe tem alguns
# megabytes, e trazer isso numa lista de dez clipes seria carregar dezenas de
# megabytes para desenhar uma tela que só precisa do tamanho.
_COLS_CLIPE = ("id, pedido_em, alvo_em, antes_seg, depois_seg, estado, tamanho, "
               "texto, gol_id, media_id, post_id, erro, atualizado_em, "
               "live_id, tipo, guardado, corte_ini, corte_fim")


def criar_pedido_clipe(alvo_em, antes_seg: int = 20, depois_seg: int = 8,
                       live_id: str = "", tipo: str = "gol") -> int:
    """Registra um pedido de corte. Devolve o id, ou 0 se falhou."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""INSERT INTO clipe (alvo_em, antes_seg, depois_seg,
                                            live_id, tipo)
                         VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                      [alvo_em, max(0, int(antes_seg)), max(1, int(depois_seg)),
                       live_id or None, tipo if tipo in ("gol", "outro") else "gol"])
            return int(c.fetchone()[0])
    except Exception:
        return 0


def clipes_a_cortar() -> list[dict]:
    """O que o agente gravador precisa fazer agora."""
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_clipe(c)
            c.execute(f"""SELECT {_COLS_CLIPE} FROM clipe
                           WHERE estado = 'pedido'
                           ORDER BY id""")
            return [_clipe_json(dict(r)) for r in c.fetchall()]
    except Exception:
        return []


def _clipe_json(d: dict) -> dict:
    for campo in ("pedido_em", "alvo_em", "atualizado_em"):
        if d.get(campo) is not None:
            d[campo] = d[campo].isoformat()
    return d


def mudar_estado_clipe(clipe_id: int, de: str, para: str) -> bool:
    """Troca de estado só se ele ainda estiver no esperado.

    O 'de' na cláusula WHERE não é decoração: dois gravadores ligados, ou um
    reenvio, poderiam pegar o mesmo pedido duas vezes. Assim só o primeiro
    consegue, e o segundo recebe False e desiste.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe SET estado = %s, atualizado_em = NOW()
                          WHERE id = %s AND estado = %s""", [para, clipe_id, de])
            return c.rowcount == 1
    except Exception:
        return False


def entregar_clipe(clipe_id: int, video: bytes) -> bool:
    """O agente devolve o mp4 recortado. O arquivo vai para o disco."""
    try:
        os.makedirs(PASTA_CLIPES, exist_ok=True)
        _limpar_clipes_velhos()
        # Escrevo num temporário e renomeio: se o processo morrer no meio, não
        # sobra um mp4 pela metade que a tela tentaria tocar.
        caminho = _caminho_do_clipe(clipe_id)
        parcial = caminho + ".parcial"
        with open(parcial, "wb") as f:
            f.write(video)
        os.replace(parcial, caminho)
    except Exception:
        return False
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            # video = NULL de propósito: se este clipe já teve bytes na coluna
            # (de antes desta mudança), é agora que eles saem de lá.
            c.execute("""UPDATE clipe
                            SET video = NULL, tamanho = %s, estado = 'pronto',
                                erro = NULL, atualizado_em = NOW()
                          WHERE id = %s AND estado IN ('pedido','cortando')""",
                      [len(video), clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def ajustar_clipe(clipe_id: int, delta_seg: int) -> bool:
    """Move a janela e devolve o clipe para a fila de corte.

    Só mexe em clipe que ainda não foi publicado — reajustar algo que já está
    no ar não teria efeito nenhum e só confundiria a tela.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe
                            SET alvo_em = alvo_em + (%s * INTERVAL '1 second'),
                                estado = 'pedido', video = NULL, tamanho = NULL,
                                erro = NULL, atualizado_em = NOW()
                          WHERE id = %s
                            AND estado IN ('pronto','erro','cortando','pedido')""",
                      [int(delta_seg), clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def redefinir_janela(clipe_id: int, antes_seg: int, depois_seg: int) -> bool:
    """Muda a janela do clipe e devolve para a fila de corte.

    antes e depois são medidos a partir do instante do lance, e depois PODE ser
    negativo: se você arrastar a fita para terminar antes do gol, o fim da
    janela fica atrás do alvo. O que precisa valer é a duração, não o sinal.
    """
    dur = int(antes_seg) + int(depois_seg)
    if dur < 3 or dur > 140:
        return False          # 140s é o teto de vídeo do X
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe
                            SET antes_seg = %s, depois_seg = %s,
                                estado = 'pedido', video = NULL, tamanho = NULL,
                                erro = NULL, atualizado_em = NOW()
                          WHERE id = %s AND estado <> 'publicado'""",
                      [int(antes_seg), int(depois_seg), clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def texto_do_clipe(clipe_id: int, texto: str) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe SET texto = %s, atualizado_em = NOW()
                          WHERE id = %s AND estado <> 'publicado'""",
                      [texto, clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def clipe_publicado(clipe_id: int, media_id: str, post_id: str) -> bool:
    """Marca como publicado e JOGA FORA o vídeo.

    Guardar megabytes de um clipe que já está no ar não serve para nada e o
    banco cresceria sem parar. O post_id fica, que é o que permite achar a
    publicação depois para aplicar a restrição no Media Studio.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe
                            SET estado = 'publicado', media_id = %s, post_id = %s,
                                video = NULL, erro = NULL, atualizado_em = NOW()
                          WHERE id = %s""", [media_id, post_id, clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def erro_no_clipe(clipe_id: int, mensagem: str) -> bool:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe SET estado = 'erro', erro = %s,
                                          atualizado_em = NOW()
                          WHERE id = %s""", [str(mensagem)[:500], clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def clipes_recentes(horas: int = 8) -> list[dict]:
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_clipe(c)
            c.execute(f"""SELECT {_COLS_CLIPE} FROM clipe
                           WHERE pedido_em > NOW() - (%s * INTERVAL '1 hour')
                           ORDER BY id DESC""", [horas])
            return [_clipe_json(dict(r)) for r in c.fetchall()]
    except Exception:
        return []


def marcar_corte(clipe_id: int, ini, fim) -> bool:
    """Guarda o trecho da fita. Não mexe no arquivo — é só uma anotação.

    É por isso que arrastar o punho é instantâneo: nada é recortado aqui.
    Passar None nos dois desfaz o corte e volta ao clipe inteiro.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""UPDATE clipe SET corte_ini = %s, corte_fim = %s,
                                          atualizado_em = NOW()
                          WHERE id = %s""",
                      [None if ini is None else float(ini),
                       None if fim is None else float(fim), clipe_id])
            return c.rowcount == 1
    except Exception:
        return False


def guardar_clipe(clipe_id: int, guardar: bool = True) -> tuple[bool, str]:
    """Marca (ou desmarca) um clipe para não ser descartado.

    Guardar copia o mp4 do disco de volta PARA o banco, e isso é de propósito.
    O disco do contêiner é efêmero: some no próximo redeploy. Para o clipe que
    você quis guardar, "some no próximo redeploy" não é guardar coisa nenhuma.
    Os descartáveis continuam só em disco, que é o que impede o banco de
    encher de novo — foi guardar TUDO no banco que derrubou tudo.
    """
    dados = None
    if guardar:
        try:
            caminho = _caminho_do_clipe(clipe_id)
            if os.path.exists(caminho):
                with open(caminho, "rb") as f:
                    dados = f.read()
        except Exception:
            dados = None
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            if guardar and dados:
                c.execute("""UPDATE clipe SET guardado = TRUE, video = %s,
                                              tamanho = %s, atualizado_em = NOW()
                              WHERE id = %s""",
                          [psycopg2.Binary(dados), len(dados), clipe_id])
            elif guardar:
                # Sem arquivo em disco: pode ser clipe antigo, cujos bytes já
                # estão na coluna. Marco assim mesmo, sem apagar o que houver.
                c.execute("UPDATE clipe SET guardado = TRUE, atualizado_em = NOW() "
                          "WHERE id = %s", [clipe_id])
            else:
                c.execute("UPDATE clipe SET guardado = FALSE, video = NULL, "
                          "atualizado_em = NOW() WHERE id = %s", [clipe_id])
            if c.rowcount != 1:
                return False, "clipe não encontrado"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if guardar and dados is None:
        return True, "guardado, mas o vídeo não estava mais em disco"
    return True, ""


def descartar_clipes(lives_ativas: list[str], horas: int = 2) -> dict:
    """Apaga os clipes que ninguém mandou guardar.

    A regra é "duas horas depois do fim do jogo". Fim de jogo eu não tenho —
    nenhuma das APIs me diz quando a TRANSMISSÃO acabou, que é o que importa
    aqui. Então uso o sinal que eu tenho de verdade: enquanto o jogo estiver
    sendo gravado, não apago nada dele. Quando ele sai do ar, os clipes com
    mais de duas horas vão embora.

    Assim nunca some clipe no meio da partida — que seria o único jeito de
    esta regra estragar a sua noite.
    """
    # O ::text[] não é enfeite. Com a lista vazia — que é o caso normal, sem
    # jogo no ar — o psycopg2 manda ARRAY[] sem tipo e o Postgres recusa com
    # "cannot determine type of empty array". A consulta inteira caía no
    # except, a função devolvia "apagados: 0" e o agendador não dizia nada.
    # Ou seja: a faxina falhava exatamente nas horas em que ela deveria rodar,
    # e em silêncio. Meu teste passou porque usei uma lista com dois jogos.
    saida = {"apagados": 0, "ids": [], "erro": ""}
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("""DELETE FROM clipe
                          WHERE guardado = FALSE
                            AND alvo_em < NOW() - (%s * INTERVAL '1 hour')
                            AND (live_id IS NULL OR live_id = ''
                                 OR NOT (live_id = ANY(%s::text[])))
                      RETURNING id""",
                      [horas, [str(x) for x in (lives_ativas or [])]])
            saida["ids"] = [linha[0] for linha in c.fetchall()]
            saida["apagados"] = len(saida["ids"])
    except Exception as e:
        saida["erro"] = f"{type(e).__name__}: {e}"
        return saida
    for cid in saida["ids"]:
        try:
            os.remove(_caminho_do_clipe(cid))
        except Exception:
            pass

    # DELETE não devolve disco: o Postgres só marca a linha como morta, e o
    # arquivo da tabela continua do mesmo tamanho. Quem devolve é o VACUUM
    # FULL, que reescreve a tabela sem os mortos.
    #
    # Rodo só quando apaguei alguma coisa, e nunca no meio de jogo — o
    # descarte já espera a transmissão sair do ar. Ele tranca a tabela
    # enquanto reescreve, mas depois da primeira faxina ela é pequena e isso
    # leva um piscar.
    #
    # Precisa de conexão própria: VACUUM não roda dentro de transação, e a
    # get_conn abre uma.
    if saida["apagados"]:
        try:
            url = _get_database_url()
            conn = psycopg2.connect(url)
            conn.autocommit = True
            conn.cursor().execute("VACUUM FULL clipe")
            conn.close()
            saida["espaco_devolvido"] = True
        except Exception as e:
            saida["espaco_devolvido"] = False
            saida["erro"] = f"apaguei, mas o VACUUM falhou: {type(e).__name__}: {e}"
    return saida


def video_do_clipe(clipe_id: int) -> bytes | None:
    """O mp4. Do disco; e, para clipes antigos, ainda do banco."""
    try:
        caminho = _caminho_do_clipe(clipe_id)
        if os.path.exists(caminho):
            with open(caminho, "rb") as f:
                return f.read()
    except Exception:
        pass
    # Clipes gravados antes desta mudança ainda têm os bytes na coluna. Não
    # apago a coluna: ela é o único lugar onde eles existem.
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_clipe(c)
            c.execute("SELECT video FROM clipe WHERE id = %s", [clipe_id])
            linha = c.fetchone()
            return bytes(linha[0]) if linha and linha[0] is not None else None
    except Exception:
        return None


def um_clipe(clipe_id: int) -> dict | None:
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_clipe(c)
            c.execute(f"SELECT {_COLS_CLIPE} FROM clipe WHERE id = %s", [clipe_id])
            linha = c.fetchone()
            return _clipe_json(dict(linha)) if linha else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════
# LIVES EM ANDAMENTO
#
# Uma lista, não um campo: numa rodada há jogos simultâneos, e a versão de um
# link só encerrava a gravação anterior quando você colava a segunda — perdia
# o primeiro jogo em silêncio.
#
# Mora no app_state, que já existe e sobrevive a redeploy. Tabela nova para
# quatro linhas de texto seria peso sem ganho.
# ══════════════════════════════════════════════════════════════════════════

CHAVE_LIVES = "clipe_lives"
CHAVE_DISPONIVEIS = "clipe_disponiveis"
MAX_LIVES = 4

# Só este canal. Você tem acordo de publicação com ele, e não com o YouTube
# inteiro — deixar colar qualquer link seria criar a chance de gravar material
# que você não pode publicar. Aqui a restrição é estrutural: nem existe campo
# para colar link, você escolhe entre as transmissões que o canal está fazendo.
CANAL = "https://www.youtube.com/@canalgoatbr"


def listar_lives() -> list[dict]:
    try:
        d = json.loads(get_state(CHAVE_LIVES) or "[]")
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _salvar_lives(lives: list) -> bool:
    try:
        set_state(CHAVE_LIVES, json.dumps(lives[:MAX_LIVES], ensure_ascii=False))
        return True
    except Exception:
        return False


def remover_live(live_id: str) -> bool:
    lives = listar_lives()
    restantes = [l for l in lives if l.get("id") != live_id]
    if len(restantes) == len(lives):
        return False
    return _salvar_lives(restantes)


def titulo_da_live(live_id: str, titulo: str) -> bool:
    """O gravador descobre o título com o yt-dlp e devolve para cá.

    Assim o botão na tela diz "AL HILAL X AL NASSR" em vez de um link, que é o
    que importa quando há quatro jogos e você precisa acertar o certo com o
    dedo, rápido.
    """
    lives = listar_lives()
    achou = False
    for l in lives:
        if l.get("id") == live_id and titulo and l.get("titulo") != titulo:
            l["titulo"] = titulo[:120]
            achou = True
    return _salvar_lives(lives) if achou else False


def lives_disponiveis() -> list[dict]:
    """O que o gravador viu no canal na última vez que olhou."""
    try:
        d = json.loads(get_state(CHAVE_DISPONIVEIS) or "{}")
        itens = d.get("itens") if isinstance(d, dict) else None
        return itens if isinstance(itens, list) else []
    except Exception:
        return []


def salvar_disponiveis(itens: list) -> bool:
    """O gravador reporta o que achou no canal. Só ele consegue: o Railway é
    IP de datacenter e o YouTube barra."""
    try:
        set_state(CHAVE_DISPONIVEIS, json.dumps(
            {"quando": datetime.now(timezone.utc).isoformat(),
             "itens": itens[:20]}, ensure_ascii=False))
        return True
    except Exception:
        return False


def adicionar_live_do_canal(video_id: str) -> tuple[bool, str]:
    """Põe para gravar uma das transmissões que o gravador achou no canal.

    Recebe o id do vídeo, e NÃO uma URL vinda da tela: assim não há como pedir
    para gravar algo fora do canal, nem por engano nem por link montado à mão.
    """
    achado = next((d for d in lives_disponiveis()
                   if d.get("id") == video_id), None)
    if not achado:
        return False, "essa transmissão não está na lista do canal"
    lives = listar_lives()
    if len(lives) >= MAX_LIVES:
        return False, f"o limite é {MAX_LIVES} jogos ao mesmo tempo"
    if any(l.get("id") == video_id for l in lives):
        return False, "esse jogo já está sendo gravado"
    lives.append({"id": video_id,
                  "url": f"https://www.youtube.com/watch?v={video_id}",
                  "titulo": achado.get("titulo") or "",
                  "criada_em": datetime.now(timezone.utc).isoformat()})
    return (True, "") if _salvar_lives(lives) else (False, "não consegui salvar")


# ══════════════════════════════════════════════════════════════════════════
# ESCALAÇÕES — quem publica primeiro
#
# Mesmo desenho do gol_visto, e pelo mesmo motivo: o UNIQUE por (fonte,
# fixture) é o que faz a medição valer. A segunda vez que a fonte reportar a
# mesma escalação não sobrescreve o horário — senão eu estaria medindo a hora
# da última consulta, e não a da descoberta.
# ══════════════════════════════════════════════════════════════════════════

def _cria_escalacao(c) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS escalacao_vista (
            id          SERIAL PRIMARY KEY,
            fonte       TEXT NOT NULL,
            chave       TEXT NOT NULL,
            fixture_af  BIGINT,
            fixture_sm  BIGINT,
            jogo        TEXT,
            comeca_em   TIMESTAMPTZ,
            conteudo    TEXT,
            visto_em    TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (fonte, chave)
        )
    """)


def registrar_escalacao(fonte: str, chave: str, jogo: str = "",
                        comeca_em=None, conteudo: str = "",
                        fixture_af=None, fixture_sm=None) -> bool:
    """Carimba a primeira vez que esta fonte publicou esta escalação.

    Devolve True só quando é a primeira — ou seja, quando é notícia.
    """
    try:
        with get_conn() as conn:
            c = conn.cursor()
            _cria_escalacao(c)
            c.execute("""
                INSERT INTO escalacao_vista
                       (fonte, chave, jogo, comeca_em, conteudo,
                        fixture_af, fixture_sm)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fonte, chave) DO NOTHING
                RETURNING id
            """, [fonte, chave, jogo, comeca_em, conteudo,
                  fixture_af, fixture_sm])
            return c.fetchone() is not None
    except Exception:
        return False


def escalacoes_vistas(desde_horas: int = 12) -> list[dict]:
    try:
        with get_conn() as conn:
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            _cria_escalacao(c)
            c.execute("""
                SELECT * FROM escalacao_vista
                 WHERE visto_em > NOW() - (%s * INTERVAL '1 hour')
                 ORDER BY visto_em DESC
            """, [desde_horas])
            linhas = [dict(r) for r in c.fetchall()]
        for l in linhas:
            for campo in ("visto_em", "comeca_em"):
                if l.get(campo):
                    l[campo] = l[campo].isoformat()
        return linhas
    except Exception:
        return []
