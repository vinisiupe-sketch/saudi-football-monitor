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

    rows = ""
    for idx, a in enumerate(articles):
        tier_color = {"A": "#22c55e", "B": "#eab308", "C": "#94a3b8"}.get(a["source_tier"], "#94a3b8")
        title = a.get("title_pt") or a.get("title_orig") or "—"
        body = a.get("body_pt") or a.get("body_orig") or ""
        copy_text = f"{title}\\n\\n{body}".replace("`", "'").replace('"', '&quot;')
        rows += f"""
        <tr>
          <td><span style="color:{tier_color};font-weight:bold">Tier {a['source_tier']}</span></td>
          <td>{a['source_name']}</td>
          <td>
            <a href="{a['url']}" target="_blank"><strong>{title}</strong></a>
            {f'<div style="color:#94a3b8;margin-top:4px;font-size:0.85em">{body}</div>' if body else ''}
            <button class="copy-btn" onclick="copyText(this, `{copy_text}`)" style="margin-top:6px">📋 Copiar</button>
          </td>
          <td style="white-space:nowrap">{(a.get('collected_at') or '')[:16]}</td>
          <td>{a.get('relevance_score', 0):.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>⚽ Saudi Football Monitor</title>
  <style>
    body {{ font-family: sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px; }}
    h1 {{ color: #38bdf8; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th {{ background: #1e293b; padding: 10px; text-align: left; color: #94a3b8; }}
    td {{ padding: 10px; border-bottom: 1px solid #1e293b; font-size: 0.9em; vertical-align: top; }}
    a {{ color: #38bdf8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .btn {{ background: #0284c7; color: white; border: none; padding: 8px 16px; cursor: pointer; border-radius: 4px; margin: 4px; }}
    .copy-btn {{ background: #334155; color: #94a3b8; border: none; padding: 4px 10px; cursor: pointer; border-radius: 4px; font-size: 0.8em; }}
    .copy-btn:hover {{ background: #475569; color: #e2e8f0; }}
    .copy-btn.copied {{ background: #166534; color: #86efac; }}
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
  <h1>⚽ Saudi Football Monitor</h1>
  <button class="btn" onclick="fetch('/api/collect',{{method:'POST'}}).then(()=>location.reload())">🔄 Coletar agora</button>
  <h2>📰 Artigos recentes ({len(articles)})</h2>
  <table>
    <tr><th>Tier</th><th>Fonte</th><th>Conteúdo</th><th>Coletado</th><th>Score</th></tr>
    {rows}
  </table>
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
    background_tasks.add_task(run_pipeline)
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
