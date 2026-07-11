"""
Phase 2 — Enriquecimento de IDs via API-Football.
Usa os tags extraídos pelo LLM (Phase 1) para buscar af_player_id e af_team_from_id
com muito mais precisão do que antes, graças ao contexto de liga e país.

Fluxo:
  league_from + country_from → league_id (mapa estático)
  club_from + league_id      → af_team_from_id  (API /teams)
  player_name + team_id      → af_player_id     (API /players)
"""
import os
import asyncio
import unicodedata
import re
import httpx
from database import get_conn, update_transfer_af_ids

_AF_BASE = "https://v3.football.api-sports.io"


def _af_key() -> str:
    return os.environ.get("API_FOOTBALL_KEY", "")


def _norm(s: str) -> str:
    """Normaliza string para comparação: minúsculo, sem acento, sem hifens."""
    s = (s or "").lower().strip()
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ─────────────────────────────────────────────────────────────────────────────
#  MAPA DE LIGAS: texto extraído pelo LLM → (league_id, season_preferida)
# ─────────────────────────────────────────────────────────────────────────────
_LEAGUE_MAP: dict[str, tuple[int, int]] = {
    # Saudi
    "saudi pro league":          (307, 2024),
    "roshn saudi league":        (307, 2024),
    "spl":                       (307, 2024),
    "liga saudi":                (307, 2024),
    "saudi first division":      (308, 2024),
    # England
    "premier league":            (39,  2024),
    "english premier league":    (39,  2024),
    "epl":                       (39,  2024),
    "championship":              (40,  2024),
    # Spain
    "la liga":                   (140, 2024),
    "primera division":          (140, 2024),
    "liga espanola":             (140, 2024),
    "segunda division":          (141, 2024),
    # Italy
    "serie a":                   (135, 2024),
    "serie a italiana":          (135, 2024),
    "serie b":                   (136, 2024),
    # Germany
    "bundesliga":                (78,  2024),
    "1. bundesliga":             (78,  2024),
    "2. bundesliga":             (79,  2024),
    # France
    "ligue 1":                   (61,  2024),
    "ligue 2":                   (62,  2024),
    # Portugal
    "primeira liga":             (94,  2024),
    "liga portugal":             (94,  2024),
    "liga nos":                  (94,  2024),
    "liga portuguesa":           (94,  2024),
    # Netherlands
    "eredivisie":                (88,  2024),
    # Turkey
    "super lig":                 (203, 2024),
    "superlig":                  (203, 2024),
    # Belgium
    "pro league":                (144, 2024),
    "jupiler pro league":        (144, 2024),
    # Brazil
    "brasileirao":               (71,  2024),
    "serie a brasileira":        (71,  2024),
    "brasileirao serie a":       (71,  2024),
    "campeonato brasileiro":     (71,  2024),
    # Argentina
    "liga profesional":          (128, 2024),
    "primera division argentina":(128, 2024),
    # Mexico
    "liga mx":                   (262, 2024),
    # USA
    "mls":                       (253, 2024),
    "major league soccer":       (253, 2024),
    # Greece
    "super league":              (197, 2024),
    # Russia
    "premier league russa":      (235, 2024),
    "rpl":                       (235, 2024),
    # Scotland
    "premiership":               (179, 2024),
    "premiership escocesa":      (179, 2024),
    # Ukraine
    "premier league ucraniana":  (333, 2024),
    # China
    "chinese super league":      (169, 2024),
    "super league chinesa":      (169, 2024),
    # Japan
    "j1 league":                 (98,  2024),
    "j league":                  (98,  2024),
    # Norway
    "eliteserien":               (103, 2024),
    "liga norueguesa":           (103, 2024),
    # Sweden
    "allsvenskan":               (113, 2024),
    # Denmark
    "superliga dinamarquesa":    (119, 2024),
    "superliga":                 (119, 2024),
    # Champions League / Copa
    "champions league":          (2,   2024),
    "europa league":             (3,   2024),
    "conference league":         (848, 2024),
}


def _resolve_league(league_from: str | None) -> tuple[int, int] | None:
    """Retorna (league_id, season) a partir do texto extraído pelo LLM."""
    if not league_from:
        return None
    key = _norm(league_from)
    if key in _LEAGUE_MAP:
        return _LEAGUE_MAP[key]
    for k, v in _LEAGUE_MAP.items():
        if k in key or key in k:
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  HTTP helper
# ─────────────────────────────────────────────────────────────────────────────
async def _af_get(client: httpx.AsyncClient, path: str, params: dict, api_key: str) -> dict:
    r = await client.get(
        f"{_AF_BASE}/{path}",
        params=params,
        headers={"x-apisports-key": api_key},
        timeout=15,
    )
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
#  LOOKUP DE TIME
# ─────────────────────────────────────────────────────────────────────────────
async def _find_team_id(
    client: httpx.AsyncClient,
    club_name: str,
    league_id: int | None,
    season: int,
    country: str | None,
    api_key: str,
) -> str | None:
    search_term = club_name[:20]

    # 1ª: nome + liga
    if league_id:
        try:
            j = await _af_get(client, "teams",
                {"search": search_term, "league": league_id, "season": season}, api_key)
            items = j.get("response") or []
            if items:
                return str(items[0]["team"]["id"])
            if j.get("errors"):
                print(f"   AF /teams error: {j['errors']}")
        except Exception as e:
            print(f"   AF /teams exception (league): {e}")

    # 2ª: nome + país
    if country:
        try:
            j = await _af_get(client, "teams",
                {"search": search_term, "country": country}, api_key)
            items = j.get("response") or []
            if items:
                nm = _norm(club_name)
                for item in items:
                    if _norm(item["team"]["name"]) == nm:
                        return str(item["team"]["id"])
                return str(items[0]["team"]["id"])
        except Exception as e:
            print(f"   AF /teams exception (country): {e}")

    # 3ª: só nome (sem liga/país) — API permite isso para /teams
    try:
        j = await _af_get(client, "teams", {"search": search_term}, api_key)
        items = j.get("response") or []
        nm = _norm(club_name)
        for item in items:
            if _norm(item["team"]["name"]) == nm:
                return str(item["team"]["id"])
        if items:
            return str(items[0]["team"]["id"])
    except Exception as e:
        print(f"   AF /teams exception (name only): {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
#  LOOKUP DE JOGADOR
# ─────────────────────────────────────────────────────────────────────────────
async def _find_player_id(
    client: httpx.AsyncClient,
    player_name: str,
    team_id: str | None,
    api_key: str,
    league_id: int | None = None,
    season: int = 2024,
) -> str | None:
    search = player_name[:20]

    # Com team_id: mais preciso
    if team_id:
        for s in [2025, 2024, 2023]:
            try:
                j = await _af_get(client, "players",
                    {"search": search, "team": team_id, "season": s}, api_key)
                items = j.get("response") or []
                if items:
                    return str(items[0]["player"]["id"])
                errs = j.get("errors")
                if errs:
                    print(f"   AF /players error (team): {errs}")
                    break
            except Exception as e:
                print(f"   AF /players exception (team+{s}): {e}")
            await asyncio.sleep(0.15)

    # Fallback com liga (API exige team OU league; nome-só retorna erro)
    if league_id:
        try:
            j = await _af_get(client, "players",
                {"search": search, "league": league_id, "season": season}, api_key)
            items = j.get("response") or []
            nm = _norm(player_name)
            for item in items:
                full  = _norm(item["player"].get("name", ""))
                first = _norm(item["player"].get("firstname", ""))
                last  = _norm(item["player"].get("lastname", ""))
                if nm in full or nm in f"{first} {last}":
                    return str(item["player"]["id"])
            if j.get("errors"):
                print(f"   AF /players error (league fallback): {j['errors']}")
        except Exception as e:
            print(f"   AF /players exception (league fallback): {e}")

    # Sem team nem league: API retornaria erro — não tenta
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNÓSTICO
# ─────────────────────────────────────────────────────────────────────────────
async def diagnose(player_name: str = "Neymar", club: str = "Al Hilal") -> dict:
    api_key = _af_key()
    out: dict = {"api_key_set": bool(api_key), "api_key_prefix": api_key[:4] + "..." if api_key else ""}
    if not api_key:
        return out
    async with httpx.AsyncClient() as client:
        try:
            # players exige team ou league
            j = await _af_get(client, "players",
                {"search": player_name[:20], "league": 307, "season": 2024}, api_key)
            out["players_response"] = {
                "results": j.get("results", 0),
                "errors": j.get("errors"),
                "first": j.get("response", [{}])[0].get("player", {}).get("name") if j.get("response") else None,
            }
        except Exception as e:
            out["players_error"] = str(e)
        try:
            j2 = await _af_get(client, "teams", {"search": club[:20]}, api_key)
            out["teams_response"] = {
                "results": j2.get("results", 0),
                "errors": j2.get("errors"),
                "first": j2.get("response", [{}])[0].get("team", {}).get("name") if j2.get("response") else None,
            }
        except Exception as e:
            out["teams_error"] = str(e)
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  ENRIQUECIMENTO DE UM REGISTRO
# ─────────────────────────────────────────────────────────────────────────────
async def enrich_one(
    meta: dict,
    client: httpx.AsyncClient,
    api_key: str,
) -> dict:
    result: dict = {}

    player_name  = meta.get("player_name") or ""
    club_from    = meta.get("club_from") or ""
    country_from = meta.get("context_country") or ""
    league_from  = meta.get("context_league") or ""

    if not player_name:
        return result

    league_info = _resolve_league(league_from)
    league_id   = league_info[0] if league_info else None
    season      = league_info[1] if league_info else 2024

    # 1. Busca team_from_id
    team_from_id = meta.get("af_team_from_id")
    if not team_from_id and club_from:
        team_from_id = await _find_team_id(
            client, club_from, league_id, season, country_from, api_key
        )
        if team_from_id:
            result["af_team_from_id"] = team_from_id
        await asyncio.sleep(0.2)

    # 2. Busca player_id
    if not meta.get("af_player_id"):
        team_for_player = team_from_id or meta.get("af_team_to_id")
        player_id = await _find_player_id(
            client, player_name, team_for_player, api_key,
            league_id=league_id, season=season,
        )
        if player_id:
            result["af_player_id"] = player_id
        await asyncio.sleep(0.2)

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  BACKFILL COMPLETO
# ─────────────────────────────────────────────────────────────────────────────
async def enrich_all_ids() -> dict:
    api_key = _af_key()
    if not api_key:
        return {"error": "API_FOOTBALL_KEY não configurado"}

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT article_id, player_name, club_from, club_to,
                   context_country, context_league,
                   af_player_id, af_team_from_id, af_team_to_id
            FROM transfer_meta
            WHERE player_name IS NOT NULL
              AND (af_player_id IS NULL OR af_team_from_id IS NULL)
            ORDER BY classified_at DESC
            LIMIT 500
        """)
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r)) for r in c.fetchall()]

    total = len(rows)
    enriched = skipped = 0
    print(f"Phase 2 enrich: {total} registros para processar...")

    BATCH = 3
    async with httpx.AsyncClient() as client:
        for i in range(0, total, BATCH):
            batch = rows[i:i + BATCH]
            results = await asyncio.gather(
                *[enrich_one(m, client, api_key) for m in batch],
                return_exceptions=True,
            )
            for meta, upd in zip(batch, results):
                if isinstance(upd, Exception) or not upd:
                    skipped += 1
                    continue
                update_transfer_af_ids(
                    meta["article_id"],
                    upd.get("af_player_id"),
                    upd.get("af_team_from_id"),
                    upd.get("af_team_to_id"),
                )
                enriched += 1
            if (i // BATCH + 1) % 5 == 0:
                print(f"   Lote {i//BATCH+1}: {enriched} enriquecidos, {skipped} sem resultado")
            await asyncio.sleep(1.5)

    print(f"Phase 2 concluido: {enriched} enriquecidos, {skipped} sem resultado de {total}")
    return {"enriched": enriched, "skipped": skipped, "total": total}
