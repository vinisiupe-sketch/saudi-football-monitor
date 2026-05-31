"""
Saudi Football Monitor — FastAPI app principal.
"""
import os
import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from database import init_db, get_recent_articles, get_low_score_articles, get_collection_logs, set_flag, get_all_flags, get_trashed_articles, cleanup_old_trash
from scheduler import run_pipeline, create_scheduler
from sources import SOURCE_MOON

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()
    cleanup_old_trash()
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

# ─── Header compartilhado ────────────────────
_ICO_HOME    = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9.5z"/><polyline points="9 21 9 12 15 12 15 21"/></svg>'
_ICO_ARCHIVE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>'
_ICO_SOURCES = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/><line x1="6.5" y1="10.8" x2="10.5" y2="6.2"/><line x1="13.5" y1="6.2" x2="17.5" y2="10.8"/><line x1="17.5" y1="13.2" x2="13.5" y2="17.8"/><line x1="10.5" y1="17.8" x2="6.5" y2="13.2"/></svg>'
_ICO_TRASH2  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>'
_ICO_PEN2    = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'

_HEADER_CSS = (
    "    header { background: #edeae4; border-bottom: 1px solid rgba(0,0,0,.1); padding: 0 20px; display: flex; align-items: center; position: sticky; top: 0; z-index: 10; height: 52px; gap: 6px; }\n"
    "    .brand { font-family: \'Bebas Neue\', sans-serif; font-size: 2rem; letter-spacing: 0.06em; color: #1a1a1a; text-decoration: none; margin-right: auto; line-height: 1; }\n"
    "    .nav-icon { width: 36px; height: 36px; border-radius: 50%; border: 1.5px solid rgba(0,0,0,.18); background: transparent; color: #999; cursor: pointer; display: flex; align-items: center; justify-content: center; text-decoration: none; transition: all .15s; flex-shrink: 0; position: relative; }\n"
    "    .nav-icon:hover { border-color: #1a1a1a; color: #1a1a1a; background: rgba(0,0,0,.04); }\n"
    "    .nav-icon.active { background: #1a1a1a; border-color: #1a1a1a; color: white; }\n"
    "    .nav-icon.cta { background: #1a1a1a; border-color: #1a1a1a; color: white; }\n"
    "    .nav-icon.cta:hover { background: #444; border-color: #444; }\n"
    "    .nav-icon[title]:hover::after { content: attr(title); position: absolute; bottom: -28px; left: 50%; transform: translateX(-50%); background: #1a1a1a; color: white; font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 8px; border-radius: 6px; white-space: nowrap; pointer-events: none; z-index: 100; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', sans-serif; }"
)

def _header(active: str) -> str:
    pages = [
        ("/",           _ICO_HOME,    "Home"),
        ("/descartadas",_ICO_ARCHIVE, "Descartadas"),
        ("/fontes",     _ICO_SOURCES, "Fontes"),
        ("/lixeira",    _ICO_TRASH2,  "Lixeira"),
        ("/gerador",    _ICO_PEN2,    "Criar Post"),
    ]
    items = ""
    for href, ico, label in pages:
        cls = "nav-icon"
        if href == active:
            cls += " active"
        elif href == "/gerador":
            cls += " cta"
        items += f'<a class="{cls}" href="{href}" title="{label}">{ico}</a>'
    return f'<header><a class="brand" href="/">IARABÃO</a>{items}</header>'



# ─── Dashboard ───────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    articles = get_recent_articles(hours=48, limit=80)
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

    CATEGORY_TEXT = {
        "transferencia": "Transferência", "sondagem": "Sondagem",
        "patrocinio": "Patrocínio",       "planejamento": "Planejamento",
        "entrevista": "Entrevista",        "resultado": "Resultado",
        "competicao": "Competição",        "treino": "Treino",
        "financeiro": "Financeiro",        "lesao": "Lesão",
        "geral": "Geral",
    }
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    ICO_ANALYSIS = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>'
    ICO_LOCK  = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
    ICO_CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    ICO_TRASH = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>'
    ICO_PEN   = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'

    cards = ""
    for a in articles:
        handle        = a.get("source_name", "").lstrip("@")
        moon          = SOURCE_MOON.get(handle, {"A": "🌕", "B": "🌖", "C": "🌗"}.get(a["source_tier"], ""))
        title         = a.get("title_pt") or a.get("title_orig") or "—"
        body_raw      = a.get("body_pt") or a.get("body_orig") or ""
        body_short    = body_raw[:280] + ("…" if len(body_raw) > 280 else "")
        body_full     = body_raw
        has_more      = len(body_raw) > 280
        category      = a.get("category") or "geral"
        category_text = CATEGORY_TEXT.get(category, "Geral")
        post_text_full = title + "\n\n" + (a.get("body_pt") or a.get("body_orig") or "") + "\n\n🗞️ @" + handle
        post_base     = f"/gerador?texto={quote(post_text_full)}&source={quote(handle)}&moon={quote(moon)}&translated=1"
        art_id        = a['id']
        # Date from published_at in Saudi time (UTC+3)
        date_display = ""
        pub_raw = a.get("published_at") or a.get("collected_at") or ""
        if pub_raw:
            try:
                dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                dt_local = dt.astimezone(timezone(timedelta(hours=3)))
                date_display = f"{dt_local.day} {MONTHS_PT[dt_local.month-1]} · {dt_local.strftime('%H:%M')}"
            except Exception:
                pass
        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-top">
              <span class="card-date">{date_display}</span>
              <div class="card-flags">
                <button class="flag-circle anal-btn"  onclick="toggleFlag('{art_id}','analise')"      title="Análise">{ICO_ANALYSIS}</button>
                <button class="flag-circle visto-btn" onclick="toggleFlag('{art_id}','naopublicado')" title="Não publicado">{ICO_LOCK}</button>
                <button class="flag-circle pub-btn"   onclick="toggleFlag('{art_id}','publicado')"    title="Publicado">{ICO_CHECK}</button>
                <button class="flag-circle desc-btn"  onclick="toggleFlag('{art_id}','descartado')"   title="Lixeira">{ICO_TRASH}</button>
              </div>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <button class="flag-expand-btn" onclick="toggleFlagExpand(this)">↓ ver mais</button>
            <p class="card-text">
              <span class="text-short">{body_short}</span>
              <span class="text-full" style="display:none">{body_full}</span>
            </p>
            {'<button class="expand-text-btn" onclick="expandText(this)">↓ ver mais</button>' if has_more else ''}
            <div class="card-bottom">
              <div class="card-tags">
                <span class="tag">{moon}</span>
                <span class="tag">@{handle}</span>
                <span class="tag">{category_text}</span>
              </div>
              <button class="flag-circle post-btn" onclick="openTmplModal('{post_base}')" title="Criar post">{ICO_PEN}</button>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IARABÃO</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #edeae4; color: #1a1a1a; }}

    {_HEADER_CSS}

    /* ── TOPBAR ── */
    .topbar {{
      display: flex; align-items: center; gap: 10px;
      flex-wrap: wrap; padding: 14px 24px 8px;
    }}
    .count {{ color: #999; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.07em; }}
    .flag-summary {{ display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }}
    .fs-badge {{
      font-size: 0.62rem; font-weight: 700; padding: 3px 10px; border-radius: 99px;
      cursor: pointer; user-select: none; transition: all .15s;
      text-transform: uppercase; letter-spacing: 0.05em;
      border: 1.5px solid transparent;
    }}
    .fs-total     {{ border-color: #ccc;    color: #999;    }}
    .fs-analise   {{ border-color: #fde68a; color: #92400e; }}
    .fs-visto     {{ border-color: #a5b4fc; color: #4338ca; }}
    .fs-publicado {{ border-color: #86efac; color: #166534; }}
    .fs-descarte  {{ border-color: #fca5a5; color: #be123c; }}
    .fs-badge:hover {{ opacity: .7; }}
    .fs-badge.active-filter {{ background: #1a1a1a; color: #edeae4; border-color: #1a1a1a; }}

    /* ── GRID ── */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 10px; padding: 10px 24px 80px; align-items: start;
    }}

    /* ── CARD ── */
    .card {{
      background: #fafaf8; border-radius: 16px;
      display: flex; flex-direction: column;
      transition: background .2s;
    }}
    .card.flag-analise   {{ background: #fefce8; }}
    .card.flag-visto     {{ background: #ede9fe; }}
    .card.flag-publicado {{ background: #dcfce7; }}
    .card.flag-descarte  {{ display: none; }}
    .card.hidden-by-filter {{ display: none; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}

    /* ── CARD TOP ── */
    .card-top {{
      display: flex; align-items: center;
      justify-content: space-between; margin-bottom: 14px;
    }}
    .card-date {{
      font-size: 0.65rem; font-weight: 700; color: #aaa;
      text-transform: uppercase; letter-spacing: 0.07em;
    }}
    .card-flags {{ display: flex; gap: 7px; }}
    .flag-circle {{
      width: 32px; height: 32px; border-radius: 50%;
      border: 1.5px solid #1a1a1a; background: transparent;
      color: #1a1a1a; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: all .15s; flex-shrink: 0;
    }}
    .flag-circle:hover {{ background: #1a1a1a; color: white; }}
    .flag-circle.on {{ background: #1a1a1a; color: white; }}
    .flag-circle.anal-btn:hover  {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.anal-btn.on     {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.visto-btn:hover {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.visto-btn.on    {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.pub-btn:hover   {{ background: #166534; border-color: #166534; color: white; }}
    .flag-circle.pub-btn.on      {{ background: #166534; border-color: #166534; color: white; }}
    .flag-circle.desc-btn:hover  {{ background: #be123c; border-color: #be123c; color: white; }}
    .flag-circle.desc-btn.on     {{ background: #be123c; border-color: #be123c; color: white; }}
    .flag-circle.post-btn        {{ background: #1a1a1a; border-color: #1a1a1a; color: white; text-decoration: none; }}
    .flag-circle.post-btn:hover  {{ background: #444; border-color: #444; color: white; }}

    /* ── TITLE ── */
    .card-title {{
      font-size: 1rem; font-weight: 700; color: #1a1a1a;
      text-decoration: none; line-height: 1.4;
      display: block; margin-bottom: 10px;
    }}
    .card-title:hover {{ opacity: .7; }}

    /* ── EXPAND FLAGADO ── */
    .flag-expand-btn {{
      background: none; border: none; cursor: pointer;
      font-size: 0.62rem; color: #aaa; padding: 0 0 10px;
      text-transform: uppercase; letter-spacing: 0.07em;
      font-weight: 700; display: none; text-align: left; transition: color .15s;
    }}
    .flag-expand-btn:hover {{ color: #1a1a1a; }}
    .card-collapsed .flag-expand-btn {{ display: block; }}
    .card-collapsed .card-text,
    .card-collapsed .card-bottom,
    .card-collapsed .expand-text-btn {{ display: none; }}
    .card-collapsed.flag-open .card-text,
    .card-collapsed.flag-open .card-bottom {{ display: flex; }}
    .card-collapsed.flag-open .card-text {{ display: block; }}
    .card-collapsed.flag-open .text-short {{ display: none; }}
    .card-collapsed.flag-open .text-full  {{ display: inline !important; }}

    /* ── EXPAND TEXTO LONGO ── */
    .expand-text-btn {{
      background: none; border: none; cursor: pointer;
      font-size: 0.62rem; color: #aaa; padding: 0 0 10px;
      text-transform: uppercase; letter-spacing: 0.07em;
      font-weight: 700; display: block; text-align: left; transition: color .15s;
    }}
    .expand-text-btn:hover {{ color: #1a1a1a; }}

    /* ── BODY TEXT ── */
    .card-text {{
      font-size: 0.82rem; color: #555; line-height: 1.65;
      margin-bottom: 16px;
    }}

    /* ── CARD BOTTOM ── */
    .card-bottom {{
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 8px;
      padding-top: 14px; border-top: 1px solid rgba(0,0,0,.07);
    }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{
      font-size: 0.6rem; font-weight: 700; color: #777;
      border: 1px solid #ccc; border-radius: 99px;
      padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em;
    }}

    /* ── COLLECT BAR ── */
    .collect-bar {{
      position: fixed; bottom: 0; left: 0; right: 0;
      background: #edeae4; border-top: 1px solid rgba(0,0,0,.1);
      padding: 10px 24px; display: flex; align-items: center; gap: 14px;
      z-index: 10;
    }}
    .collect-btn {{
      background: #1a1a1a; color: #edeae4; border: none;
      padding: 7px 20px; border-radius: 99px; cursor: pointer;
      font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; transition: opacity .15s; white-space: nowrap;
    }}
    .collect-btn:hover:not(:disabled) {{ opacity: .75; }}
    .collect-btn:disabled {{ opacity: .4; cursor: not-allowed; }}
    .progress-wrap {{ flex: 1; display: flex; flex-direction: column; gap: 3px; }}
    .progress-track {{ height: 3px; background: rgba(0,0,0,.1); border-radius: 99px; overflow: hidden; display: none; }}
    .progress-bar {{ height: 100%; width: 0%; background: #1a1a1a; border-radius: 99px; transition: width .4s ease; }}
    .progress-bar.indeterminate {{ width: 35%; animation: slide 1.2s ease-in-out infinite; }}
    @keyframes slide {{ 0% {{ transform: translateX(-100%); }} 100% {{ transform: translateX(350%); }} }}
    .last-collect {{ font-size: 0.65rem; color: #aaa; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.05em; }}
    .progress-msg {{ font-size: 0.68rem; color: #777; min-height: 14px; }}
    .progress-msg.ok  {{ color: #166534; }}
    .progress-msg.err {{ color: #be123c; }}

    /* ── TEMPLATE MODAL ── */
    .tmpl-overlay {{
      position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 200;
      display: none; align-items: center; justify-content: center;
      backdrop-filter: blur(4px);
    }}
    .tmpl-overlay.open {{ display: flex; }}
    .tmpl-modal {{
      background: #edeae4; border-radius: 24px; padding: 28px 20px 20px;
      width: 320px; max-width: calc(100vw - 32px);
      display: flex; flex-direction: column; gap: 8px;
      box-shadow: 0 20px 60px rgba(0,0,0,.3);
    }}
    .tmpl-title {{
      font-size: 0.58rem; font-weight: 700; color: #999;
      text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px;
    }}
    .tmpl-opt {{
      width: 100%; padding: 16px 20px; border-radius: 14px;
      border: 1.5px solid rgba(0,0,0,.18); background: white;
      cursor: pointer; transition: all .15s;
      display: flex; flex-direction: column; align-items: center; gap: 2px;
    }}
    .tmpl-opt:hover {{ border-color: #1a1a1a; }}
    .tmpl-opt.active {{ background: #1a1a1a; border-color: #1a1a1a; }}
    .tmpl-opt-name {{
      font-family: 'Bebas Neue', sans-serif; font-size: 1.3rem;
      letter-spacing: 0.05em; color: #1a1a1a; line-height: 1;
    }}
    .tmpl-opt.active .tmpl-opt-name {{ color: #49fcb6; }}
    .tmpl-opt-sub {{
      font-size: 0.6rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; color: #aaa;
    }}
    .tmpl-opt.active .tmpl-opt-sub {{ color: rgba(73,252,182,.7); }}
    .tmpl-slides-row {{
      display: none; gap: 8px; justify-content: center; padding: 4px 0;
    }}
    .tmpl-slides-row.show {{ display: flex; }}
    .tmpl-slide-opt {{
      flex: 1; padding: 8px 0; border-radius: 10px;
      border: 1.5px solid rgba(0,0,0,.15); background: white;
      font-size: 0.75rem; font-weight: 700; cursor: pointer;
      transition: all .15s; color: #1a1a1a;
    }}
    .tmpl-slide-opt.active {{ background: #1a1a1a; color: #49fcb6; border-color: #1a1a1a; }}
    .tmpl-criar {{
      width: 100%; padding: 14px; border-radius: 99px;
      border: 1.5px solid #1a1a1a; background: white;
      font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; cursor: pointer; transition: all .15s; margin-top: 6px;
    }}
    .tmpl-criar:hover {{ background: #1a1a1a; color: #edeae4; }}
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
    let _activeFilter = null;

    function applyFlags() {{
      let nAnalise = 0, nVisto = 0, nPub = 0, nNone = 0, nDesc = 0;
      const grid = document.querySelector('.grid');
      const cards = Array.from(document.querySelectorAll('.card[data-id]'));
      cards.forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id];
        card.classList.remove('flag-analise', 'flag-visto', 'flag-publicado', 'flag-descarte');
        card.querySelector('.anal-btn').classList.toggle('on',  f === 'analise');
        card.querySelector('.visto-btn').classList.toggle('on', f === 'naopublicado');
        card.querySelector('.pub-btn').classList.toggle('on',   f === 'publicado');
        card.querySelector('.desc-btn').classList.toggle('on',  f === 'descartado');
        if      (f === 'analise')      {{ card.classList.add('flag-analise');   nAnalise++; }}
        else if (f === 'naopublicado') {{ card.classList.add('flag-visto');     nVisto++; }}
        else if (f === 'publicado')    {{ card.classList.add('flag-publicado'); nPub++;   }}
        else if (f === 'descartado')   {{ card.classList.add('flag-descarte');  nDesc++;  }}
        else                             nNone++;
        // Colapsar apenas flags que não sejam lixeira (descartados somem do grid via CSS)
        card.classList.toggle('card-collapsed', f === 'naopublicado' || f === 'publicado' || f === 'analise');
        // Resetar expand de flagados se flag mudou
        if (!f) card.classList.remove('flag-open');
      }});
      // Reorder: sem flag → análise → publicado → não publicado (descartados ocultos)
      const order = {{ undefined: 0, 'analise': 1, 'publicado': 2, 'naopublicado': 3, 'descartado': 99 }};
      cards.sort((a, b) => (order[_flags[a.dataset.id]] ?? 0) - (order[_flags[b.dataset.id]] ?? 0));
      cards.forEach(c => grid.appendChild(c));
      const total = nAnalise + nVisto + nPub + nNone + nDesc;
      if (total > 0) {{
        document.getElementById('fc-total').textContent   = nNone;
        document.getElementById('fc-analise').textContent = nAnalise;
        document.getElementById('fc-visto').textContent   = nVisto;
        document.getElementById('fc-pub').textContent     = nPub;
        document.getElementById('fc-desc').textContent    = nDesc;
      }}
      applyFilter();
    }}

    function applyFilter() {{
      document.querySelectorAll('.card[data-id]').forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id] || 'none';
        // descartados sempre ocultos (vão pra lixeira via CSS)
        if (f === 'descartado') {{ card.classList.remove('hidden-by-filter'); return; }}
        const show = !_activeFilter || f === _activeFilter;
        card.classList.toggle('hidden-by-filter', !show);
      }});
      ['fs-total','fs-analise','fs-visto','fs-pub','fs-desc'].forEach(id => document.getElementById(id).classList.remove('active-filter'));
      if      (_activeFilter === 'none')          document.getElementById('fs-total').classList.add('active-filter');
      else if (_activeFilter === 'analise')       document.getElementById('fs-analise').classList.add('active-filter');
      else if (_activeFilter === 'naopublicado')  document.getElementById('fs-visto').classList.add('active-filter');
      else if (_activeFilter === 'publicado')     document.getElementById('fs-pub').classList.add('active-filter');
    }}

    function toggleFilter(type) {{
      _activeFilter = (_activeFilter === type) ? null : type;
      applyFilter();
    }}

    function toggleFlagExpand(btn) {{
      const card = btn.closest('.card');
      const open = card.classList.toggle('flag-open');
      btn.textContent = open ? '↑ ver menos' : '↓ ver mais';
    }}

    function expandText(btn) {{
      const p = btn.previousElementSibling;
      const short = p.querySelector('.text-short');
      const full  = p.querySelector('.text-full');
      const expanded = btn.classList.toggle('expanded');
      short.style.display = expanded ? 'none' : 'inline';
      full.style.display  = expanded ? 'inline' : 'none';
      btn.textContent = expanded ? '↑ ver menos' : '↓ ver mais';
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

    // ── Template modal ──
    let _tmplPostBase = '';
    function openTmplModal(base) {{
      _tmplPostBase = base;
      document.getElementById('tmpl-overlay').classList.add('open');
    }}
    function closeTmpl() {{ document.getElementById('tmpl-overlay').classList.remove('open'); }}
    function selectTmpl(btn) {{
      document.querySelectorAll('.tmpl-opt').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const show = btn.dataset.t === 'carrossel';
      document.getElementById('tmpl-slides-row').classList.toggle('show', show);
    }}
    function selectSlides(btn) {{
      document.querySelectorAll('.tmpl-slide-opt').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }}
    function criarPost() {{
      const tmpl  = document.querySelector('.tmpl-opt.active')?.dataset.t || 'simples';
      const nsld  = document.querySelector('.tmpl-slide-opt.active')?.dataset.n || '3';
      let url = _tmplPostBase + '&template=' + tmpl;
      if (tmpl === 'carrossel') url += '&slides=' + nsld;
      window.location.href = url;
    }}
  </script>
</head>
<body>
  {_header("/")}
  <div class="topbar">
    <span class="count">{len(articles)} notícias · 48h</span>
    <div class="flag-summary">
      <span class="fs-badge fs-total"     id="fs-total"   onclick="toggleFilter('none')"         title="Sem flag"><span id="fc-total">—</span> sem flag</span>
      <span class="fs-badge fs-analise"   id="fs-analise" onclick="toggleFilter('analise')"       title="Análise"><span id="fc-analise">—</span> análise</span>
      <span class="fs-badge fs-visto"     id="fs-visto"   onclick="toggleFilter('naopublicado')"  title="Não publicados"><span id="fc-visto">—</span> salvos</span>
      <span class="fs-badge fs-publicado" id="fs-pub"     onclick="toggleFilter('publicado')"     title="Publicados"><span id="fc-pub">—</span> publicados</span>
      <span class="fs-badge fs-descarte"  id="fs-desc"    title="Lixeira · <a href='/lixeira'>ver lixeira →</a>"><a href="/lixeira" style="color:inherit;text-decoration:none"><span id="fc-desc">—</span> lixeira →</a></span>
    </div>
  </div>
  <div class="grid">
    {cards}
  </div>
  <div class="collect-bar">
    <button class="collect-btn" id="cbtn" onclick="startCollect()">Coletar</button>
    <span class="last-collect" id="last-collect"></span>
    <div class="progress-wrap">
      <div class="progress-track" id="ptrack"><div class="progress-bar" id="pbar"></div></div>
      <span class="progress-msg" id="pmsg"></span>
    </div>
  </div>

  <!-- ── Template selector modal ── -->
  <div class="tmpl-overlay" id="tmpl-overlay" onclick="if(event.target===this)closeTmpl()">
    <div class="tmpl-modal">
      <div class="tmpl-title">Escolher formato</div>
      <button class="tmpl-opt active" data-t="simples" onclick="selectTmpl(this)">
        <div class="tmpl-opt-name">Simples</div>
      </button>
      <button class="tmpl-opt" data-t="carrossel" onclick="selectTmpl(this)">
        <div class="tmpl-opt-name">Carrossel</div>
      </button>
      <button class="tmpl-opt" data-t="transferencia" onclick="selectTmpl(this)">
        <div class="tmpl-opt-name">Transferência</div>
      </button>
      <div class="tmpl-slides-row" id="tmpl-slides-row">
        <button class="tmpl-slide-opt active" data-n="3" onclick="selectSlides(this)">3</button>
        <button class="tmpl-slide-opt" data-n="4" onclick="selectSlides(this)">4</button>
        <button class="tmpl-slide-opt" data-n="5" onclick="selectSlides(this)">5</button>
        <button class="tmpl-slide-opt" data-n="6" onclick="selectSlides(this)">6</button>
      </div>
      <button class="tmpl-criar" onclick="criarPost()">CRIAR</button>
    </div>
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



@app.get("/descartadas", response_class=HTMLResponse)
async def descartadas():
    articles = get_low_score_articles(hours=24, limit=200)

    cards = ""
    for a in articles:
        title = a.get("title_orig") or "—"
        body  = (a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        score = a.get("relevance_score", 0)
        handle = a.get("source_name", "").lstrip("@")
        collected = (a.get("collected_at") or "")[:16].replace("T", " ")
        cards += f"""
        <div class="card">
          <div class="card-body">
            <div class="card-meta">
              <span class="tag">Tier {a['source_tier']}</span>
              <span class="tag">@{handle}</span>
              <span class="score-tag">score {score:.2f}</span>
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
  <title>IARABÃO — Descartadas</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #edeae4; color: #1a1a1a; }}
    {_HEADER_CSS}
    .info {{ font-size: 0.65rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.07em; padding: 14px 24px 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 60px; align-items: start; }}
    .card {{ background: #fafaf8; border-radius: 16px; display: flex; flex-direction: column; opacity: 0.82; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-meta {{ display: flex; align-items: center; gap: 5px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: #777; border: 1px solid #ccc; border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
    .score-tag {{ font-size: 0.6rem; font-weight: 700; color: #be123c; border: 1px solid #fca5a5; border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; margin-left: auto; }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: #1a1a1a; text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ opacity: .7; }}
    .card-text {{ font-size: 0.8rem; color: #666; line-height: 1.6; }}
    .card-footer {{ display: flex; align-items: center; justify-content: flex-end; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-date {{ font-size: 0.6rem; font-weight: 700; color: #bbb; text-transform: uppercase; letter-spacing: 0.05em; }}
  </style>
</head>
<body>
  {_header("/descartadas")}
  <p class="info">{len(articles)} descartadas · 24h · Texto original sem tradução</p>
  <div class="grid">
    {cards if cards else '<p style="padding:40px 24px;font-size:0.82rem;color:#aaa;">Nenhuma notícia descartada nas últimas 24h.</p>'}
  </div>
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
    if flag and flag not in ("naopublicado", "publicado", "descartado", "analise"):
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
    if tmpl == "chamativo":
        return (
            "TEMPLATE: CHAMATIVO (1 card).\n"
            "- tipo_sugerido = \"chamativo\"\n"
            "- titulo = UMA ÚNICA PALAVRA em maiúsculas que sintetize o assunto com impacto máximo (ex: CONFIRMADO, BOMBA, OFICIAL, CHEGOU, SAIU, RENOVAÇÃO)\n"
            "- subtitulo = exatamente 2 linhas separadas por \\n resumindo a notícia de forma direta e impactante\n"
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
    if template not in ("simples", "carrossel", "transferencia", "chamativo"):
        template = "simples"
    num_slides = body.get("num_slides", 3)
    n = min(6, max(3, int(num_slides))) if template == "carrossel" else 1
    already_translated = bool(body.get("already_translated", False))
    source = (body.get("source") or "").strip().lstrip("@")
    moon = (body.get("moon") or "").strip()
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

    ANGULO_SAUDITA = (
        "PONTO DE VISTA OBRIGATÓRIO — FUTEBOL SAUDITA:\n"
        "Este é um canal sobre a Saudi Pro League. O texto DEVE ser escrito sob a perspectiva do futebol saudita, "
        "não do futebol europeu. Siga esta ordem de prioridade:\n"
        "1. ABRA com a ação ou interesse do clube saudita (ex: 'O Al Ittihad se movimenta por...', 'O Al Hilal negocia...').\n"
        "2. Apresente o jogador/notícia brevemente como contexto — não como protagonista principal.\n"
        "3. Mencione concorrência europeia apenas como segundo parágrafo, se relevante.\n"
        "NUNCA abra com a trajetória do jogador no clube europeu. NUNCA coloque o clube europeu como sujeito principal.\n"
        "Se a notícia não envolver clube saudita diretamente, foque no impacto para a liga saudita.\n"
    )
    CLUBE_NAMES_RULE = (
        "NOMES DE CLUBES: NUNCA use hífen. Grafias OBRIGATÓRIAS: Al Hilal, Al Nassr, Al Ahli, Al Ittihad, "
        "Al Ettifaq, Al Shabab, Al Fateh, Al Taawoun, Al Qadsiah, Al Fayha, Al Wahda, Al Hazm, Damac. "
        "ATENÇÃO: الاتفاق = Al Ettifaq (NÃO Al Ittihad); الاتحاد = Al Ittihad. São clubes diferentes.\n"
    )

    if already_translated:
        footer_instruction = (
            f"Ao final do texto, adicione exatamente esta linha (sem alterar): \"{source_footer}\""
            if source_footer else ""
        )
        prompt_texto = (
            "Você é um editor de conteúdo especializado na Saudi Pro League. O texto abaixo JÁ ESTÁ EM PORTUGUÊS — NÃO TRADUZA.\n\n"
            + ANGULO_SAUDITA
            + "\nTAREFA: reescreva o texto aplicando o ponto de vista saudita acima. Máximo 4 frases. "
            "Elimine contexto europeu excessivo, carreira do jogador fora da Saudi Pro League e adjetivos vagos. "
            "Mantenha fatos concretos: quem, o quê, valores, datas. "
            "Estilo: jornalismo esportivo direto.\n\n"
            "REGRAS DE FORMATO: texto corrido, sem emojis no corpo, sem hashtags, sem exclamações, "
            "sem títulos, sem negrito, sem listas, somente parágrafos simples.\n"
            + CLUBE_NAMES_RULE
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
            "Você é um editor de conteúdo especializado na Saudi Pro League.\n\n"
            + ANGULO_SAUDITA
            + "\nTAREFA: traduza para o português brasileiro e reescreva aplicando o ponto de vista saudita acima. Máximo 4 frases. "
            "Elimine contexto europeu excessivo e adjetivos vagos. "
            "Mantenha fatos concretos: quem, o quê, valores, datas.\n\n"
            "REGRAS DE FORMATO: texto corrido, sem emojis no corpo, sem hashtags, sem exclamações, "
            "sem títulos, sem negrito, sem listas, somente parágrafos simples.\n"
            + CLUBE_NAMES_RULE
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


# ─── Gestão de Fontes ──────────────────────────
OVERRIDE_FILE = "sources_override.json"

def _load_overrides() -> dict:
    """Retorna {handle: {moon, tier}} do arquivo de override."""
    try:
        with open(OVERRIDE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_overrides(data: dict):
    with open(OVERRIDE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_effective_sources() -> list[dict]:
    """Combina sources.py com overrides. Retorna lista de {handle, tier, moon}."""
    from sources import TIER_A, TIER_B, TIER_C, SOURCE_MOON
    overrides = _load_overrides()
    base: dict[str, dict] = {}
    for tier_label, tier_data in [("A", TIER_A), ("B", TIER_B), ("C", TIER_C)]:
        for h in tier_data.get("twitter_accounts", []):
            base[h] = {"handle": h, "tier": tier_label, "moon": SOURCE_MOON.get(h, "")}
    # Apply overrides
    for h, ov in overrides.items():
        if h in base:
            base[h].update(ov)
        else:
            base[h] = {"handle": h, "tier": ov.get("tier", "C"), "moon": ov.get("moon", "🌗")}
    return sorted(base.values(), key=lambda x: (x["tier"], x["handle"].lower()))


@app.get("/fontes", response_class=HTMLResponse)
async def fontes_page():
    sources = get_effective_sources()
    MOON_OPTIONS = ["🌕", "🌖", "🌗", "🌘", "🌑"]
    TIER_OPTIONS = ["A", "B", "C"]

    rows = ""
    for s in sources:
        moon_opts = "".join(
            f'<option value="{m}" {"selected" if m == s["moon"] else ""}>{m}</option>'
            for m in MOON_OPTIONS
        )
        tier_opts = "".join(
            f'<option value="{t}" {"selected" if t == s["tier"] else ""}>Tier {t}</option>'
            for t in TIER_OPTIONS
        )
        rows += f"""
        <tr data-handle="{s['handle']}">
          <td><code>@{s['handle']}</code></td>
          <td><select class="sel-tier" onchange="markDirty(this)">{tier_opts}</select></td>
          <td><select class="sel-moon" onchange="markDirty(this)">{moon_opts}</select></td>
          <td>
            <button class="btn-save" onclick="saveSingle(this)">Salvar</button>
            <button class="btn-del" onclick="delSource(this)">×</button>
          </td>
        </tr>"""

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>IARABÃO — Fontes</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #edeae4; color: #1a1a1a; }}
    {_HEADER_CSS}
    .page {{ max-width: 680px; margin: 28px auto; padding: 0 24px 80px; }}
    .page-title {{ font-size: 0.65rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; }}
    .page-sub {{ font-size: 0.75rem; color: #999; margin-bottom: 20px; }}
    .add-box {{ background: #fafaf8; border-radius: 16px; padding: 20px; margin-bottom: 12px; display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; }}
    .add-box label {{ font-size: 0.62rem; font-weight: 700; color: #999; text-transform: uppercase; letter-spacing: 0.07em; display: block; margin-bottom: 5px; }}
    .add-box input, .add-box select {{ border: 1px solid rgba(0,0,0,.12); border-radius: 10px; padding: 7px 10px; font-size: 0.85rem; background: rgba(0,0,0,.04); color: #1a1a1a; font-family: inherit; }}
    .add-box input:focus, .add-box select:focus {{ outline: none; border-color: #1a1a1a; }}
    .add-box input {{ width: 180px; }}
    .btn-primary {{ background: #1a1a1a; color: #edeae4; border: none; padding: 8px 20px; border-radius: 99px; font-size: 0.65rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.07em; transition: opacity .15s; }}
    .btn-primary:hover {{ opacity: .75; }}
    table {{ width: 100%; border-collapse: collapse; background: #fafaf8; border-radius: 16px; overflow: hidden; }}
    th {{ text-align: left; font-size: 0.62rem; font-weight: 700; color: #aaa; padding: 12px 16px; border-bottom: 1px solid rgba(0,0,0,.06); text-transform: uppercase; letter-spacing: 0.07em; }}
    td {{ padding: 10px 16px; border-bottom: 1px solid rgba(0,0,0,.04); font-size: 0.85rem; }}
    tr:last-child td {{ border-bottom: none; }}
    tr.dirty {{ background: rgba(234,179,8,.08); }}
    code {{ font-size: 0.8rem; background: rgba(0,0,0,.06); padding: 2px 7px; border-radius: 5px; }}
    select {{ border: 1px solid rgba(0,0,0,.12); border-radius: 8px; padding: 4px 8px; font-size: 0.82rem; background: rgba(0,0,0,.04); cursor: pointer; font-family: inherit; }}
    .btn-save {{ background: #1a1a1a; color: #edeae4; border: none; padding: 4px 14px; border-radius: 99px; font-size: 0.62rem; font-weight: 700; cursor: pointer; margin-right: 4px; text-transform: uppercase; letter-spacing: 0.06em; transition: opacity .15s; }}
    .btn-save:hover {{ opacity: .75; }}
    .btn-del {{ background: transparent; color: #be123c; border: 1.5px solid #fca5a5; padding: 3px 10px; border-radius: 99px; font-size: 0.75rem; font-weight: 700; cursor: pointer; transition: all .15s; }}
    .btn-del:hover {{ background: #fff1f2; }}
    .toast {{ position: fixed; bottom: 24px; right: 24px; background: #1a1a1a; color: #edeae4; padding: 10px 20px; border-radius: 99px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0; transition: opacity .3s; pointer-events: none; }}
    .toast.show {{ opacity: 1; }}
  </style>
</head>
<body>
{_header("/fontes")}
<div class="page">
  <p class="page-title">Fontes monitoradas</p>
  <p class="page-sub">{len(sources)} fontes · Alterações entram em vigor na próxima coleta</p>
  <div class="add-box">
    <div><label>Handle (sem @)</label><input id="new-handle" placeholder="ex: FabrizioRomano"></div>
    <div><label>Tier</label><select id="new-tier"><option>A</option><option selected>B</option><option>C</option></select></div>
    <div><label>Lua</label><select id="new-moon"><option>🌕</option><option>🌖</option><option selected>🌗</option><option>🌘</option><option>🌑</option></select></div>
    <button class="btn-primary" onclick="addSource()">+ Adicionar</button>
  </div>
  <table>
    <thead><tr><th>Handle</th><th>Tier</th><th>Lua</th><th>Ações</th></tr></thead>
    <tbody id="tbody">{rows}</tbody>
  </table>
</div>
<div class="toast" id="toast"></div>
<script>
  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
  }}
  function markDirty(el) {{ el.closest('tr').classList.add('dirty'); }}

  async function saveSingle(btn) {{
    const tr = btn.closest('tr');
    const handle = tr.dataset.handle;
    const tier = tr.querySelector('.sel-tier').value;
    const moon = tr.querySelector('.sel-moon').value;
    const r = await fetch('/api/fontes', {{ method: 'POST', headers: {{'content-type':'application/json'}},
      body: JSON.stringify({{ action: 'upsert', handle, tier, moon }}) }});
    if (r.ok) {{ tr.classList.remove('dirty'); showToast('Salvo'); }}
  }}

  async function delSource(btn) {{
    const tr = btn.closest('tr');
    const handle = tr.dataset.handle;
    if (!confirm(`Remover @${{handle}}?`)) return;
    const r = await fetch('/api/fontes', {{ method: 'POST', headers: {{'content-type':'application/json'}},
      body: JSON.stringify({{ action: 'delete', handle }}) }});
    if (r.ok) {{ tr.remove(); showToast('Removido'); }}
  }}

  async function addSource() {{
    const handle = document.getElementById('new-handle').value.trim().replace(/^@/, '');
    const tier = document.getElementById('new-tier').value;
    const moon = document.getElementById('new-moon').value;
    if (!handle) {{ alert('Informe o handle'); return; }}
    const r = await fetch('/api/fontes', {{ method: 'POST', headers: {{'content-type':'application/json'}},
      body: JSON.stringify({{ action: 'upsert', handle, tier, moon }}) }});
    if (r.ok) {{ showToast('Adicionado!'); setTimeout(() => location.reload(), 1000); }}
  }}
</script>
</body></html>""")


@app.get("/lixeira", response_class=HTMLResponse)
async def lixeira_page():
    cleanup_old_trash()
    articles = get_trashed_articles()
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]

    cards = ""
    for a in articles:
        handle = a.get("source_name", "").lstrip("@")
        title  = a.get("title_pt") or a.get("title_orig") or "—"
        body   = (a.get("body_pt") or a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        art_id = a["id"]
        trashed_raw = a.get("trashed_at") or ""
        trashed_display = ""
        if trashed_raw:
            try:
                from datetime import datetime, timezone, timedelta
                dt = datetime.fromisoformat(str(trashed_raw).replace(" ", "T").split("+")[0] + "+00:00")
                dt_local = dt.astimezone(timezone(timedelta(hours=3)))
                trashed_display = f"{dt_local.day} {MONTHS_PT[dt_local.month-1]} · {dt_local.strftime('%H:%M')}"
            except Exception:
                pass
        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-top">
              <span class="card-date">{trashed_display}</span>
              <button class="restore-btn" onclick="restoreCard('{art_id}', this)" title="Restaurar">↩ Restaurar</button>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <p class="card-text">{body}</p>
            <div class="card-bottom">
              <div class="card-tags">
                <span class="tag">@{handle}</span>
                <span class="tag">Tier {a['source_tier']}</span>
              </div>
            </div>
          </div>
        </div>"""

    empty = '<p style="padding:40px 24px;font-size:0.82rem;color:#aaa;">Lixeira vazia.</p>'
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>IARABÃO — Lixeira</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #edeae4; color: #1a1a1a; }}
    {_HEADER_CSS}
    .info {{ font-size: 0.65rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.07em; padding: 14px 24px 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 60px; align-items: start; }}
    .card {{ background: #fff1f2; border-radius: 16px; opacity: .82; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
    .card-date {{ font-size: 0.65rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.07em; }}
    .restore-btn {{ background: transparent; border: 1.5px solid #1a1a1a; border-radius: 99px; padding: 4px 12px; font-size: 0.62rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.07em; transition: all .15s; }}
    .restore-btn:hover {{ background: #1a1a1a; color: #edeae4; }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: #1a1a1a; text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ opacity: .7; }}
    .card-text {{ font-size: 0.8rem; color: #666; line-height: 1.6; }}
    .card-bottom {{ display: flex; align-items: center; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: #777; border: 1px solid #ccc; border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
    .removed {{ opacity: 0; transform: scale(.95); transition: all .3s; pointer-events: none; }}
  </style>
</head>
<body>
{_header("/lixeira")}
<p class="info">{len(articles)} na lixeira · descartados nos últimos 7 dias</p>
<div class="grid">
  {cards if cards else empty}
</div>
<script>
  async function restoreCard(id, btn) {{
    const card = btn.closest('.card');
    await fetch('/api/flag', {{
      method: 'POST', headers: {{'content-type': 'application/json'}},
      body: JSON.stringify({{ id, flag: null }}),
    }});
    card.classList.add('removed');
    setTimeout(() => card.remove(), 300);
  }}
</script>
</body></html>""")


@app.post("/api/fontes")
async def api_fontes(request: Request):
    body = await request.json()
    action = body.get("action")
    handle = (body.get("handle") or "").strip().lstrip("@")
    if not handle:
        return JSONResponse({"error": "handle obrigatório"}, status_code=400)
    overrides = _load_overrides()
    if action == "upsert":
        overrides[handle] = {"tier": body.get("tier", "C"), "moon": body.get("moon", "🌗")}
    elif action == "delete":
        overrides.pop(handle, None)
    else:
        return JSONResponse({"error": "action inválida"}, status_code=400)
    _save_overrides(overrides)
    return JSONResponse({"ok": True})
