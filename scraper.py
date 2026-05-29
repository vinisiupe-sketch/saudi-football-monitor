"""
Scraper — busca o artigo completo a partir de links encontrados nos tweets.
"""
import re
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9,pt;q=0.8",
}

# Seletores CSS para conteúdo principal, do mais específico ao mais genérico
CONTENT_SELECTORS = [
    "article",
    "[class*='article-body']",
    "[class*='article-content']",
    "[class*='post-content']",
    "[class*='entry-content']",
    "[class*='story-body']",
    "[class*='news-body']",
    "[class*='content-body']",
    "main",
]

# Domínios que sabemos que não valem tentar (paywalls, redes sociais, etc.)
SKIP_DOMAINS = {
    "twitter.com", "x.com", "t.co",
    "instagram.com", "facebook.com", "youtube.com",
    "whatsapp.com", "telegram.org",
}


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


async def fetch_article_content(url: str, client: httpx.AsyncClient) -> str:
    """Busca e extrai o conteúdo de um artigo. Retorna string vazia se falhar."""
    if should_skip(url):
        return ""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type:
            return ""
        return parse_article_text(resp.text, str(resp.url))
    except Exception as e:
        print(f"     ↳ scraper: falha em {url[:60]}... → {type(e).__name__}")
        return ""


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
        content = await fetch_article_content(url, client)
        if content:
            print(f"     ↳ scraper: ✅ {len(content)} chars de {url[:60]}")
            article["body_orig"] = content
            article["scraped_url"] = url
            return article

    return article
