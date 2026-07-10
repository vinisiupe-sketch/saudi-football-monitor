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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx
from database import init_db, get_recent_articles, get_low_score_articles, get_collection_logs, set_flag, get_all_flags, get_trashed_articles, get_flagged_articles, cleanup_old_trash, get_conn, get_state, set_state, get_token_status, set_token_status, get_injuries, get_transfer_articles, get_club_logo, set_club_logo, get_player_photo, set_player_photo
import psycopg2.extras
from scheduler import run_pipeline, create_scheduler
from sources import SOURCE_MOON
from glossary import SPL_CLUBS, YELO_CLUBS

scheduler = None

# ─── Seleção Saudita — detecção por palavras-chave ───
SELECAO_KEYWORDS = [
    # Árabe
    "المنتخب السعودي", "منتخب السعودية", "الأخضر", "منتخبنا",
    # Inglês
    "saudi national team", "saudi arabia national", "green falcons", "saudi nt",
    # Português
    "seleção saudita", "seleção da arábia", "selecao saudita",
]

# Termos que indicam o PAÍS (seleção) em vez de um clube específico da SPL
COUNTRY_TERMS = ["arábia saudita", "arabia saudita", "saudi arabia", "السعودية"]

# Clubes da SPL — se um destes aparecer junto com "Arábia Saudita", é notícia de clube, não de seleção
SPL_CLUB_NAMES_LOWER = [
    "al hilal", "al nassr", "al ittihad", "al ahli", "al shabab", "al taawoun",
    "al fateh", "al ettifaq", "al qadsiah", "al fayha", "al hazem", "al khaleej",
    "al kholood", "al najma", "al okhdood", "al riyadh", "al diriyah", "al ula",
    "damac", "neom", "الهلال", "النصر", "الاتحاد", "الأهلي", "الشباب", "التعاون",
    "الفتح", "الاتفاق",
]

def _is_selecao_article(a: dict) -> bool:
    text = " ".join([
        a.get("title_pt") or "", a.get("title_orig") or "",
        a.get("body_pt") or "", a.get("body_orig") or "",
    ])
    # "_" -> " " porque hashtags árabes no Twitter juntam palavras com underscore
    # (#المنتخب_السعودي) — sem isso, "المنتخب السعودي" (com espaço) em SELECAO_KEYWORDS
    # nunca batia nesse formato de hashtag, e o artigo caía na heurística de
    # país+ausência-de-clube abaixo, que tem seu próprio ponto fraco (nome de
    # jogador que colide com nome de clube). Bug real visto em 2026-06-24.
    tl = text.lower().replace("_", " ")
    if any(kw.lower() in tl for kw in SELECAO_KEYWORDS):
        return True
    # Heurística: menciona o país sauditas como time (ex: "Espanha x Arábia Saudita"),
    # sem citar nenhum clube específico da SPL → é notícia da seleção, não de clube.
    if any(c in tl for c in COUNTRY_TERMS) and not any(club in tl for club in SPL_CLUB_NAMES_LOWER):
        return True
    return False


# Termos que comprovam relação real do artigo com futebol saudita.
# Verificados no TÍTULO (não no corpo inteiro) — fontes genéricas às vezes
# raspam páginas de "resumo"/digest cujo corpo cita um clube saudita em algum
# parágrafo solto, inflando o relevance_score mesmo quando o ASSUNTO do artigo
# (refletido no título) não tem nenhuma relação com futebol saudita.
SAUDI_TITLE_SIGNAL_TERMS = SPL_CLUB_NAMES_LOWER + COUNTRY_TERMS + [
    "spl", "roshn", "saudi pro league", "liga saudita", "futebol saudita", "السعودي",
]


def _is_actually_saudi_football(a: dict) -> bool:
    """Exige que o TÍTULO (não só o corpo/score) tenha um sinal saudita claro.
    Filtro final contra falsos positivos do relevance_score (ex: notícia sobre
    Werder Bremen/clube europeu que só passou porque o corpo raspado mencionava
    a Arábia Saudita em outro trecho, sem o título ter qualquer relação real)."""
    title = f"{a.get('title_pt') or ''} {a.get('title_orig') or ''}".lower().replace("-", " ").replace("_", " ")
    if any(term in title for term in SAUDI_TITLE_SIGNAL_TERMS):
        return True
    if any(kw.lower() in title for kw in SELECAO_KEYWORDS):
        return True
    return False


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
_ICO_SELECAO = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.57a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.57a2 2 0 0 0-1.34-2.23z"/></svg>'
_ICO_INJURY  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>'
_ICO_TRANSFER= '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16V4m0 0L3 8m4-4l4 4"/><path d="M17 8v12m0 0l4-4m-4 4l-4-4"/></svg>'

_THEME_VARS_CSS = (
    "    :root { --c-bg:#edeae4; --c-bg-card:#fafaf8; --c-bg-soft:#fff; --c-text:#1a1a1a; --c-muted-1:#999; --c-muted-2:#aaa; --c-muted-3:#777; --c-muted-4:#555; --c-muted-5:#666; --c-muted-6:#444; --c-line:#ccc; --c-border:rgba(0,0,0,.1); --c-border-2:rgba(0,0,0,.18); --c-hover-tint:rgba(0,0,0,.04); --c-success:#166534; --c-error:#be123c; }\n"
    "    :root[data-theme=\"dark\"] { --c-bg:#16161a; --c-bg-card:#1e1e22; --c-bg-soft:#242428; --c-text:#ededee; --c-muted-1:#8c8c93; --c-muted-2:#84848a; --c-muted-3:#9c9ca2; --c-muted-4:#c2c0c7; --c-muted-5:#b0aeb5; --c-muted-6:#d4d2d8; --c-line:#3a3a40; --c-border:rgba(255,255,255,.1); --c-border-2:rgba(255,255,255,.2); --c-hover-tint:rgba(255,255,255,.06); --c-success:#4ade80; --c-error:#fb7185; }\n"
)

_HEADER_CSS = _THEME_VARS_CSS + (
    "    header { background: var(--c-bg); border-bottom: 1px solid var(--c-border); padding: 0 20px; display: flex; align-items: center; position: sticky; top: 0; z-index: 10; height: 52px; gap: 6px; }\n"
    "    .brand { font-family: \'Bebas Neue\', sans-serif; font-size: 2rem; letter-spacing: 0.06em; color: var(--c-text); text-decoration: none; margin-right: auto; line-height: 1; }\n"
    "    .nav-icon { width: 36px; height: 36px; border-radius: 50%; border: 1.5px solid var(--c-border-2); background: transparent; color: var(--c-muted-1); cursor: pointer; display: flex; align-items: center; justify-content: center; text-decoration: none; transition: all .15s; flex-shrink: 0; position: relative; }\n"
    "    .nav-icon:hover { border-color: var(--c-text); color: var(--c-text); background: var(--c-hover-tint); }\n"
    "    .nav-icon.active { background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); }\n"
    "    .nav-icon.cta { background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); }\n"
    "    .nav-icon.cta:hover { background: var(--c-muted-6); border-color: var(--c-muted-6); }\n"
    "    .nav-icon.selecao { background: #15803d; border-color: #15803d; color: white; }\n"
    "    .nav-icon.selecao:hover { background: #166534; border-color: #166534; }\n"
    "    .nav-icon.selecao.active { background: #14532d; border-color: #14532d; }\n"
    "    .nav-icon[title]:hover::after { content: attr(title); position: absolute; bottom: -28px; left: 50%; transform: translateX(-50%); background: var(--c-text); color: var(--c-bg); font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 8px; border-radius: 6px; white-space: nowrap; pointer-events: none; z-index: 100; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', sans-serif; }\n"
    "    .nav-badge { position: absolute; top: -4px; right: -4px; background: #ef4444; color: white; font-size: 0.48rem; font-weight: 800; min-width: 14px; height: 14px; border-radius: 99px; display: none; align-items: center; justify-content: center; padding: 0 3px; line-height: 1; border: 1.5px solid var(--c-bg); }\n"
    "    .theme-toggle .ico-sun { display: none; }\n"
    "    :root[data-theme=\"dark\"] .theme-toggle .ico-moon { display: none; }\n"
    "    :root[data-theme=\"dark\"] .theme-toggle .ico-sun { display: block; }\n"
    "    .token-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--c-muted-2); margin-right: 8px; flex-shrink: 0; cursor: default; }\n"
    "    .token-dot.ok { background: #22c55e; }\n"
    "    .token-dot.broken { background: #ef4444; }\n"
)

_THEME_INIT_SCRIPT = '<script>(function(){try{if(localStorage.getItem("iarabao_theme")==="dark")document.documentElement.setAttribute("data-theme","dark");}catch(e){}})();</script>'

def _header(active: str) -> str:
    pages = [
        ("/",           _ICO_HOME,    "Home",          "home"),
        ("/selecao",    _ICO_SELECAO, "Seleção Saudita","selecao"),
        ("/descartadas",_ICO_ARCHIVE, "Descartadas",   ""),
        ("/lesoes",         _ICO_INJURY,    "Lesões",          ""),
        ("/transferencias", _ICO_TRANSFER,  "Transferências",  ""),
        ("/fontes",         _ICO_SOURCES,   "Fontes",          ""),
        ("/lixeira",    _ICO_TRASH2,  "Lixeira",       ""),
        ("/gerador",    _ICO_PEN2,    "Criar Post",    ""),
    ]
    items = ""
    for href, ico, label, badge_tab in pages:
        cls = "nav-icon"
        if href == active:
            cls += " active"
        elif href == "/gerador":
            cls += " cta"
        elif href == "/selecao":
            cls += " selecao"
        badge = f'<span class="nav-badge" data-tab="{badge_tab}" style="display:none"></span>' if badge_tab else ""
        items += f'<a class="{cls}" href="{href}" title="{label}">{ico}{badge}</a>'
    theme_btn = (
        '<button class="nav-icon theme-toggle" type="button" onclick="toggleTheme()" title="Modo noturno">'
        '<svg class="ico-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
        '<svg class="ico-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
        '</button>'
    )
    badge_script = """<script>
(function(){
  async function loadBadges(){
    var last = localStorage.getItem('iarabao_last_visit') || new Date(Date.now()-3600000).toISOString();
    try{
      var r = await fetch('/api/badge-counts?since='+encodeURIComponent(last));
      var d = await r.json();
      Object.keys(d).forEach(function(tab){
        var el = document.querySelector('.nav-badge[data-tab="'+tab+'"]');
        if(!el) return;
        var n = d[tab];
        el.textContent = n > 99 ? '99+' : (n > 0 ? n : '');
        el.style.display = n > 0 ? 'flex' : 'none';
      });
    }catch(e){}
  }
  document.addEventListener('DOMContentLoaded', loadBadges);
  window.addEventListener('beforeunload', function(){
    localStorage.setItem('iarabao_last_visit', new Date().toISOString());
  });
})();
</script>"""
    theme_script = """<script>
function toggleTheme(){
  var html = document.documentElement;
  var isDark = html.getAttribute('data-theme') === 'dark';
  if (isDark) { html.removeAttribute('data-theme'); try{localStorage.setItem('iarabao_theme','light');}catch(e){} }
  else { html.setAttribute('data-theme','dark'); try{localStorage.setItem('iarabao_theme','dark');}catch(e){} }
}
</script>"""
    token_dot = '<span class="token-dot" id="tokenDot" title="Token X/Twitter: verificando…"></span>'
    token_script = """<script>
(function(){
  async function loadTokenStatus(){
    var el = document.getElementById('tokenDot');
    if(!el) return;
    try{
      var r = await fetch('/api/token-status');
      var d = await r.json();
      if(!d || !d.status){
        el.title = 'Token X/Twitter: ainda não verificado';
        return;
      }
      el.classList.remove('ok','broken');
      el.classList.add(d.status === 'ok' ? 'ok' : 'broken');
      var quando = '';
      try{ quando = new Date(d.checked_at).toLocaleString('pt-BR'); }catch(e){}
      el.title = 'Token X/Twitter: ' + (d.status === 'ok' ? 'OK' : 'quebrado')
        + (quando ? ' · checado em ' + quando : '')
        + (d.detail ? ' · ' + d.detail : '');
    }catch(e){}
  }
  document.addEventListener('DOMContentLoaded', loadTokenStatus);
})();
</script>"""
    return f'<header>{token_dot}<a class="brand" href="/">IARABÃO</a>{items}{theme_btn}</header>{badge_script}{theme_script}{token_script}'



# ─── Dashboard ───────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    articles = get_recent_articles(hours=48, limit=80)
    _deleted_sources = {h.upper() for h, ov in load_source_overrides().items() if ov.get("deleted")}
    articles = [
        a for a in articles
        if a.get("relevance_score", 0) >= 0.45
        and a.get("source_name", "").lstrip("@").upper() not in _deleted_sources
        and not _is_selecao_article(a)
        and _is_actually_saudi_football(a)
    ]
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
              <button class="flag-circle post-btn" onclick="window.location.href='{post_base}'" title="Criar post">{ICO_PEN}</button>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IARABÃO</title>
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}

    {_HEADER_CSS}

    /* ── TOPBAR ── */
    .topbar {{
      display: flex; align-items: center; gap: 10px;
      flex-wrap: wrap; padding: 14px 24px 8px;
    }}
    .count {{ color: var(--c-muted-1); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.07em; }}
    .flag-summary {{ display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }}
    .fs-badge {{
      font-size: 0.62rem; font-weight: 700; padding: 3px 10px; border-radius: 99px;
      cursor: pointer; user-select: none; transition: all .15s;
      text-transform: uppercase; letter-spacing: 0.05em;
      border: 1.5px solid transparent;
    }}
    .fs-total     {{ border-color: var(--c-line); color: var(--c-muted-1); }}
    .fs-analise   {{ border-color: #fde68a; color: #92400e; }}
    .fs-visto     {{ border-color: #a5b4fc; color: #4338ca; }}
    .fs-publicado {{ border-color: #86efac; color: var(--c-success); }}
    .fs-descarte  {{ border-color: #fca5a5; color: var(--c-error); }}
    .fs-badge:hover {{ opacity: .7; }}
    .fs-badge.active-filter {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}

    /* ── GRID ── */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 10px; padding: 10px 24px 80px; align-items: start;
    }}

    /* ── CARD ── */
    .card {{
      background: var(--c-bg-card); border-radius: 16px;
      display: flex; flex-direction: column;
      transition: background .2s;
    }}
    .card.flag-analise   {{ background: #fefce8; }}
    .card.flag-visto     {{ background: #ede9fe; }}
    .card.flag-publicado {{ background: #dcfce7; }}
    /* Esses 3 fundos são sempre claros (mesmo no modo noturno) — reancora as
       variáveis de tema para os valores claros dentro do card, senão texto e
       ícones (que seguem var(--c-text) etc.) ficam claros sobre fundo claro. */
    .card.flag-analise, .card.flag-visto, .card.flag-publicado {{
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card.flag-descarte  {{ display: none; }}
    .card.hidden-by-filter {{ display: none; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}

    /* ── CARD TOP ── */
    .card-top {{
      display: flex; align-items: center;
      justify-content: space-between; margin-bottom: 14px;
    }}
    .card-date {{
      font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2);
      text-transform: uppercase; letter-spacing: 0.07em;
    }}
    .card-flags {{ display: flex; gap: 7px; }}
    .flag-circle {{
      width: 32px; height: 32px; border-radius: 50%;
      border: 1.5px solid var(--c-text); background: transparent;
      color: var(--c-text); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: all .15s; flex-shrink: 0;
    }}
    .flag-circle:hover {{ background: var(--c-text); color: var(--c-bg); }}
    .flag-circle.on {{ background: var(--c-text); color: var(--c-bg); }}
    .flag-circle.anal-btn:hover  {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.anal-btn.on     {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.visto-btn:hover {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.visto-btn.on    {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.pub-btn:hover   {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.pub-btn.on      {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.desc-btn:hover  {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.desc-btn.on     {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.post-btn        {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); text-decoration: none; }}
    .flag-circle.post-btn:hover  {{ background: var(--c-muted-6); border-color: var(--c-muted-6); color: var(--c-bg); }}

    /* ── TITLE ── */
    .card-title {{
      font-size: 1rem; font-weight: 700; color: var(--c-text);
      text-decoration: none; line-height: 1.4;
      display: block; margin-bottom: 10px;
    }}
    .card-title:hover {{ opacity: .7; }}

    /* ── EXPAND FLAGADO ── */
    .flag-expand-btn {{
      background: none; border: none; cursor: pointer;
      font-size: 0.62rem; color: var(--c-muted-2); padding: 0 0 10px;
      text-transform: uppercase; letter-spacing: 0.07em;
      font-weight: 700; display: none; text-align: left; transition: color .15s;
    }}
    .flag-expand-btn:hover {{ color: var(--c-text); }}
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
      font-size: 0.62rem; color: var(--c-muted-2); padding: 0 0 10px;
      text-transform: uppercase; letter-spacing: 0.07em;
      font-weight: 700; display: block; text-align: left; transition: color .15s;
    }}
    .expand-text-btn:hover {{ color: var(--c-text); }}

    /* ── BODY TEXT ── */
    .card-text {{
      font-size: 0.82rem; color: var(--c-muted-4); line-height: 1.65;
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
      font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3);
      border: 1px solid var(--c-line); border-radius: 99px;
      padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em;
    }}

    /* ── COLLECT BAR ── */
    .collect-bar {{
      position: fixed; bottom: 0; left: 0; right: 0;
      background: var(--c-bg); border-top: 1px solid var(--c-border);
      padding: 10px 24px; display: flex; align-items: center; gap: 14px;
      z-index: 10;
    }}
    .collect-btn {{
      background: var(--c-text); color: var(--c-bg); border: none;
      padding: 7px 20px; border-radius: 99px; cursor: pointer;
      font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; transition: opacity .15s; white-space: nowrap;
    }}
    .collect-btn:hover:not(:disabled) {{ opacity: .75; }}
    .collect-btn:disabled {{ opacity: .4; cursor: not-allowed; }}
    .progress-wrap {{ flex: 1; display: flex; flex-direction: column; gap: 3px; }}
    .progress-track {{ height: 3px; background: rgba(0,0,0,.1); border-radius: 99px; overflow: hidden; display: none; }}
    .progress-bar {{ height: 100%; width: 0%; background: var(--c-text); border-radius: 99px; transition: width .4s ease; }}
    .progress-bar.indeterminate {{ width: 35%; animation: slide 1.2s ease-in-out infinite; }}
    @keyframes slide {{ 0% {{ transform: translateX(-100%); }} 100% {{ transform: translateX(350%); }} }}
    .last-collect {{ font-size: 0.65rem; color: var(--c-muted-2); white-space: nowrap; text-transform: uppercase; letter-spacing: 0.05em; }}
    .progress-msg {{ font-size: 0.68rem; color: var(--c-muted-3); min-height: 14px; }}
    .progress-msg.ok  {{ color: var(--c-success); }}
    .progress-msg.err {{ color: var(--c-error); }}
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
      let comment = null;
      if (newFlag === 'analise') {{
        comment = prompt('Por que esse artigo não deveria estar aqui? (ajuda a IA a aprender)');
        if (comment === null) return; // cancelou — não marca a flag
      }}
      // Atualiza local imediatamente (feedback instantâneo)
      if (newFlag) _flags[id] = newFlag; else delete _flags[id];
      applyFlags();
      // Persiste no banco
      try {{
        await fetch('/api/flag', {{
          method: 'POST',
          headers: {{'content-type': 'application/json'}},
          body: JSON.stringify({{ id, flag: newFlag, comment }}),
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
  {_header("/")}
  <div class="topbar">
    <span class="count">{len(articles)} notícias · 48h</span>
    <div class="flag-summary">
      <span class="fs-badge fs-total"     id="fs-total"   onclick="toggleFilter('none')"         title="Sem flag"><span id="fc-total">—</span> sem flag</span>
      <span class="fs-badge fs-analise"   id="fs-analise" title="Análise · ver lista →"><a href="/analise" style="color:inherit;text-decoration:none"><span id="fc-analise">—</span> análise →</a></span>
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
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── Seleção Saudita ─────────────────────────
@app.get("/selecao", response_class=HTMLResponse)
async def selecao_page():
    all_articles = get_recent_articles(hours=48, limit=200)
    _deleted_sources = {h.upper() for h, ov in load_source_overrides().items() if ov.get("deleted")}
    articles = [
        a for a in all_articles
        if a.get("relevance_score", 0) >= 0.45
        and a.get("source_name", "").lstrip("@").upper() not in _deleted_sources
        and _is_selecao_article(a)
        # Nota: _is_actually_saudi_football() não entra aqui de propósito — ela exige
        # o sinal saudita no TÍTULO, mas notícia de seleção é frequentemente sobre o
        # ADVERSÁRIO da Arábia na Copa (ex: técnico do Uruguai, jogador da Espanha)
        # com a Arábia citada só no corpo. _is_selecao_article() já é o filtro
        # dedicado e correto pra esse caso.
    ]
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
              <button class="flag-circle post-btn" onclick="window.location.href='{post_base}'" title="Criar post">{ICO_PEN}</button>
            </div>
          </div>
        </div>"""

    empty_msg = '<p style="padding:40px 24px;font-size:0.82rem;color:var(--c-muted-2);">Nenhuma notícia sobre a Seleção Saudita nas últimas 48h.</p>'
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IARABÃO — Seleção Saudita</title>
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .topbar {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 14px 24px 8px; }}
    .count {{ color: var(--c-muted-1); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.07em; }}
    .selecao-badge {{ background: #15803d; color: white; font-size: 0.6rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; text-transform: uppercase; letter-spacing: 0.06em; }}
    .flag-summary {{ display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }}
    .fs-badge {{ font-size: 0.62rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; cursor: pointer; user-select: none; transition: all .15s; text-transform: uppercase; letter-spacing: 0.05em; border: 1.5px solid transparent; }}
    .fs-total     {{ border-color: var(--c-line); color: var(--c-muted-1); }}
    .fs-analise   {{ border-color: #fde68a; color: #92400e; }}
    .fs-visto     {{ border-color: #a5b4fc; color: #4338ca; }}
    .fs-publicado {{ border-color: #86efac; color: var(--c-success); }}
    .fs-descarte  {{ border-color: #fca5a5; color: var(--c-error); }}
    .fs-badge:hover {{ opacity: .7; }}
    .fs-badge.active-filter {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 80px; align-items: start; }}
    .card {{ background: var(--c-bg-card); border-radius: 16px; display: flex; flex-direction: column; transition: background .2s; }}
    .card.flag-analise   {{ background: #fefce8; }}
    .card.flag-visto     {{ background: #ede9fe; }}
    .card.flag-publicado {{ background: #dcfce7; }}
    /* Esses 3 fundos são sempre claros (mesmo no modo noturno) — reancora as
       variáveis de tema para os valores claros dentro do card, senão texto e
       ícones (que seguem var(--c-text) etc.) ficam claros sobre fundo claro. */
    .card.flag-analise, .card.flag-visto, .card.flag-publicado {{
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card.flag-descarte  {{ display: none; }}
    .card.hidden-by-filter {{ display: none; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
    .card-date {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; }}
    .card-flags {{ display: flex; gap: 7px; }}
    .flag-circle {{ width: 32px; height: 32px; border-radius: 50%; border: 1.5px solid var(--c-text); background: transparent; color: var(--c-text); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all .15s; flex-shrink: 0; }}
    .flag-circle:hover {{ background: var(--c-text); color: var(--c-bg); }}
    .flag-circle.on {{ background: var(--c-text); color: var(--c-bg); }}
    .flag-circle.anal-btn:hover  {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.anal-btn.on     {{ background: #ca8a04; border-color: #ca8a04; color: white; }}
    .flag-circle.visto-btn:hover {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.visto-btn.on    {{ background: #4338ca; border-color: #4338ca; color: white; }}
    .flag-circle.pub-btn:hover   {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.pub-btn.on      {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.desc-btn:hover  {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.desc-btn.on     {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.post-btn        {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); text-decoration: none; }}
    .flag-circle.post-btn:hover  {{ background: var(--c-muted-6); border-color: var(--c-muted-6); color: var(--c-bg); }}
    .card-title {{ font-size: 1rem; font-weight: 700; color: var(--c-text); text-decoration: none; line-height: 1.4; display: block; margin-bottom: 10px; }}
    .card-title:hover {{ opacity: .7; }}
    .flag-expand-btn {{ background: none; border: none; cursor: pointer; font-size: 0.62rem; color: var(--c-muted-2); padding: 0 0 10px; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; display: none; text-align: left; transition: color .15s; }}
    .flag-expand-btn:hover {{ color: var(--c-text); }}
    .card-collapsed .flag-expand-btn {{ display: block; }}
    .card-collapsed .card-text, .card-collapsed .card-bottom, .card-collapsed .expand-text-btn {{ display: none; }}
    .card-collapsed.flag-open .card-text, .card-collapsed.flag-open .card-bottom {{ display: flex; }}
    .card-collapsed.flag-open .card-text {{ display: block; }}
    .card-collapsed.flag-open .text-short {{ display: none; }}
    .card-collapsed.flag-open .text-full  {{ display: inline !important; }}
    .expand-text-btn {{ background: none; border: none; cursor: pointer; font-size: 0.62rem; color: var(--c-muted-2); padding: 0 0 10px; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; display: block; text-align: left; transition: color .15s; }}
    .expand-text-btn:hover {{ color: var(--c-text); }}
    .card-text {{ font-size: 0.82rem; color: var(--c-muted-4); line-height: 1.65; margin-bottom: 16px; }}
    .card-bottom {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding-top: 14px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3); border: 1px solid var(--c-line); border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
  </style>
  <script>
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
        card.classList.toggle('card-collapsed', f === 'naopublicado' || f === 'publicado' || f === 'analise');
        if (!f) card.classList.remove('flag-open');
      }});
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
    function toggleFilter(type) {{ _activeFilter = (_activeFilter === type) ? null : type; applyFilter(); }}
    function toggleFlagExpand(btn) {{ const card = btn.closest('.card'); const open = card.classList.toggle('flag-open'); btn.textContent = open ? '↑ ver menos' : '↓ ver mais'; }}
    function expandText(btn) {{ const p = btn.previousElementSibling; const short = p.querySelector('.text-short'); const full = p.querySelector('.text-full'); const expanded = btn.classList.toggle('expanded'); short.style.display = expanded ? 'none' : 'inline'; full.style.display = expanded ? 'inline' : 'none'; btn.textContent = expanded ? '↑ ver menos' : '↓ ver mais'; }}
    async function loadFlags() {{ try {{ const r = await fetch('/api/flags'); _flags = await r.json(); applyFlags(); }} catch(e) {{}} }}
    async function toggleFlag(id, type) {{ const current = _flags[id]; const newFlag = (current === type) ? null : type; let comment = null; if (newFlag === 'analise') {{ comment = prompt('Por que esse artigo não deveria estar aqui? (ajuda a IA a aprender)'); if (comment === null) return; }} if (newFlag) _flags[id] = newFlag; else delete _flags[id]; applyFlags(); try {{ await fetch('/api/flag', {{ method: 'POST', headers: {{'content-type': 'application/json'}}, body: JSON.stringify({{ id, flag: newFlag, comment }}) }}); }} catch(e) {{}} }}
    document.addEventListener('DOMContentLoaded', () => {{ loadFlags(); setInterval(loadFlags, 10000); }});
  </script>
</head>
<body>
  {_header("/selecao")}
  <div class="topbar">
    <span class="count">{len(articles)} notícias · 48h</span>
    <span class="selecao-badge">🇸🇦 Seleção</span>
    <div class="flag-summary">
      <span class="fs-badge fs-total"     id="fs-total"   onclick="toggleFilter('none')"        ><span id="fc-total">—</span> sem flag</span>
      <span class="fs-badge fs-analise"   id="fs-analise" title="Análise · ver lista →"><a href="/analise" style="color:inherit;text-decoration:none"><span id="fc-analise">—</span> análise →</a></span>
      <span class="fs-badge fs-visto"     id="fs-visto"   onclick="toggleFilter('naopublicado')" ><span id="fc-visto">—</span> salvos</span>
      <span class="fs-badge fs-publicado" id="fs-pub"     onclick="toggleFilter('publicado')"    ><span id="fc-pub">—</span> publicados</span>
      <span class="fs-badge fs-descarte"  id="fs-desc"    ><a href="/lixeira" style="color:inherit;text-decoration:none"><span id="fc-desc">—</span> lixeira →</a></span>
    </div>
  </div>
  <div class="grid">
    {cards if cards else empty_msg}
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── API endpoints ────────────────────────────
@app.get("/api/articles")
async def api_articles(hours: int = 24, tier: str = None, limit: int = 100):
    return get_recent_articles(hours=hours, tier=tier, limit=limit)


@app.get("/api/badge-counts")
async def api_badge_counts(since: str = ""):
    """Conta artigos novos desde `since` (ISO timestamp) para cada aba."""
    if not since:
        logs = get_collection_logs(limit=2)
        if len(logs) >= 2:
            since = str(logs[1].get("ran_at", ""))
        else:
            since = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    articles = get_recent_articles(hours=48, limit=300)
    _deleted_sources = {h.upper() for h, ov in load_source_overrides().items() if ov.get("deleted")}
    visible = [
        a for a in articles
        if a.get("relevance_score", 0) >= 0.45
        and a.get("source_name", "").lstrip("@").upper() not in _deleted_sources
        and str(a.get("collected_at") or "") >= since
        and _is_actually_saudi_football(a)
    ]
    home_count = sum(1 for a in visible if not _is_selecao_article(a))
    selecao_count = sum(1 for a in visible if _is_selecao_article(a))
    return {"home": home_count, "selecao": selecao_count}



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


@app.get("/api/token-status")
async def api_token_status_get():
    """Status do último check diário do token X/Twitter (rotina twitter-token-check).
    Usado pela bolinha verde/vermelha no header."""
    return get_token_status()


@app.post("/api/token-status")
async def api_token_status_post(request: Request):
    """Chamado pela rotina diária (8h) ao terminar de checar o token. Body:
    {"status": "ok"|"broken", "detail": "..."} — detail é opcional."""
    payload = await request.json()
    status = payload.get("status")
    if status not in ("ok", "broken"):
        return JSONResponse({"error": "status deve ser 'ok' ou 'broken'"}, status_code=400)
    set_token_status(status, payload.get("detail", ""))
    return {"saved": True}


@app.post("/api/collect")
async def api_collect(background_tasks: BackgroundTasks, hours: int = None):
    # force=True ignora período inativo. hours opcional permite forçar uma
    # janela maior manualmente (resgate pontual); sem isso, usa o cálculo
    # dinâmico em lookback_hours() (cobre o tempo desde a última coleta OK).
    background_tasks.add_task(run_pipeline, True, hours)
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
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .info {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; padding: 14px 24px 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 60px; align-items: start; }}
    .card {{ background: var(--c-bg-card); border-radius: 16px; display: flex; flex-direction: column; opacity: 0.82; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-meta {{ display: flex; align-items: center; gap: 5px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3); border: 1px solid var(--c-line); border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
    .score-tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-error); border: 1px solid #fca5a5; border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; margin-left: auto; }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: var(--c-text); text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ opacity: .7; }}
    .card-text {{ font-size: 0.8rem; color: var(--c-muted-5); line-height: 1.6; }}
    .card-footer {{ display: flex; align-items: center; justify-content: flex-end; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-date {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.05em; }}
  </style>
</head>
<body>
  {_header("/descartadas")}
  <p class="info">{len(articles)} descartadas · 24h · Texto original sem tradução</p>
  <div class="grid">
    {cards if cards else '<p style="padding:40px 24px;font-size:0.82rem;color:var(--c-muted-2);">Nenhuma notícia descartada nas últimas 24h.</p>'}
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
    comment = (body.get("comment") or "").strip() or None
    if not article_id:
        return JSONResponse({"error": "id obrigatório"}, status_code=400)
    if flag and flag not in ("naopublicado", "publicado", "descartado", "analise"):
        return JSONResponse({"error": "flag inválida"}, status_code=400)
    set_flag(article_id, flag, comment)
    return {"ok": True, "id": article_id, "flag": flag, "comment": comment}


@app.get("/api/analise-export")
async def analise_export():
    """Exporta os artigos marcados como 'análise' em JSON, com todos os dados
    relevantes (título, corpo, fonte, score, comentário), pra análise externa
    de por que cada um foi coletado/filtrado de forma equivocada."""
    articles = get_flagged_articles("analise")
    data = [
        {
            "title_orig": a.get("title_orig"),
            "title_pt": a.get("title_pt"),
            "body_orig": a.get("body_orig"),
            "body_pt": a.get("body_pt"),
            "url": a.get("url"),
            "source_name": a.get("source_name"),
            "source_tier": a.get("source_tier"),
            "source_type": a.get("source_type"),
            "category": a.get("category"),
            "relevance_score": a.get("relevance_score"),
            "language": a.get("language"),
            "published_at": a.get("published_at"),
            "collected_at": a.get("collected_at"),
            "flagged_at": a.get("flagged_at"),
            "comment": a.get("flag_comment"),
        }
        for a in articles
    ]
    filename = f"iarabao_analise_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    # Limpa a flag 'analise' dos artigos exportados — a página /analise deve ficar
    # vazia depois do download, e só voltar a ter itens quando novos forem marcados.
    for a in articles:
        set_flag(a["id"], None)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/gerador", response_class=HTMLResponse)
async def gerador():
    with open("public/generator.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ─── Gerador de posts (Central do Arabão) ────────
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL_POST = "claude-sonnet-4-5"


def _post_rule() -> str:
    return (
        "Gere, a partir da notícia abaixo, as QUATRO variações de título a seguir — não escolha uma, gere todas:\n\n"
        "1. CURTO — até 3 palavras, MAIÚSCULAS, máximo impacto (ex: CONFIRMADO, BOMBA, OFICIAL, CHEGOU, RENOVAÇÃO). "
        "+ subtitulo_curto: 1 a 2 frases (até ~35 palavras) dando contexto da notícia, complementando o título "
        "(ex: 'Cristiano Ronaldo retorna aos gramados para disputar sua 6ª Copa do Mundo por Portugal. "
        "São 20 anos entre sua estreia, em 2006, e o Mundial de hoje.').\n"
        "2. MÉDIO — até 7 palavras, MAIÚSCULAS. Sem subtítulo.\n"
        "3. LONGO — até 10 palavras, MAIÚSCULAS, mais descritivo. NUNCA corte palavras no meio — reformule se ultrapassar o limite.\n"
        "4. TRANSFERÊNCIA — titulo_transferencia: até 7 palavras, MAIÚSCULAS, focado na movimentação do jogador. "
        "nome_jogador: nome do jogador em MAIÚSCULAS extraído do texto. "
        "status_transferencia: escolha o mais adequado entre Acerto, Anunciado, Avançado, Consulta, Conversas, "
        "De Saída, Encaminhado, Interesse, Melou, Negociação, Oficial, Opção, Proposta, Sondagem."
    )


@app.post("/api/generate-post")
async def generate_post(request: Request):
    body = await request.json()
    news = (body.get("news") or "").strip()
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
        + _post_rule()
        + "\n\nFORMATO DE SAÍDA:\nRetorne SOMENTE um objeto JSON puro, sem markdown, sem blocos de código, sem texto fora do JSON.\n\n"
        "Estrutura exata (preencha TODOS os valores, sempre):\n"
        '{\n  "titulo_curto": "...",\n  "subtitulo_curto": "...",\n  "titulo_medio": "...",\n'
        '  "titulo_longo": "...",\n  "titulo_transferencia": "...",\n'
        '  "nome_jogador": "...",\n  "status_transferencia": "..."\n}'
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
        "NOMES DE CLUBES: NUNCA use hífen. Grafias OBRIGATÓRIAS (1ª divisão/SPL): "
        + ", ".join(SPL_CLUBS) + ". "
        "Grafias OBRIGATÓRIAS (Yelo League, 2º nível): " + ", ".join(YELO_CLUBS) + ". "
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
# A lógica de overrides mora em database.py (get_effective_sources /
# load_source_overrides / save_source_overrides) — collector.py importa as
# mesmas funções, então a coleta real sempre vê exatamente a lista mostrada
# aqui. Antes, collector.py tinha sua própria leitura (de um arquivo local que
# a UI nunca escrevia), então adicionar/excluir fonte em /fontes não tinha
# NENHUM efeito na coleta (bug real reportado pelo usuário em 2026-06-24).
from database import get_effective_sources, load_source_overrides, save_source_overrides


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
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .page {{ max-width: 680px; margin: 28px auto; padding: 0 24px 80px; }}
    .page-title {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; }}
    .page-sub {{ font-size: 0.75rem; color: var(--c-muted-1); margin-bottom: 20px; }}
    .add-box {{ background: var(--c-bg-card); border-radius: 16px; padding: 20px; margin-bottom: 12px; display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; }}
    .add-box label {{ font-size: 0.62rem; font-weight: 700; color: var(--c-muted-1); text-transform: uppercase; letter-spacing: 0.07em; display: block; margin-bottom: 5px; }}
    .add-box input, .add-box select {{ border: 1px solid var(--c-border-2); border-radius: 10px; padding: 7px 10px; font-size: 0.85rem; background: var(--c-hover-tint); color: var(--c-text); font-family: inherit; }}
    .add-box input:focus, .add-box select:focus {{ outline: none; border-color: var(--c-text); }}
    .add-box input {{ width: 180px; }}
    .btn-primary {{ background: var(--c-text); color: var(--c-bg); border: none; padding: 8px 20px; border-radius: 99px; font-size: 0.65rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.07em; transition: opacity .15s; }}
    .btn-primary:hover {{ opacity: .75; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--c-bg-card); border-radius: 16px; overflow: hidden; }}
    th {{ text-align: left; font-size: 0.62rem; font-weight: 700; color: var(--c-muted-2); padding: 12px 16px; border-bottom: 1px solid var(--c-border); text-transform: uppercase; letter-spacing: 0.07em; }}
    td {{ padding: 10px 16px; border-bottom: 1px solid var(--c-hover-tint); font-size: 0.85rem; }}
    tr:last-child td {{ border-bottom: none; }}
    tr.dirty {{ background: rgba(234,179,8,.08); }}
    code {{ font-size: 0.8rem; background: var(--c-border); padding: 2px 7px; border-radius: 5px; }}
    select {{ border: 1px solid var(--c-border-2); border-radius: 8px; padding: 4px 8px; font-size: 0.82rem; background: var(--c-hover-tint); cursor: pointer; font-family: inherit; }}
    .btn-save {{ background: var(--c-text); color: var(--c-bg); border: none; padding: 4px 14px; border-radius: 99px; font-size: 0.62rem; font-weight: 700; cursor: pointer; margin-right: 4px; text-transform: uppercase; letter-spacing: 0.06em; transition: opacity .15s; }}
    .btn-save:hover {{ opacity: .75; }}
    .btn-del {{ background: transparent; color: var(--c-error); border: 1.5px solid #fca5a5; padding: 3px 10px; border-radius: 99px; font-size: 0.75rem; font-weight: 700; cursor: pointer; transition: all .15s; }}
    .btn-del:hover {{ background: #fff1f2; }}
    .toast {{ position: fixed; bottom: 24px; right: 24px; background: var(--c-text); color: var(--c-bg); padding: 10px 20px; border-radius: 99px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0; transition: opacity .3s; pointer-events: none; }}
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

    empty = '<p style="padding:40px 24px;font-size:0.82rem;color:var(--c-muted-2);">Lixeira vazia.</p>'
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>IARABÃO — Lixeira</title>
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .info {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; padding: 14px 24px 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 60px; align-items: start; }}
    .card {{
      background: #fff1f2; border-radius: 16px; opacity: .82;
      /* Fundo sempre claro (mesmo no modo noturno) — reancora as variáveis de
         tema para os valores claros, senão texto/ícones ficam claros sobre fundo claro. */
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
    .card-date {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; }}
    .restore-btn {{ background: transparent; border: 1.5px solid var(--c-text); border-radius: 99px; padding: 4px 12px; font-size: 0.62rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.07em; transition: all .15s; }}
    .restore-btn:hover {{ background: var(--c-text); color: var(--c-bg); }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: var(--c-text); text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ opacity: .7; }}
    .card-text {{ font-size: 0.8rem; color: var(--c-muted-5); line-height: 1.6; }}
    .card-bottom {{ display: flex; align-items: center; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3); border: 1px solid var(--c-line); border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
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


@app.get("/analise", response_class=HTMLResponse)
async def analise_page():
    articles = get_flagged_articles("analise")
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]

    cards = ""
    for a in articles:
        handle = a.get("source_name", "").lstrip("@")
        title  = a.get("title_pt") or a.get("title_orig") or "—"
        body   = (a.get("body_pt") or a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        art_id = a["id"]
        comment = (a.get("flag_comment") or "").strip()
        flagged_raw = a.get("flagged_at") or ""
        flagged_display = ""
        if flagged_raw:
            try:
                dt = datetime.fromisoformat(str(flagged_raw).replace(" ", "T").split("+")[0] + "+00:00")
                dt_local = dt.astimezone(timezone(timedelta(hours=3)))
                flagged_display = f"{dt_local.day} {MONTHS_PT[dt_local.month-1]} · {dt_local.strftime('%H:%M')}"
            except Exception:
                pass
        comment_html = (
            f'<p class="card-comment">💬 {comment}</p>'
            if comment else
            f'<div class="card-comment-add"><input type="text" class="comment-input" id="comment-input-{art_id}" placeholder="Por que está aqui? (opcional)" onkeydown="if(event.key===\'Enter\')saveComment(\'{art_id}\', this.nextElementSibling)"><button class="comment-save-btn" onclick="saveComment(\'{art_id}\', this)">Salvar</button></div>'
        )
        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-top">
              <span class="card-date">{flagged_display}</span>
              <button class="restore-btn" onclick="restoreCard('{art_id}', this)" title="Remover da análise">✕ remover</button>
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <p class="card-text">{body}</p>
            {comment_html}
            <div class="card-bottom">
              <div class="card-tags">
                <span class="tag">@{handle}</span>
                <span class="tag">Tier {a['source_tier']}</span>
              </div>
            </div>
          </div>
        </div>"""

    empty = '<p style="padding:40px 24px;font-size:0.82rem;color:var(--c-muted-2);">Nenhum artigo marcado para análise.</p>'
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>IARABÃO — Análise</title>
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .info-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 14px 24px 6px; }}
    .info {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; }}
    .export-btn {{ font-size: 0.62rem; font-weight: 700; padding: 6px 14px; border-radius: 99px; cursor: pointer; border: 1.5px solid var(--c-text); background: transparent; color: var(--c-text); text-transform: uppercase; letter-spacing: .05em; text-decoration: none; display: inline-flex; align-items: center; gap: 5px; }}
    .export-btn:hover {{ background: var(--c-text); color: var(--c-bg); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 60px; align-items: start; }}
    .card {{
      background: #fefce8; border-radius: 16px;
      /* Fundo sempre claro (mesmo no modo noturno) — reancora as variáveis de
         tema para os valores claros, senão texto/ícones ficam claros sobre fundo claro. */
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
    .card-date {{ font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: 0.07em; }}
    .restore-btn {{ background: transparent; border: 1.5px solid var(--c-text); border-radius: 99px; padding: 4px 12px; font-size: 0.62rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.07em; transition: all .15s; }}
    .restore-btn:hover {{ background: var(--c-text); color: var(--c-bg); }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: var(--c-text); text-decoration: none; line-height: 1.4; display: block; margin-bottom: 8px; }}
    .card-title:hover {{ opacity: .7; }}
    .card-text {{ font-size: 0.8rem; color: var(--c-muted-5); line-height: 1.6; }}
    .card-comment {{ font-size: 0.78rem; color: #92400e; background: #fef3c7; border-radius: 8px; padding: 8px 10px; margin-top: 10px; line-height: 1.5; }}
    .card-comment-empty {{ color: var(--c-muted-2); background: transparent; padding: 0; }}
    .card-comment-add {{ display: flex; gap: 6px; margin-top: 10px; }}
    .comment-input {{ flex: 1; border: 1px solid var(--c-border-2); border-radius: 8px; padding: 6px 10px; font-size: 0.76rem; font-family: inherit; background: var(--c-hover-tint); color: var(--c-text); }}
    .comment-input:focus {{ outline: none; border-color: #92400e; }}
    .comment-save-btn {{ background: transparent; border: 1.5px solid #92400e; color: #92400e; border-radius: 8px; padding: 6px 12px; font-size: 0.7rem; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: .04em; transition: all .15s; white-space: nowrap; }}
    .comment-save-btn:hover {{ background: #92400e; color: white; }}
    .card-bottom {{ display: flex; align-items: center; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3); border: 1px solid var(--c-line); border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
    .removed {{ opacity: 0; transform: scale(.95); transition: all .3s; pointer-events: none; }}
  </style>
</head>
<body>
{_header("/analise")}
<div class="info-bar">
  <p class="info">{len(articles)} marcados para análise</p>
  <a class="export-btn" href="/api/analise-export" download title="Baixa um JSON com todos os artigos marcados, pra analisar com calma">⬇ Baixar para análise</a>
</div>
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
  async function saveComment(id, btn) {{
    const input = document.getElementById('comment-input-' + id);
    const text = input.value.trim();
    if (!text) return;
    btn.disabled = true;
    try {{
      await fetch('/api/flag', {{
        method: 'POST', headers: {{'content-type': 'application/json'}},
        body: JSON.stringify({{ id, flag: 'analise', comment: text }}),
      }});
      const wrap = input.closest('.card-comment-add');
      const p = document.createElement('p');
      p.className = 'card-comment';
      p.textContent = '💬 ' + text;
      wrap.replaceWith(p);
    }} catch (e) {{
      btn.disabled = false;
    }}
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
    overrides = load_source_overrides()
    if action == "upsert":
        overrides[handle] = {"tier": body.get("tier", "C"), "moon": body.get("moon", "🌗")}
    elif action == "delete":
        overrides[handle] = {"deleted": True}
    else:
        return JSONResponse({"error": "action inválida"}, status_code=400)
    save_source_overrides(overrides)
    return JSONResponse({"ok": True})


@app.post("/api/reprocess")
async def reprocess_articles(request: Request, background_tasks: BackgroundTasks):
    """Retraduzi artigos a partir de uma data/hora. Roda em background para evitar timeout."""
    body = await request.json()
    since = body.get("since", "")  # ex: "2026-07-01 00:00:00"
    if not since:
        return JSONResponse({"error": "Campo 'since' obrigatório (ex: '2026-07-01 00:00:00')"}, status_code=400)

    from processor import call_claude
    from glossary import GLOSSARY_PROMPT, apply_glossary
    from database import update_article_body, update_article_title, update_article_meta
    from collector import compute_relevance
    import json

    force = body.get("force", False)
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if force:
            c.execute("""
                SELECT * FROM articles
                WHERE collected_at >= %s
                  AND is_duplicate = 0
                ORDER BY collected_at ASC
            """, (since,))
        else:
            c.execute("""
                SELECT * FROM articles
                WHERE collected_at >= %s
                  AND (title_pt IS NULL OR title_pt = title_orig)
                  AND is_duplicate = 0
                ORDER BY collected_at ASC
            """, (since,))
        rows = [dict(r) for r in c.fetchall()]

    if not rows:
        return JSONResponse({"ok": True, "reprocessed": 0, "msg": "Nenhum artigo para reprocessar"})

    # Traduz diretamente sem filtro de relevância
    system = (
        "Você é um redator esportivo brasileiro especializado na Saudi Pro League. "
        "Adapte o texto para o português brasileiro com estilo jornalístico natural. "
        f"{GLOSSARY_PROMPT}"
    )
    prompt_template = (
        "Traduza os artigos abaixo para português brasileiro.\n"
        "Responda SOMENTE com JSON: {{\"translations\": [{{\"title_pt\": \"...\", \"body_pt\": \"...\", \"category\": \"...\"}}]}}\n"
        "Categorias: transferencia, resultado, lesao, geral\n\n{items}"
    )

    updated = 0
    errors = []
    BATCH_SIZE = 3
    prompt_header = (
        "Traduza os artigos abaixo para português brasileiro.\n"
        'Responda SOMENTE com JSON: {"translations": [{"title_pt": "...", "body_pt": "...", "category": "..."}]}\n'
        "Categorias: transferencia, resultado, lesao, geral\n\n"
    )
    async with httpx.AsyncClient() as client:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            items_text = ""
            for idx, a in enumerate(batch):
                items_text += f"\nARTIGO {idx+1}:\nTítulo: {a.get('title_orig','')}\nTexto: {a.get('body_orig','')[:1200]}\n---"
            try:
                raw = await call_claude(
                    system=system,
                    prompt=prompt_header + items_text,  # concatenação direta — evita KeyError em .format()
                    max_tokens=2000,
                    client=client
                )
                # Strip markdown caso Haiku retorne ```json...```
                raw = raw.strip()
                if raw.startswith("```"):
                    parts = raw.split("```")
                    raw = parts[1] if len(parts) > 1 else raw
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                translations = json.loads(raw).get("translations", [])
                for idx, a in enumerate(batch):
                    if idx < len(translations):
                        t = translations[idx]
                        title_pt = apply_glossary(t.get("title_pt") or a["title_orig"])
                        body_pt  = apply_glossary(t.get("body_pt")  or a.get("body_orig", ""))
                        update_article_title(a["id"], title_pt)
                        update_article_body(a["id"], a.get("body_orig", ""), body_pt)
                        # Salva category e recalcula relevance_score com a lógica atualizada
                        category = t.get("category") or None
                        new_score = compute_relevance(
                            f"{a.get('title_orig', '')} {a.get('body_orig', '')}",
                            a.get("source_tier", "C")
                        )
                        update_article_meta(a["id"], category=category, relevance_score=new_score)
                        updated += 1
            except Exception as e:
                err = f"Lote {i//BATCH_SIZE+1}: {type(e).__name__}: {e}"
                print(f"Reprocess erro {err}")
                errors.append(err)

    return JSONResponse({"ok": True, "found": len(rows), "reprocessed": updated, "errors": errors})


@app.post("/api/reprocess-bg")
async def reprocess_articles_bg(request: Request, background_tasks: BackgroundTasks):
    """Versão background do reprocess — retorna imediatamente e processa em segundo plano."""
    body = await request.json()
    since = body.get("since", "")
    force = body.get("force", False)
    if not since:
        return JSONResponse({"error": "Campo 'since' obrigatório"}, status_code=400)

    from processor import call_claude
    from glossary import GLOSSARY_PROMPT, apply_glossary
    from database import update_article_body, update_article_title, update_article_meta
    from collector import compute_relevance
    import json as _json

    async def _run():
        if force:
            with get_conn() as conn:
                c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                c.execute("""
                    SELECT * FROM articles
                    WHERE collected_at >= %s AND is_duplicate = 0
                    ORDER BY collected_at ASC
                """, (since,))
                rows = [dict(r) for r in c.fetchall()]
        else:
            with get_conn() as conn:
                c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                c.execute("""
                    SELECT * FROM articles
                    WHERE collected_at >= %s
                      AND (title_pt IS NULL OR title_pt = title_orig)
                      AND is_duplicate = 0
                    ORDER BY collected_at ASC
                """, (since,))
                rows = [dict(r) for r in c.fetchall()]

        print(f"🔄 Reprocess BG: {len(rows)} artigos desde {since} (force={force})")
        system = (
            "Você é um redator esportivo brasileiro especializado na Saudi Pro League. "
            "Adapte o texto para o português brasileiro com estilo jornalístico natural. "
            f"{GLOSSARY_PROMPT}"
        )
        prompt_header = (
            "Traduza os artigos abaixo para português brasileiro.\n"
            'Responda SOMENTE com JSON: {"translations": [{"title_pt": "...", "body_pt": "...", "category": "..."}]}\n'
            "Categorias: transferencia, resultado, lesao, geral\n\n"
        )
        updated = 0
        BATCH_SIZE = 3
        async with httpx.AsyncClient() as client:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                items_text = ""
                for idx, a in enumerate(batch):
                    items_text += f"\nARTIGO {idx+1}:\nTítulo: {a.get('title_orig','')}\nTexto: {a.get('body_orig','')[:1200]}\n---"
                try:
                    raw = await call_claude(system=system, prompt=prompt_header + items_text, max_tokens=2000, client=client)
                    raw = raw.strip()
                    if raw.startswith("```"):
                        parts = raw.split("```")
                        raw = parts[1] if len(parts) > 1 else raw
                        if raw.startswith("json"): raw = raw[4:]
                    raw = raw.strip()
                    translations = _json.loads(raw).get("translations", [])
                    for idx, a in enumerate(batch):
                        if idx < len(translations):
                            t = translations[idx]
                            title_pt = apply_glossary(t.get("title_pt") or a["title_orig"])
                            body_pt  = apply_glossary(t.get("body_pt")  or a.get("body_orig", ""))
                            update_article_title(a["id"], title_pt)
                            update_article_body(a["id"], a.get("body_orig", ""), body_pt)
                            category = t.get("category") or None
                            new_score = compute_relevance(
                                f"{a.get('title_orig', '')} {a.get('body_orig', '')}",
                                a.get("source_tier", "C")
                            )
                            update_article_meta(a["id"], category=category, relevance_score=new_score)
                            updated += 1
                except Exception as e:
                    print(f"   ⚠️  Reprocess BG lote {i//BATCH_SIZE+1}: {e}")
        print(f"✅ Reprocess BG concluído: {updated}/{len(rows)} artigos reprocessados")

    background_tasks.add_task(_run)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM articles
            WHERE collected_at >= %s AND is_duplicate = 0
        """, (since,))
        total = c.fetchone()[0]
    return JSONResponse({"ok": True, "msg": f"Processando {total} artigos em background com Opus 4.6", "since": since, "force": force})


# ═══════════════════════════════════════════════════════════
#  MONITOR DE LESÕES
# ═══════════════════════════════════════════════════════════

@app.get("/api/debug-lesoes")
async def debug_lesoes():
    import traceback
    try:
        injuries = get_injuries(include_recovered=True)
        return {"ok": True, "count": len(injuries), "sample": injuries[:2]}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


@app.get("/lesoes", response_class=HTMLResponse)
async def page_lesoes(request: Request):
    import traceback as _tb
    try:
        return await _page_lesoes_impl(request)
    except Exception as _e:
        return HTMLResponse("<pre>" + _tb.format_exc() + "</pre>", status_code=500)


async def _page_lesoes_impl(request: Request):
    injuries = get_injuries(include_recovered=True)
    active   = [i for i in injuries if i["status"] != "recuperado"]
    recovered = [i for i in injuries if i["status"] == "recuperado"]

    STATUS_LABEL = {
        "lesionado":      ("🔴", "Lesionado"),
        "em_recuperacao": ("🟡", "Em recuperação"),
        "retornando":     ("🟢", "Retornando"),
        "recuperado":     ("⚫", "Recuperado"),
    }
    TYPE_LABEL = {
        "muscular": "Muscular", "ligamento": "Ligamento", "fratura": "Fratura",
        "cirurgia": "Cirurgia", "doença": "Doença", "contusão": "Contusão",
        "fadiga": "Fadiga", "outro": "Outro",
    }

    def _row(inj: dict) -> str:
        emoji, slabel = STATUS_LABEL.get(inj.get("status") or "lesionado", ("⚪", inj.get("status") or "—"))
        tipo = TYPE_LABEL.get(inj.get("injury_type") or "", inj.get("injury_type") or "—")
        parte = inj.get("body_part") or ""
        tipo_full = tipo + " · " + parte.capitalize() if parte else tipo
        retorno = inj.get("expected_return") or "—"
        injury_dt = ((inj.get("injury_date") or "")[:10]) or "—"
        updated = (inj.get("last_updated") or "")[:10]
        notes = inj.get("notes") or ""
        player = inj.get("player_name") or "—"
        club   = inj.get("club") or "—"
        status = inj.get("status") or "lesionado"

        # Nome original (só se diferente)
        orig = inj.get("player_name_orig") or ""
        orig_html = ('<br><small class="orig">' + orig + "</small>") if orig and orig != player else ""

        # Fontes
        sources = inj.get("sources") or []
        srcs_html = ""
        for s in sources[:4]:
            u  = s.get("url", "#")
            nm = s.get("source_name", "fonte")
            dt = s.get("published_at", "")[:10]
            srcs_html += '<a href="' + u + '" target="_blank" class="src-chip">' + nm + '<span class="src-dt">' + dt + "</span></a>"
        if len(sources) > 4:
            srcs_html += '<span class="src-chip src-more">+' + str(len(sources) - 4) + "</span>"

        # Linha de notas
        notes_row = ('<tr class="notes-row"><td colspan="8" class="td-notes">💬 ' + notes + "</td></tr>") if notes else ""

        return (
            "<tr>"
            + '<td class="td-player"><strong>' + player + "</strong>" + orig_html + "</td>"
            + '<td class="td-club">' + club + "</td>"
            + '<td class="td-date">' + injury_dt + "</td>"
            + '<td class="td-type">' + tipo_full + "</td>"
            + '<td class="td-return">' + retorno + "</td>"
            + '<td class="td-status"><span class="status-badge status-' + status + '">' + emoji + " " + slabel + "</span></td>"
            + '<td class="td-sources">' + srcs_html + "</td>"
            + '<td class="td-updated">' + updated + "</td>"
            + "</tr>"
            + notes_row
        )

    rows_active    = "".join(_row(i) for i in active)    if active    else '<tr><td colspan="8" class="empty-row">Nenhuma lesão ativa registrada.</td></tr>'
    rows_recovered = "".join(_row(i) for i in recovered) if recovered else '<tr><td colspan="8" class="empty-row">Nenhuma recuperação registrada.</td></tr>'

    count_active    = len(active)
    count_recovered = len(recovered)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IARABÃO — Lesões</title>
  {_THEME_INIT_SCRIPT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}

.lesoes-wrap {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 16px 60px;
}}
.lesoes-title {{
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 4px;
}}
.lesoes-subtitle {{
  font-size: .78rem;
  color: var(--c-muted);
  margin: 0 0 20px;
}}
.rebuild-btn {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: .75rem;
  color: var(--c-muted);
  background: none;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  margin-bottom: 20px;
  transition: color .15s, border-color .15s;
}}
.rebuild-btn:hover {{ color: var(--c-text); border-color: var(--c-muted); }}

.section-label {{
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--c-muted);
  padding: 0 0 8px;
  border-bottom: 1px solid var(--c-border);
  margin-bottom: 0;
}}
.section-count {{
  font-weight: 400;
  opacity: .7;
}}

.injuries-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: .82rem;
  margin-bottom: 32px;
}}
.injuries-table th {{
  text-align: left;
  font-size: .68rem;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--c-muted);
  padding: 10px 12px 8px;
  border-bottom: 2px solid var(--c-border);
  white-space: nowrap;
}}
.injuries-table td {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--c-border);
  vertical-align: top;
  color: var(--c-text);
}}
.injuries-table tr:hover td {{ background: var(--c-muted-2); }}
.notes-row td {{ padding: 2px 12px 10px !important; border-bottom: 1px solid var(--c-border); background: var(--c-muted-2); }}
.notes-row:hover td {{ background: var(--c-muted-2) !important; }}
.td-notes {{ font-size: .75rem; color: var(--c-muted); font-style: italic; }}

.td-player strong {{ font-weight: 600; }}
.td-player .orig {{ color: var(--c-muted); font-size: .72rem; }}
.td-club {{ white-space: nowrap; }}
.td-date, .td-updated {{ white-space: nowrap; color: var(--c-muted); font-size: .78rem; }}
.td-return {{ white-space: nowrap; }}
.empty-row {{ text-align: center; color: var(--c-muted); padding: 32px !important; }}

.status-badge {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: .72rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 99px;
  white-space: nowrap;
}}
.status-lesionado      {{ background: #fef2f2; color: #b91c1c; }}
.status-em_recuperacao {{ background: #fefce8; color: #92400e; }}
.status-retornando     {{ background: #f0fdf4; color: #15803d; }}
.status-recuperado     {{ background: var(--c-muted-2); color: var(--c-muted); }}
[data-theme=dark] .status-lesionado      {{ background: #3f1212; color: #fca5a5; }}
[data-theme=dark] .status-em_recuperacao {{ background: #3f2d00; color: #fde68a; }}
[data-theme=dark] .status-retornando     {{ background: #052e16; color: #86efac; }}
[data-theme=dark] .status-recuperado     {{ background: var(--c-muted-2); color: var(--c-muted); }}

.src-chip {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: .68rem;
  background: var(--c-muted-2);
  border-radius: 4px;
  padding: 2px 6px;
  margin: 2px 2px 2px 0;
  color: var(--c-text);
  text-decoration: none;
  white-space: nowrap;
}}
.src-chip:hover {{ background: var(--c-border); }}
.src-dt {{ color: var(--c-muted); font-size: .62rem; }}
.src-more {{ color: var(--c-muted); cursor: default; }}
a.src-chip {{ cursor: pointer; }}

details summary {{
  cursor: pointer;
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--c-muted);
  padding: 10px 0 8px;
  border-bottom: 1px solid var(--c-border);
  margin-bottom: 0;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
}}
details summary::-webkit-details-marker {{ display: none; }}
details summary::before {{ content: "▶"; font-size: .6rem; transition: transform .2s; }}
details[open] summary::before {{ transform: rotate(90deg); }}
</style>
</head>
<body>
{_header("/lesoes")}
<div class="lesoes-wrap">
  <div class="lesoes-title">Monitor de Lesões</div>
  <div class="lesoes-subtitle">Atualizado automaticamente com base nas notícias coletadas com category=lesao.</div>

  <button class="rebuild-btn" onclick="rebuild()">⟳ Reprocessar histórico</button>
  <span id="rebuild-status" style="font-size:.75rem;color:var(--c-muted);margin-left:8px;"></span>

  <div class="section-label">Ativas <span class="section-count">({count_active})</span></div>
  <table class="injuries-table">
    <thead><tr>
      <th>Jogador</th><th>Clube</th><th>Data Lesão</th><th>Tipo / Região</th>
      <th>Retorno Est.</th><th>Status</th><th>Fontes</th><th>Atualizado</th>
    </tr></thead>
    <tbody>{rows_active}</tbody>
  </table>

  <details>
    <summary>Recuperados <span class="section-count" style="font-weight:400;opacity:.7">({count_recovered})</span></summary>
    <table class="injuries-table" style="margin-top:12px">
      <thead><tr>
        <th>Jogador</th><th>Clube</th><th>Data Lesão</th><th>Tipo / Região</th>
        <th>Retorno Est.</th><th>Status</th><th>Fontes</th><th>Atualizado</th>
      </tr></thead>
      <tbody>{rows_recovered}</tbody>
    </table>
  </details>
</div>

<script>
async function rebuild() {{
  const btn = document.querySelector('.rebuild-btn');
  const st  = document.getElementById('rebuild-status');
  btn.disabled = true;
  st.textContent = 'Processando…';
  try {{
    const r = await fetch('/api/injuries/rebuild', {{method:'POST'}});
    const d = await r.json();
    st.textContent = `Concluído: ${{d.created}} criados, ${{d.updated}} atualizados, ${{d.skipped}} ignorados de ${{d.total}} artigos.`;
    setTimeout(() => location.reload(), 2000);
  }} catch(e) {{
    st.textContent = 'Erro: ' + e.message;
  }} finally {{
    btn.disabled = false;
  }}
}}
</script>
</body></html>"""
    return HTMLResponse(html)


@app.get("/api/injuries")
async def api_injuries():
    return get_injuries(include_recovered=True)


@app.post("/api/injuries/rebuild")
async def api_injuries_rebuild():
    from injury_processor import rebuild_injuries_from_history
    result = await rebuild_injuries_from_history()
    return result


# ── MONITOR DE TRANSFERÊNCIAS ────────────────────────────────────────────────

@app.get("/transferencias", response_class=HTMLResponse)
async def page_transferencias(request: Request):
    return await _page_transferencias_impl(request)


async def _page_transferencias_impl(request: Request):
    import unicodedata
    from transfer_processor import NEGO_TYPES
    from sources import SOURCE_MOON

    articles = get_transfer_articles()
    total = len(articles)
    classified = sum(1 for a in articles if a.get("nego_type"))

    _CLUB_COLORS = {
        "al hilal":            {"bg": "#1a3a8f", "color": "#fff", "abbr": "HIL"},
        "al nassr":            {"bg": "#C8990A", "color": "#fff", "abbr": "NAS"},
        "al ittihad":          {"bg": "#1a1a1a", "color": "#FFD700", "abbr": "ITT"},
        "al ahli":             {"bg": "#005522", "color": "#fff", "abbr": "AHL"},
        "al shabab":           {"bg": "#B30000", "color": "#fff", "abbr": "SHB"},
        "al ettifaq":          {"bg": "#0033AA", "color": "#FFD700", "abbr": "ETT"},
        "al fateh":            {"bg": "#2d1b82", "color": "#fff", "abbr": "FAT"},
        "al taawoun":          {"bg": "#997700", "color": "#fff", "abbr": "TAA"},
        "al qadsiah":          {"bg": "#14284e", "color": "#fff", "abbr": "QAD"},
        "damac":               {"bg": "#8B0020", "color": "#fff", "abbr": "DAM"},
        "al fayha":            {"bg": "#004d00", "color": "#FFD700", "abbr": "FAY"},
        "al hazem":            {"bg": "#8B0000", "color": "#fff", "abbr": "HAZ"},
        "al kholood":          {"bg": "#5c0080", "color": "#fff", "abbr": "KHL"},
        "al riyadh":           {"bg": "#004d00", "color": "#fff", "abbr": "RIY"},
        "al akhdoud":          {"bg": "#1e4d1e", "color": "#fff", "abbr": "AKH"},
        "al wahda":            {"bg": "#005000", "color": "#FFD700", "abbr": "WAH"},
        "al wehda":            {"bg": "#005000", "color": "#FFD700", "abbr": "WHD"},
        "al najma":            {"bg": "#1a1a1a", "color": "#fff", "abbr": "NJM"},
        "al qadisiyah":        {"bg": "#006400", "color": "#fff", "abbr": "QDS"},
        "al adalah":           {"bg": "#8B0000", "color": "#fff", "abbr": "ADA"},
        "al tai":              {"bg": "#004080", "color": "#fff", "abbr": "TAI"},
        "abha":                {"bg": "#005522", "color": "#fff", "abbr": "ABH"},
        "real madrid":         {"bg": "#001489", "color": "#fff", "abbr": "RM"},
        "barcelona":           {"bg": "#A50044", "color": "#004D98", "abbr": "FCB"},
        "atletico madrid":     {"bg": "#CE3524", "color": "#fff", "abbr": "ATM"},
        "sevilla":             {"bg": "#D52B1E", "color": "#fff", "abbr": "SEV"},
        "villarreal":          {"bg": "#C8990A", "color": "#fff", "abbr": "VIL"},
        "valencia":            {"bg": "#c05a00", "color": "#fff", "abbr": "VCF"},
        "psg":                 {"bg": "#002B5C", "color": "#DA291C", "abbr": "PSG"},
        "paris saint-germain": {"bg": "#002B5C", "color": "#DA291C", "abbr": "PSG"},
        "manchester city":     {"bg": "#5BADDD", "color": "#fff", "abbr": "MCI"},
        "manchester united":   {"bg": "#BA1313", "color": "#fff", "abbr": "MNU"},
        "chelsea":             {"bg": "#034694", "color": "#fff", "abbr": "CHE"},
        "arsenal":             {"bg": "#9B1016", "color": "#fff", "abbr": "ARS"},
        "liverpool":           {"bg": "#C8102E", "color": "#fff", "abbr": "LIV"},
        "tottenham":           {"bg": "#132257", "color": "#fff", "abbr": "TOT"},
        "aston villa":         {"bg": "#5e0019", "color": "#C5A028", "abbr": "AVL"},
        "newcastle":           {"bg": "#1a1a1a", "color": "#fff", "abbr": "NEW"},
        "juventus":            {"bg": "#1a1a1a", "color": "#fff", "abbr": "JUV"},
        "inter milan":         {"bg": "#010E80", "color": "#fff", "abbr": "INT"},
        "ac milan":            {"bg": "#8B0000", "color": "#fff", "abbr": "ACM"},
        "napoli":              {"bg": "#007DC5", "color": "#fff", "abbr": "NAP"},
        "roma":                {"bg": "#6B0000", "color": "#FFD700", "abbr": "ROM"},
        "lazio":               {"bg": "#6FA8CE", "color": "#1a1a1a", "abbr": "LAZ"},
        "atalanta":            {"bg": "#1a3a80", "color": "#fff", "abbr": "ATA"},
        "porto":               {"bg": "#003087", "color": "#FFD700", "abbr": "POR"},
        "benfica":             {"bg": "#9B0000", "color": "#fff", "abbr": "BEN"},
        "sporting cp":         {"bg": "#004D00", "color": "#FFD700", "abbr": "SPO"},
        "ajax":                {"bg": "#9B0000", "color": "#fff", "abbr": "AJX"},
        "psv":                 {"bg": "#9B0000", "color": "#fff", "abbr": "PSV"},
        "bayer leverkusen":    {"bg": "#B80000", "color": "#000", "abbr": "B04"},
        "borussia dortmund":   {"bg": "#C8A800", "color": "#000", "abbr": "BVB"},
        "bayern munich":       {"bg": "#A00020", "color": "#fff", "abbr": "BAY"},
        "rb leipzig":          {"bg": "#9B0000", "color": "#fff", "abbr": "RBL"},
        "lyon":                {"bg": "#1B2148", "color": "#D00000", "abbr": "OL"},
        "marseille":           {"bg": "#009FD4", "color": "#fff", "abbr": "OM"},
        "monaco":              {"bg": "#9B0000", "color": "#fff", "abbr": "ASM"},
        "celtic":              {"bg": "#005000", "color": "#fff", "abbr": "CEL"},
        "rangers":             {"bg": "#003082", "color": "#fff", "abbr": "RFC"},
        "galatasaray":         {"bg": "#9B0000", "color": "#FFD700", "abbr": "GAL"},
        "fenerbahce":          {"bg": "#C8A800", "color": "#1a1a1a", "abbr": "FEN"},
        "flamengo":            {"bg": "#9B0000", "color": "#000", "abbr": "FLA"},
        "fluminense":          {"bg": "#6B0000", "color": "#006400", "abbr": "FLU"},
        "corinthians":         {"bg": "#1a1a1a", "color": "#fff", "abbr": "COR"},
        "palmeiras":           {"bg": "#005000", "color": "#fff", "abbr": "PAL"},
        "sao paulo":           {"bg": "#9B0000", "color": "#fff", "abbr": "SPF"},
        "boca juniors":        {"bg": "#003087", "color": "#FFD700", "abbr": "BOC"},
        "river plate":         {"bg": "#9B0000", "color": "#fff", "abbr": "RIV"},
    }

    # Priority of transfer status (higher = more advanced)
    NTYPE_RANK = {
        "oficial": 8, "avancado": 7, "negociacoes": 6,
        "proposta": 5, "interesse": 4, "emprestimo": 3,
        "renovacao": 3, "sondagem": 1,
    }

    def _norm(s: str | None) -> str:
        s = (s or "").lower().strip()
        nfd = unicodedata.normalize("NFD", s)
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    def _club_cfg(name: str | None) -> dict:
        if not name:
            return {"bg": "#3a3a3c", "color": "#fff", "abbr": "?"}
        n = _norm(name)
        if n in _CLUB_COLORS:
            return _CLUB_COLORS[n]
        for k, v in _CLUB_COLORS.items():
            if k in n or (len(n) > 4 and n in k):
                return v
        return {"bg": "#3a3a3c", "color": "#fff", "abbr": (n[:3].upper() or "?")}

    def _logo_wrap(name: str | None, af_id: str | None = None) -> str:
        if not name:
            return '<div class="club-logo-wrap"><span class="club-crest" style="background:#3a3a3c;color:#fff">?</span></div>'
        cfg = _club_cfg(name)
        enc = quote(name, safe="")
        title_safe = name.replace('"', "&quot;").replace("&", "&amp;")
        # Prioridade 1: logo cacheado via warm-saudi-teams (IDs corretos, season 2025)
        cached_logo = get_club_logo(_logo_norm(name))
        img_url = cached_logo or (
            f"https://media.api-sports.io/football/teams/{af_id}.png" if af_id else None
        )
        if img_url:
            fallback_html = (
                f"<span class=\'club-crest\' "
                f"style=\'background:{cfg['bg']};color:{cfg['color']}\'>" 
                f"{cfg['abbr']}</span>"
            )
            return (
                f'<div class="club-logo-wrap" title="{title_safe}">'
                f'<img class="club-logo-img" src="{img_url}" alt="{title_safe}" loading="lazy"'
                f' onerror="this.parentNode.innerHTML=\'{fallback_html}\'" >'
                f'</div>'
            )
        crest = (
            f'<span class="club-crest" style="background:{cfg["bg"]};color:{cfg["color"]}">'
            f'{cfg["abbr"]}</span>'
        )
        return f'<div class="club-logo-wrap" data-club="{enc}" title="{title_safe}">{crest}</div>'


    def _nego_badge(ntype: str | None, small: bool = False) -> str:
        if not ntype:
            ntype = "sondagem"
        cfg = NEGO_TYPES.get(ntype, NEGO_TYPES["sondagem"])
        cls = "nego-badge nego-badge-sm" if small else "nego-badge"
        return (
            f'<span class="{cls}" style="background:{cfg["bg"]};color:{cfg["color"]}">'
            f'{cfg["icon"]} {cfg["label"]}</span>'
        )

    def _date_fmt(iso) -> str:
        if not iso:
            return ""
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            return dt.strftime("%d/%m")
        except Exception:
            return ""

    def _player_initials(name: str) -> str:
        parts = (name or "?").split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return (name[:2] if name else "?").upper()

    # ── Agrupamento por (jogador, origem, destino) — sem ntype ────────────
    seen: dict = {}
    for a in articles:
        pname = a.get("player_name") or ""
        cfrom = a.get("club_from") or ""
        cto   = a.get("club_to") or ""
        ntype = a.get("nego_type") or "sondagem"
        key   = (_norm(pname), _norm(cfrom), _norm(cto))
        if key not in seen:
            seen[key] = {
                "player_name":        pname or None,
                "player_position":    a.get("player_position"),
                "club_from":          cfrom or None,
                "club_to":            cto or None,
                "fee":                a.get("fee"),
                "nego_type":          ntype,
                "_unclassified":      not a.get("player_name"),
                "sources":            [],
                "af_player_id":       a.get("af_player_id") or None,
                "af_team_from_id":    a.get("af_team_from_id") or None,
                "af_team_to_id":      a.get("af_team_to_id") or None,
            }
        else:
            # Absorve IDs de api-football se o grupo ainda não os tem
            if not seen[key].get("af_player_id") and a.get("af_player_id"):
                seen[key]["af_player_id"] = a["af_player_id"]
            if not seen[key].get("af_team_from_id") and a.get("af_team_from_id"):
                seen[key]["af_team_from_id"] = a["af_team_from_id"]
            if not seen[key].get("af_team_to_id") and a.get("af_team_to_id"):
                seen[key]["af_team_to_id"] = a["af_team_to_id"]
        # Promote to highest-rank status seen for this transfer
        if NTYPE_RANK.get(ntype, 0) > NTYPE_RANK.get(seen[key]["nego_type"], 0):
            seen[key]["nego_type"] = ntype
        if a.get("fee") and not seen[key]["fee"]:
            seen[key]["fee"] = a.get("fee")
        seen[key]["sources"].append({
            "source_name":  a.get("source_name", ""),
            "url":          a.get("url", "#"),
            "published_at": a.get("published_at"),
            "nego_type":    ntype,
            "title":        a.get("title_pt") or a.get("title_orig") or "",
        })

    groups = list(seen.values())

    # ── Fuzzy dedup: merge cards com nomes parecidos + mesmo destino ─────
    # Executa múltiplos passes para capturar merges transitivos
    # (ex: A≈B e B≈C mas A não foi comparado diretamente com C no mesmo passe)
    from difflib import SequenceMatcher as _SM

    def _name_sim(a: str, b: str) -> bool:
        """True se a e b são provavelmente o mesmo jogador (variações de transliteração)."""
        if not a or not b:
            return False
        if _SM(None, a, b).ratio() > 0.82:
            return True
        ap, bp = a.split(), b.split()
        if not ap or not bp:
            return False
        last_sim  = _SM(None, ap[-1], bp[-1]).ratio()
        first_sim = _SM(None, ap[0][:4], bp[0][:4]).ratio()
        return last_sim > 0.72 and first_sim > 0.70

    for _pass in range(4):  # até 4 passes para merges transitivos
        _used: set = set()
        _merged: list = []
        _any_merge = False
        for _i, _g in enumerate(groups):
            if _i in _used:
                continue
            _ni = _norm(_g.get("player_name") or "")
            _fi = _norm(_g.get("club_from") or "")
            _ti = _norm(_g.get("club_to") or "")
            for _j in range(_i + 1, len(groups)):
                if _j in _used:
                    continue
                _g2 = groups[_j]
                _nj = _norm(_g2.get("player_name") or "")
                _fj = _norm(_g2.get("club_from") or "")
                _tj = _norm(_g2.get("club_to") or "")
                _to_ok  = (not _ti or not _tj or _ti == _tj)
                _frm_ok = (not _fi or not _fj or _fi == _fj or _name_sim(_fi, _fj))
                if _to_ok and _frm_ok and _name_sim(_ni, _nj):
                    # Merge _g2 into _g
                    _g["sources"].extend(_g2["sources"])
                    if NTYPE_RANK.get(_g2.get("nego_type"), 0) > NTYPE_RANK.get(_g.get("nego_type"), 0):
                        _g["nego_type"] = _g2["nego_type"]
                    if _g2.get("fee") and not _g.get("fee"):
                        _g["fee"] = _g2["fee"]
                    if _g2.get("player_position") and not _g.get("player_position"):
                        _g["player_position"] = _g2["player_position"]
                    # Keep the longer/more complete name
                    if len(_nj) > len(_ni):
                        _g["player_name"] = _g2["player_name"]
                        _ni = _nj
                    # Absorve club_to/from do merged se o atual estiver vazio
                    if not _ti and _tj:
                        _g["club_to"] = _g2["club_to"]
                        _ti = _tj
                    if not _fi and _fj:
                        _g["club_from"] = _g2["club_from"]
                        _fi = _fj
                    # Absorve af_ids se o grupo ainda não os tem
                    if not _g.get("af_player_id") and _g2.get("af_player_id"):
                        _g["af_player_id"] = _g2["af_player_id"]
                    if not _g.get("af_team_from_id") and _g2.get("af_team_from_id"):
                        _g["af_team_from_id"] = _g2["af_team_from_id"]
                    if not _g.get("af_team_to_id") and _g2.get("af_team_to_id"):
                        _g["af_team_to_id"] = _g2["af_team_to_id"]
                    _used.add(_j)
                    _any_merge = True
            _merged.append(_g)
            _used.add(_i)
        groups = _merged
        if not _any_merge:
            break

    # Sort sources within each group newest-first (for timeline)
    for g in groups:
        g["sources"].sort(key=lambda s: s.get("published_at") or "", reverse=True)

    n_groups = len(groups)

    type_counts: dict = {}
    for g in groups:
        t = g.get("nego_type") or "sondagem"
        type_counts[t] = type_counts.get(t, 0) + 1

    # ── Gera cards ────────────────────────────────────────────────────────
    def _card(idx: int, g: dict) -> str:
        pname  = g.get("player_name") or "?"
        pos    = g.get("player_position") or ""
        fee    = g.get("fee") or ""
        ntype  = g.get("nego_type") or "sondagem"
        accent = NEGO_TYPES.get(ntype, NEGO_TYPES["sondagem"])["color"]
        badge  = _nego_badge(ntype)
        ucls   = " tc-dim" if g.get("_unclassified") else ""
        fw     = _logo_wrap(g.get("club_from"), g.get("af_team_from_id"))
        tw     = _logo_wrap(g.get("club_to"),   g.get("af_team_to_id"))
        to_cfg   = _club_cfg(g.get("club_to"))
        card_bg  = to_cfg["bg"]
        card_txt = to_cfg["color"]

        pos_h = f'<div class="tc-pos">{pos}</div>' if pos else ""
        fee_h = f'<div class="tc-fee">{fee}</div>' if fee else ""
        initials = _player_initials(pname)
        from urllib.parse import quote as _pq
        _oe = "this.style.display='none'"
        _af_pid = g.get("af_player_id") or ""
        _photo_src = (
            f"https://media.api-sports.io/football/players/{_af_pid}.png"
            if _af_pid else
            f"/api/player-photo?name={_pq(pname)}"
        )
        avatar = (
            f'<span class="player-avatar">'
            f'<span class="player-ini">{initials}</span>'
            f'<img class="player-photo" loading="lazy"'
            f' src="{_photo_src}"'
            f' onerror="{_oe}">'
            f'</span>'
        )

        sources = g.get("sources", [])
        n_src = len(sources)
        lbl_col = f'{n_src}'
        lbl_exp = f'{lbl_col} ▴'
        lbl_col_v = f'{lbl_col} ▾'

        # Timeline entries
        tl_rows = []
        for s in sources:
            sname   = s.get("source_name", "")
            moon    = SOURCE_MOON.get(sname.lstrip("@"), "")
            slabel  = (sname.lstrip("@") or "?")
            url     = s.get("url", "#")
            date_s  = _date_fmt(s.get("published_at"))
            sntype  = s.get("nego_type") or "sondagem"
            sbadge  = _nego_badge(sntype, small=True)
            title   = (s.get("title") or "").strip()
            url_esc = url.replace('"', "&quot;")
            title_esc = (title or slabel).replace("&", "&amp;").replace("<", "&lt;")[:120]
            tl_rows.append(
                f'<div class="tl-entry">'
                f'<span class="tl-dot" style="background:{accent}"></span>'
                f'<span class="tl-date">{date_s}</span>'
                f'{sbadge}'
                f'<span class="tl-src">{moon} {slabel}</span>'
                f'<a class="tl-title" href="{url_esc}" target="_blank" rel="noopener">'
                f'{title_esc}</a>'
                f'</div>'
            )
        timeline = "\n".join(tl_rows)

        return (
            f'<div class="tc{ucls}" data-type="{ntype}" '
            f'style="--accent:{accent};background:{card_bg};color:{card_txt};border-color:transparent">'
            # ── main row
            f'<div class="tc-main">'
            f'<div class="tc-accent"></div>'
            f'<div class="tc-body">'
            f'<span class="tc-rank">#{idx}</span>'
            f'{avatar}'
            f'<div class="clubs-block">{fw}<span class="clubs-sep">›</span>{tw}</div>'
            f'<div class="tc-info">'
            f'<div class="tc-player">{pname}</div>'
            f'{pos_h}{fee_h}'
            f'</div>'
            f'<button class="expand-btn" onclick="toggleTl(this)" '
            f'data-col="{lbl_col_v}" data-exp="{lbl_exp}">'
            f'{lbl_col_v}</button>'
            f'</div>'
            f'</div>'
            # ── expandable timeline
            f'<div class="tc-timeline" hidden>'
            f'<div class="tc-badge-wrap tc-badge-exp">{badge}</div>'
            f'<div class="tl-inner">{timeline}</div>'
            f'</div>'
            f'</div>'
        )

    if groups:
        cards_html = "\n".join(_card(i + 1, g) for i, g in enumerate(groups))
    else:
        cards_html = (
            '<div class="empty"><span class="empty-icon">🔍</span>'
            '<p>Nenhuma transferência encontrada para julho de 2026.</p></div>'
        )

    # ── Botões de filtro ──────────────────────────────────────────────────
    filter_btns = ""
    for ntype, cfg in NEGO_TYPES.items():
        cnt = type_counts.get(ntype, 0)
        if cnt == 0:
            continue
        filter_btns += (
            f'<button class="filter-btn" data-type="{ntype}">'
            f'{cfg["icon"]} {cfg["label"]} <span class="filter-cnt">{cnt}</span>'
            f'</button>\n'
        )

    subtitle = (
        f"{n_groups} negociações · "
        f"{classified} de {total} artigos classificados · "
        "julho 2026"
    )

    CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.4}
:root{
  --bg:#f0f0f5;--bg-card:#fff;--text:#1c1c1e;--muted:#6b7280;--muted2:#9ca3af;
  --border:#e5e7eb;--border2:#d1d5db;--accent-blue:#147efb;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0d0d0f;--bg-card:#1c1c1e;--text:#f2f2f7;--muted:#8e8e93;--muted2:#636366;
  --border:#2c2c2e;--border2:#3a3a3c;
}}
body{background:var(--bg);color:var(--text);min-height:100vh}
.page{max-width:980px;margin:0 auto;padding:16px 12px 56px}
.hdr{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:18px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.hdr h1{font-size:1.2rem;font-weight:800;color:var(--text)}
.hdr-sub{font-size:.7rem;color:var(--muted);margin-top:3px}
.hdr-actions{display:flex;gap:6px;align-items:center;flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:4px;padding:6px 11px;border-radius:8px;font-size:.73rem;font-weight:600;border:none;cursor:pointer;text-decoration:none;transition:opacity .15s}
.btn-primary{background:var(--accent-blue);color:#fff}
.btn-sec{background:var(--bg-card);color:var(--muted);border:1px solid var(--border2)}
.btn:hover{opacity:.82}
.filters{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:12px}
.filter-btn{display:inline-flex;align-items:center;gap:4px;padding:4px 12px;border-radius:20px;font-size:.70rem;font-weight:600;border:1.5px solid var(--border2);background:var(--bg-card);color:var(--muted);cursor:pointer;transition:all .15s;line-height:1.6}
.filter-btn.active{background:var(--text);color:var(--bg);border-color:var(--text)}
.filter-cnt{font-weight:400;opacity:.7}
/* Card shell */
.tc{border-radius:11px;border:1px solid transparent;overflow:hidden;margin-bottom:6px;transition:box-shadow .15s,transform .15s}
.tc:hover{box-shadow:0 2px 16px rgba(0,0,0,.22);transform:translateY(-1px)}
/* Main row */
.tc-main{display:flex;align-items:center}
.tc-accent{width:4px;flex-shrink:0;align-self:stretch;background:var(--accent,#6b7280)}
.tc-body{flex:1;display:flex;align-items:center;gap:10px;padding:9px 13px;min-width:0;overflow:hidden}
.tc-rank{font-size:.62rem;font-weight:700;color:inherit;opacity:.45;min-width:20px;flex-shrink:0;text-align:right;font-variant-numeric:tabular-nums}
.player-avatar{position:relative;width:34px;height:34px;border-radius:50%;overflow:hidden;flex-shrink:0;display:inline-flex;align-items:center;justify-content:center}.player-ini{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:.62rem;font-weight:800;background:rgba(128,128,128,.28);color:inherit;opacity:.8;letter-spacing:-.02em}.player-photo{position:absolute;inset:0;width:34px;height:34px;object-fit:cover;object-position:top center}.player-initials{width:34px;height:34px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:.62rem;font-weight:800;background:rgba(128,128,128,.28);color:inherit;flex-shrink:0;opacity:.8;letter-spacing:-.02em}
.clubs-block{display:flex;align-items:center;gap:5px;flex-shrink:0}
.club-logo-wrap{width:36px;height:36px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.club-crest{width:36px;height:36px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-size:.48rem;font-weight:800;letter-spacing:-.02em;line-height:1;text-transform:uppercase}
.club-logo-img{width:36px;height:36px;object-fit:contain;border-radius:5px}
.clubs-sep{font-size:11px;color:inherit;opacity:.55;line-height:1}
.tc-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.tc-player{font-size:.86rem;font-weight:700;color:inherit;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.25}
.tc-pos{font-size:.67rem;color:inherit;opacity:.72;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-fee{font-size:.66rem;color:inherit;opacity:.65;font-variant-numeric:tabular-nums}
.nego-badge{display:inline-flex;align-items:center;gap:3px;padding:3px 8px;border-radius:20px;font-size:.63rem;font-weight:700;white-space:nowrap;flex-shrink:0}
.nego-badge-sm{font-size:.54rem;padding:2px 6px}
.tc-badge-wrap{flex-shrink:0}
.tc-badge-exp{padding:8px 16px 4px 18px}
/* Expand button */
.expand-btn{flex-shrink:0;padding:4px 10px;border-radius:20px;background:rgba(128,128,128,.22);border:none;color:inherit;cursor:pointer;font-size:.64rem;font-weight:600;white-space:nowrap;opacity:.82;transition:opacity .12s}
.expand-btn:hover{opacity:1}
.expand-btn.open{opacity:1}
/* Timeline */
.tc-timeline{border-top:1px solid rgba(128,128,128,.18)}
.tl-inner{padding:8px 16px 12px 18px;display:flex;flex-direction:column;gap:0}
.tl-entry{display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:1px solid rgba(128,128,128,.12)}
.tl-entry:last-child{border-bottom:none}
.tl-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;margin-top:5px}
.tl-date{font-size:.63rem;opacity:.6;flex-shrink:0;min-width:32px;font-variant-numeric:tabular-nums;margin-top:2px}
.tl-src{font-size:.63rem;opacity:.75;flex-shrink:0;white-space:nowrap;margin-top:2px}
.tl-title{flex:1;font-size:.72rem;color:inherit;opacity:.88;text-decoration:none;min-width:0;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tl-title:hover{opacity:1;text-decoration:underline}
/* Misc */
.tc-dim{opacity:.5}
.tc-dim .tc-player{font-style:italic}
.empty{text-align:center;padding:60px 16px;color:var(--muted)}
.empty-icon{font-size:2.4rem;display:block;margin-bottom:8px}
@media(max-width:600px){
  .tc-rank{display:none}
  .tc-pos,.tc-fee{display:none}
  .tl-src{display:none}
}
@media(max-width:400px){
  .tc-badge-exp{padding:6px 12px 2px 14px}
}
"""

    JS = """
(function(){
  // ── Club logos async load ────────────────────────────────────────────
  (function(){
    var done={};
    var items=[];
    document.querySelectorAll('.club-logo-wrap[data-club]').forEach(function(w){
      var enc=w.dataset.club;
      if(!enc||done[enc])return;
      done[enc]=true;
      items.push(enc);
    });
    // Escalonar requests: 1 por vez a cada 300ms para evitar rate limit
    items.forEach(function(enc,i){
      setTimeout(function(){
        var img=new Image();img.decoding='async';
        img.onload=function(){
          document.querySelectorAll('.club-logo-wrap[data-club="'+enc+'"]').forEach(function(w2){
            var i2=new Image();i2.className='club-logo-img';i2.src=img.src;
            i2.alt=decodeURIComponent(enc.replace(/[+]/g,' '));
            w2.innerHTML='';w2.appendChild(i2);
          });
        };
        img.src='/api/club-logo?name='+enc;
      }, i*300);
    });
  })();

  // ── Timeline toggle ──────────────────────────────────────────────────
  window.toggleTl=function(btn){
    var tl=btn.closest('.tc').querySelector('.tc-timeline');
    var hidden=tl.hidden;
    tl.hidden=!hidden;
    btn.textContent=hidden?btn.dataset.exp:btn.dataset.col;
    btn.classList.toggle('open',hidden);
  };

  // ── Filter buttons ───────────────────────────────────────────────────
  document.querySelectorAll('.filter-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      var type=this.dataset.type;
      if(type==='all'){
        document.querySelectorAll('.filter-btn').forEach(function(b){b.classList.remove('active')});
        this.classList.add('active');
        document.querySelectorAll('.tc').forEach(function(c){c.style.display=''});
      } else {
        document.querySelectorAll('.filter-btn[data-type="all"]').forEach(function(b){b.classList.remove('active')});
        this.classList.toggle('active');
        var active=Array.from(document.querySelectorAll('.filter-btn.active')).map(function(b){return b.dataset.type});
        if(active.length===0){
          document.querySelectorAll('.filter-btn[data-type="all"]').forEach(function(b){b.classList.add('active')});
          document.querySelectorAll('.tc').forEach(function(c){c.style.display=''});
        } else {
          document.querySelectorAll('.tc[data-type]').forEach(function(c){
            c.style.display=active.indexOf(c.dataset.type)>-1?'':'none';
          });
        }
      }
    });
  });

  // ── Reprocessar ──────────────────────────────────────────────────────
  window.rebuild=async function(btn){
    var orig=btn.textContent;btn.textContent='⏳ Processando...';btn.disabled=true;
    try{
      var r=await fetch('/api/transfers/rebuild',{method:'POST'});
      var d=await r.json();
      btn.textContent='✅ '+d.classified+' classificados';
      setTimeout(function(){location.reload()},1400);
    }catch(e){
      btn.textContent='❌ Erro';
      setTimeout(function(){btn.textContent=orig;btn.disabled=false},2000);
    }
  };
})();
"""

    html = (
        "<!DOCTYPE html>\n<html lang=\"pt-BR\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>🔄 Transferências – Saudi Monitor</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n<div class=\"page\">\n"
        "<div class=\"hdr\">\n"
        "  <div>\n"
        "    <h1>🔄 Transferências</h1>\n"
        f"    <div class=\"hdr-sub\">{subtitle}</div>\n"
        "  </div>\n"
        "  <div class=\"hdr-actions\">\n"
        "    <button class=\"btn btn-primary\" onclick=\"rebuild(this)\">⟳ Reprocessar</button>\n"
        "    <a class=\"btn btn-sec\" href=\"/\">← Início</a>\n"
        "  </div>\n"
        "</div>\n"
        "<div class=\"filters\">\n"
        "  <button class=\"filter-btn active\" data-type=\"all\">Todos</button>\n"
        f"  {filter_btns}"
        "</div>\n"
        f"<div id=\"tc-list\">\n{cards_html}\n</div>\n"
        "</div>\n"
        f"<script>{JS}</script>\n"
        "</body></html>"
    )
    return HTMLResponse(html)


@app.get("/api/transfers")
async def api_transfers():
    return get_transfer_articles()


@app.post("/api/transfers/rebuild")
async def api_transfers_rebuild():
    from transfer_processor import rebuild_transfers_from_history
    result = await rebuild_transfers_from_history()
    return result


def _logo_norm(s: str) -> str:
    """Normalização agressiva para cache de logos: minúsculo, sem acento, hífen→espaço."""
    import unicodedata as _ud, re as _re
    s = (s or "").lower().strip()
    s = _re.sub(r"[-_]+", " ", s)          # Al-Hilal → al hilal
    s = _re.sub(r"\s+", " ", s).strip()
    nfd = _ud.normalize("NFD", s)
    return "".join(c for c in nfd if _ud.category(c) != "Mn")


@app.get("/api/admin/debug-logo")
async def api_debug_logo(name: str):
    """Mostra o que a TheSportsDB retorna para um nome de clube (debug)."""
    lines = [f"Buscando: {name!r}", ""]
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            "https://www.thesportsdb.com/api/v1/json/3/searchteams.php",
            params={"t": name}
        )
        teams = (r.json().get("teams") or [])
        lines.append(f"TheSportsDB retornou {len(teams)} time(s):")
        for i, t in enumerate(teams):
            lines.append(
                f"  [{i}] {t.get('strTeam')} | country={t.get('strCountry')} "
                f"| league={t.get('strLeague')} | badge={str(t.get('strTeamBadge',''))[:60]}"
            )
        lines.append("")
        # Also try league search
        for league in ["Saudi Pro League", "Saudi Professional League"]:
            r2 = await client.get(
                "https://www.thesportsdb.com/api/v1/json/3/search_all_teams.php",
                params={"l": league}
            )
            lt = r2.json().get("teams") or []
            lines.append(f"League '{league}' → {len(lt)} times")
    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")


@app.get("/api/admin/warm-logos")
async def api_warm_logos():
    """Pré-popula cache com logos da Saudi Pro League via Transfermarkt (SA1)."""
    from urllib.parse import quote as _quote
    results = {}
    errors  = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            r = await client.get(
                "https://transfermarkt-api.fly.dev/competitions/SA1/clubs",
                params={"season_id": "2025"},
            )
            clubs = (r.json().get("clubs") or [])
            for club in clubs:
                cid  = club.get("id")
                name = club.get("name") or ""
                if cid and name:
                    nn   = _logo_norm(name)
                    logo = f"https://tmssl.akamaized.net//images/wappen/big/{cid}.png"
                    set_club_logo(nn, logo)
                    results[name] = (nn, logo)
        except Exception as e:
            errors.append(f"SA1: {e}")
    lines = [f"✅ {len(results)} times da SPL cacheados"]
    for raw, (nn, logo) in results.items():
        lines.append(f"  '{raw}' → key='{nn}' | {logo}")
    if errors:
        lines += ["", "⚠️ Erros:"] + errors
    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")


@app.get("/api/admin/debug-logo")
async def api_debug_logo(name: str):
    """Debug: mostra o que Transfermarkt retorna para um nome de clube."""
    from urllib.parse import quote as _quote
    lines = [f"Buscando: {name!r}", ""]
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            f"https://transfermarkt-api.fly.dev/clubs/search/{_quote(name)}"
        )
        results = r.json().get("results") or []
        lines.append(f"Transfermarkt retornou {len(results)} clube(s):")
        for i, c in enumerate(results[:5]):
            lines.append(
                f"  [{i}] id={c.get('id')} | {c.get('name')} | country={c.get('country')} "
                f"| logo=https://tmssl.akamaized.net//images/wappen/big/{c.get('id')}.png"
            )
    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")


@app.get("/api/admin/clear-logos")
async def api_clear_logo_cache(name: str | None = None):
    """Limpa cache de logos. Sem ?name → limpa tudo."""
    from database import get_conn
    with get_conn() as conn:
        c = conn.cursor()
        if name:
            nn = _logo_norm(name)
            c.execute("DELETE FROM club_logos WHERE name_norm = %s", (nn,))
            return HTMLResponse(f"<pre>✅ Deletado {c.rowcount} entrada(s) para '{name}'</pre>")
        else:
            c.execute("DELETE FROM club_logos")
            return HTMLResponse(f"<pre>✅ Cache limpo — {c.rowcount} entradas removidas</pre>")


@app.get("/api/admin/debug-names")
async def api_debug_names(q: str | None = None):
    """Inspeciona player_name_cache. ?q=nome faz lookup ao vivo no Transfermarkt."""
    from database import get_conn, get_player_name_cache
    from urllib.parse import quote as _quote
    import unicodedata as _ud, re as _re

    def _nkey(s: str) -> str:
        s = (s or "").strip().lower()
        nfd = _ud.normalize("NFD", s)
        s = "".join(c for c in nfd if _ud.category(c) != "Mn")
        return _re.sub(r"\s+", " ", _re.sub(r"[^\w\s]", "", s)).strip()

    lines = []

    if q:
        # Lookup ao vivo no Transfermarkt
        key = _nkey(q)
        lines.append(f"Query original : {q}")
        lines.append(f"Cache key      : {key}")
        cached = get_player_name_cache(key)
        lines.append(f"Cache atual    : {cached!r}")
        lines.append("")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"https://transfermarkt-api.fly.dev/players/search/{_quote(q)}"
                )
                lines.append(f"TM status: {r.status_code}")
                data = r.json()
                results = data.get("results") or []
                lines.append(f"TM resultados: {len(results)}")
                for i, p in enumerate(results[:5]):
                    club = (p.get("club") or {}).get("name", "?")
                    lines.append(f"  [{i}] {p.get('name')!r}  id={p.get('id')}  clube={club!r}")
        except Exception as e:
            lines.append(f"Erro TM: {e}")
    else:
        # Lista entradas do cache
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT name_query, tm_name, tm_id, fetched_at FROM player_name_cache "
                    "ORDER BY fetched_at DESC LIMIT 50"
                )
                rows = c.fetchall()
                lines.append(f"player_name_cache — {len(rows)} entradas recentes:")
                lines.append("")
                for r in rows:
                    found = r[1] or "(não encontrado)"
                    lines.append(f"{r[0]!r:40s}  →  {found!r}  (id={r[2]})")
        except Exception as e:
            lines.append(f"Erro ao ler cache: {e}")

    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")


# ──────────────────────────────────────────────────────────────────────────────
#  API-FOOTBALL  (v3.football.api-sports.io)
# ──────────────────────────────────────────────────────────────────────────────
def _af_headers() -> dict:
    key = os.getenv("API_FOOTBALL_KEY", "")
    return {"X-Apisports-Key": key} if key else {}

AF_BASE         = "https://v3.football.api-sports.io"
AF_SAUDI_LEAGUE = "307"
AF_SEASON       = "2025"  # api-football usa ano de início da temporada


@app.get("/api/admin/clear-photos")
async def api_clear_photo_cache():
    from database import get_conn
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM player_photos")
        n = c.rowcount
    return HTMLResponse(f"<pre>✅ Cache de fotos limpo — {n} entradas removidas</pre>")


@app.post("/api/admin/fix-article")
async def admin_fix_article(request: Request):
    """Força reprocessamento de um artigo específico por ID."""
    from processor import call_claude
    from glossary import GLOSSARY_PROMPT, apply_glossary
    from database import update_article_body, update_article_title, update_article_meta
    from collector import compute_relevance
    import json as _json

    body = await request.json()
    article_id = body.get("id")
    if not article_id:
        return JSONResponse({"error": "Campo 'id' obrigatório"}, status_code=400)

    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
        row = c.fetchone()

    if not row:
        return JSONResponse({"error": "Artigo não encontrado"}, status_code=404)

    a = dict(row)
    system = (
        "Você é um redator esportivo brasileiro especializado na Saudi Pro League. "
        "Adapte o texto para o português brasileiro com estilo jornalístico natural. "
        f"{GLOSSARY_PROMPT}"
    )
    prompt = (
        "Traduza o artigo abaixo para português brasileiro.\n"
        'Responda SOMENTE com JSON: {"translations": [{"title_pt": "...", "body_pt": "...", "category": "..."}]}\n'
        "Categorias: transferencia, resultado, lesao, geral\n\n"
        f"ARTIGO 1:\nTítulo: {a.get('title_orig','')}\nTexto: {a.get('body_orig','')[:1200]}\n---"
    )
    try:
        async with httpx.AsyncClient() as client:
            raw = await call_claude(system=system, prompt=prompt, max_tokens=500, client=client)
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
        translations = _json.loads(raw).get("translations", [])
        if not translations:
            return JSONResponse({"error": "Claude não retornou traduções", "raw": raw}, status_code=500)
        t = translations[0]
        title_pt = apply_glossary(t.get("title_pt") or a["title_orig"])
        body_pt  = apply_glossary(t.get("body_pt")  or a.get("body_orig", ""))
        category = t.get("category") or None
        new_score = compute_relevance(
            f"{a.get('title_orig', '')} {a.get('body_orig', '')}",
            a.get("source_tier", "C")
        )
        update_article_title(article_id, title_pt)
        update_article_body(article_id, a.get("body_orig", ""), body_pt)
        update_article_meta(article_id, category=category, relevance_score=new_score)
        return JSONResponse({"ok": True, "category": category, "relevance_score": new_score, "title_pt": title_pt[:80]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/admin/test-af")
async def api_test_af():
    """Diagnóstico: testa conexão com api-football e busca Mohamed Salah."""
    import unicodedata as _ud
    key = os.getenv("API_FOOTBALL_KEY", "")
    lines = []
    if not key:
        lines.append("❌ API_FOOTBALL_KEY NÃO CONFIGURADO no Railway")
        return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    lines.append(f"✅ Chave encontrada: {masked} (len={len(key)})")
    hdrs = {"X-Apisports-Key": key}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=hdrs) as client:
            # 1. Status da conta
            r_status = await client.get(f"{AF_BASE}/status")
            status_json = r_status.json()
            acct = status_json.get("response") or {}
            lines.append(f"Conta: {acct.get('account', {}).get('email','?')}")
            lines.append(f"Plano: {acct.get('subscription', {}).get('plan','?')}")
            requests_info = acct.get('requests', {})
            lines.append(f"Requests: {requests_info.get('current','?')} / {requests_info.get('limit_day','?')} hoje")
            errors = status_json.get("errors") or {}
            if errors:
                lines.append(f"⚠️ Erros API: {errors}")

            # 2. Busca Mohamed Salah (deve sempre ter resultado)
            r_salah = await client.get(f"{AF_BASE}/players",
                params={"search": "Mohamed Salah", "season": "2024"})
            salah_json = r_salah.json()
            salah_results = salah_json.get("response") or []
            lines.append(f"\nBusca 'Mohamed Salah' (2024): {len(salah_results)} resultado(s)")
            if salah_results:
                p = salah_results[0].get("player", {})
                lines.append(f"  → {p.get('name')} | foto: {p.get('photo','')[:60]}")
            else:
                lines.append(f"  → Sem resultados. Erros: {salah_json.get('errors')}")
                lines.append(f"  → Paging: {salah_json.get('paging')}")
                lines.append(f"  → HTTP status: {r_salah.status_code}")
    except Exception as e:
        lines.append(f"❌ Exceção: {type(e).__name__}: {e}")
    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")



@app.get("/api/admin/warm-saudi-teams")
async def api_warm_saudi_teams():
    hdrs = _af_headers()
    if not hdrs:
        return HTMLResponse("<pre>❌ API_FOOTBALL_KEY não configurado</pre>")
    lines = []
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=hdrs) as client:
            teams = []
            for _s in ("2025", "2024", "2023"):
                r = await client.get(
                    f"{AF_BASE}/teams",
                    params={"league": AF_SAUDI_LEAGUE, "season": _s},
                )
                teams = r.json().get("response") or []
                if teams:
                    lines.append(f"Season: {_s} ({len(teams)} times)")
                    break
        for t in teams:
            team = t.get("team") or {}
            tname = team.get("name") or ""
            logo  = team.get("logo") or ""
            if tname and logo:
                nn = _logo_norm(tname)
                set_club_logo(nn, logo)
                lines.append(f"{nn}: {logo}")
                # Também armazena nome curto sem sufixos de país/tipo
                import re as _re2
                nn_short = _re2.sub(
                    r"\b(saudi fc|saudi sc|fc|sc|cf|united|city|club|football|sporting)\b",
                    "", nn
                ).strip()
                if nn_short and nn_short != nn:
                    set_club_logo(nn_short, logo)
                    lines.append(f"  alias: {nn_short}")
        return HTMLResponse(
            f"<pre>✅ {len(teams)} times cacheados\n" + "\n".join(lines) + "</pre>"
        )
    except Exception as e:
        return HTMLResponse(f"<pre>❌ Erro: {e}</pre>")



@app.get("/api/admin/set-player-af-id")
async def admin_set_player_af_id_get(
    player_name: str = "",
    af_player_id: str = "",
):
    """GET para uso no browser: /api/admin/set-player-af-id?player_name=Lajami&af_player_id=43940"""
    player_name  = player_name.strip()
    af_player_id = af_player_id.strip()
    if not player_name and not af_player_id:
        # Sem params: retorna formulário HTML
        return HTMLResponse("""
<html><body style="font-family:monospace;padding:24px">
<h2>Set Player AF ID</h2>
<form method="get">
  <label>Player name (partial): <input name="player_name" size="30"></label><br><br>
  <label>AF Player ID:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <input name="af_player_id" size="12"></label><br><br>
  <button type="submit">Set ID</button>
</form>
</body></html>""")
    if not player_name or not af_player_id:
        return HTMLResponse("<pre>❌ player_name e af_player_id são obrigatórios</pre>", status_code=400)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE transfer_meta SET af_player_id = %s WHERE player_name ILIKE %s",
            (af_player_id, f"%{player_name}%")
        )
        n = c.rowcount
    from database import set_player_photo
    import unicodedata as _ud2
    nfd = _ud2.normalize("NFD", player_name.lower())
    name_norm = "".join(ch for ch in nfd if _ud2.category(ch) != "Mn")
    set_player_photo(name_norm, f"https://media.api-sports.io/football/players/{af_player_id}.png")
    return HTMLResponse(f"<pre>✅ {n} registro(s) de '{player_name}' → af_player_id={af_player_id}</pre>")


@app.post("/api/admin/set-player-af-id")
async def admin_set_player_af_id(request: Request):
    """Define manualmente o af_player_id para todos os registros de um jogador.
    Body: {"player_name": "Qasim Lajami", "af_player_id": "43940"}
    """
    body = await request.json()
    player_name  = (body.get("player_name") or "").strip()
    af_player_id = str(body.get("af_player_id") or "").strip()
    if not player_name or not af_player_id:
        return JSONResponse({"error": "player_name e af_player_id são obrigatórios"}, status_code=400)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE transfer_meta SET af_player_id = %s WHERE player_name ILIKE %s",
            (af_player_id, f"%{player_name}%")
        )
        n = c.rowcount
    # Limpa cache de foto para forçar reload com novo ID
    from database import set_player_photo
    import unicodedata as _ud2
    nfd = _ud2.normalize("NFD", player_name.lower())
    name_norm = "".join(c for c in nfd if _ud2.category(c) != "Mn")
    set_player_photo(name_norm, f"https://media.api-sports.io/football/players/{af_player_id}.png")
    return JSONResponse({"ok": True, "updated": n, "player_name": player_name, "af_player_id": af_player_id})


@app.get("/api/admin/backfill-af-ids")
async def api_backfill_af_ids(limit: int = 200, dry_run: str = ""):
    """Backfill af_player_id / af_team_from_id / af_team_to_id para transfer_meta
    existentes que foram criados antes do plano Pro (ficaram com IDs nulos).

    Parâmetros:
      limit   — máximo de registros a processar (padrão 200)
      dry_run — qualquer valor ativa modo somente-leitura (mostra o que seria feito)
    """
    from database import get_transfers_missing_af_ids, update_transfer_af_ids
    from transfer_processor import enrich_with_af_ids

    hdrs = _af_headers()
    if not hdrs:
        return HTMLResponse("<pre>❌ API_FOOTBALL_KEY não configurado</pre>")

    rows = get_transfers_missing_af_ids()
    rows = rows[:limit]
    lines = [f"📋 {len(rows)} registros sem af_ids (limit={limit}, dry_run={'sim' if dry_run else 'não'})"]
    updated = skipped = already = 0

    async with httpx.AsyncClient(timeout=12.0, headers=hdrs) as client:
        for row in rows:
            aid = row["article_id"]
            before = {
                "af_player_id":    row.get("af_player_id"),
                "af_team_from_id": row.get("af_team_from_id"),
                "af_team_to_id":   row.get("af_team_to_id"),
            }
            # Só busca se ainda há algum campo null
            if all(before[k] for k in before):
                already += 1
                continue

            data = {
                "player_name":  row.get("player_name") or "",
                "club_from":    row.get("club_from") or "",
                "club_to":      row.get("club_to") or "",
                "af_player_id":    row.get("af_player_id"),
                "af_team_from_id": row.get("af_team_from_id"),
                "af_team_to_id":   row.get("af_team_to_id"),
            }
            try:
                enriched = await enrich_with_af_ids(data, client)
            except Exception as e:
                lines.append(f"  ❌ {aid[:12]} erro: {e}")
                skipped += 1
                continue

            new_pid  = enriched.get("af_player_id")
            new_fid  = enriched.get("af_team_from_id")
            new_tid  = enriched.get("af_team_to_id")
            changed = (
                (new_pid  and not before["af_player_id"])  or
                (new_fid  and not before["af_team_from_id"]) or
                (new_tid  and not before["af_team_to_id"])
            )
            if changed:
                if not dry_run:
                    update_transfer_af_ids(aid, new_pid, new_fid, new_tid)
                label = "✅" if not dry_run else "🔍(dry)"
                lines.append(
                    f"  {label} {aid[:12]} | {data['player_name']} | "
                    f"player={new_pid} from={new_fid} to={new_tid}"
                )
                updated += 1
            else:
                skipped += 1

    lines.append(f"\n✅ Concluído: {updated} atualizados, {skipped} sem dados, {already} já tinham ids")
    return HTMLResponse("<pre>" + "\n".join(lines) + "</pre>")


@app.get("/api/club-logo")
async def api_club_logo(name: str):
    name_norm = _logo_norm(name)
    cached = get_club_logo(name_norm)
    if cached is None:
        logo_url = ""
        hdrs = _af_headers()
        if hdrs:
            try:
                import unicodedata as _ud2
                def _af_n(s):
                    nfd = _ud2.normalize("NFD", (s or "").strip())
                    return "".join(c for c in nfd if _ud2.category(c) != "Mn").lower()
                async with httpx.AsyncClient(timeout=7.0, headers=hdrs) as client:
                    r = await client.get(
                        f"{AF_BASE}/teams",
                        params={"search": _af_n(name)},
                    )
                    results = r.json().get("response") or []
                    if results:
                        saudi  = [t for t in results if (t.get("team") or {}).get("country") == "Saudi Arabia"]
                        name_l = _af_n(name)
                        exact  = [t for t in results if _af_n((t.get("team") or {}).get("name","")) == name_l]
                        chosen = (exact[0] if exact else (saudi[0] if saudi else results[0])).get("team") or {}
                        logo_url = chosen.get("logo") or ""
            except Exception as e:
                print(f"api-football logo error for '{name}': {e}")
        # Só cacheia se encontrou logo real — falhas serão retentadas na próxima carga
        if logo_url:
            set_club_logo(name_norm, logo_url)
            cached = logo_url
    if not cached:
        return Response(status_code=404)
    return RedirectResponse(cached, status_code=302)


@app.get("/api/player-photo")
async def api_player_photo(name: str, debug: str = ""):
    import unicodedata as _ud
    nfd = _ud.normalize("NFD", name.lower().strip())
    name_norm = "".join(c for c in nfd if _ud.category(c) != "Mn")
    cached = get_player_photo(name_norm)
    if cached is not None and not debug:
        if not cached:
            return Response(status_code=404)
        return RedirectResponse(cached, status_code=302)
    photo_url = ""
    debug_lines = [f"name={name!r}  name_norm={name_norm!r}"]
    hdrs = _af_headers()
    if not hdrs:
        if debug:
            return HTMLResponse("<pre>❌ API_FOOTBALL_KEY não configurado</pre>")
        return Response(status_code=404)
    try:
        import unicodedata as _ud3
        def _af_name(s):
            nfd2 = _ud3.normalize("NFD", (s or "").strip())
            return "".join(c for c in nfd2 if _ud3.category(c) != "Mn")
        search_name = _af_name(name)
        debug_lines.append(f"search_name={search_name!r}")
        async with httpx.AsyncClient(timeout=10.0, headers=hdrs) as client:
            results = []
            last_raw = {}
            # Pro plan: sem restrição de liga — tenta temporadas 2025/2024/2023
            for _season in ("2025", "2024", "2023"):
                r = await client.get(
                    f"{AF_BASE}/players",
                    params={"search": search_name, "season": _season},
                )
                last_raw = r.json()
                results = last_raw.get("response") or []
                debug_lines.append(
                    f"season={_season} (sem league) → HTTP {r.status_code}  "
                    f"results={len(results)}  "
                    f"errors={last_raw.get('errors')}  "
                    f"paging={last_raw.get('paging')}"
                )
                if results:
                    break
            if results:
                p = results[0].get("player") or {}
                photo_url = p.get("photo") or ""
                debug_lines.append(f"✅ player={p.get('name')}  photo={photo_url}")
            else:
                debug_lines.append("❌ Nenhum resultado em nenhuma temporada")
    except Exception as e:
        debug_lines.append(f"❌ Exceção: {type(e).__name__}: {e}")
    if debug:
        return HTMLResponse("<pre>" + "\n".join(debug_lines) + "</pre>")
    # Só cacheia se encontrou foto real
    if photo_url:
        set_player_photo(name_norm, photo_url)
    if not photo_url:
        return Response(status_code=404)
    return RedirectResponse(photo_url, status_code=302)
