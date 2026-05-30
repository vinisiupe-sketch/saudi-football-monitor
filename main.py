"""
Saudi Football Monitor — FastAPI app principal.
"""
import os
import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import quote
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from database import init_db, get_recent_articles, get_low_score_articles, get_collection_logs, set_flag, get_all_flags
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

# Servir fontes e máscaras para o gerador de posts
app.mount("/fonts", StaticFiles(directory="public/fonts"), name="fonts")
app.mount("/masks", StaticFiles(directory="public/masks"), name="masks")


# ─── Dashboard ───────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    articles = get_recent_articles(hours=24, limit=50)
    articles = [a for a in articles if a.get("relevance_score", 0) >= 0.34]
    articles.sort(key=lambda a: a.get("collected_at") or "", reverse=True)

    CATEGORY_EMOJI = {
        "transferencia": ("🔄", "#dbeafe", "#1d4ed8"),
        "sondagem":      ("🔎", "#e0f2fe", "#0369a1"),
        "patrocinio":    ("🤝", "#ede9fe", "#6d28d9"),
        "planejamento":  ("📋", "#f0fdf4", "#166534"),
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
        moon       = {"A": "🌕", "B": "🌓", "C": "🌗"}.get(a["source_tier"], "")
        title = a.get("title_pt") or a.get("title_orig") or "—"
        body  = (a.get("body_pt") or a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        image_url = a.get("image_url") or ""
        category = a.get("category")
        copy_text = f"{title}\\n\\n{a.get('body_pt') or a.get('body_orig') or ''}".replace("`", "'")
        source_handle = a.get("source_name", "").lstrip("@")
        post_text_full = title + "\n\n" + (a.get("body_pt") or a.get("body_orig") or "") + "\n\n🗞️ @" + source_handle
        post_url = f"/gerador?texto={quote(post_text_full)}&source={quote(source_handle)}&tier={quote(a.get('source_tier',''))}&translated=1"
        collected = (a.get("collected_at") or "")[:16].replace("T", " ")
        category = category or "geral"
        emoji, emoji_bg, emoji_color = CATEGORY_EMOJI.get(category, CATEGORY_EMOJI["geral"])
        art_id = a['id']
        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-meta">
              <span class="tier-badge" style="background:{tier_bg};color:{tier_color}">Tier {a['source_tier']}</span>
              <span class="cat-emoji" title="{category}">{emoji}</span>
              <span class="source">@{a['source_name'].lstrip('@')}</span>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <button class="expand-btn" onclick="toggleExpand(this)" title="Expandir card">▼ ver mais</button>
            <p class="card-text">{body}</p>
            <div class="card-footer">
              <span class="card-date">{collected} · {moon} @{a['source_name'].lstrip('@')}</span>
              <div class="btn-row">
                <button class="flag-btn visto-btn" onclick="toggleFlag('{art_id}','naopublicado')">🔖 Não publicado</button>
                <button class="flag-btn pub-btn"   onclick="toggleFlag('{art_id}','publicado')">📢 Publicado</button>
                <button class="copy-btn" onclick="copyText(this, `{copy_text}`)">📋 Copiar</button>
                <a class="copy-btn" href="{post_url}" style="text-decoration:none;">✍️ Post</a>
              </div>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚽ Centrão do Noticião</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
    /* ── NAV ── */
    header {{ background: white; border-bottom: 1px solid #e2e8f0; padding: 0 24px; display: flex; align-items: center; gap: 32px; position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.06); height: 56px; }}
    .brand {{ font-size: 1.1rem; font-weight: 800; color: #0f172a; text-decoration: none; white-space: nowrap; }}
    nav {{ display: flex; gap: 4px; }}
    .nav-link {{ padding: 8px 14px; border-radius: 7px; font-size: 0.88rem; font-weight: 600; color: #64748b; text-decoration: none; transition: all .15s; }}
    .nav-link:hover {{ background: #f1f5f9; color: #0f172a; }}
    .nav-link.active {{ background: #eff6ff; color: #0284c7; }}
    /* ── TOPBAR ── */
    .topbar {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin: 14px 24px 6px; }}
    .count {{ color: #64748b; font-size: 0.85rem; }}
    .flag-summary {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .fs-badge {{ font-size: 0.75rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; }}
    .fs-total     {{ background: #f1f5f9; color: #475569; }}
    .fs-visto     {{ background: #e0e7ff; color: #3730a3; }}
    .fs-publicado {{ background: #bbf7d0; color: #166534; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; padding: 16px 24px 24px; align-items: start; }}
    /* ── CARDS ── */
    .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.08); display: flex; flex-direction: column; transition: box-shadow .2s, background .2s; }}
    .card:hover {{ box-shadow: 0 6px 20px rgba(0,0,0,.13); }}
    .card.flag-visto {{ background: #e0e7ff; border: 2px solid #6366f1; box-shadow: 0 4px 14px rgba(99,102,241,.25); }}
    .card.flag-publicado {{ background: #bbf7d0; border: 2px solid #16a34a; box-shadow: 0 4px 14px rgba(22,163,74,.25); }}
    .card-body {{ padding: 16px; display: flex; flex-direction: column; }}
    .card-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
    .tier-badge {{ font-size: 0.72rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
    .cat-emoji {{ font-size: 1rem; line-height: 1; }}
    .source {{ font-size: 0.8rem; color: #64748b; }}
    .card-title {{ font-size: 0.97rem; font-weight: 700; color: #0f172a; text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ color: #0284c7; }}
    .card-text {{ font-size: 0.82rem; color: #475569; line-height: 1.55; }}
    .card-footer {{ display: flex; align-items: center; justify-content: space-between; margin-top: 14px; padding-top: 10px; border-top: 1px solid #e2e8f0; flex-wrap: wrap; gap: 6px; }}
    .card-date {{ font-size: 0.75rem; color: #94a3b8; }}
    .btn-row {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .copy-btn {{ background: #f1f5f9; color: #475569; border: none; padding: 5px 10px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; white-space: nowrap; }}
    .copy-btn:hover {{ background: #e2e8f0; }}
    .copy-btn.copied {{ background: #dcfce7; color: #16a34a; }}
    a.copy-btn {{ background: #f0fdf4; color: #15803d; }}
    a.copy-btn:hover {{ background: #dcfce7; }}
    .flag-btn {{ border: none; padding: 5px 10px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; white-space: nowrap; transition: all .15s; }}
    .flag-btn.visto-btn   {{ background: #e0e7ff; color: #3730a3; }}
    .flag-btn.visto-btn.on   {{ background: #6366f1; color: white; }}
    .flag-btn.pub-btn     {{ background: #dcfce7; color: #166534; }}
    .flag-btn.pub-btn.on     {{ background: #16a34a; color: white; }}
    /* ── COLLAPSE ── */
    .card-collapsed .card-text,
    .card-collapsed .card-footer {{ display: none; }}
    .expand-btn {{ background: none; border: none; cursor: pointer; font-size: 0.75rem; color: #94a3b8; padding: 2px 0 0; display: none; }}
    .card-collapsed .expand-btn {{ display: inline-block; }}
    /* ── FILTER ── */
    .fs-badge {{ cursor: pointer; user-select: none; }}
    .fs-badge:hover {{ opacity: .8; }}
    .fs-badge.active-filter {{ outline: 2px solid #0284c7; outline-offset: 2px; }}
    .card.hidden-by-filter {{ display: none; }}
    /* ── FOOTER COLLECT BAR ── */
    .collect-bar {{
      position: sticky; bottom: 0; background: white;
      border-top: 1px solid #e2e8f0; padding: 12px 24px;
      display: flex; align-items: center; gap: 16px;
      box-shadow: 0 -2px 8px rgba(0,0,0,.06); z-index: 10;
    }}
    .collect-btn {{
      background: #0284c7; color: white; border: none; padding: 9px 22px;
      border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 700;
      transition: background .15s; white-space: nowrap;
    }}
    .collect-btn:hover:not(:disabled) {{ background: #0369a1; }}
    .collect-btn:disabled {{ background: #94a3b8; cursor: not-allowed; }}
    .progress-wrap {{ flex: 1; display: flex; flex-direction: column; gap: 4px; }}
    .progress-track {{ height: 6px; background: #e2e8f0; border-radius: 99px; overflow: hidden; display: none; }}
    .progress-bar {{ height: 100%; width: 0%; background: #0284c7; border-radius: 99px; transition: width .4s ease; }}
    .progress-bar.indeterminate {{
      width: 35%; animation: slide 1.2s ease-in-out infinite;
    }}
    @keyframes slide {{
      0%   {{ transform: translateX(-100%); }}
      100% {{ transform: translateX(350%); }}
    }}
    .last-collect {{ font-size: 0.8rem; color: #94a3b8; white-space: nowrap; }}
    .progress-msg {{ font-size: 0.8rem; color: #64748b; min-height: 16px; }}
    .progress-msg.ok  {{ color: #16a34a; }}
    .progress-msg.err {{ color: #be123c; }}
  </style>
  <script>
    // ── Copiar ──
    function copyText(btn, text) {{
      navigator.clipboard.writeText(text).then(() => {{
        btn.textContent = '✅ Copiado';
        btn.classList.add('copied');
        setTimeout(() => {{ btn.textContent = '📋 Copiar'; btn.classList.remove('copied'); }}, 2000);
      }});
    }}

    // ── Flags — sincronizado via DB ──
    let _flags = {{}};
    let _activeFilter = null; // null | 'none' | 'naopublicado' | 'publicado'

    function applyFlags() {{
      let nVisto = 0, nPub = 0, nNone = 0;
      document.querySelectorAll('.card[data-id]').forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id];
        card.classList.remove('flag-visto', 'flag-publicado');
        card.querySelector('.visto-btn').classList.toggle('on', f === 'naopublicado');
        card.querySelector('.pub-btn').classList.toggle('on', f === 'publicado');
        if (f === 'naopublicado')   {{ card.classList.add('flag-visto');     nVisto++; }}
        else if (f === 'publicado') {{ card.classList.add('flag-publicado'); nPub++;   }}
        else                          nNone++;
        // Collapse flagged cards
        card.classList.toggle('card-collapsed', !!f);
      }});
      const total = nVisto + nPub + nNone;
      if (total > 0) {{
        document.getElementById('fc-total').textContent = nNone;
        document.getElementById('fc-visto').textContent = nVisto;
        document.getElementById('fc-pub').textContent   = nPub;
      }}
      applyFilter();
    }}

    function applyFilter() {{
      document.querySelectorAll('.card[data-id]').forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id] || 'none';
        const show = !_activeFilter || f === _activeFilter;
        card.classList.toggle('hidden-by-filter', !show);
      }});
      // Update badge highlight
      ['fs-total','fs-visto','fs-pub'].forEach(id => document.getElementById(id).classList.remove('active-filter'));
      if (_activeFilter === 'none')          document.getElementById('fs-total').classList.add('active-filter');
      else if (_activeFilter === 'naopublicado') document.getElementById('fs-visto').classList.add('active-filter');
      else if (_activeFilter === 'publicado')    document.getElementById('fs-pub').classList.add('active-filter');
    }}

    function toggleFilter(type) {{
      _activeFilter = (_activeFilter === type) ? null : type;
      applyFilter();
    }}

    function toggleExpand(btn) {{
      const card = btn.closest('.card');
      card.classList.remove('card-collapsed');
      btn.style.display = 'none';
    }}

    async function loadFlags() {{
      try {{
        const r = await fetch('/api/flags');
        _flags = await r.json();
        applyFlags();
      }} catch(e) {{}}
    }}

    async function toggleFlag(id, type) {{
      const current = _flags[id];
      const newFlag = (current === type) ? null : type;
      // Atualiza local imediatamente (feedback instantâneo)
      if (newFlag) _flags[id] = newFlag; else delete _flags[id];
      applyFlags();
      // Persiste no banco
      try {{
        await fetch('/api/flag', {{
          method: 'POST',
          headers: {{'content-type': 'application/json'}},
          body: JSON.stringify({{ id, flag: newFlag }}),
        }});
      }} catch(e) {{}}
    }}

    async function loadLastCollect() {{
      try {{
        const r = await fetch('/api/logs?limit=1');
        const l = await r.json();
        if (!l.length) return;
        const raw = l[0].ran_at.replace(' ', 'T');
        const dt = new Date(raw.includes('+') || raw.endsWith('Z') ? raw : raw + 'Z');
        const fmt = dt.toLocaleString('pt-BR', {{ timeZone: 'America/Sao_Paulo', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }});
        document.getElementById('last-collect').textContent = 'Última coleta: ' + fmt;
      }} catch(e) {{}}
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      loadFlags();
      loadLastCollect();
      setInterval(loadFlags, 10000);
    }});

    // ── Coletar ──
    async function startCollect() {{
      const btn   = document.getElementById('cbtn');
      const bar   = document.getElementById('pbar');
      const track = document.getElementById('ptrack');
      const msg   = document.getElementById('pmsg');

      btn.disabled = true;
      track.style.display = 'block';
      bar.classList.add('indeterminate');
      msg.textContent = 'Coletando notícias...';
      msg.className = 'progress-msg';

      // Guarda o ID do último log antes de coletar
      let lastId = -1;
      try {{
        const r = await fetch('/api/logs?limit=1');
        const l = await r.json();
        if (l.length) lastId = l[0].id;
      }} catch(e) {{}}

      try {{ await fetch('/api/collect', {{ method: 'POST' }}); }} catch(e) {{}}

      // Poll até aparecer um log novo (ID diferente)
      for (let i = 0; i < 45; i++) {{
        await new Promise(r => setTimeout(r, 2000));
        try {{
          const r = await fetch('/api/logs?limit=1');
          const l = await r.json();
          if (l.length && l[0].id !== lastId) {{ break; }}
        }} catch(e) {{}}
      }}

      bar.classList.remove('indeterminate');
      bar.style.width = '100%';
      msg.textContent = '✅ Concluído! Recarregando...';
      msg.className = 'progress-msg ok';
      setTimeout(() => location.reload(), 1000);
    }}
  </script>
</head>
<body>
  <header>
    <a class="brand" href="/">⚽ Centrão do Noticião</a>
    <nav>
      <a class="nav-link active" href="/">Home</a>
      <a class="nav-link" href="/descartadas">🗂️ Descartadas</a>
      <a class="nav-link" href="/gerador">✍️ Criar Post</a>
    </nav>
  </header>
  <div class="topbar">
    <span class="count">{len(articles)} notícias nas últimas 24h</span>
    <div class="flag-summary">
      <span class="fs-badge fs-total"     id="fs-total"     onclick="toggleFilter('none')"         title="Filtrar sem flag">⬜ <span id="fc-total">—</span> sem flag</span>
      <span class="fs-badge fs-visto"     id="fs-visto"     onclick="toggleFilter('naopublicado')"  title="Filtrar não publicados">🔖 <span id="fc-visto">—</span> não publicados</span>
      <span class="fs-badge fs-publicado" id="fs-pub"       onclick="toggleFilter('publicado')"     title="Filtrar publicados">📢 <span id="fc-pub">—</span> publicados</span>
    </div>
  </div>
  <div class="grid">
    {cards}
  </div>
  <div class="collect-bar">
    <button class="collect-btn" id="cbtn" onclick="startCollect()">🔄 Coletar agora</button>
    <span class="last-collect" id="last-collect"></span>
    <div class="progress-wrap">
      <div class="progress-track" id="ptrack"><div class="progress-bar" id="pbar"></div></div>
      <span class="progress-msg" id="pmsg"></span>
    </div>
  </div>
  <footer style="text-align:center;padding:14px;font-size:0.75rem;color:#94a3b8;border-top:1px solid #e2e8f0;background:white;">
    © {__import__('datetime').datetime.now().year} Central do Arabão — Todos os direitos reservados
  </footer>
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



@app.get("/descartadas", response_class=HTMLResponse)
async def descartadas():
    articles = get_low_score_articles(hours=24, limit=200)

    CATEGORY_EMOJI = {
        "transferencia": ("🔄", "#dbeafe", "#1d4ed8"),
        "sondagem":      ("🔎", "#e0f2fe", "#0369a1"),
        "patrocinio":    ("🤝", "#ede9fe", "#6d28d9"),
        "planejamento":  ("📋", "#f0fdf4", "#166534"),
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
        title = a.get("title_orig") or "—"
        body  = (a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        image_url = a.get("image_url") or ""
        category = a.get("category") or "geral"
        score = a.get("relevance_score", 0)
        collected = (a.get("collected_at") or "")[:16].replace("T", " ")
        emoji, emoji_bg, emoji_color = CATEGORY_EMOJI.get(category, CATEGORY_EMOJI["geral"])
        if image_url:
            img_html = f'<div class="card-img" style="background-image:url({image_url})"></div>'
        else:
            img_html = f'<div class="card-img no-img" style="background:{emoji_bg};color:{emoji_color}">{emoji}</div>'
        cards += f"""
        <div class="card">
          {img_html}
          <div class="card-body">
            <div class="card-meta">
              <span class="tier-badge" style="background:{tier_bg};color:{tier_color}">Tier {a['source_tier']}</span>
              <span class="source">@{a['source_name'].lstrip('@')}</span>
              <span class="score-badge">score {score:.2f}</span>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <p class="card-text">{body}</p>
            <div class="card-footer">
              <span class="card-date">{collected}</span>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>🗂️ Descartadas — Saudi Football Monitor</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
    header {{ background: white; border-bottom: 1px solid #e2e8f0; padding: 0 24px; display: flex; align-items: center; gap: 32px; position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.06); height: 56px; }}
    .brand {{ font-size: 1.1rem; font-weight: 800; color: #0f172a; text-decoration: none; white-space: nowrap; }}
    nav {{ display: flex; gap: 4px; }}
    .nav-link {{ padding: 8px 14px; border-radius: 7px; font-size: 0.88rem; font-weight: 600; color: #64748b; text-decoration: none; transition: all .15s; }}
    .nav-link:hover {{ background: #f1f5f9; color: #0f172a; }}
    .nav-link.active {{ background: #eff6ff; color: #0284c7; }}
    .info {{ color: #64748b; font-size: 0.85rem; margin: 16px 24px 8px; }}
    .info strong {{ color: #0f172a; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; padding: 16px 24px 40px; }}
    .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.08); display: flex; flex-direction: column; opacity: 0.88; }}
    .card-img {{ height: 160px; background-size: cover; background-position: center; background-color: #e2e8f0; }}
    .card-img.no-img {{ display: flex; align-items: center; justify-content: center; font-size: 2.5rem; }}
    .card-body {{ padding: 14px; display: flex; flex-direction: column; flex: 1; }}
    .card-meta {{ display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }}
    .tier-badge {{ font-size: 0.72rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
    .source {{ font-size: 0.78rem; color: #64748b; }}
    .score-badge {{ font-size: 0.7rem; background: #fff7ed; color: #c2410c; padding: 2px 7px; border-radius: 20px; font-weight: 700; margin-left: auto; }}
    .card-title {{ font-size: 0.9rem; font-weight: 700; color: #0f172a; text-decoration: none; line-height: 1.4; display: block; margin-bottom: 6px; }}
    .card-title:hover {{ color: #0284c7; }}
    .card-text {{ font-size: 0.8rem; color: #64748b; line-height: 1.55; flex: 1; }}
    .card-footer {{ display: flex; align-items: center; justify-content: flex-end; margin-top: 12px; padding-top: 8px; border-top: 1px solid #f1f5f9; }}
    .card-date {{ font-size: 0.72rem; color: #94a3b8; }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">⚽ Centrão do Noticião</a>
    <nav>
      <a class="nav-link" href="/">Home</a>
      <a class="nav-link active" href="/descartadas">🗂️ Descartadas</a>
      <a class="nav-link" href="/gerador">✍️ Criar Post</a>
    </nav>
  </header>
  <p class="info">{len(articles)} notícias com score abaixo de 0.34 nas últimas 24h &nbsp;·&nbsp; <strong>Textos originais, sem tradução</strong></p>
  <div class="grid">
    {cards if cards else '<p style="padding:40px 24px;color:#94a3b8;">Nenhuma notícia descartada nas últimas 24h.</p>'}
  </div>
  <footer style="text-align:center;padding:14px;font-size:0.75rem;color:#94a3b8;border-top:1px solid #e2e8f0;background:white;">
    © {__import__('datetime').datetime.now().year} Central do Arabão — Todos os direitos reservados
  </footer>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/api/flags")
async def api_get_flags():
    return get_all_flags()


@app.post("/api/flag")
async def api_set_flag(request: Request):
    body = await request.json()
    article_id = body.get("id", "").strip()
    flag = body.get("flag") or None  # None = remover
    if not article_id:
        return JSONResponse({"error": "id obrigatório"}, status_code=400)
    if flag and flag not in ("naopublicado", "publicado"):
        return JSONResponse({"error": "flag inválida"}, status_code=400)
    set_flag(article_id, flag)
    return {"ok": True, "id": article_id, "flag": flag}


@app.get("/gerador", response_class=HTMLResponse)
async def gerador():
    with open("public/generator.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ─── Gerador de posts (Central do Arabão) ────────
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL_POST = "claude-sonnet-4-5"


def _tmpl_rule(tmpl: str, n: int) -> str:
    if tmpl == "carrossel":
        content = max(1, n - 2)
        return (
            f"TEMPLATE: CARROSSEL ({n} slides).\n"
            f"- tipo_sugerido = \"carrossel\"\n"
            f"- Gere EXATAMENTE {n} slides no array \"slides\"\n"
            f"- slides[0] = capa: titulo em MAIÚSCULAS (3-4 palavras, máx 30 chars — NUNCA corte palavras no meio, reformule se necessário), corpo = subtítulo da notícia (1 frase)\n"
            f"- slides[1..{n-2}] = conteúdo: divide o texto em {content} partes iguais. Cada parte: titulo curto em MAIÚSCULAS + corpo até 5 linhas em PT-BR\n"
            f"- slides[{n-1}] = CTA: titulo=\"SIGA @CENTRALDOARABAO\", corpo=\"\"\n"
            f"- num_slides = {n}"
        )
    if tmpl == "transferencia":
        return (
            "TEMPLATE: TRANSFERÊNCIA (1 card).\n"
            "- tipo_sugerido = \"transferencia\"\n"
            "- Extraia do texto o nome do jogador → nome_jogador em maiúsculas\n"
            "- Extraia o tipo de anúncio (ex: \"Contratação definitiva\", \"Empréstimo\", \"Saída confirmada\") → tipo_anuncio\n"
            "- slides = []"
        )
    return (
        "TEMPLATE: SIMPLES (1 card).\n"
        "- tipo_sugerido = \"simples\"\n"
        "- Gere um título impactante em maiúsculas, máximo 60 caracteres.\n"
        "- NUNCA corte palavras no meio. Se ultrapassar o limite, reformule com palavras mais curtas mantendo o sentido completo.\n"
        "- slides = []"
    )


@app.post("/api/generate-post")
async def generate_post(request: Request):
    body = await request.json()
    news = (body.get("news") or "").strip()
    template = body.get("template", "simples")
    if template not in ("simples", "carrossel", "transferencia"):
        template = "simples"
    num_slides = body.get("num_slides", 3)
    n = min(6, max(3, int(num_slides))) if template == "carrossel" else 1
    already_translated = bool(body.get("already_translated", False))
    source = (body.get("source") or "").strip().lstrip("@")
    tier = (body.get("tier") or "").strip().upper()
    moon = {"A": "🌕", "B": "🌓", "C": "🌗"}.get(tier, "")
    source_footer = f"🗞️ @{source} {moon}".strip() if source else ""

    if not news:
        return JSONResponse({"error": "Campo 'news' vazio."}, status_code=400)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY não configurada."}, status_code=500)

    prompt_visual = (
        "Você é um editor de conteúdo esportivo especializado na Saudi Pro League (Roshn Saudi League).\n\n"
        + _tmpl_rule(template, n)
        + "\n\nFORMATO DE SAÍDA:\nRetorne SOMENTE um objeto JSON puro, sem markdown, sem blocos de código, sem texto fora do JSON.\n\n"
        "Estrutura exata (preencha os valores):\n"
        '{\n  "titulo": "TÍTULO COMPLETO EM MAIÚSCULAS — não truncar, reformular se muito longo",\n'
        '  "subtitulo": "uma frase resumindo a notícia em português",\n'
        '  "texto_completo": "notícia em português, 2 a 4 parágrafos",\n'
        f'  "slides": [],\n  "tipo_sugerido": "{template}",\n  "num_slides": {n},\n'
        '  "nome_jogador": null,\n  "tipo_anuncio": null\n}'
    )

    if already_translated:
        footer_instruction = (
            f"Ao final do texto, adicione exatamente esta linha (sem alterar): \"{source_footer}\""
            if source_footer else ""
        )
        prompt_texto = (
            "Você é um editor de texto esportivo objetivo e direto. O texto abaixo JÁ ESTÁ EM PORTUGUÊS — NÃO TRADUZA.\n\n"
            "TAREFA: reescreva de forma CURTA e DIRETA. Máximo 4 frases. "
            "Elimine qualquer repetição, contexto desnecessário, adjetivos vagos e encheção de linguiça. "
            "Mantenha as informações concretas essenciais: quem, o quê, quando, valores. "
            "Estilo: jornalismo esportivo objetivo — sem enrolar, sem inflar.\n\n"
            "REGRAS DE FORMATO: texto corrido, sem emojis no corpo, sem hashtags, sem exclamações, "
            "sem títulos, sem negrito, sem listas, somente parágrafos simples.\n"
            "NOMES DE CLUBES: NUNCA use hífen (Al Hilal, não Al-Hilal).\n"
            + (footer_instruction + "\n" if footer_instruction else "")
            + "Responda SOMENTE com o texto final reescrito, sem comentários nem explicações."
        )
    else:
        footer_instruction = (
            f"Ao final, adicione exatamente esta linha (sem alterar): \"{source_footer}\""
            if source_footer else
            "Ao final, \"Fonte:\" seguido do autor ou veículo identificável no texto original."
        )
        prompt_texto = (
            "Você é um editor de texto esportivo objetivo e direto.\n\n"
            "TAREFA: traduza para o português brasileiro e reescreva de forma CURTA e DIRETA. Máximo 4 frases. "
            "Elimine qualquer repetição, contexto desnecessário, adjetivos vagos e encheção de linguiça. "
            "Mantenha as informações concretas essenciais: quem, o quê, quando, valores.\n\n"
            "REGRAS DE FORMATO: texto corrido, sem emojis no corpo, sem hashtags, sem exclamações, "
            "sem títulos, sem negrito, sem listas, somente parágrafos simples.\n"
            "NOMES DE CLUBES: NUNCA use hífen (Al Hilal, não Al-Hilal).\n"
            + footer_instruction
        )

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    def make_payload(system: str, max_tokens: int):
        return {
            "model": CLAUDE_MODEL_POST,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": news}],
        }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp_visual, resp_texto = await asyncio.gather(
                client.post(CLAUDE_API_URL, json=make_payload(prompt_visual, 2048), headers=headers),
                client.post(CLAUDE_API_URL, json=make_payload(prompt_texto, 1024), headers=headers),
            )

        if resp_visual.status_code != 200:
            err = resp_visual.json().get("error", {})
            return JSONResponse({"error": err.get("message", f"Claude API: HTTP {resp_visual.status_code}")}, status_code=resp_visual.status_code)

        raw = resp_visual.json()["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        import re
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw = m.group(0)
        parsed = json.loads(raw)

        texto_post = ""
        if resp_texto.status_code == 200:
            texto_post = (resp_texto.json()["content"][0].get("text") or "").strip()

        parsed["legenda_instagram"] = texto_post or parsed.get("legenda_instagram", "")
        return parsed

    except json.JSONDecodeError:
        return JSONResponse({"error": "Resposta inválida da API Claude."}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Erro ao chamar Claude API: {e}"}, status_code=500)


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
