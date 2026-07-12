"""
Raspa transferências da Saudi Pro League direto do Transfermarkt.
URL: https://www.transfermarkt.com.br/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/2026

Estrutura da página (26/27):
  - .box com h2 contendo nome/ID do clube
  - Dentro: tabelas com thead "Entradas" (in) e "Saídas" (out)
  - Colunas: Jogador | Idade | Nac. | Posição | Pos | Valor de mercado |
             Origem/Destino (logo) | Origem/Destino (nome) |
             Quantia paga [+ \n data em <i class="normaler-text">]

Fotos: buscadas nas páginas de perfil individual (com ?lm=...) em batch.
"""
import re
import asyncio
import httpx
from bs4 import BeautifulSoup
from database import upsert_window_transfers, get_window_transfers_last_scraped, clear_window_transfers

TM_BASE = "https://www.transfermarkt.com.br"
TM_URL  = f"{TM_BASE}/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/2026"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com.br/",
}


def _extract_id(href: str, pattern: str) -> str | None:
    m = re.search(pattern, href or "")
    return m.group(1) if m else None


def _parse_date(cell) -> str | None:
    if cell is None:
        return None
    date_tag = cell.find("i", class_="normaler-text")
    if not date_tag:
        return None
    text = date_tag.get_text(strip=True)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _fee_text(cell) -> str:
    if cell is None:
        return ""
    tag = cell.find("i", class_="normaler-text")
    if tag:
        tag.decompose()
    return cell.get_text(separator=" ", strip=True)


def _parse_transfers(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    transfers: list[dict] = []
    seen: set[str] = set()

    for box in soup.select(".box"):
        club_h2 = box.select_one("h2 a[href]")
        if not club_h2:
            continue
        club_name = (club_h2.get("title") or club_h2.text).strip()
        club_href = club_h2.get("href", "")
        club_id = _extract_id(club_href, r"/(\d+)/saison_id") or _extract_id(club_href, r"/(\d+)(?:/|$)")
        club_logo = (
            f"https://tmssl.akamaized.net//images/wappen/homepageSmall/{club_id}.png"
            if club_id else None
        )

        for table in box.select("table"):
            th = table.select_one("thead th")
            if not th:
                continue
            th_text = th.text.strip()
            if th_text.startswith("Entrada"):
                direction = "in"
            elif th_text.startswith("Saída"):
                direction = "out"
            else:
                continue

            for row in table.select("tbody tr"):
                cells = row.select("td")
                if len(cells) < 7:
                    continue

                # Jogador (col 0)
                p_link = cells[0].select_one("a.spielprofil_tooltip, a[href*='/profil/spieler/']")
                if not p_link:
                    continue
                player_name = p_link.text.strip()
                player_href = p_link.get("href", "")
                player_id   = _extract_id(player_href, r"/spieler/(\d+)")
                if not player_name or not player_id:
                    continue

                age = cells[1].text.strip()
                # Nationality: flag img title em col 2
                flag_img = cells[2].find("img") if len(cells) > 2 else None
                nationality = (flag_img.get("title") or flag_img.get("alt") or "").strip() if flag_img else ""
                _fsrc = (flag_img.get("data-src") or flag_img.get("src") or "") if flag_img else ""
                flag_url = _fsrc if _fsrc and not _fsrc.startswith("data:") else None

                pos = cells[3].text.strip()
                mv  = cells[5].text.strip()

                # Clube de origem/destino: col 6 = logo, col 7 = nome
                other_link = cells[6].select_one("a[href]") or (cells[7].select_one("a[href]") if len(cells) > 7 else None)
                other_href    = other_link.get("href", "") if other_link else ""
                other_club_id = _extract_id(other_href, r"/(\d+)(?:/|$)")
                other_club_name = cells[7].text.strip() if len(cells) > 7 else cells[6].text.strip()
                other_club_logo = (
                    f"https://tmssl.akamaized.net//images/wappen/homepageSmall/{other_club_id}.png"
                    if other_club_id else None
                )

                # Col 8: fee + data
                fee_cell = cells[8] if len(cells) > 8 else None
                transfer_date = _parse_date(fee_cell)
                fee = _fee_text(fee_cell)

                key = f"{player_id}_{direction}_{club_id}"
                if key in seen:
                    continue
                seen.add(key)

                if direction == "in":
                    team_in  = {"name": club_name,       "logo": club_logo}
                    team_out = {"name": other_club_name,  "logo": other_club_logo}
                else:
                    team_in  = {"name": other_club_name,  "logo": other_club_logo}
                    team_out = {"name": club_name,        "logo": club_logo}

                transfers.append({
                    "player_id":     player_id,
                    "player_href":   player_href,   # usado só durante o scrape
                    "player_name":   player_name,
                    "photo":         None,           # preenchido por _enrich_photos
                    "age":           age,
                    "nationality":   nationality,
                    "flag_url":      flag_url,
                    "position":      pos,
                    "market_value":  mv,
                    "fee":           fee,
                    "transfer_date": transfer_date,
                    "team_in":       team_in,
                    "team_out":      team_out,
                    "direction":     direction,
                })

    return transfers


async def _fetch_portrait(client: httpx.AsyncClient, player_href: str) -> str | None:
    """Busca URL do retrato na página de perfil do jogador no TM (inclui ?lm=...)."""
    try:
        url = f"{TM_BASE}{player_href}"
        r = await client.get(url, follow_redirects=True, timeout=12.0)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        # Tenta seletores do cabeçalho de perfil
        for sel in [
            "img.data-header__profile-image",
            "img[src*='portrait/big']",
            "img[src*='portrait/medium']",
            "img[src*='portrait/small']",
            "img[data-src*='portrait']",
        ]:
            img = soup.select_one(sel)
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if "portrait" in src and "?" in src:
                    return src
    except Exception:
        pass
    return None


async def _enrich_photos(transfers: list[dict], client: httpx.AsyncClient) -> None:
    """Busca fotos reais (com ?lm=...) das páginas de perfil — batches de 5."""
    id_to_href: dict[str, str] = {}
    for t in transfers:
        pid  = t.get("player_id")
        href = t.get("player_href")
        if pid and href and pid not in id_to_href:
            id_to_href[pid] = href

    BATCH = 5
    photo_map: dict[str, str] = {}
    pids = list(id_to_href.keys())
    print(f"  Buscando fotos de {len(pids)} jogadores...")

    for i in range(0, len(pids), BATCH):
        batch = pids[i : i + BATCH]
        results = await asyncio.gather(
            *[_fetch_portrait(client, id_to_href[pid]) for pid in batch],
            return_exceptions=True,
        )
        for pid, res in zip(batch, results):
            if isinstance(res, str) and res:
                photo_map[pid] = res
        await asyncio.sleep(0.8)

    print(f"  Fotos encontradas: {len(photo_map)}/{len(pids)}")

    for t in transfers:
        pid = t.get("player_id")
        if pid and pid in photo_map:
            t["photo"] = photo_map[pid]


async def run_janela_scrape() -> dict:
    """Raspa o TM, enriquece com fotos de perfil e persiste no banco."""
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=HEADERS
        ) as client:
            r = await client.get(TM_URL)
            r.raise_for_status()

            transfers = _parse_transfers(r.text)
            if not transfers:
                return {"ok": False, "error": "Nenhuma transferencia encontrada - possivel bloqueio ou mudanca de HTML"}

            # Enriquece fotos via páginas de perfil individuais
            await _enrich_photos(transfers, client)

        clear_window_transfers()
        saved = upsert_window_transfers(transfers)
        print(f"Janela scrape: {saved} transferencias salvas")
        return {"ok": True, "total": saved}

    except Exception as e:
        print(f"Erro no janela scrape: {e}")
        return {"ok": False, "error": str(e)}
