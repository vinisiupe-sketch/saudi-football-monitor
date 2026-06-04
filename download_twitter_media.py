"""
Baixa todas as mídias (fotos) do perfil @centraldoarabao de 2026
usando o RSSHub já configurado no projeto.

Uso:
    python download_twitter_media.py
"""

import os
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import re

OUTPUT_DIR = Path("public/player-images/raw")
ACCOUNT    = "centraldoarabao"
YEAR       = 2026

RSSHUB_URL = "https://rsshub-production-794a.up.railway.app/twitter/media/{username}?limit=100"
RAILWAY_TOKEN = "1a12b67772301514278a23a800e598de47f5ff74"

HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "accept": "application/rss+xml, application/xml, text/xml, */*",
}

def fetch_rss(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_date(date_str: str):
    """Parse RSS pubDate."""
    try:
        # Format: Mon, 01 Jan 2026 12:00:00 +0000
        dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y %H:%M:%S %z")
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def extract_images_from_item(item: ET.Element) -> list[str]:
    """Extract image URLs from RSS item (enclosure, media:content, or img in description)."""
    urls = []
    ns = {"media": "http://search.yahoo.com/mrss/"}

    # media:content
    for mc in item.findall("media:content", ns):
        url = mc.get("url", "")
        if url and "twimg.com" in url:
            base = re.sub(r'\?.*$', '', url)
            if not re.search(r'\.(jpg|jpeg|png|webp)$', base, re.I):
                base = base + ".jpg"
            urls.append(base + "?name=large")

    # enclosure
    for enc in item.findall("enclosure"):
        url = enc.get("url", "")
        t   = enc.get("type", "")
        if url and "image" in t:
            urls.append(url)

    # img tags inside description/content
    desc = ""
    for tag in ("description", "content:encoded", "{http://purl.org/rss/1.0/modules/content/}encoded"):
        el = item.find(tag)
        if el is not None and el.text:
            desc = el.text
            break

    for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.IGNORECASE):
        if any(x in src for x in ("pbs.twimg.com", "twimg.com")) and src not in urls:
            base = re.sub(r'\?.*$', '', src)
            if not re.search(r'\.(jpg|jpeg|png|webp)$', base, re.I):
                base = base + ".jpg"
            src = base + "?name=large"
            urls.append(src)

    # Also check for twimg URLs directly in description text
    for url in re.findall(r'https://pbs\.twimg\.com/media/[^\s"\'<>]+', desc):
        base = re.sub(r'\?.*$', '', url)
        # Ensure .jpg extension before query string
        if not re.search(r'\.(jpg|jpeg|png|webp)$', base, re.I):
            base = base + ".jpg"
        clean = base + "?name=large"
        if clean not in urls:
            urls.append(clean)

    return urls

def download_file(url: str, dest: Path):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        dest.write_bytes(r.read())

def get_item_id(item: ET.Element) -> str:
    guid = item.find("guid")
    if guid is not None and guid.text:
        # Extract tweet ID from URL
        m = re.search(r'/status/(\d+)', guid.text)
        if m:
            return m.group(1)
        return re.sub(r'[^a-zA-Z0-9]', '', guid.text)[-16:]
    return str(int(time.time()))

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    url = RSSHUB_URL.format(username=ACCOUNT)
    print(f"📡  Buscando feed de @{ACCOUNT}…")
    print(f"    {url}\n")

    try:
        xml_text = fetch_rss(url)
    except Exception as e:
        print(f"❌  Erro ao buscar RSS: {e}")
        sys.exit(1)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"❌  Erro ao parsear XML: {e}")
        print(xml_text[:500])
        sys.exit(1)

    channel = root.find("channel")
    if channel is None:
        channel = root

    items = channel.findall("item")
    print(f"✅  {len(items)} itens no feed\n")

    total_images = 0
    skipped_year = 0

    for item in items:
        pub_el = item.find("pubDate")
        pub_date = parse_date(pub_el.text) if pub_el is not None and pub_el.text else None

        if pub_date:
            if pub_date.year < YEAR:
                skipped_year += 1
                continue
            if pub_date.year > YEAR:
                continue
            date_str = pub_date.strftime("%Y-%m-%d")
        else:
            date_str = "unknown"

        tweet_id  = get_item_id(item)
        img_urls  = extract_images_from_item(item)

        if not img_urls:
            continue

        for i, img_url in enumerate(img_urls):
            ext  = "jpg"
            dest = OUTPUT_DIR / f"{date_str}_{tweet_id}_{i+1}.{ext}"
            if dest.exists():
                print(f"  ⏭  já existe  {dest.name}")
                continue
            try:
                download_file(img_url, dest)
                total_images += 1
                print(f"  ✅  {dest.name}")
            except Exception as e:
                print(f"  ❌  erro: {e}  ({img_url[:60]}…)")

        time.sleep(0.2)

    print(f"\n🏁  Concluído — {total_images} imagens salvas em {OUTPUT_DIR}/")
    if skipped_year:
        print(f"    ({skipped_year} itens de outros anos ignorados)")
    print(f"\n📂  Próximo passo: abra a pasta, revise as fotos e renomeie")
    print(f"    as boas com o nome do jogador: salah.jpg, neymar.jpg…")

if __name__ == "__main__":
    main()
