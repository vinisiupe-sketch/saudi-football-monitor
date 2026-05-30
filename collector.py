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
from sources import (
    TIER_A, TIER_B, TIER_C,
    TWITTER_RSS_PROVIDERS, KEYWORDS, TIER_WEIGHTS
)
from database import make_article_id

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


def compute_relevance(text: str, tier: str) -> float:
    text_lower = text.lower()
    all_keywords = [kw for lang_kws in KEYWORDS.values() for kw in lang_kws]
    hits = sum(1 for kw in all_keywords if kw.lower() in text_lower)
    keyword_score = min(hits / 5.0, 1.0)
    tier_bonus = TIER_WEIGHTS.get(tier, 1) / 3.0
    return round((keyword_score * 0.7) + (tier_bonus * 0.3), 3)


FOOTBALL_REQUIRED = [
    # must match at least one of these to be considered football content
    "football", "futebol", "soccer", "league", "liga", "clube", "club", "transfer",
    "contrato", "jogador", "player", "técnico", "coach", "treinador", "gol", "goal",
    "partida", "jogo", "match", "game", "temporada", "season", "copa", "cup",
    "campeonato", "championship", "torneio", "tournament", "escalação", "lineup",
    "pro league", "saudi pro", "roshn", "dls", "spl",
    "al hilal", "al nassr", "al ittihad", "al ahli", "al shabab", "al fateh",
    "al ettifaq", "al qadsiah", "al fayha", "al taawoun", "al wahda", "damac",
    "al-hilal", "al-nassr", "al-ittihad", "al-ahli", "al-shabab",
    "الهلال", "النصر", "الاتحاد", "الأهلي", "الشباب", "الفتح", "التعاون",
    "الخلود", "القادسية", "الفيحاء", "الحزم", "الخليج", "الأخدود", "ضمك",
    "دوري", "مباراة", "لاعب", "مدرب", "الفريق", "الانتقال", "عقد", "إعارة",
]

# Arabic keywords that are also common words — don't count as Saudi hits alone
AMBIGUOUS_ARABIC = {"الاتفاق", "التعاون", "الاتحاد", "الفتح", "الشباب", "دوري"}

def is_relevant(text: str, min_hits: int = 3, title: str = "") -> bool:
    text_lower = text.lower()
    # Must have at least one football-specific term
    if not any(kw in text_lower for kw in FOOTBALL_REQUIRED):
        return False
    # Count keyword hits — ambiguous Arabic words only count if another Saudi keyword also present
    hits = 0
    ambiguous_hits = 0
    for lang_kws in KEYWORDS.values():
        for kw in lang_kws:
            if kw.lower() in text_lower:
                if kw in AMBIGUOUS_ARABIC:
                    ambiguous_hits += 1
                else:
                    hits += 1
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
            return url, provider
        except Exception as e:
            print(f"       ↳ {provider}: ❌ {type(e).__name__}: {e}")
            continue
    return None


CYCLE_HOURS = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 120)) // 60 or 2
ARTICLE_MAX_AGE_HOURS = int(os.environ.get("ARTICLE_MAX_AGE_HOURS", 48))


def parse_entries(feed, source_name: str, source_tier: str, source_type: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARTICLE_MAX_AGE_HOURS)

    articles = []
    for entry in feed.entries[:30]:
        title = getattr(entry, "title", "") or ""
        # Ignora retweets
        if title.startswith("RT ") or title.startswith("RT@"):
            continue
        summary = getattr(entry, "summary", "") or ""
        link = getattr(entry, "link", "") or ""
        body = re.sub(r"<[^>]+>", " ", summary).strip()
        full_text = f"{title} {body}"
        if not is_relevant(full_text, min_hits=1):
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
    # Load override sources (added via /fontes page)
    override_file = "sources_override.json"
    override_extra: dict[str, str] = {}  # handle -> tier
    try:
        import json as _json
        with open(override_file) as _f:
            for h, ov in _json.load(_f).items():
                override_extra[h] = ov.get("tier", "C")
    except Exception:
        pass

    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        seen_handles: set[str] = set()
        for tier_label, tier_data in [("A", TIER_A), ("B", TIER_B), ("C", TIER_C)]:
            # Somente Twitter — RSS desabilitado
            for username in tier_data.get("twitter_accounts", []):
                tasks.append((tier_label, "twitter", f"@{username}", username))
                seen_handles.add(username.lower())
        # Add sources from override that aren't already in sources.py
        for handle, tier_label in override_extra.items():
            if handle.lower() not in seen_handles:
                tasks.append((tier_label, "twitter", f"@{handle}", handle))
                seen_handles.add(handle.lower())
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
        print(f"     → ⛔ todos os provedores falharam para {name}")
        return None
    rss_url, provider = result
    feed = feedparser.parse((await client.get(rss_url, headers=HEADERS, timeout=15, follow_redirects=True)).text)
    articles = parse_entries(feed, name, tier, "twitter")
    print(f"     → {len(articles)} posts relevantes via {provider}")
    return articles
