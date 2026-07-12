"""
Raspa transferências da Saudi Pro League direto do Transfermarkt.
URL: https://www.transfermarkt.com.br/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/2026

Estrutura da página (26/27):
  - .box com h2 contendo nome/ID do clube
  - Dentro: tabelas com thead "Entradas" (in) e "Saídas" (out)
  - Colunas: Jogador | Idade | Nac. | Posição | Pos | Valor de mercado |
             Origem/Destino (logo) | Origem/Destino (nome) |
             Quantia paga [+ \n data em <i class="normaler-text">]
"""
import re
import httpx
from bs4 import BeautifulSoup
from database import upsert_window_transfers, get_window_transfers_last_scraped, clear_window_transfers

TM_URL = "https://www.transfermarkt.com.br/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/2026"
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
    """Extrai data de transferência da coluna 8.
    O TM inclui <i class="normaler-text">DD/MM/YYYY</i> dentro da célula."""
    if cell is None:
        return None
    date_tag = cell.find("i", class_="normaler-text")
    if not date_tag:
        return None
    text = date_tag.get_text(strip=True)
    # Formato TM: DD/MM/YYYY  →  YYYY-MM-DD
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _fee_text(cell) -> str:
    """Retorna só o texto da quantia (sem a data que fica em <i>)."""
    if cell is None:
        return ""
    # Remove a tag <i> antes de pegar o texto
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
                player_id   = _extract_id(p_link.get("href", ""), r"/spieler/(\d+)")
                if not player_name or not player_id:
                    continue

                age = cells[1].text.strip()
                # Nationality: flag img title in col 2
                flag_img = cells[2].find("img") if len(cells) > 2 else None
                nationality = (flag_img.get("title") or flag_img.get("alt") or "").strip() if flag_img else ""
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

                # Col 8: fee + data (data em <i class="normaler-text">)
                fee_cell = cells[8] if len(cells) > 8 else None
                transfer_date = _parse_date(fee_cell)
                fee = _fee_text(fee_cell)

                key = f"{player_id}_{direction}_{club_id}"
                if key in seen:
                    continue
                seen.add(key)

                # TM portrait — use data-src from lazy img if present in col 0
                _pimg = cells[0].find("img")
                _psrc = (_pimg.get("data-src") or _pimg.get("src") or "") if _pimg else ""
                if _psrc and "portrait" in _psrc:
                    photo = _psrc.split("?")[0]  # strip query params
                else:
                    photo = f"https://img.a.transfermarkt.technology/portrait/small/{player_id}.jpg"

                if direction == "in":
                    team_in  = {"name": club_name,       "logo": club_logo}
                    team_out = {"name": other_club_name,  "logo": other_club_logo}
                else:
                    team_in  = {"name": other_club_name,  "logo": other_club_logo}
                    team_out = {"name": club_name,        "logo": club_logo}

                transfers.append({
                    "player_id":     player_id,
                    "player_name":   player_name,
                    "photo":         photo,
                    "age":           age,
                    "nationality":   nationality,
                    "position":      pos,
                    "market_value":  mv,
                    "fee":           fee,
                    "transfer_date": transfer_date,
                    "team_in":       team_in,
                    "team_out":      team_out,
                    "direction":     direction,
                })

    return transfers


async def run_janela_scrape() -> dict:
    """Raspa o TM e persiste no banco. Retorna resumo."""
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=HEADERS
        ) as client:
            r = await client.get(TM_URL)
            r.raise_for_status()

        transfers = _parse_transfers(r.text)
        if not transfers:
            return {"ok": False, "error": "Nenhuma transferencia encontrada - possivel bloqueio ou mudanca de HTML"}

        # Limpa dados antigos antes de inserir nova temporada
        clear_window_transfers()
        saved = upsert_window_transfers(transfers)
        print(f"Janela scrape: {saved} transferencias salvas")
        return {"ok": True, "total": saved}

    except Exception as e:
        print(f"Erro no janela scrape: {e}")
        return {"ok": False, "error": str(e)}
