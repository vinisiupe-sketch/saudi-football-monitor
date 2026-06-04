"""
Baixa imagens a partir dos arquivos de URLs coletados pelo Chrome.
Coloque os arquivos urls_*.txt na mesma pasta e rode:

    python download_from_urls.py

As imagens vão para public/player-images/raw/
"""

import os
import sys
import time
import urllib.request
from pathlib import Path
from glob import glob

OUTPUT_DIR = Path("public/player-images/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def download(url: str, dest: Path):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        dest.write_bytes(r.read())

# Collect all URLs from txt files
url_files = glob("urls_*.txt") + glob(str(Path.home() / "Downloads" / "urls_*.txt"))
if not url_files:
    print("❌  Nenhum arquivo urls_*.txt encontrado.")
    print("   Coloque os arquivos baixados pelo Chrome aqui ou em Downloads/")
    sys.exit(1)

all_urls = []
for f in url_files:
    lines = Path(f).read_text().strip().splitlines()
    lines = [l.strip() for l in lines if l.strip().startswith("http")]
    all_urls.extend(lines)
    print(f"  📄  {f}: {len(lines)} URLs")

all_urls = list(dict.fromkeys(all_urls))  # deduplicate preserving order
print(f"\n📥  Total: {len(all_urls)} imagens para baixar\n")

ok = 0
fail = 0
for i, url in enumerate(all_urls, 1):
    # Extract filename: use twimg hash if available, otherwise sequential index
    if "pbs.twimg.com/media/" in url:
        base = url.split("pbs.twimg.com/media/")[-1].split("?")[0].replace(".jpg", "")
        dest = OUTPUT_DIR / f"{base}.jpg"
    else:
        dest = OUTPUT_DIR / f"img_{i:04d}.jpg"
    if dest.exists():
        print(f"  ⏭  [{i}/{len(all_urls)}] já existe {dest.name}")
        ok += 1
        continue
    try:
        download(url, dest)
        ok += 1
        print(f"  ✅  [{i}/{len(all_urls)}] {dest.name}")
    except Exception as e:
        fail += 1
        print(f"  ❌  [{i}/{len(all_urls)}] {e}")
    time.sleep(0.15)

print(f"\n🏁  {ok} baixadas, {fail} erros → {OUTPUT_DIR}/")
print(f"\n📂  Próximo passo: abra a pasta e renomeie as fotos úteis")
print(f"    Ex: salah.jpg, neymar.jpg, mitrovicr.jpg")
