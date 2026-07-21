"""
Raspa transferências da Saudi Pro League direto do Transfermarkt.
Fotos via API-Football removidas — frontend usa bandeira da nacionalidade no círculo.
"""
import re
import httpx
from bs4 import BeautifulSoup
from database import (
    upsert_window_transfers, delete_stale_window_transfers,
    get_window_transfers_last_scraped,
)

TM_BASE = "https://www.transfermarkt.com.br"
TM_URL  = f"{TM_BASE}/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/2026"
TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com.br/",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

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


# ── Parsing TM ───────────────────────────────────────────────────────────────

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

                p_link = cells[0].select_one("a.spielprofil_tooltip, a[href*='/profil/spieler/']")
                if not p_link:
                    continue
                player_name = p_link.text.strip()
                player_id   = _extract_id(p_link.get("href", ""), r"/spieler/(\d+)")
                if not player_name or not player_id:
                    continue

                age = cells[1].text.strip()
                flag_img = cells[2].find("img") if len(cells) > 2 else None
                nationality = (flag_img.get("title") or flag_img.get("alt") or "").strip() if flag_img else ""
                _fsrc = (flag_img.get("data-src") or flag_img.get("src") or "") if flag_img else ""
                flag_url = _fsrc if _fsrc and not _fsrc.startswith("data:") else None

                pos = cells[3].text.strip()
                mv  = cells[5].text.strip()

                other_link = cells[6].select_one("a[href]") or (cells[7].select_one("a[href]") if len(cells) > 7 else None)
                other_href    = other_link.get("href", "") if other_link else ""
                other_club_id = _extract_id(other_href, r"/(\d+)(?:/|$)")
                other_club_name = cells[7].text.strip() if len(cells) > 7 else cells[6].text.strip()
                other_club_logo = (
                    f"https://tmssl.akamaized.net//images/wappen/homepageSmall/{other_club_id}.png"
                    if other_club_id else None
                )

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
                    "player_name":   player_name,
                    "photo":         None,   # preenchido por _enrich_photos_af
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


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_janela_scrape() -> dict:
    """Raspa TM e persiste no banco."""
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=TM_HEADERS
        ) as client:
            r = await client.get(TM_URL)
            r.raise_for_status()

        transfers = _parse_transfers(r.text)
        if not transfers:
            return {"ok": False, "error": "Nenhuma transferencia encontrada"}

        saved, current_ids = upsert_window_transfers(transfers)
        removed = delete_stale_window_transfers(current_ids)
        print(f"Janela scrape: {saved} upserted, {removed} removidos")
        return {"ok": True, "total": saved, "removed": removed}

    except Exception as e:
        print(f"Erro no janela scrape: {e}")
        return {"ok": False, "error": str(e)}
