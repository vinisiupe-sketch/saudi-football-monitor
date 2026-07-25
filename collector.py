"""
Coletor de RSS — busca posts do X (via Nitter/RSSHub) e feeds de notícias.
Sem API paga do Twitter necessária.
"""
import os
import feedparser
import httpx
import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from sources import TWITTER_RSS_PROVIDERS, KEYWORDS, TIER_WEIGHTS, TIER_A, TIER_B, TIER_C
from clubs import match_saudi_club, match_saudi_club_risky

# Contas de veículos generalistas (futebol mundial, não só saudita).
# Para elas, exige menção explícita a clube/seleção saudita para passar.
STRICT_SOURCES = {
    "aawsat_spt",      # Al Sharq Al-Awsat — jornalismo esportivo global
    "ariyadhiah_br",   # Al Riyadhiah — canal esportivo pan-árabe
}
from database import make_article_id, get_effective_sources

REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiFootballMonitor/1.0; "
        "+https://github.com/seu-usuario/saudi-football-monitor)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    arabic_chars = len(re.findall(r'[؀-ۿ]', text))
    total = max(len(text), 1)
    if arabic_chars / total > 0.2:
        return "ar"
    pt_words = {"foi", "são", "está", "com", "por", "que", "uma", "para", "não", "dos"}
    words = set(text.lower().split())
    if len(words & pt_words) >= 2:
        return "pt"
    return "en"


# Matching de keyword com fronteira de palavra real em vez de substring "in"
# ingênuo. Necessário porque árabe é aglutinante — prefixos/sufixos (ال-, م-,
# -ة, -ته...) colam direto na raiz sem espaço — então um termo curto como "عقد"
# (contrato) bate como substring dentro de "المنعقد" (convocado/reunido), que
# não tem nada a ver com futebol. Foi exatamente assim que a reunião do Conselho de
# Cooperação do Golfo (caso real sinalizado pelo usuário em 2026-06-24) passou pelo
# gate FOOTBALL_REQUIRED: "المنعقد" continha "عقد" como substring solta. Mesmo
# princípio já usado em clubs.py para nomes de clube — agora replicado aqui pra
# qualquer keyword (inglês/português/árabe), já que frases com espaço (ex: "al hilal",
# "pro league") continuam funcionando normalmente com este esquema.
#
# Fronteira usa (?<![^\w_]) ... na verdade (?<![^\W_]) / (?![^\W_]) — trata "_"
# como fronteira válida (não como caractere de palavra), porque hashtags árabes
# no Twitter juntam palavras com underscore (#دوري_روشن_السعودي). Com \w puro,
# "السعودي" dentro desse hashtag não bateria (o "_" bloquearia a fronteira) —
# mesmo bug descoberto e corrigido em clubs.py, replicado aqui por consistência.
_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _compile_word_pattern(word: str) -> re.Pattern:
    cached = _KEYWORD_PATTERN_CACHE.get(word)
    if cached is None:
        # Frases com mais de uma palavra (ex: "saudi national team") também precisam
        # casar quando o separador real é "_" em vez de espaço — comum em hashtags
        # árabes (#المنتخب_السعودي) — por isso o espaço escapado vira [\s_]+.
        escaped = re.escape(word.lower()).replace(r"\ ", r"[\s_]+")
        cached = re.compile(r"(?<![^\W_])" + escaped + r"(?![^\W_])", re.IGNORECASE | re.UNICODE)
        _KEYWORD_PATTERN_CACHE[word] = cached
    return cached


def _contains_word(text_lower: str, word: str) -> bool:
    return bool(_compile_word_pattern(word).search(text_lower))


def compute_relevance(text: str, tier: str) -> float:
    text_lower = text.lower()
    all_keywords = [kw for lang_kws in KEYWORDS.values() for kw in lang_kws]
    has_federation_context = any(fc in text_lower for fc in _FEDERATION_COMPOUNDS)
    hits = 0
    for kw in all_keywords:
        if _contains_word(text_lower, kw):
            # "الاتحاد" em contexto de federação externa não conta
            if kw == "الاتحاد" and has_federation_context:
                continue
            hits += 1
    # Nomes de clubes sauditas são sinal forte — consistente com is_relevant().
    if match_saudi_club(text_lower):
        hits += 2
    elif match_saudi_club_risky(text_lower):
        hits += 1
    keyword_score = min(hits / 5.0, 1.0)
    tier_bonus = TIER_WEIGHTS.get(tier, 1) / 3.0
    return round((keyword_score * 0.7) + (tier_bonus * 0.3), 3)


FOOTBALL_REQUIRED = [
    # Termos gerais de futebol (qualquer idioma)
    "football", "futebol", "soccer", "league", "liga", "clube", "club", "transfer",
    "contrato", "jogador", "player", "técnico", "coach", "treinador", "gol", "goal",
    "partida", "jogo", "match", "game", "temporada", "season", "copa", "cup",
    "campeonato", "championship", "torneio", "tournament", "escalação", "lineup",
    "pro league", "saudi pro", "roshn", "dls", "spl",
    # Clubes sauditas em inglês
    "al hilal", "al nassr", "al ittihad", "al ahli", "al shabab", "al fateh",
    "al ettifaq", "al ettifak", "al qadsiah", "al fayha", "al taawoun", "al wahda", "damac",
    "al-hilal", "al-nassr", "al-ittihad", "al-ahli", "al-shabab", "al-ettifaq",
    # Variante sem espaço/hífen — formato comum de hashtag (#AlAhli, #AlNassr...)
    "alhilal", "alnassr", "alittihad", "alahli", "alqadsiah",
    "alshabab", "alfateh", "altaawoun", "alettifaq", "alwahda", "alfayha",
    # Clubes sauditas em árabe (nomes próprios — não ambíguos)
    "الهلال", "النصر", "الأهلي", "الخلود",
    "الفيحاء", "الحزم", "الأخدود", "ضمك",
    # Termos árabes de futebol — qualificam o contexto
    "مدرب", "لاعب", "مباراة", "دوري", "انتقال", "صفقة", "رحيل", "عقد", "إعارة",
    # Seleção Saudita — o app tem uma aba dedicada (/selecao, ver main.py) pra esse
    # conteúdo, então ele PRECISA continuar sendo coletado (não é pra excluir).
    # Tinha um caso real (2026-06-24) de um tweet sobre a seleção que só passava
    # pelo gate por acidente (via o bug do "لاعب" dentro de "اللاعب" — já corrigido
    # acima) — agora tem sinal explícito e seguro, sem depender de bug de substring.
    # Mesma lista usada em SELECAO_KEYWORDS (main.py) pra rotear pra aba certa.
    "المنتخب السعودي", "منتخب السعودية", "الأخضر", "منتخبنا",
    "saudi national team", "saudi arabia national", "green falcons", "saudi nt",
    "seleção saudita", "seleção da arábia", "selecao saudita",
]

# Palavras árabes genéricas — só contam se outro keyword Saudi não-ambíguo também presente
# Termos de treinador/jogador/transferência também são genéricos (qualquer país usa essas
# palavras) — viraram ambíguos depois que um artigo sobre a federação turca de futebol
# (sem nenhum termo saudita real) passou pelo filtro só por citar "مدرب" e "لاعب".
#
# IMPORTANTE: الخليج/الاتفاق/التعاون/الشباب/الفتح/القادسية NÃO estão aqui de propósito,
# mesmo sendo ambíguas. Tentei tratá-las aqui primeiro, mas esse mecanismo só se aplica
# quando strict_ambiguous=True — e fontes Twitter (a maioria das fontes monitoradas)
# sempre chamam com strict_ambiguous=False, contornando a defesa completamente. Foi
# exatamente assim que os 2 falsos positivos reais de 2026-06-24 passaram (reunião do
# Conselho de Cooperação do Golfo via @OKAZ_online, jogadores jovens da seleção mexicana
# via @aawsat_spt — ambas fontes Twitter). Essas 6 palavras foram removidas de
# KEYWORDS["arabic"] (sources.py) e agora são tratadas EXCLUSIVAMENTE via
# RISKY_VARIANTS/match_saudi_club_risky em clubs.py, que exige corroboração de forma
# incondicional (não depende de strict_ambiguous nem de source_type). Não as adicione
# de volta aqui nem em KEYWORDS sem reavaliar esse bypass.
AMBIGUOUS_ARABIC = {
    "الاتحاد", "دوري", "الفريق", "اللاعب", "المدرب",
    "مدرب", "لاعب", "صفقة", "صفقات", "انتقال", "انتقالات",
    "إعارة", "رحيل", "عقد", "تعاقد", "تجديد",
}

# Compostos que provam que "الاتحاد" é FIFA/UEFA/outra federação, NÃO Al Ittihad.
# Quando qualquer um está presente, o hit de "الاتحاد" é ignorado.
_FEDERATION_COMPOUNDS = [
    "الاتحاد الدولي",      # FIFA / qualquer federação internacional
    "الاتحاد الأوروبي",    # UEFA / União Europeia
    "الاتحاد الأرجنتيني",
    "الاتحاد الألماني",
    "الاتحاد الأردني",
    "الاتحاد الإنجليزي",
    "الاتحاد الانجليزي",
    "الاتحاد الإسباني",
    "الاتحاد الفرنسي",
    "الاتحاد الإيطالي",
    "الاتحاد البرازيلي",
    "الاتحاد الأمريكي",
    "الاتحاد الآسيوي",
]

# Presença de Copa do Mundo SEM clube saudita → rejeitar.
# Adicionado após contaminação maciça de artigos do Mundial 2026 (julho/2026).
WORLD_CUP_TERMS = [
    "كأس العالم", "المونديال", "world cup", "mundial",
    "coupe du monde", "copa del mundo", "copa do mundo", "mondiali",
]

def is_relevant(text: str, min_hits: int = 3, title: str = "", strict_ambiguous: bool = True) -> bool:
    text_lower = text.lower()
    club_hit = match_saudi_club(text_lower)
    club_risky_hit = match_saudi_club_risky(text_lower)

    # Hard-filter 1: Copa do Mundo sem clube saudita → rejeitar sempre.
    # "الاتحاد الدولي لكرة القدم" (FIFA) dispara "copa" via "كأس العالم" nos textos
    # sobre o Mundial — sem clube saudita explícito não tem relevância para o monitor.
    if any(_contains_word(text_lower, wc) for wc in WORLD_CUP_TERMS):
        if not club_hit:
            return False

    # Must have at least one football-specific term — ou um clube saudita reconhecido
    if not (club_hit or any(_contains_word(text_lower, kw) for kw in FOOTBALL_REQUIRED)):
        return False

    # Count keyword hits — ambiguous Arabic words only count if another Saudi keyword also present.
    # strict_ambiguous=False (usado para contas de Twitter curadas) trata esses termos como
    # diretos: o risco de falso positivo é baixo quando a fonte já é jornalista de futebol
    # saudita — MAS "الاتحاد" é exceção: mesmo em fontes curadas aparece como FIFA/UEFA.
    # Por isso tem checagem explícita de contexto de federação abaixo.
    hits = 0
    ambiguous_hits = 0
    # Detecta contexto de federação externa uma única vez (mais eficiente que checar por kw)
    has_federation_context = any(fc in text_lower for fc in _FEDERATION_COMPOUNDS)
    for lang_kws in KEYWORDS.values():
        for kw in lang_kws:
            if _contains_word(text_lower, kw):
                # "الاتحاد" + contexto de federação externa → não conta: é FIFA/UEFA, não Al Ittihad
                if kw == "الاتحاد" and has_federation_context:
                    continue
                if strict_ambiguous and kw in AMBIGUOUS_ARABIC:
                    ambiguous_hits += 1
                else:
                    hits += 1
    if club_hit:
        hits += 1
    if club_risky_hit:
        ambiguous_hits += 1
    # Ambiguous hits only count if there's already a clear Saudi hit
    if hits > 0:
        hits += ambiguous_hits
    return hits >= min_hits


async def fetch_feed(url: str, client: httpx.AsyncClient) -> Optional[feedparser.FeedParserDict]:
    try:
        resp = await client.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            return None
        return feed
    except Exception as e:
        print(f"  ⚠️  Falha ao buscar {url[:60]}... → {type(e).__name__}: {e}")
        return None


async def resolve_twitter_rss(username: str, client: httpx.AsyncClient) -> Optional[tuple[str, str]]:
    """
    Tenta cada provedor e retorna (url, provider_name) do primeiro que funcionar.
    Faz GET real e verifica se o feed tem entradas — HEAD não é suficiente.
    """
    for template in TWITTER_RSS_PROVIDERS:
        url = template.format(username=username)
        provider = url.split("/")[2]
        try:
            resp = await client.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
            if resp.status_code >= 400:
                print(f"       ↳ {provider}: HTTP {resp.status_code}")
                continue
            feed = feedparser.parse(resp.text)
            if feed.bozo and not feed.entries:
                print(f"       ↳ {provider}: feed inválido/vazio (bozo={feed.bozo})")
                continue
            if not feed.entries:
                print(f"       ↳ {provider}: feed OK mas sem entradas")
                continue
            print(f"       ↳ {provider}: ✅ {len(feed.entries)} entradas")
            return url, provider, feed
        except Exception as e:
            print(f"       ↳ {provider}: ❌ {type(e).__name__}: {e}")
            continue
    return None


CYCLE_HOURS = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 120)) // 60 or 2
ARTICLE_MAX_AGE_HOURS = int(os.environ.get("ARTICLE_MAX_AGE_HOURS", 48))


def parse_entries(feed, source_name: str, source_tier: str, source_type: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARTICLE_MAX_AGE_HOURS)
    # Nome de exibição da conta (ex: "Twitter @Germán García Grova" -> "germán garcía grova"),
    # usado para diferenciar auto-retweet/repost da própria conta (comum quando jornalistas
    # reforçam um furo já publicado) de retweet de conteúdo de terceiros, que continua ignorado.
    feed_title = getattr(getattr(feed, "feed", None), "title", "") or ""
    account_display_name = feed_title.split("@", 1)[-1].strip().lower() if "@" in feed_title else ""
    account_handle = source_name.lstrip("@").lower()

    articles = []
    for entry in feed.entries[:50]:
        title = getattr(entry, "title", "") or ""
        # Ignora retweets de terceiros; permite auto-retweet/repost da própria conta monitorada
        if title.startswith("RT ") or title.startswith("RT@"):
            rt_label = title[3:].split(":", 1)[0].strip().lstrip("@").lower()
            if rt_label not in (account_display_name, account_handle):
                continue
        summary = getattr(entry, "summary", "") or ""
        # Try entry.content (feedparser sometimes has full article body here)
        if len(summary) < 150:
            for _c in (getattr(entry, "content", None) or []):
                _val = _c.get("value", "") if isinstance(_c, dict) else ""
                if len(_val) > len(summary):
                    summary = _val
                    break
        link = getattr(entry, "link", "") or ""
        body = re.sub(r"<[^>]+>", " ", summary).strip()
        full_text = f"{title} {body}"
        # Contas de Twitter monitoradas são todas jornalistas de futebol curados —
        # 1 sinal saudita claro já basta (o gate FOOTBALL_REQUIRED acima já garante
        # contexto de futebol). Feeds RSS (Google News etc.) cobrem futebol mundial,
        # então continuam exigindo 2 sinais pra evitar ruído de notícias não-sauditas.
        min_hits = 1 if source_type == "twitter" else 2
        if not is_relevant(full_text, min_hits=min_hits, strict_ambiguous=(source_type != "twitter")):
            continue
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                # Descarta notícias mais antigas que o ciclo atual
                if published_dt < cutoff:
                    continue
                published = published_dt.isoformat()
            except Exception:
                pass
        else:
            # Sem data de publicação: descarta para evitar notícias antigas sem timestamp
            continue
        article_id = make_article_id(link, title)
        lang = detect_language(full_text)
        score = compute_relevance(full_text, source_tier)
        # Fontes generalistas: exige menção saudita ou score cai abaixo do threshold
        if account_handle in STRICT_SOURCES and not match_saudi_club(full_text.lower()):
            score = min(score, 0.2)
        articles.append({
            "id": article_id,
            "source_name": source_name,
            "source_tier": source_tier,
            "source_type": source_type,
            "url": link,
            "title_orig": title[:500],
            "title_pt": None,
            "body_orig": body[:3000],
            "body_pt": None,
            "language": lang,
            "published_at": published,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "relevance_score": score,
        })
    return articles


async def collect_all(hours: int = None) -> dict:
    global ARTICLE_MAX_AGE_HOURS
    if hours:
        ARTICLE_MAX_AGE_HOURS = hours
    all_articles = []
    stats = {"sources_ok": 0, "sources_fail": 0}
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    # Fontes efetivas = sources.py (TIER_A/B/C) + overrides salvos via /fontes
    # (fontes adicionadas, excluídas ou com tier trocado). Mesma função usada
    # pela própria página /fontes pra exibir a lista — antes a coleta lia um
    # arquivo local que a UI nunca escrevia, então editar fontes ali não tinha
    # nenhum efeito real na coleta (bug real, 2026-06-24).
    effective_sources = get_effective_sources()

    async with httpx.AsyncClient(limits=limits) as client:
        # Tasks de Twitter: vêm dos overrides (via /fontes) + sources.py — mesma
        # lista que a página /fontes exibe, garantindo consistência total.
        twitter_tasks = [
            (s["tier"], "twitter", f"@{s['handle']}", s["handle"])
            for s in effective_sources
        ]
        # Tasks de RSS: feeds estáticos definidos em sources.py. Não passam por
        # overrides (o /fontes só gerencia contas do Twitter), então lemos direto
        # de TIER_A/B/C — sem risco de inconsistência com a UI.
        rss_tasks = [
            (tier_label, "rss", _rss_feed_name(feed_url), feed_url)
            for tier_label, tier_data in [("A", TIER_A), ("B", TIER_B), ("C", TIER_C)]
            for feed_url in tier_data.get("rss_feeds", [])
        ]
        tasks = twitter_tasks + rss_tasks
        BATCH_SIZE = 10
        for i in range(0, len(tasks), BATCH_SIZE):
            batch = tasks[i:i + BATCH_SIZE]
            batch_coroutines = []
            for tier, stype, name, target in batch:
                if stype == "twitter":
                    batch_coroutines.append(_collect_twitter(client, tier, name, target))
                else:
                    batch_coroutines.append(_collect_rss(client, tier, name, target))
            results = await asyncio.gather(*batch_coroutines, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) or result is None:
                    stats["sources_fail"] += 1
                else:
                    stats["sources_ok"] += 1
                    all_articles.extend(result)
    seen_ids = set()
    unique_articles = []
    for art in all_articles:
        if art["id"] not in seen_ids:
            seen_ids.add(art["id"])
            unique_articles.append(art)
    print(f"\n📡 Coleta: {stats['sources_ok']} ok, {stats['sources_fail']} falhas")
    print(f"   {len(unique_articles)} artigos relevantes\n")
    return {"articles": unique_articles, **stats}


def _rss_feed_name(url: str) -> str:
    """Gera um nome legível para um feed RSS a partir da URL, usado como source_name
    no banco. Para feeds do Google News com site:X, retorna 'site:X'. Para outros,
    retorna o domínio limpo."""
    if "news.google.com" in url:
        m = re.search(r'site:([^\s&+%]+)', url)
        if m:
            return f"site:{m.group(1)}"
        # Feed genérico do Google News — extrai a query pra identificar
        m2 = re.search(r'[?&]q=([^&]{1,40})', url)
        return f"Google News: {m2.group(1)}" if m2 else "Google News"
    # Domínio direto (arabnews, saudigazette, etc.)
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        return domain or url[:50]
    except Exception:
        return url[:50]


async def _collect_rss(client, tier, name, url) -> Optional[list]:
    print(f"  🌐 RSS [{tier}] {name[:40]}")
    feed = await fetch_feed(url, client)
    if feed is None:
        return None
    articles = parse_entries(feed, name, tier, "rss")
    print(f"     → {len(articles)} artigos")
    return articles


async def _collect_twitter(client, tier, name, username) -> Optional[list]:
    print(f"  🐦 Twitter [{tier}] {name}")
    result = await resolve_twitter_rss(username, client)
    if result is None:
        return None
    url, provider, feed = result
    articles = parse_entries(feed, name, tier, "twitter")
    print(f"     → {len(articles)} artigos ({provider})")
    return articles
