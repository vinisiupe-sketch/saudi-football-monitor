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


def _temporada_tm() -> int:
    """Ano com que o TM rotula a temporada saudita corrente (vira em agosto).

    Estava fixo em 2026 no código; em agosto de 2027 isso passaria a raspar a
    temporada errada em silêncio, que é o pior tipo de defeito."""
    from datetime import date
    hoje = date.today()
    return hoje.year if hoje.month >= 8 else hoje.year - 1


TM_SAISON = _temporada_tm()
TM_URL   = f"{TM_BASE}/saudi-professional-league/transfers/wettbewerb/SA1/saison_id/{TM_SAISON}"
# Mudanças de treinador (visão detalhada): traz quem saiu e o sucessor por clube.
TM_COACH_URL = (
    f"{TM_BASE}/saudi-professional-league/trainerwechsel/wettbewerb/SA1"
    f"/plus/1/saison_id/{TM_SAISON}"
)
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


# ── Treinadores ───────────────────────────────────────────────────────────────

def _parse_coach_changes(html: str) -> list[dict]:
    """Lê a tabela de mudanças de treinador: clube, quem saiu e o sucessor.

    O TM aninha tabelas dentro das células, então as linhas precisam ser lidas
    como filhas DIRETAS do tbody — o select recursivo mistura as linhas internas
    com as de verdade. Linhas de seção ("Mudanças gerenciais antes da primeira
    rodada") têm uma célula só e caem fora pelo tamanho."""
    soup = BeautifulSoup(html, "lxml")
    mudancas: list[dict] = []

    def _tecnico(td):
        a = td.select_one("a[href*='/profil/trainer/']")
        if not a:
            return None
        nome = a.get_text(strip=True)
        tid = _extract_id(a.get("href", ""), r"/trainer/(\d+)")
        if not nome or not tid:
            return None
        return {"nome": nome, "id": tid, "href": a.get("href", "")}

    for table in soup.select("table"):
        cabecalho = [th.get_text(strip=True) for th in table.select("thead th")]
        if not any("Sucessor" in c for c in cabecalho):
            continue
        corpo = table.find("tbody")
        if not corpo:
            continue
        for tr in corpo.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 9:
                continue
            img = tds[0].find("img")
            clube = ((img.get("title") or img.get("alt") or "").strip()) if img else ""
            if not clube:
                continue
            saiu, chegou = _tecnico(tds[1]), _tecnico(tds[8])
            if saiu or chegou:
                mudancas.append({"clube": clube, "saiu": saiu, "chegou": chegou})
    return mudancas


async def _coach_nationality(client, href: str) -> tuple[str, str | None]:
    """Nacionalidade do treinador, lida da ficha dele.

    A página de mudanças não traz bandeira, e pegar a primeira bandeira do perfil
    daria errado: a ordem lá é país do clube atual, país de nascimento e só então
    a nacionalidade. Por isso o campo é buscado pelo rótulo."""
    try:
        r = await client.get(TM_BASE + href if href.startswith("/") else href)
        if r.status_code != 200:
            return "", None
        soup = BeautifulSoup(r.text, "lxml")

        def _do_span(span):
            im = span.select_one("img")
            if im and (im.get("title") or im.get("alt")):
                return (im.get("title") or im.get("alt")).strip(), \
                       (im.get("src") or im.get("data-src") or None)
            txt = span.get_text(" ", strip=True)
            return (txt.split()[0] if txt else ""), None

        for li in soup.select("li.data-header__label"):
            if "Nacionalidade" in li.get_text():
                span = li.select_one("span.data-header__content")
                if span:
                    nome, url = _do_span(span)
                    if nome:
                        return nome, url
        # fallback: bloco "Dados de perfil"
        for rot in soup.select("span.info-table__content--regular"):
            if "Nacionalidade" in rot.get_text():
                val = rot.find_next_sibling("span")
                if val:
                    nome, url = _do_span(val)
                    if nome:
                        return nome, url
        return "", None
    except Exception:
        return "", None


async def _scrape_coaches(client) -> list[dict]:
    """Devolve as mudanças de treinador no mesmo formato das transferências."""
    r = await client.get(TM_COACH_URL)
    r.raise_for_status()
    mudancas = _parse_coach_changes(r.text)

    # Só quem CHEGOU precisa de bandeira — no post, as saídas são só nome.
    nacs: dict[str, tuple[str, str | None]] = {}
    for m in mudancas:
        c = m.get("chegou")
        if c and c["id"] not in nacs:
            nacs[c["id"]] = await _coach_nationality(client, c["href"])

    registros: list[dict] = []
    for m in mudancas:
        clube = m["clube"]
        for quem, direcao in (("chegou", "in"), ("saiu", "out")):
            t = m.get(quem)
            if not t:
                continue
            nacionalidade, flag_url = nacs.get(t["id"], ("", None))
            registros.append({
                "player_id":     f"t{t['id']}",   # prefixo evita colidir com jogador
                "player_name":   t["nome"],
                "photo":         None,
                "age":           "",
                "nationality":   nacionalidade,
                "flag_url":      flag_url,
                "position":      "Treinador",
                "market_value":  "",
                "fee":           "",
                "transfer_date": None,
                "team_in":       {"name": clube if direcao == "in" else "", "logo": None},
                "team_out":      {"name": clube if direcao == "out" else "", "logo": None},
                "direction":     direcao,
            })
    return registros


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

            # Treinadores são um extra: se essa parte falhar, as transferências
            # de jogadores não podem ser perdidas junto.
            tecnicos: list[dict] = []
            try:
                tecnicos = await _scrape_coaches(client)
            except Exception as e:
                print(f"  ⚠️  Treinadores não raspados: {type(e).__name__}: {e}")

        saved, current_ids = upsert_window_transfers(transfers + tecnicos)
        removed = delete_stale_window_transfers(current_ids)
        print(f"Janela scrape: {saved} upserted ({len(tecnicos)} de treinador), {removed} removidos")
        return {"ok": True, "total": saved, "tecnicos": len(tecnicos), "removed": removed}

    except Exception as e:
        print(f"Erro no janela scrape: {e}")
        return {"ok": False, "error": str(e)}
