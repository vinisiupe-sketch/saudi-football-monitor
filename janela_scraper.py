"""
Raspa transferências da Saudi Pro League direto do Transfermarkt.
Fotos dos jogadores: buscadas via API-Football (com cache no banco).
"""
import re
import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from database import (
    upsert_window_transfers, clear_window_transfers,
    get_window_transfers_last_scraped,
    get_janela_player_photos, upsert_janela_player_photo,
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

AF_KEY  = os.environ.get("API_FOOTBALL_KEY", "")
AF_BASE = "https://v3.football.api-sports.io"


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


# ── API-Football photos ───────────────────────────────────────────────────────

async def _try_af_search(
    client: httpx.AsyncClient, headers: dict, player_name: str, league: int, season: int
) -> str | None:
    try:
        r = await client.get(
            f"{AF_BASE}/players",
            headers=headers,
            params={"search": player_name, "league": league, "season": season},
            timeout=10.0,
        )
        if r.status_code == 200:
            results = r.json().get("response", [])
            if results:
                return results[0].get("player", {}).get("photo")
    except Exception:
        pass
    return None


# Ligas para fallback quando jogador não está na Saudi (307)
# Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Liga NOS, MLS, Süper Lig, Eredivisie, J-League
_FALLBACK_LEAGUES = (39, 140, 135, 78, 61, 94, 253, 203, 88, 98)


async def _fetch_af_photo(client: httpx.AsyncClient, player_name: str) -> str | None:
    """Busca foto: primeiro na Saudi Pro League (307), depois em ligas-fonte comuns."""
    if not AF_KEY:
        return None
    headers = {"x-apisports-key": AF_KEY}

    # Fase 1: Saudi (307) seasons 2024/2023/2025/2026 em paralelo
    saudi = await asyncio.gather(
        *[_try_af_search(client, headers, player_name, 307, s) for s in (2024, 2023, 2025, 2026)],
        return_exceptions=True,
    )
    for res in saudi:
        if isinstance(res, str) and res:
            return res

    # Fase 2: ligas-fonte × seasons 2024 + 2025 em paralelo
    fallback = await asyncio.gather(
        *[
            _try_af_search(client, headers, player_name, lg, s)
            for s in (2024, 2025)
            for lg in _FALLBACK_LEAGUES
        ],
        return_exceptions=True,
    )
    for res in fallback:
        if isinstance(res, str) and res:
            return res

    return None


async def _enrich_photos_af(transfers: list[dict]) -> None:
    """Enriquece fotos via API-Football com cache persistente no banco."""
    photo_cache = get_janela_player_photos()

    # Players que faltam no cache
    missing: dict[str, str] = {}  # player_id → player_name
    for t in transfers:
        pid = t.get("player_id")
        if pid and pid not in photo_cache and pid not in missing:
            missing[pid] = t.get("player_name", "")

    print(f"  AF fotos: {len(photo_cache)} em cache, {len(missing)} a buscar")

    if missing and AF_KEY:
        BATCH = 5
        pids = list(missing.keys())
        async with httpx.AsyncClient(timeout=15.0) as client:
            for i in range(0, len(pids), BATCH):
                batch = pids[i : i + BATCH]
                results = await asyncio.gather(
                    *[_fetch_af_photo(client, missing[pid]) for pid in batch],
                    return_exceptions=True,
                )
                for pid, res in zip(batch, results):
                    if isinstance(res, str) and res:
                        photo_cache[pid] = res
                        upsert_janela_player_photo(pid, res)
                await asyncio.sleep(0.3)

        found = sum(1 for pid in pids if pid in photo_cache)
        print(f"  AF fotos: {found}/{len(pids)} encontradas")

    # Aplica fotos nos transfers
    for t in transfers:
        pid = t.get("player_id")
        if pid and pid in photo_cache:
            t["photo"] = photo_cache[pid]


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_janela_scrape() -> dict:
    """Raspa TM, enriquece fotos via API-Football e persiste no banco."""
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=TM_HEADERS
        ) as client:
            r = await client.get(TM_URL)
            r.raise_for_status()

        transfers = _parse_transfers(r.text)
        if not transfers:
            return {"ok": False, "error": "Nenhuma transferencia encontrada"}

        await _enrich_photos_af(transfers)

        clear_window_transfers()
        saved = upsert_window_transfers(transfers)
        print(f"Janela scrape: {saved} transferencias salvas")
        return {"ok": True, "total": saved}

    except Exception as e:
        print(f"Erro no janela scrape: {e}")
        return {"ok": False, "error": str(e)}
