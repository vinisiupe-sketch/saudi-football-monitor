"""
Saudi Football Monitor — FastAPI app principal.
"""
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from database import init_db, get_recent_articles, get_collection_logs
from scheduler import run_pipeline, create_scheduler

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    # Roda pipeline na inicialização
    asyncio.create_task(run_pipeline())
    yield
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(title="Saudi Football Monitor", lifespan=lifespan)


# ─── Dashboard ───────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    articles = get_recent_articles(hours=24, limit=50)
    articles = [a for a in articles if a.get("relevance_score", 0) >= 0.34]

    CATEGORY_EMOJI = {
        "transferencia": ("🔄", "#dbeafe", "#1d4ed8"),
        "patrocinio":    ("🤝", "#ede9fe", "#6d28d9"),
        "planejamento":  ("📋", "#e0f2fe", "#0369a1"),
        "entrevista":    ("🎙️", "#fef3c7", "#b45309"),
        "resultado":     ("⚽", "#dcfce7", "#15803d"),
        "competicao":    ("🏆", "#fef9c3", "#a16207"),
        "treino":        ("🏋️", "#f0fdf4", "#166534"),
        "financeiro":    ("💰", "#fdf4ff", "#7e22ce"),
        "lesao":         ("🩺", "#fff1f2", "#be123c"),
        "geral":         ("📰", "#f1f5f9", "#475569"),
    }

    cards = ""
    for a in articles:
        tier_color = {"A": "#16a34a", "B": "#ca8a04", "C": "#64748b"}.get(a["source_tier"], "#64748b")
        tier_bg    = {"A": "#dcfce7", "B": "#fef9c3", "C": "#f1f5f9"}.get(a["source_tier"], "#f1f5f9")
        title = a.get("title_pt") or a.get("title_orig") or "—"
        body  = (a.get("body_pt") or a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        image_url = a.get("image_url") or ""
        category = a.get("category") or "geral"
        emoji, emoji_bg, emoji_color = CATEGORY_EMOJI.get(category, CATEGORY_EMOJI["geral"])
        copy_text = f"{title}\\n\\n{a.get('body_pt') or a.get('body_orig') or ''}".replace("`", "'")
        collected = (a.get("collected_at") or "")[:16].replace("T", " ")
        img_html = (
            f'<div class="card-img" style="background-image:url({image_url})"></div>'
            if image_url else
            f'<div class="card-img no-img" style="background:{emoji_bg};color:{emoji_color}">{emoji}</div>'
        )
        cards += f"""
        <div class="card">
          {img_html}
          <div class="card-body">
            <div class="card-meta">
              <span class="tier-badge" style="background:{tier_bg};color:{tier_color}">Tier {a['source_tier']}</span>
              <span class="source">@{a['source_name'].lstrip('@')}</span>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <p class="card-text">{body}</p>
            <div class="card-footer">
              <span class="card-date">{collected}</span>
              <button class="copy-btn" onclick="copyText(this, `{copy_text}`)">📋 Copiar</button>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚽ Saudi Football Monitor</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
    header {{ background: white; border-bottom: 1px solid #e2e8f0; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
    header h1 {{ font-size: 1.2rem; font-weight: 700; color: #0f172a; }}
    .collect-btn {{ background: #0284c7; color: white; border: none; padding: 8px 18px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 600; }}
    .collect-btn:hover {{ background: #0369a1; }}
    .count {{ color: #64748b; font-size: 0.85rem; margin: 16px 24px 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; padding: 16px 24px 40px; }}
    .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.08); display: flex; flex-direction: column; transition: box-shadow .2s; }}
    .card:hover {{ box-shadow: 0 6px 20px rgba(0,0,0,.13); }}
    .card-img {{ height: 180px; background-size: cover; background-position: center; background-color: #e2e8f0; }}
    .card-img.no-img {{ display: flex; align-items: center; justify-content: center; font-size: 3rem; background: #e2e8f0; }}
    .card-body {{ padding: 16px; display: flex; flex-direction: column; flex: 1; }}
    .card-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
    .tier-badge {{ font-size: 0.72rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
    .source {{ font-size: 0.8rem; color: #64748b; }}
    .card-title {{ font-size: 0.97rem; font-weight: 700; color: #0f172a; text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ color: #0284c7; }}
    .card-text {{ font-size: 0.82rem; color: #475569; line-height: 1.55; flex: 1; }}
    .card-footer {{ display: flex; align-items: center; justify-content: space-between; margin-top: 14px; padding-top: 10px; border-top: 1px solid #f1f5f9; }}
    .card-date {{ font-size: 0.75rem; color: #94a3b8; }}
    .copy-btn {{ background: #f1f5f9; color: #475569; border: none; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.78rem; }}
    .copy-btn:hover {{ background: #e2e8f0; }}
    .copy-btn.copied {{ background: #dcfce7; color: #16a34a; }}
  </style>
  <script>
    function copyText(btn, text) {{
      navigator.clipboard.writeText(text).then(() => {{
        btn.textContent = '✅ Copiado';
        btn.classList.add('copied');
        setTimeout(() => {{ btn.textContent = '📋 Copiar'; btn.classList.remove('copied'); }}, 2000);
      }});
    }}
  </script>
</head>
<body>
  <header>
    <h1>⚽ Saudi Football Monitor</h1>
    <button class="collect-btn" onclick="fetch('/api/collect',{{method:'POST'}}).then(()=>location.reload())">🔄 Coletar agora</button>
  </header>
  <p class="count">{len(articles)} notícias nas últimas 24h</p>
  <div class="grid">
    {cards}
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── API endpoints ────────────────────────────
@app.get("/api/articles")
async def api_articles(hours: int = 24, tier: str = None, limit: int = 100):
    return get_recent_articles(hours=hours, tier=tier, limit=limit)



@app.get("/api/stats")
async def api_stats():
    articles = get_recent_articles(hours=24, limit=500)
    logs = get_collection_logs(limit=1)
    return {
        "articles_last_24h": len(articles),
        "by_tier": {
            "A": sum(1 for a in articles if a["source_tier"] == "A"),
            "B": sum(1 for a in articles if a["source_tier"] == "B"),
            "C": sum(1 for a in articles if a["source_tier"] == "C"),
        },
        "last_collection": logs[0] if logs else None,
    }


@app.get("/api/logs")
async def api_logs(limit: int = 20):
    return get_collection_logs(limit=limit)


@app.post("/api/collect")
async def api_collect(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_pipeline, True)  # force=True ignora período inativo
    return {"status": "started"}



@app.get("/api/twitter-test")
async def twitter_test(username: str = "FabrizioRomano"):
    """Testa todos os provedores RSS para uma conta do Twitter. Ex: /api/twitter-test?username=FabrizioRomano"""
    import httpx
    import feedparser
    from sources import TWITTER_RSS_PROVIDERS

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; SaudiFootballMonitor/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    results = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for template in TWITTER_RSS_PROVIDERS:
            url = template.format(username=username)
            provider = url.split("/")[2]
            try:
                resp = await client.get(url, headers=HEADERS)
                feed = feedparser.parse(resp.text)
                entries = len(feed.entries)
                results.append({
                    "provider": provider,
                    "url": url,
                    "status": resp.status_code,
                    "entries": entries,
                    "ok": entries > 0,
                    "sample": feed.entries[0].get("title", "")[:100] if entries > 0 else None,
                })
            except Exception as e:
                results.append({
                    "provider": provider,
                    "url": url,
                    "status": None,
                    "entries": 0,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                })

    working = [r for r in results if r["ok"]]
    return {
        "username_tested": username,
        "working_providers": len(working),
        "results": results,
    }
