"""
Scraper — busca o artigo completo a partir de links encontrados nos tweets.
"""
import re
import json
import httpx
from urllib.parse import quote
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9,pt;q=0.8",
}

# Seletores CSS para conteúdo principal, do mais específico ao mais genérico
CONTENT_SELECTORS = [
    "[itemprop='articleBody']",
    "article",
    "[class*='article-body']",
    "[class*='article-content']",
    "[class*='article-text']",
    "[class*='article-detail']",
    "[class*='news-detail']",
    "[class*='news-content']",
    "[class*='post-content']",
    "[class*='entry-content']",
    "[class*='story-body']",
    "[class*='news-body']",
    "[class*='content-body']",
    "[class*='article-wrap']",
    "main",
]

# Domínios que sabemos que não valem tentar (paywalls, redes sociais, etc.)
SKIP_DOMAINS = {
    "twitter.com", "x.com", "t.co",
    "instagram.com", "facebook.com", "youtube.com",
    "whatsapp.com", "telegram.org",
}


# ─── Google News redirect resolver ────────────────────────────────────────────
# Feeds RSS "site:X" via Google News (usados pra arriyadiyah.com e outros sites
# árabes) não trazem a URL real do artigo no <link> — trazem um link de
# redirecionamento (news.google.com/rss/articles/CBMi...) que só resolve via
# JavaScript no navegador. Sem decodificar, o scraper baixava a página-casca do
# Google (só JS, sem texto da matéria) e o card ficava só com o título.
#
# A técnica abaixo é a mesma usada por bibliotecas públicas de "google news
# decoder": a página do link de redirect carrega um atributo data-n-a-sg
# (assinatura), data-n-a-ts (timestamp) e data-n-a-id (o próprio ID do artigo,
# igual ao trecho da URL) — com esses 3 valores dá pra chamar o endpoint
# interno batchexecute do Google e receber de volta a URL real do artigo.
GOOGLE_NEWS_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def _extract_gn_redirect_attrs(html: str) -> tuple[str, str, str] | None:
    m_sg = re.search(r'data-n-a-sg="([^"]+)"', html)
    m_ts = re.search(r'data-n-a-ts="([^"]+)"', html)
    m_id = re.search(r'data-n-a-id="([^"]+)"', html)
    if not (m_sg and m_ts and m_id):
        return None
    return m_sg.group(1), m_ts.group(1), m_id.group(1)


async def resolve_google_news_url(link: str, client: httpx.AsyncClient) -> str | None:
    """Resolve um link news.google.com/rss/articles/... pra URL real do artigo."""
    if "news.google.com" not in link:
        return link
    try:
        resp = await client.get(link, headers=HEADERS, timeout=10, follow_redirects=True)
        attrs = _extract_gn_redirect_attrs(resp.text)
        if not attrs:
            return None
        signature, timestamp, gn_art_id = attrs
        inner_payload = [
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            gn_art_id, int(timestamp), signature,
        ]
        f_req = json.dumps([[["Fbv4je", json.dumps(inner_payload)]]])
        body = f"f.req={quote(f_req)}"
        headers = {
            **HEADERS,
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        }
        resp2 = await client.post(GOOGLE_NEWS_BATCHEXECUTE_URL, headers=headers, content=body, timeout=10)
        parts = resp2.text.split("\n\n")
        if len(parts) < 2:
            return None
        outer = json.loads(parts[1])
        inner = json.loads(outer[0][2])
        real_url = inner[1]
        return real_url if isinstance(real_url, str) and real_url.startswith("http") else None
    except Exception as e:
        print(f"     ↳ gn-decoder: falha ao resolver {link[:60]}... → {type(e).__name__}: {e}")
        return None


def extract_urls(text: str) -> list[str]:
    """Extrai URLs do texto do tweet."""
    urls = re.findall(r'https?://[^\s<>"\']+', text)
    return [u.rstrip(".,)") for u in urls]


def should_skip(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(skip in domain for skip in SKIP_DOMAINS)
    except Exception:
        return True


def parse_article_text(html: str, url: str) -> str:
    """Extrai o texto principal do HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove elementos de ruído
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "form", "iframe", "noscript", "figure"]):
        tag.decompose()

    # Tenta seletores específicos primeiro
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 200:
                return text[:4000]

    # Fallback: maior bloco de parágrafos
    paragraphs = soup.find_all("p")
    text = " ".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50)
    return text[:4000] if len(text) > 200 else ""


def parse_og_image(html: str) -> str:
    """Extrai a imagem principal via og:image ou twitter:image."""
    soup = BeautifulSoup(html, "html.parser")
    for attr in [("property", "og:image"), ("name", "twitter:image"), ("property", "og:image:url")]:
        tag = soup.find("meta", {attr[0]: attr[1]})
        if tag and tag.get("content"):
            return tag["content"]
    return ""


async def fetch_article_content(url: str, client: httpx.AsyncClient) -> tuple[str, str]:
    """Busca e extrai conteúdo e imagem de um artigo. Retorna (texto, image_url)."""
    if should_skip(url):
        return "", ""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return "", ""
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type:
            return "", ""
        html = resp.text
        return parse_article_text(html, str(resp.url)), parse_og_image(html)
    except Exception as e:
        print(f"     ↳ scraper: falha em {url[:60]}... → {type(e).__name__}")
        return "", ""


async def enrich_with_article(article: dict, client: httpx.AsyncClient) -> dict:
    """
    Tenta buscar o artigo completo a partir de URLs encontradas no corpo do tweet.
    Se conseguir, substitui body_orig pelo conteúdo completo.
    """
    body = article.get("body_orig", "") or ""
    urls = extract_urls(body)

    # Também tenta a URL principal do artigo
    main_url = article.get("url", "")
    if main_url and main_url not in urls:
        urls.insert(0, main_url)

    for url in urls:
        if should_skip(url):
            continue
        # Links do Google News (feeds "site:X") são redirects que só resolvem via
        # JS — decodifica pra URL real do artigo antes de tentar raspar.
        real_url = url
        if "news.google.com" in url:
            resolved = await resolve_google_news_url(url, client)
            if not resolved:
                continue
            real_url = resolved
            if should_skip(real_url):
                continue
        content, image_url = await fetch_article_content(real_url, client)
        if content:
            print(f"     ↳ scraper: ✅ {len(content)} chars de {real_url[:60]}")
            article["body_orig"] = content
            article["scraped_url"] = real_url
            if image_url:
                article["image_url"] = image_url
            return article

    return article
