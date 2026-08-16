"""
Saudi Football Monitor — FastAPI app principal.
"""
import os
import re
import asyncio
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx
from database import init_db, get_recent_articles, get_low_score_articles, get_collection_logs, set_flag, get_all_flags, get_trashed_articles, get_flagged_articles, cleanup_old_trash, get_conn, get_state, set_state, get_token_status, set_token_status, get_injuries, get_window_transfers, get_window_transfers_last_scraped, upsert_window_transfers
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
    # Clube da SPL no título = notícia de clube, não de seleção, mesmo que o corpo
    # mencione "seleção saudita" como descrição da nacionalidade de um jogador.
    # Ex: "Al Ittihad avança por jogador da seleção saudita" → transferência, não seleção.
    title = f"{a.get('title_pt') or ''} {a.get('title_orig') or ''}".lower().replace("-", " ").replace("_", " ")
    title_has_spl_club = any(club in title for club in SPL_CLUB_NAMES_LOWER)
    if any(kw.lower() in tl for kw in SELECAO_KEYWORDS):
        if title_has_spl_club:
            return False  # clube no título prevalece: é notícia de transferência/clube
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
_ICO_ANALISE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>'
_ICO_NUMEROS = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>'
_ICO_INJURY  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>'
_ICO_JANELA  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16V4m0 0L3 8m4-4 4 4"/><path d="M17 8v12m0 0 4-4m-4 4-4-4"/></svg>'

_THEME_VARS_CSS = (
    "    :root { --c-bg:#edeae4; --c-bg-card:#fafaf8; --c-bg-soft:#fff; --c-text:#1a1a1a; --c-muted-1:#999; --c-muted-2:#aaa; --c-muted-3:#777; --c-muted-4:#555; --c-muted-5:#666; --c-muted-6:#444; --c-line:#ccc; --c-border:rgba(0,0,0,.1); --c-border-2:rgba(0,0,0,.18); --c-hover-tint:rgba(0,0,0,.04); --c-success:#166534; --c-error:#be123c; }\n"
    "    :root[data-theme=\"dark\"] { --c-bg:#16161a; --c-bg-card:#1e1e22; --c-bg-soft:#242428; --c-text:#ededee; --c-muted-1:#8c8c93; --c-muted-2:#84848a; --c-muted-3:#9c9ca2; --c-muted-4:#c2c0c7; --c-muted-5:#b0aeb5; --c-muted-6:#d4d2d8; --c-line:#3a3a40; --c-border:rgba(255,255,255,.1); --c-border-2:rgba(255,255,255,.2); --c-hover-tint:rgba(255,255,255,.06); --c-success:#4ade80; --c-error:#fb7185; }\n"
)

_HEADER_CSS = _THEME_VARS_CSS + (
    "    header { background: var(--c-bg); border-bottom: 1px solid var(--c-border); padding: 10px 16px; display: flex; align-items: center; position: sticky; top: 0; z-index: 10; gap: 6px; }\n"
    "    .brand { font-family: \'Bebas Neue\', sans-serif; font-size: 2rem; letter-spacing: 0.06em; color: var(--c-text); text-decoration: none; margin-right: auto; line-height: 1; }\n"
    "    .nav-icon { width: 32px; height: 32px; border-radius: 8px; border: none; background: none; color: var(--c-muted-3); cursor: pointer; display: flex; align-items: center; justify-content: center; text-decoration: none; transition: background .15s, color .15s; flex-shrink: 0; position: relative; }\n"
    "    .nav-icon:hover { background: var(--c-hover-tint); color: var(--c-text); }\n"
    "    .nav-icon.active { background: var(--c-hover-tint); color: var(--c-text); }\n"
    "    .nav-icon.cta { background: var(--c-text); color: var(--c-bg); border-radius: 8px; }\n"
    "    .nav-icon.cta:hover { background: var(--c-muted-6); }\n"
    "    .nav-icon.selecao { background: #15803d; color: white; }\n"
    "    .nav-icon.selecao:hover { background: #166534; }\n"
    "    .nav-icon.selecao.active { background: #14532d; }\n"
    "    .nav-icon[title]:hover::after { content: attr(title); position: absolute; bottom: -28px; left: 50%; transform: translateX(-50%); background: var(--c-text); color: var(--c-bg); font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 8px; border-radius: 6px; white-space: nowrap; pointer-events: none; z-index: 100; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', sans-serif; }\n"
    "    .nav-badge { position: absolute; top: -4px; right: -4px; background: #ef4444; color: white; font-size: 0.48rem; font-weight: 800; min-width: 14px; height: 14px; border-radius: 99px; display: none; align-items: center; justify-content: center; padding: 0 3px; line-height: 1; border: 1.5px solid var(--c-bg); }\n"
    "    .theme-toggle .ico-sun { display: none; }\n"
    "    :root[data-theme=\"dark\"] .theme-toggle .ico-moon { display: none; }\n"
    "    :root[data-theme=\"dark\"] .theme-toggle .ico-sun { display: block; }\n"
    "    .token-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--c-muted-2); margin-right: 8px; flex-shrink: 0; cursor: default; }\n"
    "    .token-dot.ok { background: #22c55e; }\n"
    "    .token-dot.broken { background: #ef4444; }\n"
)

_THEME_INIT_SCRIPT = '<script>document.documentElement.setAttribute("data-theme","dark");</script>'

def _header(active: str) -> str:
    pages = [
        ("/",            _ICO_HOME,    "Home",        "home", "#16a34a"),
        ("/descartadas", _ICO_ARCHIVE, "Descartadas", "",     "#6366f1"),
        ("/lesoes",      _ICO_INJURY,  "Lesões",      "",     "#ef4444"),
        ("/janela",      _ICO_JANELA,  "Janela",      "",     "#3b82f6"),
        ("/fontes",      _ICO_SOURCES, "Fontes",      "",     "#a855f7"),
        ("/lixeira",     _ICO_TRASH2,  "Lixeira",     "",     "#f97316"),
        ("/analise",     _ICO_ANALISE, "Análise",     "",     "#d97706"),
        ("/numeros",     _ICO_NUMEROS, "Números",     "",     "#0ea5e9"),
    ]
    items = ""
    for href, ico, label, badge_tab, color in pages:
        cls = "nav-icon"
        style = ""
        if href == active:
            cls += " active"
            style = f'style="color:{color};background:color-mix(in srgb,{color} 14%,transparent)"' 
        badge = f'<span class="nav-badge" data-tab="{badge_tab}" style="display:none"></span>' if badge_tab else ""
        items += f'<a class="{cls}" {style} href="{href}" title="{label}">{ico}{badge}</a>'
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
    theme_script = ""  # dark-only
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
    return f'<header>{token_dot}<a class="brand" href="/">IARABÃO</a>{items}</header>{badge_script}{theme_script}{token_script}'



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
        "mercado":       ("🔀", "#dbeafe", "#1d4ed8"),
        "financas":      ("💰", "#fdf4ff", "#7e22ce"),
        "entrevista":    ("🎙️", "#fef3c7", "#b45309"),
        "competicao":    ("🏆", "#fef9c3", "#a16207"),
        "treino":        ("🏋️", "#f0fdf4", "#166534"),
        "lesao":         ("🩺", "#fff1f2", "#be123c"),
        "geral":         ("📰", "#f1f5f9", "#475569"),
    }

    CATEGORY_TEXT = {
        "mercado": "Mercado",      "financas": "Finanças",
        "competicao": "Competição","entrevista": "Entrevista",
        "lesao": "Lesão",          "treino": "Treino",
        "geral": "Geral",
    }
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    ICO_COPY    = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    ICO_WAND    = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h.01"/><path d="M17.8 6.2 19 5"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/></svg>'
    ICO_ANALYSIS = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>'
    ICO_LOCK  = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
    ICO_CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    ICO_TRASH = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>'
    ICO_PEN   = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'

    cards = ""
    for a in articles:
        handle        = a.get("source_name", "").lstrip("@")
        moon          = SOURCE_MOON.get(handle, {"A": "🌕", "B": "🌖", "C": "🌗"}.get(a["source_tier"], ""))
        body_raw      = a.get("body_pt") or a.get("body_orig") or ""
        body_full     = body_raw
        category      = a.get("category") or "geral"
        category_text = CATEGORY_TEXT.get(category, "Geral")
        cat_emoji     = CATEGORY_EMOJI.get(category, ("📰", "", ""))[0]
        copy_text     = body_raw + "\n\n🗞️ @" + handle + " " + moon
        copy_safe     = copy_text.replace("&", "&amp;").replace('"', "&quot;")
        post_text_full = copy_text
        post_base     = f"/gerador?texto={quote(post_text_full)}&source={quote(handle)}&moon={quote(moon)}&translated=1"
        news_safe     = body_raw.replace("&", "&amp;").replace('"', "&quot;")
        art_id        = a['id']
        article_url   = (a.get('url') or '#').replace('"', '&quot;')
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
        <div class="card" data-id="{art_id}" data-category="{category}">
          <div class="card-body">
            <div class="card-top">
              <div class="card-meta">
                <img class="author-avatar" src="https://unavatar.io/twitter/{handle}" alt="@{handle}" onerror="this.style.display='none'">
                <span class="tag">@{handle}</span>
                <span class="tag">{moon}</span>
                <span class="card-date">{date_display}</span>
              </div>
              <span class="cat-badge cat-{category}">{cat_emoji} {category_text}</span>
            </div>
            <p class="card-text" data-url="{article_url}" onclick="if(!window._dragHappened&&this.dataset.url&&this.dataset.url!='#')window.open(this.dataset.url,'_blank')" style="cursor:pointer">{body_full}</p>
            <div class="card-bottom">
              <button class="flag-circle anal-btn"  onclick="toggleFlag('{art_id}','analise')"    title="Análise">{ICO_ANALYSIS}</button>
              <button class="flag-circle copy-btn" data-copy="{copy_safe}" onclick="copyFromBtn(this)" title="Copiar">{ICO_COPY}</button>
              <button class="flag-circle wand-btn" data-news="{news_safe}" data-source="{handle}" data-moon="{moon}" data-category="{category}" onclick="gerarTexto(this)" title="Gerar post">{ICO_WAND}</button>
              <button class="flag-circle desc-btn"  onclick="toggleFlag('{art_id}','descartado')" title="Lixeira">{ICO_TRASH}</button>
              <button class="flag-circle pub-btn"   onclick="toggleFlag('{art_id}','publicado')"  title="Publicado">{ICO_CHECK}</button>
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
    .card.flag-analise   {{ display: none; }}
    .card.flag-visto     {{ background: #ede9fe; }}
    .card.flag-publicado {{ background: #dcfce7; }}
    .card.flag-visto, .card.flag-publicado {{
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card.flag-descarte  {{ display: none; }}
    .card.hidden-by-cat  {{ display: none !important; }}
    .cat-filters {{ display:flex; gap:6px; padding:6px 24px 10px; overflow-x:auto; scrollbar-width:none; }}
    .cat-filters::-webkit-scrollbar {{ display:none; }}
    .cat-filter {{ background:transparent; border:1.5px solid var(--c-border-2); border-radius:99px; padding:5px 13px; font-size:0.62rem; font-weight:700; color:var(--c-muted-4); cursor:pointer; text-transform:uppercase; letter-spacing:0.06em; white-space:nowrap; transition:all .15s; }}
    .cat-filter:hover {{ border-color:var(--c-text); color:var(--c-text); }}
    .cat-filter.active {{ background:var(--c-text); color:var(--c-bg); border-color:var(--c-text); }}
    .coleta-btn {{ background:transparent; border:1.5px solid var(--c-border-2); border-radius:99px; padding:4px 11px; font-size:0.6rem; font-weight:700; color:var(--c-muted-4); cursor:pointer; letter-spacing:0.05em; margin-left:auto; }}
    .coleta-btn:hover {{ border-color:var(--c-text); color:var(--c-text); }}
    .coleta-painel {{ display:none; margin:0 24px 12px; padding:14px 16px; border:1.5px solid var(--c-border-2); border-radius:12px; }}
    .coleta-painel.aberto {{ display:block; }}
    .coleta-titulo {{ font-size:0.7rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:6px; }}
    .coleta-aviso {{ font-size:0.68rem; color:var(--c-muted-4); line-height:1.45; margin-bottom:10px; }}
    .coleta-itens {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
    .coleta-item {{ display:inline-flex; align-items:center; gap:5px; border:1.5px solid var(--c-border-2); border-radius:99px; padding:5px 12px; font-size:0.65rem; font-weight:700; cursor:pointer; user-select:none; }}
    .coleta-item.on {{ background:var(--c-text); color:var(--c-bg); border-color:var(--c-text); }}
    .coleta-acoes {{ display:flex; align-items:center; gap:10px; }}
    .coleta-salvar {{ background:var(--c-text); color:var(--c-bg); border:none; border-radius:99px; padding:6px 16px; font-size:0.65rem; font-weight:800; cursor:pointer; }}
    .coleta-status {{ font-size:0.66rem; color:var(--c-muted-4); }}
    .card.hidden-by-filter {{ display: none; }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}

    /* ── CARD TOP ── */
    .card-top {{
      display: flex; flex-direction: column; align-items: flex-start;
      gap: 6px; margin-bottom: 8px;
    }}
    .card-date {{
      font-size: 0.65rem; font-weight: 700; color: var(--c-muted-2);
      text-transform: uppercase; letter-spacing: 0.07em;
    }}
    .card-flags {{ display: flex; gap: 7px; }}
    /* ── CATEGORY BADGES ── */
    .cat-badge {{ font-size: 0.6rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; text-transform: uppercase; letter-spacing: 0.05em; display: inline-flex; align-items: center; gap: 4px; }}
    .cat-mercado    {{ background: rgba(34,197,94,.18);  color: #16a34a; }}
    .cat-competicao {{ background: rgba(234,179,8,.18);  color: #a16207; }}
    .cat-lesao      {{ background: rgba(239,68,68,.18);  color: #dc2626; }}
    .cat-geral      {{ background: rgba(100,116,139,.18);color: #475569; }}
    .cat-treino     {{ background: rgba(59,130,246,.18); color: #1d4ed8; }}
    .cat-entrevista {{ background: rgba(139,92,246,.18); color: #7c3aed; }}
    .cat-financas   {{ background: rgba(20,184,166,.18); color: #0f766e; }}

    /* ── AUTHOR AVATAR ── */
    .author-avatar {{ width: 26px; height: 26px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }}
    .card-meta {{ display: flex; align-items: center; gap: 6px; min-width: 0; flex-wrap: wrap; }}
    .card-actions {{ display: flex; gap: 4px; align-items: center; flex-shrink: 0; }}

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
    .flag-circle.pub-btn:hover   {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.pub-btn.on      {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.desc-btn:hover  {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.desc-btn.on     {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    /* post-btn: em standby — retornará futuramente */
    .flag-circle.post-btn        {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); text-decoration: none; }}
    .flag-circle.post-btn:hover  {{ background: var(--c-muted-6); border-color: var(--c-muted-6); color: var(--c-bg); }}
    .flag-circle.wand-btn        {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); }}
    .flag-circle.wand-btn:hover  {{ background: var(--c-muted-6); border-color: var(--c-muted-6); color: var(--c-bg); }}
    .flag-circle.copy-btn:hover  {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); }}

    /* ── TITLE ── */
    .card-title {{
      font-size: 1rem; font-weight: 700; color: var(--c-text);
      text-decoration: none; line-height: 1.4;
      display: block; margin-bottom: 10px;
    }}

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
    .card-collapsed.flag-open .card-text,
    .card-collapsed.flag-open .card-bottom {{ display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }}
    .card-collapsed.flag-open .card-text {{ display: block; }}
    .card-collapsed.flag-open .text-short {{ display: none; }}
    .card-collapsed.flag-open .text-full  {{ display: inline !important; }}

    /* ── EXPAND TEXTO LONGO ── */

    /* ── BODY TEXT ── */
    .card-text {{
      font-size: 0.82rem; color: var(--c-muted-4); line-height: 1.65;
      margin-bottom: 16px;
    }}

    /* ── CARD BOTTOM ── */
    .card-bottom {{
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 8px;
      padding-top: 10px; border-top: 1px solid var(--c-line);
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
    function copyFromBtn(btn) {{
      const text = btn.dataset.copy;
      navigator.clipboard.writeText(text).then(() => {{
        const orig = btn.innerHTML;
        btn.innerHTML = '✅';
        setTimeout(() => {{ btn.innerHTML = orig; }}, 2000);
      }});
    }}

    // ── Flags — sincronizado via DB ──
    let _flags = {{}};

    function applyFlags() {{
      const grid  = document.querySelector('.grid');
      const cards = Array.from(document.querySelectorAll('.card[data-id]'));
      cards.forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id];
        card.classList.remove('flag-analise','flag-visto','flag-publicado','flag-descarte','card-collapsed');
        card.querySelector('.anal-btn').classList.toggle('on',  f === 'analise');
        card.querySelector('.pub-btn').classList.toggle('on',   f === 'publicado');
        card.querySelector('.desc-btn').classList.toggle('on',  f === 'descartado');
        if      (f === 'analise')    card.classList.add('flag-analise');
        else if (f === 'publicado')  card.classList.add('flag-publicado');
        else if (f === 'descartado') card.classList.add('flag-descarte');
        if (!f) card.classList.remove('flag-open');
      }});
      const order = {{ undefined: 0, 'analise': 0, 'publicado': 2, 'descartado': 99 }};
      cards.sort((a, b) => (order[_flags[a.dataset.id]] ?? 0) - (order[_flags[b.dataset.id]] ?? 0));
      cards.forEach(c => grid.appendChild(c));
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
    <button class="coleta-btn" onclick="toggleColetaPainel()" title="Escolher quais categorias são traduzidas">⚙️ Coleta</button>
  </div>
  </div>
  <div id="coletaPainel" class="coleta-painel">
    <div class="coleta-titulo">Categorias que são traduzidas</div>
    <div class="coleta-aviso">O que ficar desmarcado é guardado sem tradução e não aparece aqui. Economiza tokens — reversível a qualquer momento.</div>
    <div id="coletaItens" class="coleta-itens"></div>
    <div class="coleta-acoes">
      <button class="coleta-salvar" onclick="salvarColeta()">Salvar</button>
      <span id="coletaStatus" class="coleta-status"></span>
    </div>
  </div>
  <div class="cat-filters">
    <button class="cat-filter active" onclick="filterCat(this,'')">Todos</button>
    <button class="cat-filter" onclick="filterCat(this,'mercado')">🔀 Mercado</button>
    <button class="cat-filter" onclick="filterCat(this,'financas')">💰 Finanças</button>
    <button class="cat-filter" onclick="filterCat(this,'competicao')">🏆 Competição</button>
    <button class="cat-filter" onclick="filterCat(this,'entrevista')">🎙️ Entrevista</button>
    <button class="cat-filter" onclick="filterCat(this,'lesao')">🩺 Lesão</button>
    <button class="cat-filter" onclick="filterCat(this,'treino')">🏋️ Treino</button>
    <button class="cat-filter" onclick="filterCat(this,'geral')">📰 Geral</button>
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

<div id="gerar-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)fecharGerarModal()">
  <div style="background:var(--c-bg-card);border-radius:14px;padding:22px 24px;max-width:560px;width:92%;max-height:78vh;display:flex;flex-direction:column;gap:14px;border:1px solid var(--c-border);box-shadow:0 20px 60px rgba(0,0,0,.4);">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
      <span style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--c-muted-2);">✨ Post gerado</span>
      <button onclick="fecharGerarModal()" style="background:none;border:none;cursor:pointer;color:var(--c-muted-3);font-size:1.3rem;line-height:1;padding:0 2px;">×</button>
    </div>
    <div id="gerar-output" style="font-size:0.83rem;line-height:1.65;color:var(--c-text);white-space:pre-wrap;overflow-y:auto;flex:1;min-height:60px;"></div>
    <div style="display:flex;justify-content:flex-end;flex-shrink:0;">
      <button id="gerar-copy-btn" style="display:none;background:var(--c-text);color:var(--c-bg);border:none;border-radius:8px;padding:8px 18px;font-size:0.72rem;font-weight:700;cursor:pointer;letter-spacing:.04em;">Copiar texto</button>
    </div>
  </div>
</div>
<script>
async function gerarTexto(btn) {{
  const news     = btn.dataset.news;
  const source   = btn.dataset.source;
  const moon     = btn.dataset.moon;
  const category = btn.dataset.category || '';
  const modal  = document.getElementById('gerar-modal');
  const output = document.getElementById('gerar-output');
  const copyBtn = document.getElementById('gerar-copy-btn');
  modal.style.display = 'flex';
  output.innerHTML = '<span style="color:var(--c-muted-2)">Gerando texto…</span>';
  copyBtn.style.display = 'none';
  const origHTML = btn.innerHTML;
  btn.innerHTML = '⏳';
  btn.disabled  = true;
  try {{
    const resp = await fetch('/api/gerar-texto', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{news, source, moon, category}})
    }});
    const data = await resp.json();
    if (data.error) {{
      output.textContent = '❌ ' + data.error;
    }} else {{
      output.textContent = data.texto;
      copyBtn.style.display = 'block';
      copyBtn.onclick = function() {{
        navigator.clipboard.writeText(data.texto).then(() => {{
          copyBtn.textContent = '✅ Copiado!';
          setTimeout(() => {{ copyBtn.textContent = 'Copiar texto'; }}, 2000);
        }});
      }};
    }}
  }} catch(e) {{
    output.textContent = '❌ Erro de rede.';
  }} finally {{
    btn.innerHTML = origHTML;
    btn.disabled  = false;
  }}
}}
function fecharGerarModal() {{
  document.getElementById('gerar-modal').style.display = 'none';
}}
</script>

<div id="gerar-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)fecharGerarModal()">
  <div style="background:var(--c-bg-card);border-radius:14px;padding:22px 24px;max-width:560px;width:92%;max-height:78vh;display:flex;flex-direction:column;gap:14px;border:1px solid var(--c-border);box-shadow:0 20px 60px rgba(0,0,0,.4);">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
      <span style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--c-muted-2);">✨ Post gerado</span>
      <button onclick="fecharGerarModal()" style="background:none;border:none;cursor:pointer;color:var(--c-muted-3);font-size:1.3rem;line-height:1;padding:0 2px;">×</button>
    </div>
    <div id="gerar-output" style="font-size:0.83rem;line-height:1.65;color:var(--c-text);white-space:pre-wrap;overflow-y:auto;flex:1;min-height:60px;"></div>
    <div style="display:flex;justify-content:flex-end;flex-shrink:0;">
      <button id="gerar-copy-btn" style="display:none;background:var(--c-text);color:var(--c-bg);border:none;border-radius:8px;padding:8px 18px;font-size:0.72rem;font-weight:700;cursor:pointer;letter-spacing:.04em;">Copiar texto</button>
    </div>
  </div>
</div>
<script>
async function gerarTexto(btn) {{
  const news     = btn.dataset.news;
  const source   = btn.dataset.source;
  const moon     = btn.dataset.moon;
  const category = btn.dataset.category || '';
  const modal  = document.getElementById('gerar-modal');
  const output = document.getElementById('gerar-output');
  const copyBtn = document.getElementById('gerar-copy-btn');
  modal.style.display = 'flex';
  output.innerHTML = '<span style="color:var(--c-muted-2)">Gerando texto…</span>';
  copyBtn.style.display = 'none';
  const origHTML = btn.innerHTML;
  btn.innerHTML = '⏳';
  btn.disabled  = true;
  try {{
    const resp = await fetch('/api/gerar-texto', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{news, source, moon, category}})
    }});
    const data = await resp.json();
    if (data.error) {{
      output.textContent = '❌ ' + data.error;
    }} else {{
      output.textContent = data.texto;
      copyBtn.style.display = 'block';
      copyBtn.onclick = function() {{
        navigator.clipboard.writeText(data.texto).then(() => {{
          copyBtn.textContent = '✅ Copiado!';
          setTimeout(() => {{ copyBtn.textContent = 'Copiar texto'; }}, 2000);
        }});
      }};
    }}
  }} catch(e) {{
    output.textContent = '❌ Erro de rede.';
  }} finally {{
    btn.innerHTML = origHTML;
    btn.disabled  = false;
  }}
}}
function fecharGerarModal() {{
  document.getElementById('gerar-modal').style.display = 'none';
}}
</script>
<style>
.card{{ will-change: transform; }}
.card.dragging{{ transition: none !important; z-index: 10; }}
</style>
<script>
(function(){{
  const THRESHOLD = 90;
  let startX=0,startY=0,_card=null;
  window._dragHappened=false;
  function cardOf(el){{ return el.closest && el.closest('.card[data-id]'); }}
  function onStart(card,x,y){{
    _card=card; startX=x; startY=y;
    card.classList.add('dragging');
    card.style.transition='none';
  }}
  function onMove(x){{
    if(!_card) return;
    const dx=x-startX;
    if(Math.abs(dx)>6) window._dragHappened=true;
    const rot=Math.min(Math.max(dx*0.05,-8),8);
    _card.style.transform=`translateX(${{dx}}px) rotate(${{rot}}deg)`;
    if(dx>20){{
      const a=Math.min(dx/THRESHOLD,1);
      _card.style.outline=`2px solid rgba(34,197,94,${{a}})`;
      _card.style.boxShadow=`0 0 30px rgba(34,197,94,${{a*0.25}})`;
    }} else if(dx<-20){{
      const a=Math.min(-dx/THRESHOLD,1);
      _card.style.outline=`2px solid rgba(239,68,68,${{a}})`;
      _card.style.boxShadow=`0 0 30px rgba(239,68,68,${{a*0.25}})`;
    }} else {{
      _card.style.outline=''; _card.style.boxShadow='';
    }}
  }}
  function onEnd(x){{
    if(!_card) return;
    const dx=x-startX;
    const card=_card; _card=null;
    card.classList.remove('dragging');
    card.style.transition='transform 0.3s,outline 0.2s,box-shadow 0.2s';
    card.style.transform=''; card.style.outline=''; card.style.boxShadow='';
    if(dx>THRESHOLD) toggleFlag(card.dataset.id,'publicado');
    else if(dx<-THRESHOLD) toggleFlag(card.dataset.id,'descartado');
    setTimeout(()=>{{ window._dragHappened=false; }},60);
  }}
  document.addEventListener('mousedown',e=>{{
    const card=cardOf(e.target);
    if(!card||e.target.closest('button,a,input,textarea,select')) return;
    onStart(card,e.clientX,e.clientY);
  }});
  document.addEventListener('mousemove',e=>{{ if(_card) onMove(e.clientX); }});
  document.addEventListener('mouseup',  e=>onEnd(e.clientX));
  document.addEventListener('touchstart',e=>{{
    const card=cardOf(e.target);
    if(!card||e.target.closest('button,a,input,textarea,select')) return;
    onStart(card,e.touches[0].clientX,e.touches[0].clientY);
  }},{{passive:true}});
  document.addEventListener('touchmove',e=>{{
    if(!_card) return;
    const dx=Math.abs(e.touches[0].clientX-startX);
    const dy=Math.abs(e.touches[0].clientY-startY);
    if(dx>dy){{ e.preventDefault(); onMove(e.touches[0].clientX); }}
  }},{{passive:false}});
  document.addEventListener('touchend',e=>onEnd(e.changedTouches[0].clientX));
}})();
// -- Painel de coleta: escolhe quais categorias VALEM traducao --------------
// Diferente do filtro de exibicao: aqui a decisao acontece ANTES de gastar token.
// O que fica desmarcado e guardado sem traduzir e nao chega na tela.
const CAT_ROTULOS={{mercado:'🔀 Mercado',lesao:'🩺 Lesao',competicao:'🏆 Competicao',entrevista:'🎙 Entrevista',treino:'🏋 Treino',financas:'💰 Financas',geral:'📰 Geral'}};
let _coletaAtivas=[];
function toggleColetaPainel(){{
  const p=document.getElementById('coletaPainel');
  p.classList.toggle('aberto');
  if(p.classList.contains('aberto')) carregarColeta();
}}
async function carregarColeta(){{
  try{{
    const d=await (await fetch('/api/categorias-ativas')).json();
    _coletaAtivas=d.ativas.slice();
    renderColeta();
  }}catch(e){{ document.getElementById('coletaStatus').textContent='Erro ao carregar.'; }}
}}
function renderColeta(){{
  document.getElementById('coletaItens').innerHTML=Object.keys(CAT_ROTULOS).map(function(c){{
    return '<span class="coleta-item'+(_coletaAtivas.indexOf(c)>=0?' on':'')+'" onclick="alternarCat(&quot;'+c+'&quot;)">'+CAT_ROTULOS[c]+'</span>';
  }}).join('');
}}
function alternarCat(c){{
  _coletaAtivas = _coletaAtivas.indexOf(c)>=0 ? _coletaAtivas.filter(function(x){{return x!==c;}}) : _coletaAtivas.concat([c]);
  renderColeta();
}}
async function salvarColeta(){{
  const st=document.getElementById('coletaStatus');
  if(!_coletaAtivas.length){{ st.textContent='Marque ao menos uma categoria.'; return; }}
  st.textContent='Salvando...';
  try{{
    const r=await fetch('/api/categorias-ativas',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{ativas:_coletaAtivas}})}});
    const d=await r.json();
    st.textContent = d.filtro_ligado
      ? 'Salvo. So essas categorias serao traduzidas daqui pra frente.'
      : 'Salvo. Todas ativas - sem filtro e sem custo de triagem.';
  }}catch(e){{ st.textContent='Erro ao salvar.'; }}
}}

let _catFilter='';
function filterCat(btn,cat){{
  _catFilter=cat;
  document.querySelectorAll('.cat-filter').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card[data-category]').forEach(card=>{{
    card.classList.toggle('hidden-by-cat', !!(cat && card.dataset.category!==cat));
  }});
}}
</script>
<style>
.card{{ will-change: transform; }}
.card.dragging{{ transition: none !important; z-index: 10; }}
</style>
<script>
(function(){{
  const THRESHOLD = 90;
  let startX=0,startY=0,_card=null;
  window._dragHappened=false;
  function cardOf(el){{ return el.closest && el.closest('.card[data-id]'); }}
  function onStart(card,x,y){{
    _card=card; startX=x; startY=y;
    card.classList.add('dragging');
    card.style.transition='none';
  }}
  function onMove(x){{
    if(!_card) return;
    const dx=x-startX;
    if(Math.abs(dx)>6) window._dragHappened=true;
    const rot=Math.min(Math.max(dx*0.05,-8),8);
    _card.style.transform=`translateX(${{dx}}px) rotate(${{rot}}deg)`;
    if(dx>20){{
      const a=Math.min(dx/THRESHOLD,1);
      _card.style.outline=`2px solid rgba(34,197,94,${{a}})`;
      _card.style.boxShadow=`0 0 30px rgba(34,197,94,${{a*0.25}})`;
    }} else if(dx<-20){{
      const a=Math.min(-dx/THRESHOLD,1);
      _card.style.outline=`2px solid rgba(239,68,68,${{a}})`;
      _card.style.boxShadow=`0 0 30px rgba(239,68,68,${{a*0.25}})`;
    }} else {{
      _card.style.outline=''; _card.style.boxShadow='';
    }}
  }}
  function onEnd(x){{
    if(!_card) return;
    const dx=x-startX;
    const card=_card; _card=null;
    card.classList.remove('dragging');
    card.style.transition='transform 0.3s,outline 0.2s,box-shadow 0.2s';
    card.style.transform=''; card.style.outline=''; card.style.boxShadow='';
    if(dx>THRESHOLD) toggleFlag(card.dataset.id,'publicado');
    else if(dx<-THRESHOLD) toggleFlag(card.dataset.id,'descartado');
    setTimeout(()=>{{ window._dragHappened=false; }},60);
  }}
  document.addEventListener('mousedown',e=>{{
    const card=cardOf(e.target);
    if(!card||e.target.closest('button,a,input,textarea,select')) return;
    onStart(card,e.clientX,e.clientY);
  }});
  document.addEventListener('mousemove',e=>{{ if(_card) onMove(e.clientX); }});
  document.addEventListener('mouseup',  e=>onEnd(e.clientX));
  document.addEventListener('touchstart',e=>{{
    const card=cardOf(e.target);
    if(!card||e.target.closest('button,a,input,textarea,select')) return;
    onStart(card,e.touches[0].clientX,e.touches[0].clientY);
  }},{{passive:true}});
  document.addEventListener('touchmove',e=>{{
    if(!_card) return;
    const dx=Math.abs(e.touches[0].clientX-startX);
    const dy=Math.abs(e.touches[0].clientY-startY);
    if(dx>dy){{ e.preventDefault(); onMove(e.touches[0].clientX); }}
  }},{{passive:false}});
  document.addEventListener('touchend',e=>onEnd(e.changedTouches[0].clientX));
}})();
let _catFilter='';
function filterCat(btn,cat){{
  _catFilter=cat;
  document.querySelectorAll('.cat-filter').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card[data-category]').forEach(card=>{{
    card.classList.toggle('hidden-by-cat', !!(cat && card.dataset.category!==cat));
  }});
}}
</script>
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
        "mercado":       ("🔀", "#dbeafe", "#1d4ed8"),
        "financas":      ("💰", "#fdf4ff", "#7e22ce"),
        "entrevista":    ("🎙️", "#fef3c7", "#b45309"),
        "competicao":    ("🏆", "#fef9c3", "#a16207"),
        "treino":        ("🏋️", "#f0fdf4", "#166534"),
        "lesao":         ("🩺", "#fff1f2", "#be123c"),
        "geral":         ("📰", "#f1f5f9", "#475569"),
    }
    CATEGORY_TEXT = {
        "mercado": "Mercado",      "financas": "Finanças",
        "competicao": "Competição","entrevista": "Entrevista",
        "lesao": "Lesão",          "treino": "Treino",
        "geral": "Geral",
    }
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    ICO_COPY    = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    ICO_WAND    = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h.01"/><path d="M17.8 6.2 19 5"/><path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/></svg>'
    ICO_ANALYSIS = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>'
    ICO_LOCK  = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
    ICO_CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    ICO_TRASH = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>'
    ICO_PEN   = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'

    cards = ""
    for a in articles:
        handle        = a.get("source_name", "").lstrip("@")
        moon          = SOURCE_MOON.get(handle, {"A": "🌕", "B": "🌖", "C": "🌗"}.get(a["source_tier"], ""))
        body_raw      = a.get("body_pt") or a.get("body_orig") or ""
        body_full     = body_raw
        category      = a.get("category") or "geral"
        category_text = CATEGORY_TEXT.get(category, "Geral")
        cat_emoji     = CATEGORY_EMOJI.get(category, ("📰", "", ""))[0]
        copy_text     = body_raw + "\n\n🗞️ @" + handle + " " + moon
        copy_safe     = copy_text.replace("&", "&amp;").replace('"', "&quot;")
        post_text_full = copy_text
        post_base     = f"/gerador?texto={quote(post_text_full)}&source={quote(handle)}&moon={quote(moon)}&translated=1"
        news_safe     = body_raw.replace("&", "&amp;").replace('"', "&quot;")
        art_id        = a['id']
        article_url   = (a.get('url') or '#').replace('"', '&quot;')
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
        <div class="card" data-id="{art_id}" data-category="{category}">
          <div class="card-body">
            <div class="card-top">
              <div class="card-meta">
                <img class="author-avatar" src="https://unavatar.io/twitter/{handle}" alt="@{handle}" onerror="this.style.display='none'">
                <span class="tag">@{handle}</span>
                <span class="tag">{moon}</span>
                <span class="card-date">{date_display}</span>
              </div>
              <span class="cat-badge cat-{category}">{cat_emoji} {category_text}</span>
            </div>
            <p class="card-text" data-url="{article_url}" onclick="if(!window._dragHappened&&this.dataset.url&&this.dataset.url!='#')window.open(this.dataset.url,'_blank')" style="cursor:pointer">{body_full}</p>
            <div class="card-bottom">
              <button class="flag-circle anal-btn"  onclick="toggleFlag('{art_id}','analise')"    title="Análise">{ICO_ANALYSIS}</button>
              <button class="flag-circle copy-btn" data-copy="{copy_safe}" onclick="copyFromBtn(this)" title="Copiar">{ICO_COPY}</button>
              <button class="flag-circle wand-btn" data-news="{news_safe}" data-source="{handle}" data-moon="{moon}" data-category="{category}" onclick="gerarTexto(this)" title="Gerar post">{ICO_WAND}</button>
              <button class="flag-circle desc-btn"  onclick="toggleFlag('{art_id}','descartado')" title="Lixeira">{ICO_TRASH}</button>
              <button class="flag-circle pub-btn"   onclick="toggleFlag('{art_id}','publicado')"  title="Publicado">{ICO_CHECK}</button>
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
    .fs-publicado {{ border-color: #86efac; color: var(--c-success); }}
    .fs-descarte  {{ border-color: #fca5a5; color: var(--c-error); }}
    .fs-badge:hover {{ opacity: .7; }}
    .fs-badge.active-filter {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 80px; align-items: start; }}
    .card {{ background: var(--c-bg-card); border-radius: 16px; display: flex; flex-direction: column; transition: background .2s; }}
    .card.flag-analise   {{ display: none; }}
    .card.flag-visto     {{ background: #ede9fe; }}
    .card.flag-publicado {{ background: #dcfce7; }}
    .card.flag-visto, .card.flag-publicado {{
      --c-bg: #edeae4; --c-bg-card: #fafaf8; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card.flag-descarte  {{ display: none; }}
    .card.hidden-by-cat  {{ display: none !important; }}
    .cat-filters {{ display:flex; gap:6px; padding:6px 24px 10px; overflow-x:auto; scrollbar-width:none; }}
    .cat-filters::-webkit-scrollbar {{ display:none; }}
    .cat-filter {{ background:transparent; border:1.5px solid var(--c-border-2); border-radius:99px; padding:5px 13px; font-size:0.62rem; font-weight:700; color:var(--c-muted-4); cursor:pointer; text-transform:uppercase; letter-spacing:0.06em; white-space:nowrap; transition:all .15s; }}
    .cat-filter:hover {{ border-color:var(--c-text); color:var(--c-text); }}
    .cat-filter.active {{ background:var(--c-text); color:var(--c-bg); border-color:var(--c-text); }}
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
    .flag-circle.pub-btn:hover   {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.pub-btn.on      {{ background: var(--c-success); border-color: var(--c-success); color: white; }}
    .flag-circle.desc-btn:hover  {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.desc-btn.on     {{ background: var(--c-error); border-color: var(--c-error); color: white; }}
    .flag-circle.post-btn        {{ background: var(--c-text); border-color: var(--c-text); color: var(--c-bg); text-decoration: none; }}
    .flag-circle.post-btn:hover  {{ background: var(--c-muted-6); border-color: var(--c-muted-6); color: var(--c-bg); }}
    .card-title {{ font-size: 1rem; font-weight: 700; color: var(--c-text); text-decoration: none; line-height: 1.4; display: block; margin-bottom: 10px; }}
    .flag-expand-btn {{ background: none; border: none; cursor: pointer; font-size: 0.62rem; color: var(--c-muted-2); padding: 0 0 10px; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; display: none; text-align: left; transition: color .15s; }}
    .flag-expand-btn:hover {{ color: var(--c-text); }}
    .card-collapsed .flag-expand-btn {{ display: block; }}
    .card-collapsed.flag-open .card-text, .card-collapsed.flag-open .card-bottom {{ display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }}
    .card-collapsed.flag-open .card-text {{ display: block; }}
    .card-collapsed.flag-open .text-short {{ display: none; }}
    .card-collapsed.flag-open .text-full  {{ display: inline !important; }}
    .card-text {{ font-size: 0.82rem; color: var(--c-muted-4); line-height: 1.65; margin-bottom: 16px; }}
    .card-bottom {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding-top: 14px; border-top: 1px solid rgba(0,0,0,.07); }}
    .card-tags {{ display: flex; gap: 5px; flex-wrap: wrap; }}
    .tag {{ font-size: 0.6rem; font-weight: 700; color: var(--c-muted-3); border: 1px solid var(--c-line); border-radius: 99px; padding: 3px 9px; text-transform: uppercase; letter-spacing: 0.05em; }}
  </style>
  <script>
    let _flags = {{}};
    function applyFlags() {{
      const grid  = document.querySelector('.grid');
      const cards = Array.from(document.querySelectorAll('.card[data-id]'));
      cards.forEach(card => {{
        const id = card.dataset.id;
        const f  = _flags[id];
        card.classList.remove('flag-analise','flag-visto','flag-publicado','flag-descarte','card-collapsed');
        card.querySelector('.anal-btn').classList.toggle('on',  f === 'analise');
        card.querySelector('.pub-btn').classList.toggle('on',   f === 'publicado');
        card.querySelector('.desc-btn').classList.toggle('on',  f === 'descartado');
        if      (f === 'analise')    card.classList.add('flag-analise');
        else if (f === 'publicado')  card.classList.add('flag-publicado');
        else if (f === 'descartado') card.classList.add('flag-descarte');
        if (!f) card.classList.remove('flag-open');
      }});
      const order = {{ undefined: 0, 'analise': 0, 'publicado': 2, 'descartado': 99 }};
      cards.sort((a, b) => (order[_flags[a.dataset.id]] ?? 0) - (order[_flags[b.dataset.id]] ?? 0));
      cards.forEach(c => grid.appendChild(c));
    }}
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
  </div>
  </div>
  <div class="cat-filters">
    <button class="cat-filter active" onclick="filterCat(this,'')">Todos</button>
    <button class="cat-filter" onclick="filterCat(this,'mercado')">🔀 Mercado</button>
    <button class="cat-filter" onclick="filterCat(this,'financas')">💰 Finanças</button>
    <button class="cat-filter" onclick="filterCat(this,'competicao')">🏆 Competição</button>
    <button class="cat-filter" onclick="filterCat(this,'entrevista')">🎙️ Entrevista</button>
    <button class="cat-filter" onclick="filterCat(this,'lesao')">🩺 Lesão</button>
    <button class="cat-filter" onclick="filterCat(this,'treino')">🏋️ Treino</button>
    <button class="cat-filter" onclick="filterCat(this,'geral')">📰 Geral</button>
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


@app.get("/api/admin/collect-now")
async def api_collect_now(hours: int = 12):
    """Coleta sob demanda com janela ampliada, disparada em BACKGROUND.

    Serve pra resgatar matéria que ficou de fora porque a janela do ciclo normal
    é curta: o agendador roda a cada 30min e só olha as últimas ~2h, então uma
    notícia de 5h atrás nunca entra sozinha, mesmo com a fonte funcionando.

    Roda solta de propósito: a pipeline leva minutos, e se ficasse presa ao request
    o cliente desconectaria antes do fim e o FastAPI cancelaria a coleta no meio
    (foi o que aconteceu na primeira versão). Acompanhe o resultado em /api/logs."""
    asyncio.create_task(run_pipeline(True, hours))
    return {"status": "started", "hours": hours, "acompanhe": "/api/logs"}


@app.post("/api/collect")
async def api_collect(background_tasks: BackgroundTasks, hours: int = None):
    # force=True ignora período inativo. hours opcional permite forçar uma
    # janela maior manualmente (resgate pontual); sem isso, usa o cálculo
    # dinâmico em lookback_hours() (cobre o tempo desde a última coleta OK).
    background_tasks.add_task(run_pipeline, True, hours)
    return {"status": "started"}




@app.post("/api/admin/collect-source")
async def admin_collect_source(username: str, hours: int = 6):
    """
    Coleta tweets de uma conta específica em isolamento (sem competição de batch).
    Útil para resgatar tweets que falharam silenciosamente durante coleta em lote.
    """
    from collector import resolve_twitter_rss, parse_entries
    import collector as _collector
    from processor import process_and_save
    from database import get_effective_sources

    sources = get_effective_sources()
    source_info = next((s for s in sources if s["handle"].lower() == username.lower()), None)
    if source_info is None:
        return JSONResponse({"error": f"Conta @{username} não encontrada nas fontes"}, status_code=404)

    tier = source_info["tier"]
    name = f"@{username}"
    _collector.ARTICLE_MAX_AGE_HOURS = hours

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=5)
    ) as client:
        result = await resolve_twitter_rss(username, client)

    if result is None:
        return {"status": "fail", "account": username, "tier": tier,
                "error": "Todos os providers RSS falharam"}

    url, provider, feed = result
    articles = parse_entries(feed, name, tier, "twitter")

    if not articles:
        return {"status": "ok", "account": username, "tier": tier,
                "provider": provider, "hours_window": hours,
                "articles_found": 0, "articles_new": 0}

    process_result = await process_and_save(articles)
    return {
        "status": "ok",
        "account": username,
        "tier": tier,
        "provider": provider,
        "hours_window": hours,
        "articles_found": len(articles),
        "articles_new": process_result.get("articles_new", 0),
        "articles_dup": process_result.get("articles_dup", 0),
    }


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
# ─── Club emoji map for post generation ──────────────────────────────────────
_CLUB_EMOJI_MAP = [
    # (canonical, emoji_pair, [keywords_lowercase])
    ("Al Hilal",    "🔵⚪️", ["hilal", "al-hilal", "al hilal", "alhilal", "الهلال"]),
    ("Al Nassr",    "🟡🔵", ["nassr", "nasr", "al-nassr", "al nassr", "alnassr", "النصر"]),
    ("Al Ittihad",  "⚫️🟡", ["al ittihad", "al-ittihad", "alittihad", "ittihad jeddah", "الاتحاد"]),
    ("Al Ahli",     "🟢⚪️", ["al ahli", "al-ahli", "alahli", "al ahly", "al-ahly", "alahly", "الأهلي", "الاهلي"]),
    ("Al Ettifaq",  "🟢🔴", ["ettifaq", "al-ettifaq", "al ettifaq", "alettifaq", "الاتفاق"]),
    ("Al Shabab",   "⚪️⚫️", ["shabab", "al-shabab", "alshabab", "الشباب"]),
    ("Al Fateh",    "🔵🟢", ["al fateh", "al-fateh", "alfateh", "al fath", "alfath", "الفتح"]),
    ("Al Fayha",    "🟠🔵", ["fayha", "feiha", "faiha", "al-fayha", "alfayha", "الفيحاء"]),
    ("Al Khaleej",  "🟢🟡", ["khaleej", "khalij", "al-khaleej", "alkhaleej", "الخليج"]),
    ("Al Qadsiah",  "🔴🟡", ["qadsiah", "qadisiyah", "qadisiya", "alqadsiah", "القادسية"]),
    ("Al Taawoun",  "🟡⚪️", ["taawoun", "taawon", "taawun", "al-taawoun", "altaawoun", "التعاون"]),
    ("Al Orobah",   "🟡🟢", ["orobah", "orubah", "orouba", "al-orobah", "العروبة"]),
    ("Al Riyadh",   "⚫️🔴", ["al riyadh", "al-riyadh", "alriyadh", "الرياض"]),
    ("Al Raed",     "🔴⚫️", ["al raed", "al-raed", "alraed", "الرائد"]),
    ("Al Okhdood",  "🔵⚫️", ["okhdood", "okhdud", "akhdoud", "ukhdood", "alokhdood", "الأخدود"]),
    ("Al Kholood",  "🔴🟢", ["kholood", "khulood", "kholud", "alkholood", "الخلود"]),
    ("Al Faisaly",  "🔴⚪️", ["faisaly", "faysaly", "faisali", "alfaisaly", "الفيصلي"]),
    ("Al Diraiyah", "🟤⚪️", ["diraiyah", "diriyah", "deriyah", "aldiraiyah", "الدرعية"]),
    ("Abha",        "🔵🔴", ["abha"]),
    ("Damac",       "🔴🟤", ["damac", "damak", "dhamk", "ضمك"]),
    ("Neom",        "🔵🟣", ["neom", "نيوم"]),
]

def _detect_saudi_club(text: str):
    """Returns (canonical, emoji_pair) for the first Saudi club found in text."""
    tl = text.lower()
    best = None
    for canonical, emoji, keywords in _CLUB_EMOJI_MAP:
        for kw in keywords:
            pos = tl.find(kw)
            if pos != -1:
                if best is None or pos < best[0]:
                    best = (pos, canonical, emoji)
                break
    return (best[1], best[2]) if best else None

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
        "4. MERCADO — titulo_mercado: até 7 palavras, MAIÚSCULAS, focado na movimentação do jogador. "
        "nome_jogador: nome do jogador em MAIÚSCULAS extraído do texto. "
        "status_mercado: escolha o mais adequado entre Acerto, Anunciado, Avançado, Consulta, Conversas, "
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
        '  "titulo_longo": "...",\n  "titulo_mercado": "...",\n'
        '  "nome_jogador": "...",\n  "status_mercado": "..."\n}'
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




@app.post("/api/gerar-texto")
async def gerar_texto_api(request: Request):
    """Gera texto adaptado (ponto de vista saudita) sem navegação."""
    body = await request.json()
    news     = (body.get("news")     or "").strip()
    source   = (body.get("source")   or "").strip().lstrip("@")
    moon     = (body.get("moon")     or "").strip()
    category = (body.get("category") or "").strip().lower()
    if not news:
        return JSONResponse({"error": "Campo 'news' vazio."}, status_code=400)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY não configurada."}, status_code=500)

    source_footer = f"🗞️ @{source} {moon}".strip() if source else ""
    footer_instruction = (
        f'Ao final do texto, adicione exatamente esta linha (sem alterar): "{source_footer}"\n'
        if source_footer else ""
    )
    angulo = (
        "PONTO DE VISTA — FUTEBOL SAUDITA:\n"
        "Este é um canal sobre a Saudi Pro League. Reordene as informações do texto para que "
        "o clube saudita seja o sujeito da primeira frase. Isso é uma REORDENAÇÃO do que já está "
        "escrito, não um convite para adicionar informação nova.\n"
        "NUNCA coloque o clube europeu como sujeito principal.\n"
    )
    clubes = (
        "NOMES DE CLUBES: NUNCA use hífen. Grafias OBRIGATÓRIAS (SPL): "
        + ", ".join(SPL_CLUBS) + ". "
        + "ATENÇÃO: الاتفاق = Al Ettifaq (NÃO Al Ittihad); الاتحاد = Al Ittihad.\n"
    )
    emoji_flags = (
        "\nFLAGS DE EMOJI (aplique nesta notícia de mercado):\n"
        "- Coloque \U0001f1f8\U0001f1e6 imediatamente APÓS o nome do clube saudita na PRIMEIRA menção. "
        "Nas menções seguintes ao mesmo clube, sem emoji.\n"
        "- Coloque o emoji da bandeira da nacionalidade do jogador imediatamente ANTES do nome do jogador "
        "na PRIMEIRA menção. Nas menções seguintes, sem emoji.\n"
        "- Exemplo: 'O Al Hilal \U0001f1f8\U0001f1e6 negocia com \U0001f1f3\U0001f1f1 Crysencio Summerville.'\n"
        "- A nacionalidade do jogador deve ser inferida do texto original. "
        "Se não estiver clara, omita o emoji.\n"
    ) if category == "mercado" else ""
    prompt = (
        "Você é um editor de conteúdo especializado na Saudi Pro League. "
        "O texto abaixo JÁ ESTÁ EM PORTUGUÊS — NÃO TRADUZA.\n\n"
        + angulo
        + "\nREGRA ABSOLUTA — LEIA COM ATENÇÃO:\n"
        "O texto abaixo é a ÚNICA fonte de verdade. Você NÃO pode usar nenhum conhecimento "
        "externo, histórico de jogadores, informações de treino ou suposições.\n"
        "- Se o texto diz que um jogador está no Bayern de Munique, escreva Bayern de Munique — "
        "mesmo que você saiba que ele jogou em outro clube no passado.\n"
        "- NÃO corrija, NÃO complemente, NÃO confirme com conhecimento externo.\n"
        "- NÃO adicione clube atual, posição, idade, valor ou qualquer dado ausente no texto.\n"
        "- Se o texto não mencionar valor de transferência, NÃO escreva valor.\n"
        "- Se o texto não confirmar acerto, NÃO escreva que houve acerto.\n"
        "Trate cada notícia como se você não soubesse NADA sobre os jogadores envolvidos.\n"
        + emoji_flags
        + "\nTAREFA: reordene e condense o texto sob o ponto de vista saudita.\n"
        "\nCOMPRIMENTO — REGRA RÍGIDA:\n"
        "O texto final deve ter NO MÁXIMO o mesmo número de frases do original. "
        "Se o original tem 2 frases, o resultado tem 2 frases (ou menos). "
        "NUNCA escreva mais frases que o original. Menos é melhor que mais.\n"
        "\nPROIBIDO — frases de fechamento, análise ou opinião:\n"
        "- NÃO escreva frases sobre ambição, protagonismo, projeto, estratégia ou intenções do clube.\n"
        "- NÃO escreva sobre o que o movimento demonstra, representa ou significa.\n"
        "- NÃO escreva sobre o que a diretoria trabalha para viabilizar.\n"
        "- NÃO adicione frase de conclusão, contexto de mercado ou comentário editorial.\n"
        "Se você removeu o contexto europeu e sobraram poucas frases, ENTREGUE poucas frases. "
        "NÃO preencha o espaço.\n"
        "\nEstilo: jornalismo esportivo direto, texto corrido, sem hashtags, "
        "sem exclamações, sem títulos, sem negrito, sem listas.\n"
        + clubes
        + footer_instruction
        + "Responda SOMENTE com o texto final, sem comentários."
    )
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL_POST,
        "max_tokens": 800,
        "system": prompt,
        "messages": [{"role": "user", "content": news}],
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(CLAUDE_API_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            err = resp.json().get("error", {})
            return JSONResponse({"error": err.get("message", f"Claude API HTTP {resp.status_code}")}, status_code=resp.status_code)
        texto = (resp.json()["content"][0].get("text") or "").strip()
        if category == "mercado":
            club = _detect_saudi_club(news)
            if club:
                texto = f"\U0001f6a8{club[1]} {texto}"
            else:
                texto = f"\U0001f6a8\U0001f1f8\U0001f1e6 {texto}"
        return {"texto": texto}
    except Exception as e:
        return JSONResponse({"error": f"Erro: {e}"}, status_code=500)



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
                e0 = feed.entries[0] if entries > 0 else None
                results.append({
                    "provider": provider,
                    "url": url,
                    "status": resp.status_code,
                    "entries": entries,
                    "ok": entries > 0,
                    "sample": e0.get("title", "")[:100] if e0 else None,
                    "full_title": e0.get("title", "") if e0 else None,
                    "full_summary": e0.get("summary", "") if e0 else None,
                    "has_published_parsed": bool(getattr(e0, "published_parsed", None)) if e0 else None,
                    "published": e0.get("published", "") if e0 else None,
                    "link": e0.get("link", "") if e0 else None,
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


@app.get("/numeros", response_class=HTMLResponse)
async def numeros_page():
    hdr = _header("/numeros")
    FLAG_MAP_JS = '{"Saudi Arabia": "🇸🇦", "Portugal": "🇵🇹", "Brazil": "🇧🇷", "Argentina": "🇦🇷", "Colombia": "🇨🇴", "England": "🇬🇧", "France": "🇫🇷", "Belgium": "🇧🇪", "Netherlands": "🇳🇱", "Spain": "🇪🇸", "Italy": "🇮🇹", "Germany": "🇩🇪", "Norway": "🇳🇴", "Sweden": "🇸🇪", "Denmark": "🇩🇰", "Greece": "🇬🇷", "Senegal": "🇸🇳", "Mali": "🇲🇱", "Ivory Coast": "🇨🇮", "Cote d\'Ivoire": "🇨🇮", "Cameroon": "🇨🇲", "Nigeria": "🇳🇬", "Ghana": "🇬🇭", "Algeria": "🇩🇿", "Morocco": "🇲🇦", "Tunisia": "🇹🇳", "Egypt": "🇪🇬", "Guinea": "🇬🇳", "Croatia": "🇭🇷", "Serbia": "🇷🇸", "Poland": "🇵🇱", "Ukraine": "🇺🇦", "Russia": "🇷🇺", "Uruguay": "🇺🇾", "Chile": "🇨🇱", "Mexico": "🇲🇽", "USA": "🇺🇸", "United States": "🇺🇸", "Japan": "🇯🇵", "South Korea": "🇰🇷", "Korea Republic": "🇰🇷", "Australia": "🇦🇺", "Iran": "🇮🇷", "Iraq": "🇮🇶", "Jordan": "🇯🇴", "Bosnia": "🇧🇦", "Bosnia and Herzegovina": "🇧🇦", "Montenegro": "🇲🇪", "Wales": "🏴", "Scotland": "🏴", "Ireland": "🇮🇪", "Turkey": "🇹🇷", "Czech Republic": "🇨🇿", "Slovakia": "🇸🇰", "Austria": "🇦🇹", "Switzerland": "🇨🇭", "Georgia": "🇬🇪", "Armenia": "🇦🇲", "Tajikistan": "🇹🇯", "Ecuador": "🇪🇨", "Peru": "🇵🇪", "Venezuela": "🇻🇪", "Paraguay": "🇵🇾", "Bolivia": "🇧🇴", "Costa Rica": "🇨🇷", "Panama": "🇵🇦", "Jamaica": "🇯🇲", "Qatar": "🇶🇦", "UAE": "🇦🇪", "United Arab Emirates": "🇦🇪", "Kuwait": "🇰🇼", "Bahrain": "🇧🇭", "Oman": "🇴🇲", "Syria": "🇸🇾", "Lebanon": "🇱🇧", "Palestine": "🇵🇸", "Albania": "🇦🇱", "North Macedonia": "🇲🇰", "Slovenia": "🇸🇮", "Romania": "🇷🇴", "Bulgaria": "🇧🇬", "Hungary": "🇭🇺", "Finland": "🇫🇮", "Iceland": "🇮🇸", "Israel": "🇮🇱", "China": "🇨🇳", "India": "🇮🇳", "DR Congo": "🇨🇩", "Congo": "🇨🇬", "Gabon": "🇬🇦", "Burkina Faso": "🇧🇫", "Zambia": "🇿🇲", "South Africa": "🇿🇦", "Kenya": "🇰🇪", "Angola": "🇦🇴", "Cape Verde": "🇨🇻", "Equatorial Guinea": "🇬🇶", "Gambia": "🇬🇲", "Guinea-Bissau": "🇬🇼", "Benin": "🇧🇯", "Togo": "🇹🇬", "Niger": "🇳🇪", "Libya": "🇱🇾", "Sudan": "🇸🇩", "Mauritania": "🇲🇷"}'
    CLUB_SHORT_JS = '{"Al Khaleej Saihat": "Khaleej", "Al Kholood": "Kholood", "Al Najma": "Najma", "Al Okhdood": "Okhdood", "Al Riyadh": "Riyadh", "Al Shabab": "Shabab", "Al Taawon": "Taawoun", "Al-Ahli Jeddah": "Ahli", "Al-Ettifaq": "Ettifaq", "Al-Fateh": "Fateh", "Al-Fayha": "Fayha", "Al-Hazm": "Hazm", "Al-Hilal Saudi FC": "Hilal", "Al-Ittihad FC": "Ittihad", "Al-Nassr": "Nassr", "Al-Qadisiyah FC": "Qadsiah", "Damac": "Damac", "NEOM": "Neom"}'
    # Mesma fonte usada pelo backend — evita a lista da tela ficar defasada da API,
    # que foi o que aconteceu quando a 2026/27 começou e o filtro não a oferecia.
    SEASONS_JS = json.dumps(_af_available_seasons())
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IARABÃO — Números</title>
{_THEME_INIT_SCRIPT}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
{_HEADER_CSS}

.numeros-wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 60px; }}
.numeros-title {{ font-size: 1.15rem; font-weight: 700; color: var(--c-text); margin: 0 0 4px; }}
.numeros-subtitle {{ font-size: .78rem; color: var(--c-muted-3); margin: 0 0 18px; }}

.tabbar {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 18px; border-bottom: 1px solid var(--c-border); padding-bottom: 10px; }}
.tab-btn {{
  background: none; border: 1px solid var(--c-border-2); border-radius: 99px;
  padding: 6px 16px; font-size: .75rem; font-weight: 700; color: var(--c-muted-3);
  cursor: pointer; transition: all .15s; text-transform: uppercase; letter-spacing: .04em;
}}
.tab-btn:hover {{ color: var(--c-text); border-color: var(--c-muted-3); }}
.tab-btn.active {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}

.subtabbar {{ display: flex; gap: 6px; margin-bottom: 14px; }}
.subtab-btn {{
  background: none; border: none; border-bottom: 2px solid transparent;
  padding: 6px 4px; font-size: .82rem; font-weight: 600; color: var(--c-muted-3);
  cursor: pointer; transition: all .15s;
}}
.subtab-btn:hover {{ color: var(--c-text); }}
.subtab-btn.active {{ color: var(--c-text); border-bottom-color: var(--c-text); }}
.subtab-panel {{ display: none; }}
.subtab-panel.active {{ display: block; }}

.filters-row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }}
.filters-row select, .filters-row input {{
  padding: 6px 10px; border-radius: 8px; border: 1px solid var(--c-border);
  background: var(--c-bg-card); color: var(--c-text); font-size: .78rem; outline: none;
}}
.filters-row select:focus, .filters-row input:focus {{ border-color: var(--c-muted-3); }}
.filters-row label {{ font-size: .68rem; color: var(--c-muted-3); text-transform: uppercase; letter-spacing: .05em; display: flex; flex-direction: column; gap: 3px; }}

.result-card {{
  background: var(--c-bg-card); border-radius: 16px; padding: 18px 20px;
  margin-bottom: 16px;
}}
.result-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
.result-title {{ font-size: .85rem; font-weight: 700; color: var(--c-text); }}
.copy-btn {{
    .fj-topo {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
    .fj-info {{ font-size:0.72rem; color:var(--c-muted-4); }}
    .fj-refresh {{ background:transparent; border:1.5px solid var(--c-border-2); border-radius:99px; padding:5px 14px; font-size:0.65rem; font-weight:700; color:var(--c-muted-4); cursor:pointer; }}
    .fj-refresh:hover {{ border-color:var(--c-text); color:var(--c-text); }}
    .fj-status {{ font-size:0.66rem; color:var(--c-muted-4); }}
    .fj-card {{ margin-bottom:12px; }}
    .fj-cab {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }}
    .fj-conf {{ font-weight:800; font-size:0.95rem; }}
    .fj-selo {{ font-size:0.6rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; border:1.5px solid var(--c-border-2); border-radius:99px; padding:3px 9px; color:var(--c-muted-4); }}
    .fj-selo.fj-vivo {{ border-color:#22c55e; color:#22c55e; }}
    .fj-selo.fj-fim {{ border-color:var(--c-text); color:var(--c-text); }}
    .fj-texto {{ white-space:pre-wrap; font-family:inherit; font-size:0.9rem; line-height:1.6; margin:0; padding:12px 14px; border-radius:10px; background:var(--c-bg-soft); }}
    .fj-aguardando {{ font-size:0.75rem; color:var(--c-muted-4); padding:6px 0; }}
    .nome-completo {{ color:var(--c-muted-4); font-weight:400; }}
  display: flex; align-items: center; gap: 5px;
  background: var(--c-text); color: var(--c-bg); border: none; border-radius: 8px;
  padding: 6px 14px; font-size: .72rem; font-weight: 700; cursor: pointer;
  transition: background .15s; white-space: nowrap;
}}
.copy-btn:hover {{ background: var(--c-muted-6); }}
.copy-btn.copied {{ background: var(--c-success); color: white; }}
.result-pre {{
  white-space: pre-wrap; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: .82rem; line-height: 1.7; color: var(--c-muted-4);
  background: var(--c-bg-soft); border-radius: 10px; padding: 14px 16px;
  max-height: 420px; overflow-y: auto;
}}
.result-meta {{ font-size: .65rem; color: var(--c-muted-2); text-transform: uppercase; letter-spacing: .05em; margin-top: 8px; }}
.loading-state, .error-state {{ text-align: center; color: var(--c-muted-3); padding: 24px; font-size: .82rem; }}
.error-state {{ color: #dc2626; }}

.player-picker {{ display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }}
.player-avatar-preview {{ width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: var(--c-bg-soft); }}

.player-picker-v2 {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 16px; }}
.picker-group {{ position: relative; min-width: 240px; flex: 1; }}
.picker-label {{ font-size: .68rem; color: var(--c-muted-3); text-transform: uppercase; letter-spacing: .05em; display: block; margin-bottom: 4px; }}
.optional-tag {{ text-transform: none; font-weight: 400; opacity: .7; }}
.search-combo {{ position: relative; }}
.search-combo input {{
  width: 100%; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--c-border);
  background: var(--c-bg-card); color: var(--c-text); font-size: .8rem; outline: none;
}}
.search-combo input:focus {{ border-color: var(--c-muted-3); }}
.search-results {{
  display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 20;
  background: var(--c-bg-card); border: 1px solid var(--c-border); border-radius: 10px;
  margin-top: 4px; max-height: 260px; overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,.15);
}}
.search-item {{
  display: flex; align-items: center; gap: 8px; padding: 7px 10px; font-size: .8rem;
  cursor: pointer; color: var(--c-text);
}}
.search-item:hover {{ background: var(--c-bg-soft); }}
.search-item small {{ color: var(--c-muted-3); font-weight: 400; }}
.search-empty {{ padding: 10px; font-size: .76rem; color: var(--c-muted-3); }}
.search-crest {{ width: 20px; height: 20px; object-fit: contain; }}
.search-avatar {{ width: 24px; height: 24px; border-radius: 50%; object-fit: cover; background: var(--c-bg-soft); }}
.search-avatar-ph {{ width: 24px; height: 24px; border-radius: 50%; background: var(--c-bg-soft); display: inline-block; }}
.selected-chip {{
  display: none; align-items: center; gap: 6px; margin-top: 6px; padding: 5px 10px;
  background: var(--c-bg-soft); border-radius: 99px; font-size: .78rem; font-weight: 600;
  color: var(--c-text); width: fit-content;
}}
.chip-clear {{
  background: none; border: none; color: var(--c-muted-3); cursor: pointer; font-size: .75rem;
  padding: 0 2px; line-height: 1;
}}
.chip-clear:hover {{ color: var(--c-text); }}

.club-filter-wrap {{ margin-bottom: 14px; }}
.club-chip-list {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }}
.club-chip-item {{
  display: flex; align-items: center; gap: 6px; padding: 5px 12px 5px 8px;
  background: var(--c-bg-card); border: 1px solid var(--c-border); border-radius: 99px;
  font-size: .78rem; font-weight: 600; color: var(--c-muted-3); cursor: pointer;
  transition: all .15s; user-select: none;
}}
.club-chip-item:hover {{ border-color: var(--c-muted-3); }}
.club-chip-item.checked {{ color: var(--c-text); border-color: var(--c-text); background: var(--c-bg-soft); }}
.club-chip-item img {{ width: 16px; height: 16px; object-fit: contain; }}
.club-chip-item input {{ display: none; }}

.col-copy-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }}
.col-copy-btn {{
  background: var(--c-bg-soft); color: var(--c-muted-3); border: 1px solid var(--c-border);
  padding: 4px 10px; font-size: .68rem; font-weight: 700; border-radius: 6px; cursor: pointer;
  transition: all .15s;
}}
.col-copy-btn:hover {{ color: var(--c-text); border-color: var(--c-muted-3); }}
.col-copy-btn.copied {{ background: var(--c-success); color: white; border-color: var(--c-success); }}
</style>
</head>
<body>
{hdr}
<div class="numeros-wrap">
  <div class="numeros-title">Números — Saudi Pro League</div>
  <div class="numeros-subtitle">Estatísticas via API-Football, prontas pra copiar e colar. Estatísticas numéricas ausentes aparecem como 0; dados cadastrais ausentes (nacionalidade, posição, clube) aparecem como "Não informado" — nada é estimado ou inventado.</div>

  <div class="tabbar">
    <button class="tab-btn active" onclick="showTab('rankings',this)">Rankings</button>
    <button class="tab-btn" onclick="showTab('classificacao',this)">Classificação</button>
    <button class="tab-btn" onclick="showTab('jogador',this)">Jogador</button>
    <button class="tab-btn" onclick="showTab('fimdejogo',this); carregarJogosDoDia()">⏱️ Fim de Jogo</button>
  </div>

  <div id="tab-fimdejogo" class="tab-panel">
    <div class="fj-topo">
      <span class="fj-info">Jogos de hoje e ontem. Quando a partida encerra, o texto aparece pronto — é só copiar.</span>
      <button class="fj-refresh" onclick="carregarJogosDoDia()">Atualizar</button>
      <span id="fjStatus" class="fj-status"></span>
    </div>
    <div id="fjLista"><div class="result-card"><div class="loading-state">Carregando jogos…</div></div></div>
  </div>

  <div id="tab-rankings" class="tab-panel active">
    <div class="subtabbar">
      <button class="subtab-btn active" onclick="showSubtab('rk','artilharia',this)">Artilharia</button>
      <button class="subtab-btn" onclick="showSubtab('rk','assistencias',this)">Assistências</button>
      <button class="subtab-btn" onclick="showSubtab('rk','ga',this)">Participações em Gols</button>
    </div>
    <div class="filters-row">
      <label>Temporada
        <select id="rkSeason" onchange="loadRankings()"></select>
      </label>
      <label>Clube
        <select id="rkTeam" onchange="loadRankings()"><option value="0">Todos</option></select>
      </label>
      <label>Qtd. de atletas
        <select id="rkLimit" onchange="loadRankings()">
          <option value="5">5</option><option value="10" selected>10</option>
          <option value="15">15</option><option value="20">20</option>
          <option value="25">25</option><option value="30">30</option>
          <option value="999">Todos</option>
        </select>
      </label>
    </div>
    <div id="rk-artilharia" class="subtab-panel active"><div class="result-card"><div class="loading-state">Carregando…</div></div></div>
    <div id="rk-assistencias" class="subtab-panel"><div class="result-card"><div class="loading-state">Carregando…</div></div></div>
    <div id="rk-ga" class="subtab-panel"><div class="result-card"><div class="loading-state">Carregando…</div></div></div>
  </div>

  <div id="tab-classificacao" class="tab-panel">
    <div class="filters-row">
      <label>Temporada
        <select id="stSeason" onchange="loadStandings()"></select>
      </label>
      <label>Exibir
        <select id="stMode" onchange="loadStandings()">
          <option value="4">G4</option>
          <option value="5">G5</option>
          <option value="7" selected>G7</option>
          <option value="8">G8</option>
          <option value="all">Completa</option>
        </select>
      </label>
    </div>
    <div id="standings-result"><div class="result-card"><div class="loading-state">Carregando…</div></div></div>
  </div>

  <div id="tab-jogador" class="tab-panel">
    <div class="player-picker-v2">
      <div class="picker-group">
        <label class="picker-label">Clube <span class="optional-tag">(opcional)</span></label>
        <div class="search-combo">
          <input type="text" id="jgClubSearch" placeholder="Buscar clube por nome..." autocomplete="off" oninput="onClubSearchInput()">
          <div id="jgClubResults" class="search-results"></div>
        </div>
        <div id="jgClubSelected" class="selected-chip"></div>
      </div>
      <div class="picker-group">
        <label class="picker-label">Jogador</label>
        <div class="search-combo">
          <input type="text" id="jgPlayerSearch" placeholder="Nome, sobrenome ou parte dele..." autocomplete="off" oninput="onPlayerSearchInput()">
          <div id="jgPlayerResults" class="search-results"></div>
        </div>
        <div id="jgPlayerSelected" class="selected-chip"></div>
      </div>
    </div>

    <div class="subtabbar">
      <button class="subtab-btn active" onclick="showSubtab('jg','temporada',this)">Temporada</button>
      <button class="subtab-btn" onclick="showSubtab('jg','partida',this)">Partida específica</button>
    </div>

    <div id="jg-temporada" class="subtab-panel active">
      <div id="jgClubFilterWrap" class="club-filter-wrap" style="display:none">
        <label class="picker-label">Clube(s) do jogador <span class="optional-tag">(marque 1 ou mais, ou "Todos")</span></label>
        <div id="jgClubFilterList" class="club-chip-list"></div>
      </div>
      <div id="jgSeasonFilterWrap" class="club-filter-wrap" style="display:none">
        <label class="picker-label">Temporada(s) <span class="optional-tag">(marque 1 ou mais, ou "Todas")</span></label>
        <div id="jgSeasonFilterList" class="club-chip-list"></div>
      </div>
      <div id="jgLeagueFilterWrap" class="club-filter-wrap" style="display:none">
        <label class="picker-label">Competição</label>
        <div id="jgLeagueFilterList" class="club-chip-list"></div>
      </div>
      <div id="player-season-result"><div class="result-card"><div class="loading-state">Selecione um jogador acima.</div></div></div>
    </div>

    <div id="jg-partida" class="subtab-panel">
      <div class="filters-row">
        <label>Temporada
          <select id="fxSeason" onchange="loadFixtures()"></select>
        </label>
        <label>Partida
          <select id="fxFixture" onchange="loadFixturePlayer()"><option value="">Selecione o jogador primeiro</option></select>
        </label>
      </div>
      <div id="fixture-player-result"><div class="result-card"><div class="loading-state">Selecione um jogador e uma partida acima.</div></div></div>
    </div>
  </div>
</div>

<script>
const FLAG_MAP = {FLAG_MAP_JS};
const CLUB_SHORT = {CLUB_SHORT_JS};
const SEASONS = {SEASONS_JS};

function flagFor(nat) {{ return FLAG_MAP[nat] || '🏳️'; }}
function clubShort(name) {{
  if (!name) return '—';
  if (CLUB_SHORT[name]) return CLUB_SHORT[name];
  let s = name
    .replace(/\\bSaudi\\b/gi, '')
    .replace(/\\bClub\\b/gi, '')
    .replace(/\\bFC\\b/gi, '')
    .replace(/\\bSC\\b/gi, '')
    .replace(/^Al[- ]/i, '')
    .replace(/\s+/g, ' ')
    .trim();
  return s || name;
}}
function pad2(n) {{ return String(n ?? 0).padStart(2,'0'); }}

// Detalhe "[03⚽+01🅰]" das participações em gols, escondendo a parte zerada:
// "+00🅰" só ocupava espaço e dava a impressão de dado faltando.
function detalheGA(gols, assist) {{
  const g = Number(gols) || 0, a = Number(assist) || 0;
  const partes = [];
  if (g > 0) partes.push(pad2(g) + '⚽');
  if (a > 0) partes.push(pad2(a) + '\\u{{1F170}}️');
  return partes.length ? ' [' + partes.join('+') + ']' : '';
}}
function naNum(v) {{ return (v === null || v === undefined) ? 0 : v; }}
function naText(v) {{ return (v === null || v === undefined || v === '') ? 'Não informado' : v; }}
function fmtRating(v) {{
  const n = (v === null || v === undefined || isNaN(parseFloat(v))) ? 0 : parseFloat(v);
  return n.toFixed(1);
}}
function medalFor(place) {{
  const p = (place || '').toLowerCase();
  if (p.includes('1st') || p === 'winner') return '🏆';
  if (p.includes('2nd') || p.includes('runner')) return '🥈';
  if (p.includes('3rd')) return '🥉';
  return '🎖️';
}}

function rankBadges(items, valueKey) {{
  const badges = ['🥇','🥈','🥉'];
  let out = []; let lastVal = null; let lastRank = 0;
  items.forEach((it, idx) => {{
    const val = it[valueKey];
    let rank;
    if (lastVal !== null && val === lastVal) {{ rank = lastRank; }}
    else {{ rank = lastRank + 1; }}
    lastVal = val; lastRank = rank;
    let badge;
    if (rank <= 3) badge = badges[rank-1];
    else if (rank <= 9) badge = String(rank) + '️⃣';
    else if (rank === 10) badge = '🔟';
    else badge = rank + '.';
    out.push(badge);
  }});
  return out;
}}

function fillSelect(sel, items, valueKey, labelKey, placeholder) {{
  sel.innerHTML = '';
  if (placeholder) {{ const o = document.createElement('option'); o.value=''; o.textContent=placeholder; sel.appendChild(o); }}
  items.forEach(it => {{
    const o = document.createElement('option');
    o.value = it[valueKey]; o.textContent = it[labelKey];
    sel.appendChild(o);
  }});
}}

function setupSeasonSelects() {{
  ['rkSeason','stSeason','fxSeason'].forEach(id => {{
    const sel = document.getElementById(id);
    sel.innerHTML = '';
    SEASONS.forEach(y => {{
      const o = document.createElement('option');
      o.value = y; o.textContent = y + '/' + String(y+1).slice(2);
      if (y === SEASONS[0]) o.selected = true;
      sel.appendChild(o);
    }});
  }});
}}

function showTab(name, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}
// ── FIM DE JOGO ───────────────────────────────────────────────────────────
// Objetivo é velocidade: abrir a guia e copiar. A lista se atualiza sozinha, e o
// texto de cada jogo encerrado é buscado em paralelo, já pronto no card.
let _fjTimer = null;

async function carregarJogosDoDia() {{
  const lista = document.getElementById('fjLista');
  const st = document.getElementById('fjStatus');
  st.textContent = 'atualizando…';
  try {{
    const d = await fetchJSON('/api/numeros/jogos-do-dia?dias=2&_=' + Date.now());
    if (!d.jogos.length) {{
      lista.innerHTML = '<div class="result-card"><div class="loading-state">Nenhum jogo hoje nem ontem.</div></div>';
      st.textContent = '';
      return;
    }}
    lista.innerHTML = d.jogos.map(j => cardDoJogo(j)).join('');
    // Busca o texto dos encerrados em paralelo — quando chega, preenche o card.
    d.jogos.filter(j => j.encerrado).forEach(async j => {{
      try {{
        const t = await fetchJSON('/api/numeros/fim-de-jogo?fixture=' + j.fixture);
        const box = document.getElementById('fj-txt-' + j.fixture);
        if (box && t.texto) {{
          box.textContent = t.texto + (t.aviso ? '\\n\\n⚠️ ' + t.aviso : '');
          const b = document.getElementById('fj-btn-' + j.fixture);
          // Texto incompleto não ganha botão: copiar agora geraria post errado.
          // A lista se re-atualiza sozinha em 60s e tenta de novo.
          if (b && t.completo) {{ b.style.display = ''; b.onclick = () => copyBlock(b, t.texto); }}
        }}
      }} catch(e) {{}}
    }});
    st.textContent = 'atualizado ' + new Date().toLocaleTimeString('pt-BR').slice(0,5);
  }} catch(e) {{
    lista.innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
    st.textContent = '';
  }}
  clearTimeout(_fjTimer);
  _fjTimer = setTimeout(carregarJogosDoDia, 60000);
}}

function cardDoJogo(j) {{
  const placar = (j.gols_casa === null || j.gols_casa === undefined) ? 'x' : j.gols_casa + 'x' + j.gols_fora;
  let selo;
  if (j.encerrado) selo = '<span class="fj-selo fj-fim">encerrado</span>';
  else if (j.minuto !== null && j.minuto !== undefined) selo = '<span class="fj-selo fj-vivo">' + j.minuto + "'</span>";
  else selo = '<span class="fj-selo">' + (j.data || '').slice(11) + '</span>';
  return '<div class="result-card fj-card">' +
    '<div class="fj-cab">' + selo +
      '<span class="fj-conf">' + j.cor_casa + ' ' + j.casa + ' ' + placar + ' ' + j.fora + ' ' + j.cor_fora + '</span>' +
      '<button class="copy-btn" id="fj-btn-' + j.fixture + '" style="display:none">📋 Copiar</button>' +
    '</div>' +
    (j.encerrado
      ? '<pre class="fj-texto" id="fj-txt-' + j.fixture + '">gerando texto…</pre>'
      : '<div class="fj-aguardando">Em andamento — o texto aparece assim que o jogo acabar.</div>') +
  '</div>';
}}

function showSubtab(group, name, btn) {{
  const prefix = group === 'rk' ? 'rk-' : 'jg-';
  const parent = btn.closest(group === 'rk' ? '#tab-rankings' : '#tab-jogador');
  parent.querySelectorAll('.subtab-panel').forEach(p => p.classList.remove('active'));
  parent.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(prefix + name).classList.add('active');
  btn.classList.add('active');
}}

function copyBlock(btn, text) {{
  navigator.clipboard.writeText(text).then(() => {{
    const orig = btn.textContent;
    btn.textContent = '✅ Copiado!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 1800);
  }});
}}

function renderResultCard(container, title, bodyText, meta) {{
  container.innerHTML =
    '<div class="result-card">' +
    '<div class="result-head"><span class="result-title">' + title + '</span>' +
    '<button class="copy-btn" onclick="copyBlock(this, this.closest(\\'.result-card\\').dataset.copytext)">📋 Copiar</button></div>' +
    '<div class="result-pre">' + bodyText.replace(/</g,'&lt;') + '</div>' +
    (meta ? '<div class="result-meta">' + meta + '</div>' : '') +
    '</div>';
  container.querySelector('.result-card').dataset.copytext = bodyText;
}}

// copyText separa o que aparece na tela do que vai pra área de transferência: o
// cabeçalho ajuda a conferir a tabela, mas atrapalha ao colar no post/planilha.
function renderStandingsCard(container, title, bodyText, meta, columns, copyText) {{
  const colButtons = columns.map((c, i) =>
    '<button class="copy-btn col-copy-btn" data-col="' + i + '" onclick="copyColumn(this)">\\u{{1F4CB}} ' + c.key + '</button>'
  ).join('');
  container.innerHTML =
    '<div class="result-card">' +
    '<div class="result-head"><span class="result-title">' + title + '</span>' +
    '<button class="copy-btn" onclick="copyBlock(this, this.closest(\\'.result-card\\').dataset.copytext)">\\u{{1F4CB}} Copiar tudo</button></div>' +
    '<div class="col-copy-row">' + colButtons + '</div>' +
    '<div class="result-pre">' + bodyText.replace(/</g,'&lt;') + '</div>' +
    (meta ? '<div class="result-meta">' + meta + '</div>' : '') +
    '</div>';
  const card = container.querySelector('.result-card');
  card.dataset.copytext = (copyText !== undefined && copyText !== null) ? copyText : bodyText;
  card._columns = columns;
}}

function copyColumn(btn) {{
  const card = btn.closest('.result-card');
  const idx = parseInt(btn.dataset.col, 10);
  const col = card._columns[idx];
  // Sem o nome da coluna, pela mesma razão do "Copiar tudo": o que se cola é dado.
  const text = col.values.join('\\n');
  navigator.clipboard.writeText(text).then(() => {{
    const orig = btn.textContent;
    btn.textContent = '\\u2705';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 1400);
  }});
}}

async function fetchJSON(url) {{
  const r = await fetch(url);
  const d = await r.json();
  if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}}

async function getRankingRows(sortKey, path, season, team, limit) {{
  if (team !== '0') {{
    const d = await fetchJSON('/api/numeros/team-stats?team=' + team + '&season=' + season + '&sort=' + sortKey + '&limit=' + limit);
    return {{ players: d.players, teamFiltered: true, teamName: d.players.length ? d.players[0].team : '' }};
  }}
  const d = await fetchJSON('/api/numeros/' + path + '?season=' + season + '&limit=' + limit);
  return {{ players: d.players, teamFiltered: false, teamName: '' }};
}}

async function loadRankings() {{
  const season = document.getElementById('rkSeason').value;
  const team = document.getElementById('rkTeam').value;
  const limit = document.getElementById('rkLimit').value;
  const seasonLabel = season + '/' + String(Number(season)+1).slice(2);

  try {{
    const r = await getRankingRows('goals', 'topscorers', season, team, limit);
    const badges = rankBadges(r.players, 'goals');
    let txt = '⚽🇸🇦 ARTILHARIA — SAUDI PRO LEAGUE ' + seasonLabel + (r.teamFiltered ? ' · ' + clubShort(r.teamName) : '') + '\\n\\n';
    r.players.forEach((p, i) => {{
      txt += badges[i] + ' ' + flagFor(p.nationality) + ' ' + p.name + (r.teamFiltered ? '' : ' (' + clubShort(p.team) + ')') + ' - ' + naNum(p.goals) + '\\n';
    }});
    renderResultCard(document.getElementById('rk-artilharia'), 'Artilharia', txt.trim(),
      'Temporada ' + seasonLabel + ' · Saudi Pro League' + (r.teamFiltered ? ' · ranking interno completo do elenco (' + clubShort(r.teamName) + ')' : '') + ' · fonte: API-Football');
  }} catch(e) {{
    document.getElementById('rk-artilharia').innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
  }}

  try {{
    const r = await getRankingRows('assists', 'topassists', season, team, limit);
    const badges = rankBadges(r.players, 'assists');
    let txt = '\\u{{1F170}}️🇸🇦 ASSISTÊNCIAS — SAUDI PRO LEAGUE ' + seasonLabel + (r.teamFiltered ? ' · ' + clubShort(r.teamName) : '') + '\\n\\n';
    r.players.forEach((p, i) => {{
      txt += badges[i] + ' ' + flagFor(p.nationality) + ' ' + p.name + (r.teamFiltered ? '' : ' (' + clubShort(p.team) + ')') + ' - ' + naNum(p.assists) + '\\n';
    }});
    renderResultCard(document.getElementById('rk-assistencias'), 'Assistências', txt.trim(),
      'Temporada ' + seasonLabel + ' · Saudi Pro League' + (r.teamFiltered ? ' · ranking interno completo do elenco (' + clubShort(r.teamName) + ')' : '') + ' · fonte: API-Football');
  }} catch(e) {{
    document.getElementById('rk-assistencias').innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
  }}

  try {{
    const r = await getRankingRows('ga', 'goal-contributions', season, team, limit);
    const badges = rankBadges(r.players, 'ga');
    let txt = '📊🇸🇦 PARTICIPAÇÕES EM GOLS — SAUDI PRO LEAGUE ' + seasonLabel + (r.teamFiltered ? ' · ' + clubShort(r.teamName) : '') + '\\n\\n';
    r.players.forEach((p, i) => {{
      txt += badges[i] + ' ' + flagFor(p.nationality) + ' ' + p.name + (r.teamFiltered ? '' : ' (' + clubShort(p.team) + ')') + ' - ' + naNum(p.ga) + detalheGA(p.goals, p.assists) + '\\n';
    }});
    renderResultCard(document.getElementById('rk-ga'), 'Participações em Gols (G+A)', txt.trim(),
      'Temporada ' + seasonLabel + ' · Saudi Pro League' + (r.teamFiltered ? ' · ranking interno completo do elenco (' + clubShort(r.teamName) + ')' : ' · combina top-20 de artilharia e assistências') + ' · fonte: API-Football');
  }} catch(e) {{
    document.getElementById('rk-ga').innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
  }}
}}

async function loadStandings() {{
  const season = document.getElementById('stSeason').value;
  const mode = document.getElementById('stMode').value;
  const container = document.getElementById('standings-result');
  const seasonLabel = season + '/' + String(Number(season)+1).slice(2);
  try {{
    const d = await fetchJSON('/api/numeros/standings?season=' + season);
    const n = mode === 'all' ? d.table.length : parseInt(mode, 10);
    const rows = d.table.slice(0, n);
    const label = mode === 'all' ? 'CLASSIFICAÇÃO COMPLETA' : 'G' + n;
    let linhas = '';
    rows.forEach(r => {{
      linhas += r.rank + '\\t' + clubShort(r.team).toUpperCase() + '\\t' + naNum(r.points) + '\\t' + naNum(r.played) + '\\t' + naNum(r.wins) + '\\t' + naNum(r.goals_diff) + '\\n';
    }});
    const txt = label + ' — SAUDI PRO LEAGUE ' + seasonLabel + '\\n\\n'
              + 'POS\\tTIME\\tPTS\\tJ\\tV\\tSG\\n' + linhas;
    const columns = [
      {{ key: 'POS', values: rows.map(r => String(r.rank)) }},
      {{ key: 'TIME', values: rows.map(r => clubShort(r.team).toUpperCase()) }},
      {{ key: 'PTS', values: rows.map(r => String(naNum(r.points))) }},
      {{ key: 'J', values: rows.map(r => String(naNum(r.played))) }},
      {{ key: 'V', values: rows.map(r => String(naNum(r.wins))) }},
      {{ key: 'SG', values: rows.map(r => String(naNum(r.goals_diff))) }},
    ];
    renderStandingsCard(container, label, txt.trim(),
      'Temporada ' + seasonLabel + ' · Saudi Pro League · formato tabulado (TSV) — cole direto em planilha ou Canva · fonte: API-Football',
      columns, linhas.trim());
  }} catch(e) {{
    container.innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
  }}
}}

let jgAllTeams = [];
let jgSelectedTeam = null;
let jgSelectedPlayer = null;
let jgPlayerSearchTimer = null;
let _lastPlayerResults = [];

function renderClubResults(list) {{
  const box = document.getElementById('jgClubResults');
  if (!list.length) {{ box.innerHTML = '<div class="search-empty">Nenhum clube encontrado.</div>'; box.style.display = 'block'; return; }}
  box.innerHTML = list.map(t =>
    '<div class="search-item" onclick="selectClub(' + t.id + ')">' +
    '<img src="' + (t.logo||'') + '" class="search-crest" onerror="this.style.visibility=\\'hidden\\'">' +
    '<span>' + t.name + '</span></div>'
  ).join('');
  box.style.display = 'block';
}}

function onClubSearchInput() {{
  const q = document.getElementById('jgClubSearch').value.trim().toLowerCase();
  if (!q) {{ document.getElementById('jgClubResults').style.display = 'none'; return; }}
  const matches = jgAllTeams.filter(t => t.name.toLowerCase().includes(q)).slice(0, 8);
  renderClubResults(matches);
}}

function selectClub(id) {{
  const t = jgAllTeams.find(x => x.id === id);
  if (!t) return;
  jgSelectedTeam = t;
  document.getElementById('jgClubSearch').value = '';
  document.getElementById('jgClubResults').style.display = 'none';
  document.getElementById('jgClubResults').innerHTML = '';
  const chip = document.getElementById('jgClubSelected');
  chip.style.display = 'flex';
  chip.innerHTML = '<img src="' + (t.logo||'') + '" class="search-crest"><span>' + t.name + '</span>' +
    '<button type="button" class="chip-clear" onclick="clearClub()">✕</button>';
  if (!document.getElementById('jgPlayerSearch').value.trim()) loadSquadPreview();
}}

function clearClub() {{
  jgSelectedTeam = null;
  document.getElementById('jgClubSelected').style.display = 'none';
  document.getElementById('jgClubSelected').innerHTML = '';
  if (!document.getElementById('jgPlayerSearch').value.trim()) {{
    document.getElementById('jgPlayerResults').style.display = 'none';
    document.getElementById('jgPlayerResults').innerHTML = '';
  }}
}}

async function loadSquadPreview() {{
  if (!jgSelectedTeam) return;
  const box = document.getElementById('jgPlayerResults');
  box.innerHTML = '<div class="search-empty">Carregando elenco…</div>';
  box.style.display = 'block';
  try {{
    const d = await fetchJSON('/api/numeros/squad?team=' + jgSelectedTeam.id);
    renderPlayerResults(d.players.map(p => ({{ player_id: p.id, name: p.name, photo: p.photo, team: jgSelectedTeam.name, team_id: jgSelectedTeam.id, team_logo: jgSelectedTeam.logo }})));
  }} catch(e) {{
    box.innerHTML = '<div class="search-empty">Erro ao carregar elenco.</div>';
  }}
}}

// A API devolve o nome abreviado ("A. Lacazette") — mostrar o nome por extenso ao
// lado evita a dúvida de qual "A." é, principalmente com sobrenomes repetidos.
function nomeExibido(p) {{
  const completo = (p.full_name || '').trim();
  if (!completo || completo === p.name) return p.name;
  return p.name + ' <small class="nome-completo">· ' + completo + '</small>';
}}

function renderPlayerResults(list) {{
  _lastPlayerResults = list;
  const box = document.getElementById('jgPlayerResults');
  if (!list.length) {{ box.innerHTML = '<div class="search-empty">Nenhum jogador encontrado.</div>'; box.style.display = 'block'; return; }}
  box.innerHTML = list.map((p, i) =>
    '<div class="search-item" onclick="selectPlayerByIndex(' + i + ')">' +
    (p.photo ? '<img src="' + p.photo + '" class="search-avatar" onerror="this.style.visibility=\\'hidden\\'">' : '<span class="search-avatar-ph"></span>') +
    '<span>' + nomeExibido(p) + (p.team ? ' <small>(' + p.team + ')</small>' : '') + '</span></div>'
  ).join('');
  box.style.display = 'block';
}}

function onPlayerSearchInput() {{
  const q = document.getElementById('jgPlayerSearch').value.trim();
  clearTimeout(jgPlayerSearchTimer);
  if (!q) {{
    if (jgSelectedTeam) {{ loadSquadPreview(); }} else {{
      document.getElementById('jgPlayerResults').style.display = 'none';
      document.getElementById('jgPlayerResults').innerHTML = '';
    }}
    return;
  }}
  if (q.length < 3) {{
    const box = document.getElementById('jgPlayerResults');
    box.innerHTML = '<div class="search-empty">Digite ao menos 3 letras…</div>';
    box.style.display = 'block';
    return;
  }}
  jgPlayerSearchTimer = setTimeout(async () => {{
    const season = SEASONS[0];
    const box = document.getElementById('jgPlayerResults');
    box.innerHTML = '<div class="search-empty">Buscando…</div>';
    box.style.display = 'block';
    try {{
      let url = '/api/numeros/player-search?q=' + encodeURIComponent(q) + '&season=' + season;
      if (jgSelectedTeam) url += '&team=' + jgSelectedTeam.id;
      const d = await fetchJSON(url);
      renderPlayerResults(d.players);
    }} catch(e) {{
      box.innerHTML = '<div class="search-empty">' + e.message + '</div>';
    }}
  }}, 350);
}}

function selectPlayerByIndex(i) {{ selectPlayer(_lastPlayerResults[i]); }}

let jgCareerTeamIds = [];
let jgPlayerClubs = [];
let jgSelectedSeasons = [];
let jgPlayerLeagues = [];
let jgAllSeasons = [];
let jgSelectedLeagueId = null;
let jgCombos = [];

async function selectPlayer(p) {{
  jgSelectedPlayer = p;
  document.getElementById('jgPlayerSearch').value = '';
  document.getElementById('jgPlayerResults').style.display = 'none';
  document.getElementById('jgPlayerResults').innerHTML = '';
  const chip = document.getElementById('jgPlayerSelected');
  chip.style.display = 'flex';
  chip.innerHTML = (p.photo ? '<img src="' + p.photo + '" class="search-avatar">' : '') +
    '<span>' + ((p.full_name || '').trim() || p.name) + (p.team ? ' (' + p.team + ')' : '') + '</span>' +
    '<button type="button" class="chip-clear" onclick="clearPlayer()">✕</button>';
  jgCareerTeamIds = [];
  jgSelectedSeasons = [];
  jgSelectedLeagueId = null;
  await loadPlayerFacets();
  loadPlayerSeason();
  loadFixtures();
}}

function clearPlayer() {{
  jgSelectedPlayer = null;
  jgCareerTeamIds = [];
  jgPlayerClubs = [];
  jgSelectedSeasons = [];
  jgPlayerLeagues = [];
  jgAllSeasons = [];
  jgSelectedLeagueId = null;
  jgCombos = [];
  document.getElementById('jgPlayerSelected').style.display = 'none';
  document.getElementById('jgPlayerSelected').innerHTML = '';
  document.getElementById('jgClubFilterWrap').style.display = 'none';
  document.getElementById('jgClubFilterList').innerHTML = '';
  document.getElementById('jgSeasonFilterWrap').style.display = 'none';
  document.getElementById('jgSeasonFilterList').innerHTML = '';
  document.getElementById('jgLeagueFilterWrap').style.display = 'none';
  document.getElementById('jgLeagueFilterList').innerHTML = '';
  document.getElementById('player-season-result').innerHTML = '<div class="result-card"><div class="loading-state">Selecione um jogador acima.</div></div>';
  document.getElementById('fixture-player-result').innerHTML = '<div class="result-card"><div class="loading-state">Selecione um jogador e uma partida acima.</div></div>';
  document.getElementById('fxFixture').innerHTML = '<option value="">Selecione o jogador primeiro</option>';
}}

async function loadPlayerFacets() {{
  const wraps = ['jgClubFilterWrap','jgSeasonFilterWrap','jgLeagueFilterWrap'];
  if (!jgSelectedPlayer) {{ wraps.forEach(w => document.getElementById(w).style.display = 'none'); return; }}
  const requestedFor = jgSelectedPlayer.player_id;
  wraps.forEach(w => document.getElementById(w).style.display = 'block');
  document.getElementById('jgClubFilterList').innerHTML = '<div class="search-empty">Carregando filtros do jogador…</div>';
  document.getElementById('jgSeasonFilterList').innerHTML = '';
  document.getElementById('jgLeagueFilterList').innerHTML = '';
  try {{
    const d = await fetchJSON('/api/numeros/player-facets?player=' + requestedFor + '&_=' + Date.now());
    if (!jgSelectedPlayer || jgSelectedPlayer.player_id !== requestedFor) return;  // jogador trocou enquanto isso carregava
    jgPlayerClubs = d.clubs;
    jgPlayerLeagues = d.leagues;
    jgAllSeasons = d.seasons;
    jgCombos = d.combos;
    if (!jgCombos.length) {{
      document.getElementById('jgClubFilterList').innerHTML = '<div class="search-empty">Nenhum dado encontrado pra esse jogador nas temporadas disponíveis.</div>';
      return;
    }}
    renderAllFilters();
  }} catch(e) {{
    if (!jgSelectedPlayer || jgSelectedPlayer.player_id !== requestedFor) return;
    document.getElementById('jgClubFilterList').innerHTML = '<div class="search-empty">Erro ao carregar filtros do jogador.</div>';
  }}
}}

// Opções realmente possíveis de um filtro, considerando SÓ os outros dois.
// É isso que faz o cruzamento valer nos dois sentidos: escolher um clube encolhe
// temporadas e competições, e escolher uma competição encolhe os clubes.
function availableFor(facet) {{
  const out = new Set();
  jgCombos.forEach(c => {{
    if (facet !== 'club' && jgCareerTeamIds.length && !jgCareerTeamIds.includes(c.team)) return;
    if (facet !== 'season' && jgSelectedSeasons.length && !jgSelectedSeasons.includes(c.season)) return;
    if (facet !== 'league' && jgSelectedLeagueId !== null && c.league !== jgSelectedLeagueId) return;
    out.add(facet === 'club' ? c.team : (facet === 'season' ? c.season : c.league));
  }});
  return out;
}}

// Se uma escolha antiga deixou de ser possível por causa do que acabou de mudar,
// ela é solta (volta pra "Todos") em vez de travar a tela num cruzamento vazio.
function pruneFilters(changed) {{
  ['club','season','league'].forEach(f => {{
    if (f === changed) return;
    const ok = availableFor(f);
    if (f === 'club') jgCareerTeamIds = jgCareerTeamIds.filter(id => ok.has(id));
    else if (f === 'season') jgSelectedSeasons = jgSelectedSeasons.filter(y => ok.has(y));
    else if (jgSelectedLeagueId !== null && !ok.has(jgSelectedLeagueId)) jgSelectedLeagueId = null;
  }});
}}

function renderAllFilters() {{
  renderClubFilterList();
  renderSeasonFilterList();
  renderLeagueFilterList();
}}

function applyFilterChange(changed) {{
  pruneFilters(changed);
  renderAllFilters();
  loadPlayerSeason();
}}

function renderClubFilterList() {{
  const list = document.getElementById('jgClubFilterList');
  const ok = availableFor('club');
  const allChecked = jgCareerTeamIds.length === 0;
  let html = '<div class="club-chip-item' + (allChecked ? ' checked' : '') + '" onclick="setClubsAll()"><span>Todos</span></div>';
  html += jgPlayerClubs.filter(c => ok.has(c.id)).map(c => {{
    const checked = jgCareerTeamIds.includes(c.id);
    return '<label class="club-chip-item' + (checked ? ' checked' : '') + '">' +
      '<input type="checkbox" ' + (checked ? 'checked' : '') + ' onchange="onClubFilterToggle(' + c.id + ', this.checked)">' +
      (c.logo ? '<img src="' + c.logo + '">' : '') + '<span>' + c.name + '</span></label>';
  }}).join('');
  list.innerHTML = html;
}}

function setClubsAll() {{
  jgCareerTeamIds = [];  // desmarca os individuais; vazio = todos
  applyFilterChange('club');
}}

function onClubFilterToggle(teamId, isChecked) {{
  if (isChecked) {{
    if (!jgCareerTeamIds.includes(teamId)) jgCareerTeamIds.push(teamId);
  }} else {{
    jgCareerTeamIds = jgCareerTeamIds.filter(id => id !== teamId);
  }}
  applyFilterChange('club');
}}

function renderSeasonFilterList() {{
  const list = document.getElementById('jgSeasonFilterList');
  const ok = availableFor('season');
  const allChecked = jgSelectedSeasons.length === 0;
  let html = '<div class="club-chip-item' + (allChecked ? ' checked' : '') + '" onclick="setSeasonsAll()"><span>Todas</span></div>';
  html += jgAllSeasons.filter(y => ok.has(y)).map(y => {{
    const checked = jgSelectedSeasons.includes(y);
    return '<label class="club-chip-item' + (checked ? ' checked' : '') + '">' +
      '<input type="checkbox" ' + (checked ? 'checked' : '') + ' onchange="onSeasonToggle(' + y + ', this.checked)">' +
      '<span>' + y + '/' + String(y + 1).slice(2) + '</span></label>';
  }}).join('');
  list.innerHTML = html;
}}

function setSeasonsAll() {{
  jgSelectedSeasons = [];
  applyFilterChange('season');
}}

function onSeasonToggle(year, isChecked) {{
  if (isChecked) {{
    if (!jgSelectedSeasons.includes(year)) jgSelectedSeasons.push(year);
  }} else {{
    jgSelectedSeasons = jgSelectedSeasons.filter(y => y !== year);
  }}
  applyFilterChange('season');
}}

function renderLeagueFilterList() {{
  const list = document.getElementById('jgLeagueFilterList');
  const ok = availableFor('league');
  let html = '<div class="club-chip-item' + (jgSelectedLeagueId === null ? ' checked' : '') + '" onclick="setLeagueFilter(null)"><span>Todas</span></div>';
  html += jgPlayerLeagues.filter(l => ok.has(l.id)).map(l => {{
    const checked = jgSelectedLeagueId === l.id;
    return '<div class="club-chip-item' + (checked ? ' checked' : '') + '" onclick="setLeagueFilter(' + l.id + ')"><span>' + l.name + '</span></div>';
  }}).join('');
  list.innerHTML = html;
}}

function setLeagueFilter(id) {{
  jgSelectedLeagueId = id;
  applyFilterChange('league');
}}

document.addEventListener('click', function(e) {{
  if (!e.target.closest('.search-combo')) {{
    const cr = document.getElementById('jgClubResults'); if (cr) cr.style.display = 'none';
    const pr = document.getElementById('jgPlayerResults'); if (pr && !jgSelectedTeam) pr.style.display = 'none';
  }}
}});

async function loadPlayerSeason() {{
  const container = document.getElementById('player-season-result');
  if (!jgSelectedPlayer) {{ container.innerHTML = '<div class="result-card"><div class="loading-state">Selecione um jogador acima.</div></div>'; return; }}
  const requestedFor = jgSelectedPlayer.player_id;
  container.innerHTML = '<div class="result-card"><div class="loading-state">Carregando…</div></div>';
  const player = requestedFor;
  const teamsParam = jgCareerTeamIds.join(',');
  const seasonsParam = jgSelectedSeasons.join(',');
  const leagueParam = jgSelectedLeagueId === null ? '' : String(jgSelectedLeagueId);
  try {{
    let url = '/api/numeros/player-stats?player=' + player + '&_=' + Date.now();
    if (teamsParam) url += '&teams=' + teamsParam;
    if (seasonsParam) url += '&seasons=' + seasonsParam;
    if (leagueParam) url += '&league=' + encodeURIComponent(leagueParam);
    const d = await fetchJSON(url);
    if (!jgSelectedPlayer || jgSelectedPlayer.player_id !== requestedFor) return;  // jogador trocou enquanto isso carregava
    const s = d.stats;
    const seasons = d.seasons || [];
    const seasonLabel = seasons.length <= 1
      ? (seasons.length ? (seasons[0] + '/' + String(seasons[0] + 1).slice(2)) : 'todas')
      : (seasons[0] + '/' + String(seasons[0] + 1).slice(2)) + ' a ' + (seasons[seasons.length - 1] + '/' + String(seasons[seasons.length - 1] + 1).slice(2));
    const teamsLabel = d.teams && d.teams.length ? d.teams.map(t => clubShort(t)).join(' + ') : 'todos os times';
    const leagueLabel = (d.leagues && d.leagues.length === 1) ? d.leagues[0].name : ((d.leagues && d.leagues.length > 1) ? 'várias competições' : 'todas as competições');
    let txt = flagFor(d.nationality) + ' ' + d.name + ' pelo ' + teamsLabel + ' — ' + leagueLabel + ' (' + seasonLabel + '):\\n\\n';
    txt += '⚔️ ' + naNum(s.appearences) + ' jogos\\n';
    txt += '✅ ' + naNum(s.ga) + ' participações em gols\\n';
    txt += '⚽ ' + naNum(s.goals) + ' gols\\n';
    txt += '\\u{{1F170}}️ ' + naNum(s.assists) + ' assistências\\n';
    txt += '⭐ Nota média: ' + fmtRating(s.rating) + '\\n';
    txt += '🟨 ' + naNum(s.yellow_cards) + ' amarelos 🟥 ' + naNum(s.red_cards) + ' vermelhos\\n';
    if (d.titles && d.titles.length) {{
      txt += '\\nTítulos:\\n';
      d.titles.forEach(ti => {{ txt += medalFor(ti.place) + ' ' + ti.league + ' ' + ti.season + '\\n'; }});
    }}
    if (d.competicoes_reconstruidas && d.competicoes_reconstruidas.length) {{
      txt += '\\nℹ️ ' + d.competicoes_reconstruidas.join(', ') +
             ': a API-Football não publica estatística por jogador nessa edição, ' +
             'então jogos, gols e cartões foram contados por nós partida a partida ' +
             '(escalações + eventos). Minutos e nota não entram nessa contagem.';
    }}
    if (d.competicoes_sem_dados && d.competicoes_sem_dados.length) {{
      txt += '\\n⚠️ Fora da conta: ' + d.competicoes_sem_dados.join(', ') +
             '. A API-Football registra a participação, mas não tem estatísticas por jogador nessa edição — ' +
             'preferimos não somar a inventar número.';
    }}
    renderResultCard(container, 'Estatísticas', txt.trim(),
      'Temporada(s) ' + seasonLabel + ' · ' + teamsLabel + ' · ' + leagueLabel + (d.titles && d.titles.length ? ' · títulos: cruzamento por temporada + competição plausível, não por clube exato' : '') + (d.competicoes_sem_dados && d.competicoes_sem_dados.length ? ' · ⚠️ ' + d.competicoes_sem_dados.length + ' competição(ões) sem dados na fonte' : '') + ' · fonte: API-Football');
  }} catch(e) {{
    if (!jgSelectedPlayer || jgSelectedPlayer.player_id !== requestedFor) return;
    container.innerHTML = '<div class="result-card"><div class="error-state">' + (e.message || 'Nenhum dado encontrado pra essa combinação de filtros.') + '</div></div>';
  }}
}}

async function loadFixtures() {{
  const fxSel = document.getElementById('fxFixture');
  if (!jgSelectedPlayer) {{ fxSel.innerHTML = '<option value="">Selecione o jogador primeiro</option>'; return; }}
  const player = jgSelectedPlayer.player_id;
  const team = jgSelectedPlayer.team_id;
  if (!team) {{ fxSel.innerHTML = '<option value="">Time do jogador não disponível</option>'; return; }}
  const season = document.getElementById('fxSeason').value;
  fxSel.innerHTML = '<option value="">Carregando partidas do jogador…</option>';
  try {{
    const d = await fetchJSON('/api/numeros/player-fixtures?player=' + player + '&team=' + team + '&season=' + season);
    if (!d.fixtures.length) {{
      fxSel.innerHTML = '<option value="">Nenhuma partida encontrada nesta temporada</option>';
      return;
    }}
    const items = d.fixtures.map(f => ({{
      id: f.fixture_id,
      label: f.date + ' · ' + f.home + ' ' + naNum(f.goals_home) + 'x' + naNum(f.goals_away) + ' ' + f.away + ' (' + (f.round||'') + ')'
    }}));
    fillSelect(fxSel, items, 'id', 'label', 'Selecione a partida');
  }} catch(e) {{
    fxSel.innerHTML = '<option value="">Erro ao carregar partidas</option>';
  }}
}}

async function loadFixturePlayer() {{
  const fixture = document.getElementById('fxFixture').value;
  const container = document.getElementById('fixture-player-result');
  if (!fixture || !jgSelectedPlayer) return;
  const player = jgSelectedPlayer.player_id;
  container.innerHTML = '<div class="result-card"><div class="loading-state">Carregando…</div></div>';
  try {{
    const d = await fetchJSON('/api/numeros/fixture-player?fixture=' + fixture + '&player=' + player);
    let txt = d.name + ' — ' + naText(d.team) + '\\n\\n';
    txt += '⏱️ ' + naNum(d.minutes) + ' min em campo (' + naText(d.position) + ')\\n';
    txt += '⭐ Nota: ' + fmtRating(d.rating) + '\\n';
    txt += '⚽ Gols: ' + naNum(d.goals) + '  \\u{{1F170}}️ Assistências: ' + naNum(d.assists) + '\\n';
    if (d.goals_conceded !== null || d.saves !== null) {{
      txt += '🧤 ' + naNum(d.goals_conceded) + ' gols sofridos · ' + naNum(d.saves) + ' defesas\\n';
    }}
    txt += '🎯 Finalizações: ' + naNum(d.shots_on) + '/' + naNum(d.shots_total) + ' no alvo\\n';
    txt += '📈 Passes: ' + naNum(d.passes_total) + ' (' + naNum(d.passes_accuracy) + '% de acerto)\\n';
    txt += '🤝 Duelos vencidos: ' + naNum(d.duels_won) + '/' + naNum(d.duels_total) + '\\n';
    txt += '👊 Faltas sofridas: ' + naNum(d.fouls_drawn) + '\\n';
    if (d.yellow_cards) txt += '🟨 Cartão amarelo\\n';
    if (d.red_cards) txt += '🟥 Cartão vermelho\\n';
    renderResultCard(container, 'Estatísticas na partida', txt.trim(), 'Fonte: API-Football (dados por partida)');
  }} catch(e) {{
    container.innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
  }}
}}

async function init() {{
  setupSeasonSelects();
  try {{
    const meta = await fetchJSON('/api/numeros/meta?season=' + SEASONS[0]);
    jgAllTeams = meta.teams;
    fillSelect(document.getElementById('rkTeam'), [{{id:0,name:'Todos'}}, ...meta.teams], 'id', 'name', null);
  }} catch(e) {{}}
  loadRankings();
  loadStandings();
}}

init();
</script>
</body></html>
"""
    return HTMLResponse(html)


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
    CATEGORY_TEXT_L = {
        "mercado": "Mercado", "financas": "Finanças",
        "competicao": "Competição", "entrevista": "Entrevista",
        "lesao": "Lesão", "treino": "Treino", "geral": "Geral",
    }
    CATEGORY_EMOJI_L = {
        "mercado": "🔀", "financas": "💰", "entrevista": "🎙️",
        "competicao": "🏆", "treino": "🏋️", "lesao": "🩺", "geral": "📰",
    }
    ICO_RESTORE_L = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>'
    ICO_COPY_L = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'

    cards = ""
    for a in articles:
        handle       = a.get("source_name", "").lstrip("@")
        body_raw     = a.get("body_pt") or a.get("body_orig") or ""
        body_full    = body_raw
        category     = a.get("category") or "geral"
        category_txt = CATEGORY_TEXT_L.get(category, "Geral")
        cat_emoji    = CATEGORY_EMOJI_L.get(category, "📰")
        art_id       = a["id"]
        article_url  = (a.get("url") or "#").replace('"', "&quot;")
        copy_text    = body_raw
        copy_safe    = copy_text.replace("&","&amp;").replace('"',"&quot;")
        moon         = SOURCE_MOON.get(handle, {"A": "🌕", "B": "🌖", "C": "🌗"}.get(a.get("source_tier", ""), ""))
        # Date
        date_display = ""
        pub_raw = a.get("published_at") or a.get("collected_at") or a.get("trashed_at") or ""
        if pub_raw:
            try:
                dt = datetime.fromisoformat(pub_raw.replace("Z","+00:00").replace(" ","T").split("+")[0]+"+00:00")
                dt_local = dt.astimezone(timezone(timedelta(hours=3)))
                date_display = f"{dt_local.day} {MONTHS_PT[dt_local.month-1]} · {dt_local.strftime('%H:%M')}"
            except Exception:
                pass

        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-top">
              <span class="cat-badge cat-{category}">{cat_emoji} {category_txt}</span>
              <div class="card-flags">
                <button class="flag-circle restore-circ" onclick="restoreCard('{art_id}',this)" title="Restaurar">{ICO_RESTORE_L}</button>
              </div>
            </div>
            <p class="card-text" data-url="{article_url}" onclick="if(this.dataset.url&&this.dataset.url!='#')window.open(this.dataset.url,'_blank')" style="cursor:pointer">{body_full}</p>
            <div class="card-bottom">
              <div class="card-meta">
                <img class="author-avatar" src="https://unavatar.io/twitter/{handle}" alt="@{handle}" onerror="this.style.display='none'">
                <span class="tag">@{handle}</span>
                <span class="tag">{moon}</span>
                <span class="card-date">{date_display}</span>
              </div>
              <div class="card-actions">
                <button class="flag-circle copy-btn" data-copy="{copy_safe}" onclick="copyFromBtn(this)" title="Copiar">{ICO_COPY_L}</button>
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
    /* Card same as home */
    .card {{
      background: var(--c-bg-card); border-radius: 16px;
      display: flex; flex-direction: column;
      transition: background .2s;
      background: #fff1f2;
      --c-bg: #edeae4; --c-bg-card: #fff1f2; --c-bg-soft: #fff; --c-text: #1a1a1a;
      --c-muted-1: #999; --c-muted-2: #aaa; --c-muted-3: #777; --c-muted-4: #555;
      --c-muted-5: #666; --c-muted-6: #444; --c-line: #ccc;
      --c-border: rgba(0,0,0,.1); --c-border-2: rgba(0,0,0,.18); --c-hover-tint: rgba(0,0,0,.04);
    }}
    .card-body {{ padding: 20px; display: flex; flex-direction: column; }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }}
    .card-flags {{ display: flex; gap: 7px; }}
    .cat-badge {{
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.6rem; font-weight: 700; padding: 3px 9px; border-radius: 99px;
      text-transform: uppercase; letter-spacing: 0.05em;
      background: #f1f5f9; color: #475569;
    }}
    .cat-mercado    {{ background:#dbeafe; color:#1d4ed8; }}
    .cat-financas   {{ background:#fdf4ff; color:#7e22ce; }}
    .cat-entrevista {{ background:#fef3c7; color:#b45309; }}
    .cat-competicao {{ background:#fef9c3; color:#a16207; }}
    .cat-treino     {{ background:#f0fdf4; color:#166534; }}
    .cat-lesao      {{ background:#fff1f2; color:#be123c; }}
    .cat-geral      {{ background:#f1f5f9; color:#475569; }}
    .card-date {{ font-size:0.65rem; font-weight:700; color:var(--c-muted-2); text-transform:uppercase; letter-spacing:0.07em; }}
    .card-text {{ font-size: 0.8rem; color: var(--c-muted-5); line-height: 1.6; margin: 0; }}
    .card-bottom {{ display:flex; align-items:center; justify-content:space-between; margin-top:12px; padding-top:12px; border-top:1px solid rgba(0,0,0,.07); }}
    .card-meta {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .card-actions {{ display:flex; gap:7px; }}
    .tag {{ font-size:0.6rem; font-weight:700; color:var(--c-muted-3); border:1px solid var(--c-line); border-radius:99px; padding:3px 9px; text-transform:uppercase; letter-spacing:0.05em; }}
    .author-avatar {{ width:20px; height:20px; border-radius:50%; object-fit:cover; }}
    .flag-circle {{
      width: 28px; height: 28px; border-radius: 50%;
      border: 1.5px solid var(--c-border-2); background: var(--c-bg-soft);
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; transition: all .15s; color: var(--c-muted-4);
    }}
    .flag-circle:hover {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}
    .restore-circ {{ border-color: #be123c; color: #be123c; }}
    .restore-circ:hover {{ background: #be123c; color: #fff; border-color: #be123c; }}
    .removing {{ opacity:0; transform:scale(.95); transition:all .3s; pointer-events:none; }}
  </style>
</head>
<body>
{_header("/lixeira")}
<p class="info">{len(articles)} na lixeira · descartados recentes</p>
<div class="grid">
  {cards if cards else empty}
</div>
<script>
  async function restoreCard(id, btn) {{
    const card = btn.closest('.card');
    card.classList.add('removing');
    await fetch('/api/flag', {{
      method:'POST', headers:{{'content-type':'application/json'}},
      body: JSON.stringify({{ id, flag: null }}),
    }});
    setTimeout(() => card.remove(), 300);
  }}
  function copyFromBtn(btn) {{
    const txt = btn.dataset.copy || '';
    navigator.clipboard.writeText(txt).catch(() => {{}});
    btn.style.background = '#16a34a';
    btn.style.color = '#fff';
    setTimeout(() => {{ btn.style.background=''; btn.style.color=''; }}, 900);
  }}
</script>
</body></html>""")


@app.get("/analise", response_class=HTMLResponse)
async def analise_page():
    articles = get_flagged_articles("analise")
    MONTHS_PT = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    CAT_TEXT_A  = {"mercado":"Mercado","financas":"Finanças","competicao":"Competição","entrevista":"Entrevista","lesao":"Lesão","treino":"Treino","geral":"Geral"}
    CAT_EMOJI_A = {"mercado":"🔀","financas":"💰","entrevista":"🎙️","competicao":"🏆","treino":"🏋️","lesao":"🩺","geral":"📰"}
    ICO_COPY_A  = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    ICO_CLOSE_A = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'

    cards = ""
    for a in articles:
        handle       = a.get("source_name", "").lstrip("@")
        body_raw     = a.get("body_pt") or a.get("body_orig") or ""
        body_full    = body_raw
        category     = a.get("category") or "geral"
        category_txt = CAT_TEXT_A.get(category, "Geral")
        cat_emoji    = CAT_EMOJI_A.get(category, "📰")
        art_id       = a["id"]
        article_url  = (a.get("url") or "#").replace('"', "&quot;")
        copy_safe    = body_raw.replace("&","&amp;").replace('"','&quot;')
        moon         = SOURCE_MOON.get(handle, {"A":"🌕","B":"🌖","C":"🌗"}.get(a.get("source_tier",""),""))
        comment      = (a.get("flag_comment") or "").strip()
        date_display = ""
        pub_raw = a.get("flagged_at") or a.get("published_at") or a.get("collected_at") or ""
        if pub_raw:
            try:
                dt = datetime.fromisoformat(str(pub_raw).replace(" ","T").replace("Z","+00:00").split("+")[0]+"+00:00")
                dt_local = dt.astimezone(timezone(timedelta(hours=3)))
                date_display = f"{dt_local.day} {MONTHS_PT[dt_local.month-1]} · {dt_local.strftime('%H:%M')}"
            except Exception:
                pass
        if comment:
            comment_html = f'<p class="card-comment">💬 {comment}</p>'
        else:
            cid = f"ci-{art_id}"
            comment_html = (
                f'<div class="card-comment-add">'
                f'<input type="text" class="comment-input" id="{cid}" placeholder="Motivo / observação…"'
                f' onkeydown="if(event.key===\'Enter\')saveCommentA(\'{art_id}\',this)">'
                f'<button class="comment-save-btn" onclick="saveCommentA(\'{art_id}\',document.getElementById(\'{cid}\'))">Salvar</button>'
                f'</div>'
            )

        cards += f"""
        <div class="card" data-id="{art_id}">
          <div class="card-body">
            <div class="card-top">
              <span class="cat-badge cat-{category}">{cat_emoji} {category_txt}</span>
              <div class="card-flags">
                <button class="flag-circle remove-circ" onclick="removeCardA('{art_id}',this)" title="Remover da análise">{ICO_CLOSE_A}</button>
              </div>
            </div>
            <p class="card-text" data-url="{article_url}" onclick="if(this.dataset.url&&this.dataset.url!='#')window.open(this.dataset.url,'_blank')" style="cursor:pointer">{body_full}</p>
            {comment_html}
            <div class="card-bottom">
              <div class="card-meta">
                <img class="author-avatar" src="https://unavatar.io/twitter/{handle}" alt="@{handle}" onerror="this.style.display='none'">
                <span class="tag">@{handle}</span>
                <span class="tag">{moon}</span>
                <span class="card-date">{date_display}</span>
              </div>
              <div class="card-actions">
                <button class="flag-circle copy-btn" data-copy="{copy_safe}" onclick="copyFromBtnA(this)" title="Copiar">{ICO_COPY_A}</button>
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
    .info-bar {{ display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; padding:14px 24px 6px; }}
    .info {{ font-size:0.65rem; font-weight:700; color:var(--c-muted-2); text-transform:uppercase; letter-spacing:0.07em; }}
    .export-btn {{ font-size:0.62rem; font-weight:700; padding:6px 14px; border-radius:99px; cursor:pointer; border:1.5px solid var(--c-text); background:transparent; color:var(--c-text); text-transform:uppercase; letter-spacing:.05em; text-decoration:none; display:inline-flex; align-items:center; gap:5px; transition:all .15s; }}
    .export-btn:hover {{ background:var(--c-text); color:var(--c-bg); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:10px; padding:10px 24px 60px; align-items:start; }}
    .card {{
      background:#fefce8; border-radius:16px; display:flex; flex-direction:column; transition:background .2s;
      --c-bg:#edeae4; --c-bg-card:#fefce8; --c-bg-soft:#fff; --c-text:#1a1a1a;
      --c-muted-1:#999; --c-muted-2:#aaa; --c-muted-3:#777; --c-muted-4:#555;
      --c-muted-5:#666; --c-muted-6:#444; --c-line:#ccc;
      --c-border:rgba(0,0,0,.1); --c-border-2:rgba(0,0,0,.18); --c-hover-tint:rgba(0,0,0,.04);
    }}
    .card-body {{ padding:20px; display:flex; flex-direction:column; }}
    .card-top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }}
    .card-flags {{ display:flex; gap:7px; }}
    .cat-badge {{ display:inline-flex; align-items:center; gap:4px; font-size:0.6rem; font-weight:700; padding:3px 9px; border-radius:99px; text-transform:uppercase; letter-spacing:0.05em; background:#f1f5f9; color:#475569; }}
    .cat-mercado    {{ background:#dbeafe; color:#1d4ed8; }}
    .cat-financas   {{ background:#fdf4ff; color:#7e22ce; }}
    .cat-entrevista {{ background:#fef3c7; color:#b45309; }}
    .cat-competicao {{ background:#fef9c3; color:#a16207; }}
    .cat-treino     {{ background:#f0fdf4; color:#166534; }}
    .cat-lesao      {{ background:#fff1f2; color:#be123c; }}
    .cat-geral      {{ background:#f1f5f9; color:#475569; }}
    .card-date {{ font-size:0.65rem; font-weight:700; color:var(--c-muted-2); text-transform:uppercase; letter-spacing:0.07em; }}
    .card-text {{ font-size:0.8rem; color:var(--c-muted-5); line-height:1.6; margin:0; }}
    .card-comment {{ font-size:0.78rem; color:#92400e; background:#fef3c7; border-radius:8px; padding:8px 10px; margin-top:10px; line-height:1.5; }}
    .card-comment-add {{ display:flex; gap:6px; margin-top:10px; }}
    .comment-input {{ flex:1; border:1px solid var(--c-border-2); border-radius:8px; padding:6px 10px; font-size:0.76rem; font-family:inherit; background:var(--c-hover-tint); color:var(--c-text); }}
    .comment-input:focus {{ outline:none; border-color:#92400e; }}
    .comment-save-btn {{ background:transparent; border:1.5px solid #92400e; color:#92400e; border-radius:8px; padding:6px 12px; font-size:0.7rem; font-weight:700; cursor:pointer; text-transform:uppercase; letter-spacing:.04em; transition:all .15s; white-space:nowrap; }}
    .comment-save-btn:hover {{ background:#92400e; color:white; }}
    .card-bottom {{ display:flex; align-items:center; justify-content:space-between; margin-top:12px; padding-top:12px; border-top:1px solid rgba(0,0,0,.07); }}
    .card-meta {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .card-actions {{ display:flex; gap:7px; }}
    .tag {{ font-size:0.6rem; font-weight:700; color:var(--c-muted-3); border:1px solid var(--c-line); border-radius:99px; padding:3px 9px; text-transform:uppercase; letter-spacing:0.05em; }}
    .author-avatar {{ width:20px; height:20px; border-radius:50%; object-fit:cover; }}
    .flag-circle {{ width:28px; height:28px; border-radius:50%; border:1.5px solid var(--c-border-2); background:var(--c-bg-soft); display:flex; align-items:center; justify-content:center; cursor:pointer; transition:all .15s; color:var(--c-muted-4); }}
    .flag-circle:hover {{ background:var(--c-text); color:var(--c-bg); border-color:var(--c-text); }}
    .remove-circ {{ border-color:#92400e; color:#92400e; }}
    .remove-circ:hover {{ background:#92400e; color:#fff; border-color:#92400e; }}
    .removing {{ opacity:0; transform:scale(.95); transition:all .3s; pointer-events:none; }}
  </style>
</head>
<body>
{_header("/analise")}
<div class="info-bar">
  <p class="info">{len(articles)} marcados para análise</p>
  <a class="export-btn" href="/api/analise-export" download>⬇ Baixar para análise</a>
</div>
<div class="grid">
  {cards if cards else empty}
</div>
<script>
  async function removeCardA(id, btn) {{
    const card = btn.closest('.card');
    card.classList.add('removing');
    await fetch('/api/flag', {{
      method:'POST', headers:{{'content-type':'application/json'}},
      body: JSON.stringify({{ id, flag: null }}),
    }});
    setTimeout(() => card.remove(), 300);
  }}
  async function saveCommentA(id, input) {{
    const text = input.value.trim();
    if (!text) return;
    try {{
      await fetch('/api/flag', {{
        method:'POST', headers:{{'content-type':'application/json'}},
        body: JSON.stringify({{ id, flag:'analise', comment:text }}),
      }});
      const wrap = input.closest('.card-comment-add');
      const p = document.createElement('p');
      p.className = 'card-comment';
      p.textContent = '💬 ' + text;
      wrap.replaceWith(p);
    }} catch(e) {{}}
  }}
  function copyFromBtnA(btn) {{
    navigator.clipboard.writeText(btn.dataset.copy || '').catch(()=>{{}});
    btn.style.background='#16a34a'; btn.style.color='#fff';
    setTimeout(()=>{{ btn.style.background=''; btn.style.color=''; }}, 900);
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
        "Traduza o tweet para o português brasileiro de forma fiel ao original — sem acrescentar informações, contextos ou palavras que não estejam no tweet. "
        # O card exibe SOMENTE o body_pt; o title_pt não aparece junto. Sem isso o modelo
        # joga a primeira frase no título e o corpo começa no meio da notícia.
        "REGRA CRÍTICA — body_pt É AUTOSSUFICIENTE: o body_pt aparece sozinho na tela, sem o título ao lado. "
        "Ele deve conter a tradução COMPLETA do tweet, do começo ao fim, incluindo a primeira frase. "
        "JAMAIS omita a abertura por já tê-la usado no title_pt. "
        "Use estilo jornalístico fluido e direto, como ge.globo.com ou ESPN Brasil: frases limpas, gramática precisa, sem expansões. "
        "Preserve nomes próprios, siglas e dados exatamente como no original. "
        f"{GLOSSARY_PROMPT}"
    )
    prompt_template = (
        "Traduza os artigos abaixo para português brasileiro.\n"
        "Responda SOMENTE com JSON: {{\"translations\": [{{\"title_pt\": \"...\", \"body_pt\": \"...\", \"category\": \"...\"}}]}}\n"
        "Categorias: mercado, competicao, lesao, geral\n\n{items}"
    )

    updated = 0
    errors = []
    BATCH_SIZE = 3
    prompt_header = (
        "Traduza os artigos abaixo para português brasileiro.\n"
        'Responda SOMENTE com JSON: {"translations": [{"title_pt": "...", "body_pt": "...", "category": "..."}]}\n'
        "Categorias: mercado, competicao, lesao, geral\n\n"
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
            "Categorias: mercado, competicao, lesao, geral\n\n"
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

    def _card(inj: dict) -> str:
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
        orig_html = ('<span class="injury-orig">' + orig + "</span>") if orig and orig != player else ""

        # Timeline de atualizações — uma entrada por notícia que tocou nesta lesão,
        # cada uma carregando o status inferido NAQUELE momento (quando disponível;
        # notícias processadas antes desta feature não têm status salvo na fonte,
        # e caem no ponto neutro "atualização").
        sources = inj.get("sources") or []
        sources_sorted = sorted(sources, key=lambda s: s.get("published_at") or "")
        timeline_html = ""
        for s in sources_sorted:
            u  = s.get("url", "#")
            nm = s.get("source_name", "fonte")
            dt = s.get("published_at", "") or "—"
            ttl = s.get("title", "") or nm
            s_status = s.get("status")
            if s_status and s_status in STATUS_LABEL:
                s_emoji, s_label = STATUS_LABEL[s_status]
                pill_html = '<span class="status-pill sm status-' + s_status + '">' + s_emoji + " " + s_label + "</span>"
                dot_class = "status-" + s_status
            else:
                pill_html = '<span class="status-pill sm status-desconhecido">Atualização</span>'
                dot_class = "status-desconhecido"
            timeline_html += (
                '<div class="timeline-item">'
                + '<span class="timeline-dot ' + dot_class + '"></span>'
                + '<div class="timeline-content">'
                + '<div class="timeline-top">' + pill_html + '<span class="timeline-date">' + dt + "</span></div>"
                + '<a href="' + u + '" target="_blank" class="timeline-title">' + ttl + " · " + nm + "</a>"
                + "</div>"
                + "</div>"
            )
        timeline_section = (
            '<details class="injury-timeline"><summary>Histórico <span class="section-count">('
            + str(len(sources_sorted)) + ')</span></summary><div class="timeline">'
            + timeline_html + "</div></details>"
        ) if sources_sorted else ""

        notes_html = ('<div class="injury-notes">💬 ' + notes + "</div>") if notes else ""
        retorno_html = (" · Retorno est.: " + retorno) if retorno and retorno != "—" else ""

        return (
            '<div class="injury-card">'
            + '<div class="injury-card-top">'
            + '<span class="status-pill status-' + status + '">' + emoji + " " + slabel + "</span>"
            + '<span class="injury-updated">Atualizado ' + updated + "</span>"
            + "</div>"
            + '<div class="injury-player">' + player + orig_html + "</div>"
            + '<div class="injury-club">' + club + "</div>"
            + '<div class="injury-detail">' + tipo_full + retorno_html + " · Lesão em " + injury_dt + "</div>"
            + notes_html
            + timeline_section
            + "</div>"
        )

    cards_active    = "".join(_card(i) for i in active)    if active    else '<div class="empty-state">Nenhuma lesão ativa registrada.</div>'
    cards_recovered = "".join(_card(i) for i in recovered) if recovered else '<div class="empty-state">Nenhuma recuperação registrada.</div>'

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

.injury-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-bottom: 32px;
}}
.injury-card {{
  background: var(--c-bg-card);
  border-radius: 16px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}}
.injury-card-top {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}}
.injury-updated {{
  font-size: .65rem;
  font-weight: 700;
  color: var(--c-muted-2);
  text-transform: uppercase;
  letter-spacing: .06em;
  white-space: nowrap;
}}
.injury-player {{
  font-size: 1rem;
  font-weight: 700;
  color: var(--c-text);
}}
.injury-orig {{
  display: block;
  font-weight: 400;
  font-size: .72rem;
  color: var(--c-muted-3);
  margin-top: 2px;
}}
.injury-club {{
  font-size: .75rem;
  color: var(--c-muted-3);
}}
.injury-detail {{
  font-size: .82rem;
  color: var(--c-muted-4);
  line-height: 1.55;
}}
.injury-notes {{
  font-size: .75rem;
  color: var(--c-muted-3);
  font-style: italic;
  background: var(--c-bg-soft);
  border-radius: 8px;
  padding: 8px 10px;
}}
.injury-bottom {{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--c-border);
}}
.empty-state {{ text-align: center; color: var(--c-muted-3); padding: 32px !important; }}

.injury-timeline {{ margin-top: 4px; }}
.injury-timeline summary {{ padding: 8px 0 6px; font-size: .65rem; }}
.timeline {{
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 2px 2px 4px;
}}
.timeline-item {{ display: flex; gap: 10px; align-items: flex-start; }}
.timeline-dot {{
  width: 8px; height: 8px; border-radius: 50%;
  margin-top: 5px; flex-shrink: 0;
  background: var(--c-muted-2);
}}
.timeline-dot.status-lesionado      {{ background: #ef4444; }}
.timeline-dot.status-em_recuperacao {{ background: #f59e0b; }}
.timeline-dot.status-retornando     {{ background: #22c55e; }}
.timeline-dot.status-recuperado     {{ background: var(--c-muted-2); }}
.timeline-dot.status-desconhecido   {{ background: var(--c-muted-2); }}
.timeline-content {{ flex: 1; min-width: 0; }}
.timeline-top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 3px; flex-wrap: wrap; }}
.timeline-date {{ font-size: .65rem; color: var(--c-muted-2); white-space: nowrap; }}
.timeline-title {{
  display: block;
  font-size: .78rem;
  color: var(--c-muted-4);
  text-decoration: none;
  line-height: 1.4;
}}
.timeline-title:hover {{ color: var(--c-text); text-decoration: underline; }}
.status-pill.sm {{ font-size: .62rem; padding: 2px 6px; }}
.status-pill.status-desconhecido {{ background: var(--c-muted-2); color: var(--c-muted-3); }}

.status-pill {{
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
.status-recuperado     {{ background: var(--c-muted-2); color: var(--c-muted-3); }}
[data-theme=dark] .status-lesionado      {{ background: #3f1212; color: #fca5a5; }}
[data-theme=dark] .status-em_recuperacao {{ background: #3f2d00; color: #fde68a; }}
[data-theme=dark] .status-retornando     {{ background: #052e16; color: #86efac; }}
[data-theme=dark] .status-recuperado     {{ background: var(--c-muted-2); color: var(--c-muted-3); }}

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
.src-dt {{ color: var(--c-muted-3); font-size: .62rem; }}
.src-more {{ color: var(--c-muted-3); cursor: default; }}
a.src-chip {{ cursor: pointer; }}

details summary {{
  cursor: pointer;
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--c-muted-3);
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
  <div class="injury-grid">{cards_active}</div>

  <details>
    <summary>Recuperados <span class="section-count" style="font-weight:400;opacity:.7">({count_recovered})</span></summary>
    <div class="injury-grid" style="margin-top:12px">{cards_recovered}</div>
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

@app.get("/api/admin/fix-article")
async def admin_fix_article_get(id: str = ""):
    """Mesma coisa do POST, só que acionável direto pela URL (?id=...).

    Existe porque o reprocessamento de um card específico precisa ser disparável
    sem front — os outros endpoints /api/admin/* já seguem esse mesmo padrão."""
    return await _fix_article_by_id(id)


@app.post("/api/admin/fix-article")
async def admin_fix_article(request: Request):
    """Força reprocessamento de um artigo específico por ID."""
    body = await request.json()
    return await _fix_article_by_id(body.get("id"))


async def _fix_article_by_id(article_id: str):
    from processor import call_claude
    from glossary import GLOSSARY_PROMPT, apply_glossary
    from database import update_article_body, update_article_title, update_article_meta
    from collector import compute_relevance
    import json as _json

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
        "Traduza o tweet para o português brasileiro de forma fiel ao original — sem acrescentar informações, contextos ou palavras que não estejam no tweet. "
        # O card exibe SOMENTE o body_pt; o title_pt não aparece junto. Sem isso o modelo
        # joga a primeira frase no título e o corpo começa no meio da notícia.
        "REGRA CRÍTICA — body_pt É AUTOSSUFICIENTE: o body_pt aparece sozinho na tela, sem o título ao lado. "
        "Ele deve conter a tradução COMPLETA do tweet, do começo ao fim, incluindo a primeira frase. "
        "JAMAIS omita a abertura por já tê-la usado no title_pt. "
        "Use estilo jornalístico fluido e direto, como ge.globo.com ou ESPN Brasil: frases limpas, gramática precisa, sem expansões. "
        "Preserve nomes próprios, siglas e dados exatamente como no original. "
        f"{GLOSSARY_PROMPT}"
    )
    prompt = (
        "Traduza o artigo abaixo para português brasileiro.\n"
        'Responda SOMENTE com JSON: {"translations": [{"title_pt": "...", "body_pt": "...", "category": "..."}]}\n'
        "Categorias: mercado, competicao, lesao, geral\n\n"
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


@app.get("/api/admin/refix-tweets")
async def admin_refix_tweets(hours: int = 24, dry_run: int = 0, limit: int = 80):
    """Retraduz tweets recentes cujo corpo perdeu a abertura da notícia.

    Contexto: o prompt antigo tratava título e corpo como manchete + continuação, então
    o modelo às vezes jogava a primeira frase no title_pt e começava o body_pt no meio.
    Como o card exibe SÓ o corpo, o fato principal sumia da tela. O prompt já foi
    corrigido; isto aqui conserta o que ficou gravado errado antes da correção.

    Só reprocessa o que está de fato suspeito (ver _body_perdeu_abertura), pra não
    gastar chamada de API — nem reescrever — cards que já estão corretos.
    dry_run=1 devolve só o diagnóstico, sem tocar em nada."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT id, source_name, title_pt, body_orig, body_pt
            FROM articles
            WHERE source_type = 'twitter'
              AND collected_at >= %s
              AND is_duplicate = 0
              AND body_pt IS NOT NULL
              AND title_pt IS NOT NULL
            ORDER BY collected_at DESC
            LIMIT %s
        """, (since, limit))
        rows = [dict(r) for r in c.fetchall()]

    suspects = [r for r in rows if _body_perdeu_abertura(r)]

    if dry_run:
        return {
            "hours": hours, "analisados": len(rows), "suspeitos": len(suspects),
            "amostra": [
                {"id": r["id"], "fonte": r["source_name"],
                 "title_pt": (r["title_pt"] or "")[:90],
                 "body_pt_inicio": (r["body_pt"] or "")[:90]}
                for r in suspects[:15]
            ],
        }

    sem = asyncio.Semaphore(3)

    async def refix(r):
        async with sem:
            try:
                resp = await _fix_article_by_id(r["id"])
                ok = not isinstance(resp, JSONResponse) or resp.status_code == 200
                return {"id": r["id"], "ok": ok}
            except Exception as e:
                return {"id": r["id"], "ok": False, "erro": str(e)}

    results = await asyncio.gather(*[refix(r) for r in suspects])
    return {
        "hours": hours, "analisados": len(rows), "suspeitos": len(suspects),
        "corrigidos": sum(1 for x in results if x.get("ok")),
        "falhas": [x for x in results if not x.get("ok")],
    }


def _body_perdeu_abertura(row: dict) -> bool:
    """Heurística conservadora: o corpo traduzido não cobre o que o título traduzido diz.

    Compara as palavras significativas do title_pt com as do body_pt. Se o título
    carrega conteúdo (nomes, clubes, verbo da ação) que não aparece em lugar nenhum
    do corpo, é sinal de que aquela primeira frase virou manchete e foi retirada do
    corpo — exatamente o caso do tweet do Ndiaye. Quando o corpo já repete o título,
    nada é sinalizado."""
    title = (row.get("title_pt") or "").lower()
    body = (row.get("body_pt") or "").lower()
    if not title or not body:
        return False
    stop = {
        "de", "do", "da", "dos", "das", "e", "o", "a", "os", "as", "para", "por", "com",
        "em", "no", "na", "nos", "nas", "um", "uma", "que", "ao", "aos", "à", "às",
        "se", "mais", "sobre", "após", "entre", "pelo", "pela", "seu", "sua", "the",
    }
    palavras = {w.strip(".,:;!?\"'()[]") for w in title.split()}
    palavras = {w for w in palavras if len(w) > 3 and w not in stop}
    if len(palavras) < 3:
        return False
    ausentes = [w for w in palavras if w not in body]
    return (len(ausentes) / len(palavras)) >= 0.5

# ─── Janela de Transferências (API Football) ─────────────────────────────────

# ─── Números (estatísticas via API-Football) ─────────────────────────────────
AF_LEAGUE_SPL = 307  # Saudi Pro League — confirmado via /leagues?id=307
_AF_CACHE: dict = {}
_AF_CACHE_TTL = 1800  # 30min — padrão pra consultas sem temporada definida

# O cache único de 30 min tratava igual duas coisas muito diferentes: a temporada em
# andamento, que muda a cada rodada, e as encerradas, que não mudam nunca mais. Com
# isso a classificação podia ficar meia hora velha depois de um jogo, enquanto dados
# de 2019 eram rebuscados na API sem necessidade.
_AF_CACHE_TTL_CORRENTE = 180     # 3min — temporada em andamento
_AF_CACHE_TTL_HISTORICO = 21600  # 6h — temporada encerrada não muda
# Jogo ao vivo e o minuto seguinte ao apito: aqui o cache é o inimigo. Medido em
# 15/08/2026 — a partida ficou 11min congelada em "78'" porque a consulta por id
# não tem season e caía no padrão de 30min.
_AF_TTL_AO_VIVO = 30             # 30s — placar e eventos de jogo em andamento


def _af_ttl(params: dict) -> int:
    """Quanto tempo a resposta desta consulta pode ficar guardada."""
    s = params.get("season")
    if s is None:
        return _AF_CACHE_TTL
    try:
        return _AF_CACHE_TTL_CORRENTE if int(s) >= _af_temporada_corrente() else _AF_CACHE_TTL_HISTORICO
    except (TypeError, ValueError):
        return _AF_CACHE_TTL

async def _af_get(path: str, params: dict, ttl: int | None = None) -> tuple[dict | None, str | None]:
    """GET genérico na API-Football com cache em memória e mensagens de erro claras.
    Retorna (data, None) em sucesso ou (None, mensagem_erro).

    ttl: sobrescreve o tempo de cache. Necessário porque _af_ttl() deduz o TTL da
    temporada nos params, e consultas SEM season (fixture por id, jogos por data)
    caíam no padrão de 30min — inaceitável pra jogo ao vivo, onde o placar de
    meia hora atrás é simplesmente o placar errado."""
    af_key = os.environ.get("API_FOOTBALL_KEY", "")
    if not af_key:
        return None, "API_FOOTBALL_KEY não configurada no servidor."
    cache_key = path + "?" + json.dumps(params, sort_keys=True)
    now = time.time()
    cached = _AF_CACHE.get(cache_key)
    if cached and (now - cached[0]) < (ttl if ttl is not None else _af_ttl(params)):
        return cached[1], None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://v3.football.api-sports.io/{path}",
                headers={"x-apisports-key": af_key},
                params=params,
            )
            if r.status_code != 200:
                return None, f"API-Football HTTP {r.status_code}"
            data = r.json()
            if data.get("errors"):
                errs = data["errors"]
                msg = ", ".join(str(v) for v in errs.values()) if isinstance(errs, dict) else str(errs)
                if msg:
                    return None, f"API-Football: {msg}"
            _AF_CACHE[cache_key] = (now, data)
            return data, None
    except Exception as e:
        return None, f"Erro ao consultar API-Football: {type(e).__name__}: {e}"


AF_PRIMEIRA_TEMPORADA = 2016


def _af_temporada_corrente() -> int:
    """Ano com que a API-Football rotula a temporada da Pro League em andamento.

    A liga saudita vira em agosto (2026/27 começa em 13/08/2026 e a API chama de
    2026). Antes de agosto, a temporada corrente ainda é a do ano anterior."""
    hoje = datetime.now()
    return hoje.year if hoje.month >= 8 else hoje.year - 1


def _af_available_seasons() -> list[int]:
    """Temporadas oferecidas nos filtros, da mais recente pra mais antiga.

    Calculado em vez de fixo: a lista antiga era hardcoded e parava em 2025, então
    quando a temporada 2026/27 começou o filtro simplesmente não a oferecia, mesmo
    com a API já devolvendo classificação e artilharia. Agora entra sozinha."""
    return list(range(_af_temporada_corrente(), AF_PRIMEIRA_TEMPORADA - 1, -1))


def _af_player_scan_seasons() -> list[int]:
    """Janela de temporadas varrida ao montar a carreira de um jogador.

    Vai até o ano seguinte de propósito: a API-Football NÃO usa uma convenção única
    pra numerar temporada. A Pro League (307) rotula pelo ano de INÍCIO — 2025/26 = 2025.
    Já a King's Cup (504) rotula pelo ano de TÉRMINO — 2025/26 = 2026 (confirmado em
    /leagues?id=504: season 2026 vai de 2025-08-31 a 2026-05-08). Se varrêssemos só até
    2025 perderíamos silenciosamente a copa da temporada corrente."""
    return list(range(2016, datetime.now().year + 2))


_AF_LEAGUE_SEASON_MAP: dict = {}


async def _af_league_start_years(league_id: int) -> dict:
    """{ano_rotulado_pela_API: ano_real_de_INÍCIO} pra uma competição.

    Serve pra normalizar as convenções divergentes descritas em _af_player_scan_seasons,
    pra que o filtro de temporada da guia Jogador signifique sempre a mesma coisa
    ("2025/26") independente da competição.

    NUNCA cacheia resultado vazio. Uma falha transitória (rate limit) devolvendo {} e
    sendo cacheada faz a temporada cair no rótulo cru da API — e aí a King's Cup 2025/26
    reaparece como "2026" e some do filtro de 2025/26, derrubando 1 jogo do total. Foi
    exatamente o que aconteceu em produção: o total do NEOM voltou de 31 pra 30 jogos."""
    cached = _AF_LEAGUE_SEASON_MAP.get(league_id)
    if cached and (time.time() - cached[0]) < _AF_CACHE_TTL:
        return cached[1]
    data, err = await _af_get("leagues", {"id": league_id})
    mapping = {}
    if not err and data:
        for item in data.get("response", []):
            for s in item.get("seasons", []):
                year = s.get("year")
                if year is None:
                    continue
                start = s.get("start") or ""
                try:
                    mapping[year] = int(start[:4]) if len(start) >= 4 else year
                except ValueError:
                    mapping[year] = year
    if mapping:
        _AF_LEAGUE_SEASON_MAP[league_id] = (time.time(), mapping)
        return mapping
    if cached:
        return cached[1]  # falhou agora, mas o que já sabíamos continua valendo
    return {}


# Competições continentais onde clubes sauditas jogam. As sauditas são descobertas
# sozinhas (/leagues?country=Saudi-Arabia); estas precisam ser nomeadas porque são
# de "país" World/Asia e não sairiam naquela consulta.
AF_LIGAS_CONTINENTAIS = [
    17,    # AFC Champions League Elite
    18,    # AFC Champions League Two
    1168,  # FIFA Intercontinental Cup
]


def _cobertura_exige_apuracao(cov: dict) -> bool:
    """True quando a API não publica estatística por jogador, mas dá pra apurar.

    É esta flag que torna o sistema à prova de futuro: se a API-Football restaurar a
    cobertura de uma competição, ela vira False sozinha e voltamos a usar o número da
    fonte, sem ninguém precisar mexer no código. Verificado que a flag é fiel: acusou
    corretamente Pro League (tem), King's Cup 2025/26 (não tem) e Super Cup (nunca teve)."""
    fx = (cov or {}).get("fixtures") or {}
    return (not fx.get("statistics_players")) and bool(fx.get("events")) and bool(fx.get("lineups"))


async def _af_competicoes_a_apurar(seasons: list[int]) -> list[dict]:
    """Descobre quais (competição, temporada) precisam de apuração nossa."""
    alvos = {}

    async def registrar(item, season_filtro=None):
        lg = item.get("league") or {}
        lid = lg.get("id")
        if lid is None:
            return
        for s in item.get("seasons", []) or []:
            ano = s.get("year")
            if ano is None or (season_filtro and ano not in season_filtro):
                continue
            if _cobertura_exige_apuracao(s.get("coverage")):
                alvos[(lid, ano)] = {"league_id": lid, "season": ano, "league_name": lg.get("name")}

    for season in seasons:
        data, err = await _af_get("leagues", {"country": "Saudi-Arabia", "season": season})
        if not err and data:
            for item in data.get("response", []):
                await registrar(item, {season})

    for lid in AF_LIGAS_CONTINENTAIS:
        data, err = await _af_get("leagues", {"id": lid})
        if not err and data:
            for item in data.get("response", []):
                await registrar(item, set(seasons))

    return sorted(alvos.values(), key=lambda a: (a["league_id"], a["season"]))


async def _af_varrer_competicao(league_id: int, season: int, league_name: str = None) -> dict:
    """Apura, partida a partida, os números de todos os jogadores de uma competição.

    Reprocessa a competição inteira em vez de somar só as partidas novas: são ~2
    chamadas por partida (escalação + eventos), o que dá ordem de 130 requisições por
    competição — irrelevante diante do limite diário de 75.000 — e elimina a chance de
    somar duas vezes a mesma partida, que seria o erro mais provável no caminho
    incremental. O total gravado é sempre recalculado do zero."""
    from database import salvar_stats_apuradas, marcar_partidas_apuradas

    fx, err = await _af_get("fixtures", {"league": league_id, "season": season})
    if err or not fx:
        return {"league_id": league_id, "season": season, "erro": err or "sem resposta"}
    partidas = [
        f for f in fx.get("response", [])
        if ((f.get("fixture") or {}).get("status") or {}).get("short") in ("FT", "AET", "PEN")
    ]
    if not partidas:
        return {"league_id": league_id, "season": season, "partidas": 0, "linhas": 0}

    sem = asyncio.Semaphore(4)

    async def apurar(f):
        fid = (f.get("fixture") or {}).get("id")
        async with sem:
            lu, e1 = await _af_get("fixtures/lineups", {"fixture": fid})
            ev, e2 = await _af_get("fixtures/events", {"fixture": fid})
        if e1 and e2:
            return fid, None, []
        registros = []

        # Titulares e reservas relacionados: só quem começou conta como jogo aqui;
        # quem entrou é detectado pelos eventos de substituição abaixo.
        atuou = {}
        for bloco in ((lu or {}).get("response", []) if not e1 else []):
            tid = ((bloco.get("team") or {}).get("id"))
            tname = ((bloco.get("team") or {}).get("name"))
            for p in bloco.get("startXI", []) or []:
                pl = p.get("player") or {}
                if pl.get("id"):
                    atuou[pl["id"]] = {"team_id": tid, "team_name": tname, "player_name": pl.get("name")}

        eventos = (ev or {}).get("response", []) if not e2 else []
        for e in eventos:
            tid = ((e.get("team") or {}).get("id"))
            tname = ((e.get("team") or {}).get("name"))
            if e.get("type") == "subst":
                entrou = e.get("assist") or {}
                if entrou.get("id"):
                    atuou.setdefault(entrou["id"], {
                        "team_id": tid, "team_name": tname, "player_name": entrou.get("name")})

        contagem = {pid: {"goals": 0, "assists": 0, "yellow_cards": 0, "red_cards": 0} for pid in atuou}
        for e in eventos:
            tipo, detalhe = e.get("type"), e.get("detail")
            autor = (e.get("player") or {}).get("id")
            ajuda = (e.get("assist") or {}).get("id")
            if tipo == "Goal" and detalhe not in ("Missed Penalty", "Own Goal"):
                if autor in contagem:
                    contagem[autor]["goals"] += 1
                if ajuda in contagem:
                    contagem[ajuda]["assists"] += 1
            elif tipo == "Card" and autor in contagem:
                if detalhe == "Yellow Card":
                    contagem[autor]["yellow_cards"] += 1
                elif detalhe in ("Red Card", "Second Yellow card"):
                    contagem[autor]["red_cards"] += 1

        for pid, info in atuou.items():
            c = contagem.get(pid, {})
            registros.append({
                "player_id": pid, "team_id": info["team_id"], "team_name": info["team_name"],
                "player_name": info["player_name"], "goals": c.get("goals", 0),
                "assists": c.get("assists", 0), "yellow_cards": c.get("yellow_cards", 0),
                "red_cards": c.get("red_cards", 0),
            })
        status = ((f.get("fixture") or {}).get("status") or {}).get("short")
        return fid, status, registros

    resultados = await asyncio.gather(*[apurar(f) for f in partidas])

    totais = {}
    processadas = []
    for fid, status, registros in resultados:
        if status:
            processadas.append((fid, league_id, season, status))
        for r in registros:
            chave = (r["player_id"], r["team_id"])
            acc = totais.setdefault(chave, {
                "league_id": league_id, "season": season, "league_name": league_name,
                "player_id": r["player_id"], "team_id": r["team_id"],
                "team_name": r["team_name"], "player_name": r["player_name"],
                "appearences": 0, "goals": 0, "assists": 0, "yellow_cards": 0, "red_cards": 0,
            })
            acc["appearences"] += 1
            for k in ("goals", "assists", "yellow_cards", "red_cards"):
                acc[k] += r[k]

    linhas = list(totais.values())
    salvar_stats_apuradas(linhas)
    marcar_partidas_apuradas(processadas)
    return {
        "league_id": league_id, "season": season, "league_name": league_name,
        "partidas": len(partidas), "jogadores": len(linhas),
    }


async def _af_varrer_tudo(seasons: list[int] = None) -> dict:
    """Descobre e varre todas as competições sem cobertura por jogador."""
    seasons = seasons or _af_player_scan_seasons()
    alvos = await _af_competicoes_a_apurar(seasons)
    resultados = []
    for a in alvos:
        resultados.append(await _af_varrer_competicao(a["league_id"], a["season"], a["league_name"]))
    return {"competicoes_detectadas": len(alvos), "resultados": resultados}


async def _af_player_rows(player: int):
    """Linhas de estatística confiáveis de um jogador, já normalizadas por temporada real.

    Regra central: DESCARTA linhas cujo league.id é null. Isso não é preciosismo — foi
    verificado ao vivo que essas linhas são fabricadas pelo agregador da API-Football.
    Exemplo real (player 297749, NEOM): /players?id=...&season=2025 devolvia uma linha
    "King's Cup" sem id com 19 jogos e 2 gols, enquanto a consulta direta à competição
    real (/players?id=...&league=504&season=2025) devolve ZERO registros, e a edição
    correta (league=504&season=2026) devolve 1 jogo e 0 gols — que é o número certo.
    Como não dá pra reconsultar uma competição sem id, essas linhas são inutilizáveis
    e somá-las só produziria número errado."""
    seasons_to_check = _af_player_scan_seasons()
    sem = asyncio.Semaphore(4)

    async def fetch_season(season):
        async with sem:
            data, err = await _af_get("players", {"id": player, "season": season})
        if err or not data:
            return None
        resp = data.get("response", [])
        return resp[0] if resp else None

    raw = await asyncio.gather(*[fetch_season(s) for s in seasons_to_check])

    player_info = None
    candidate_rows = []
    descartadas = []
    for entry in raw:
        if not entry:
            continue
        if player_info is None:
            player_info = entry.get("player", {})
        for s in entry.get("statistics", []):
            lg = s.get("league") or {}
            if lg.get("id") is None:
                # Linha sem competição identificável — não confiável, fica FORA da conta.
                # Mas é registrada pra poder avisar o usuário, em vez de a competição
                # sumir da tela sem explicação (foi a dúvida real: "cadê a King's Cup?").
                tm = s.get("team") or {}
                descartadas.append({
                    "league": lg.get("name"),
                    "team_id": tm.get("id"),
                    "team": tm.get("name"),
                    "season": lg.get("season"),
                })
                continue
            candidate_rows.append(s)

    league_ids = {(r.get("league") or {}).get("id") for r in candidate_rows}
    league_ids.discard(None)
    lsem = asyncio.Semaphore(3)  # sem isso, ~18 chamadas simultâneas estouram o rate limit

    async def league_map(lid):
        async with lsem:
            return await _af_league_start_years(lid)

    league_ids = list(league_ids)
    maps = await asyncio.gather(*[league_map(lid) for lid in league_ids])
    start_year_by_league = dict(zip(league_ids, maps))

    rows = []
    for s in candidate_rows:
        lg = s.get("league") or {}
        lid = lg.get("id")
        labelled = lg.get("season")
        mapping = start_year_by_league.get(lid) or {}
        real_season = mapping.get(labelled, labelled)
        rows.append({"stat": s, "real_season": real_season})

    # Competição que a fonte cita mas não cobre com estatística por jogador: em vez de
    # desistir, conta pelas partidas (escalação + eventos). Confirmado com a King's Cup
    # 2025/26 do R. Enrique: 5 jogos e 4 gols, batendo com a realidade.
    # Competições que a fonte não cobre por jogador entram pelo que NÓS apuramos
    # partida a partida e guardamos (ver _af_varrer_competicao). Vem do banco, então
    # não custa requisição nenhuma aqui — e, principalmente, aparece mesmo quando o
    # agregado do jogador não menciona a competição: era o caso do Toney, cuja King's
    # Cup 2025/26 não existia em nenhuma linha, nem corrompida.
    from database import get_stats_apuradas_do_jogador

    reconstruidas = []
    ja_cobertos = {
        (((r["stat"].get("team") or {}).get("id")), ((r["stat"].get("league") or {}).get("id")))
        for r in rows
    }
    for ap in get_stats_apuradas_do_jogador(player):
        chave = (ap["team_id"], ap["league_id"])
        if chave in ja_cobertos:
            continue  # a fonte já entrega essa competição pra esse time — não duplicar
        mapa = await _af_league_start_years(ap["league_id"])
        rows.append({
            "stat": {
                "team": {"id": ap["team_id"], "name": ap.get("team_name")},
                "league": {"id": ap["league_id"], "name": ap.get("league_name"), "season": ap["season"]},
                "games": {"appearences": ap["appearences"], "minutes": None, "rating": None},
                "goals": {"total": ap["goals"], "assists": ap["assists"]},
                "cards": {"yellow": ap["yellow_cards"], "red": ap["red_cards"]},
            },
            "real_season": mapa.get(ap["season"], ap["season"]),
            "reconstruido": True,
        })
        ja_cobertos.add(chave)
        reconstruidas.append({"league": ap.get("league_name"), "team_id": ap["team_id"]})

    # Sobra o que nem a fonte cobre nem conseguimos apurar — vira aviso na tela.
    sem_dados = [
        d for d in descartadas
        if not any(r["league"] == d.get("league") and r["team_id"] == d.get("team_id")
                   for r in reconstruidas)
    ]
    return player_info, rows, sem_dados, reconstruidas


@app.get("/api/numeros/meta")
async def api_numeros_meta(season: int = 2025):
    """Times da SPL na temporada (pra popular filtros de clube/jogador)."""
    data, err = await _af_get("teams", {"league": AF_LEAGUE_SPL, "season": season})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    teams = [
        {"id": t["team"]["id"], "name": t["team"]["name"], "logo": t["team"]["logo"]}
        for t in data.get("response", [])
    ]
    teams.sort(key=lambda x: x["name"])
    return {"season": season, "seasons_available": _af_available_seasons(), "teams": teams}


@app.get("/api/numeros/squad")
async def api_numeros_squad(team: int):
    """Elenco de um clube (pra popular o seletor de jogador)."""
    data, err = await _af_get("players/squads", {"team": team})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    resp = data.get("response", [])
    if not resp:
        return {"team": None, "players": []}
    return {
        "team": resp[0].get("team"),
        "players": [
            {"id": p["id"], "name": p["name"], "number": p.get("number"), "position": p.get("position"), "photo": p.get("photo")}
            for p in resp[0].get("players", [])
        ],
    }


def _player_stat_row(entry: dict) -> dict | None:
    """Extrai a linha de estatística da SPL de uma entrada de topscorers/topassists
    (cada entrada já vem com UMA statistics[0] resolvida pro contexto da consulta)."""
    stats = entry.get("statistics") or []
    if not stats:
        return None
    s = stats[0]
    games = s.get("games") or {}
    goals = s.get("goals") or {}
    p = entry.get("player") or {}
    g = goals.get("total")
    a = goals.get("assists")
    return {
        "player_id": p.get("id"),
        "name": p.get("name"),
        "photo": p.get("photo"),
        "nationality": p.get("nationality"),
        "team": (s.get("team") or {}).get("name"),
        "team_id": (s.get("team") or {}).get("id"),
        "team_logo": (s.get("team") or {}).get("logo"),
        "appearences": games.get("appearences"),
        "goals": g,
        "assists": a,
        "ga": (g or 0) + (a or 0) if (g is not None or a is not None) else None,
    }


@app.get("/api/numeros/topscorers")
async def api_numeros_topscorers(season: int = 2025, limit: int = 20, team: int = 0):
    data, err = await _af_get("players/topscorers", {"league": AF_LEAGUE_SPL, "season": season})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    rows = [r for r in (_player_stat_row(e) for e in data.get("response", [])) if r]
    if team:
        rows = [r for r in rows if r["team_id"] == team]
    rows = rows[:max(1, min(limit, 20))]
    return {"season": season, "league": "Saudi Pro League", "team_filter": team or None, "count": len(rows), "players": rows}


@app.get("/api/numeros/topassists")
async def api_numeros_topassists(season: int = 2025, limit: int = 20, team: int = 0):
    data, err = await _af_get("players/topassists", {"league": AF_LEAGUE_SPL, "season": season})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    rows = [r for r in (_player_stat_row(e) for e in data.get("response", [])) if r]
    if team:
        rows = [r for r in rows if r["team_id"] == team]
    rows = rows[:max(1, min(limit, 20))]
    return {"season": season, "league": "Saudi Pro League", "team_filter": team or None, "count": len(rows), "players": rows}


@app.get("/api/numeros/goal-contributions")
async def api_numeros_goal_contributions(season: int = 2025, limit: int = 20, team: int = 0):
    """G+A: combina os rankings de artilharia e assistências (cada um top-20 da API-
    Football — não existe endpoint nativo de G+A) e reordena pela soma real dos dois
    campos retornados pela API. Jogadores fora de ambos os top-20 não entram aqui —
    isso é uma limitação real da API, não uma omissão arbitrária."""
    d1, e1 = await _af_get("players/topscorers", {"league": AF_LEAGUE_SPL, "season": season})
    if e1:
        return JSONResponse({"error": e1}, status_code=502)
    d2, e2 = await _af_get("players/topassists", {"league": AF_LEAGUE_SPL, "season": season})
    if e2:
        return JSONResponse({"error": e2}, status_code=502)
    merged: dict[int, dict] = {}
    for e in (d1.get("response", []) + d2.get("response", [])):
        row = _player_stat_row(e)
        if row and row["player_id"] is not None:
            merged[row["player_id"]] = row
    rows = list(merged.values())
    if team:
        rows = [r for r in rows if r["team_id"] == team]
    rows.sort(key=lambda r: (r["ga"] if r["ga"] is not None else -1), reverse=True)
    rows = rows[:max(1, min(limit, 40))]
    return {
        "season": season, "league": "Saudi Pro League", "team_filter": team or None,
        "count": len(rows), "players": rows,
        "note": "Combina os top-20 de artilharia e assistências da API-Football — jogadores fora dessas duas listas não aparecem.",
    }


@app.get("/api/numeros/team-stats")
async def api_numeros_team_stats(team: int, season: int = 2025, sort: str = "goals", limit: int = 40):
    """Ranking INTERNO COMPLETO de um clube: pagina por TODOS os jogadores retornados
    por /players?team=X&league=307&season=Y (confirmado paginado — ver debug histórico),
    incluindo jogadores com 0 gols/assistências. Diferente dos rankings gerais (topscorers/
    topassists, limitados ao top-20 da competição), aqui o universo é o elenco real do
    clube, então a ordenação interna é sempre completa e correta."""
    page = 1
    rows: list[dict] = []
    while True:
        data, err = await _af_get("players", {"team": team, "league": AF_LEAGUE_SPL, "season": season, "page": page})
        if err:
            return JSONResponse({"error": err}, status_code=502)
        resp = data.get("response", [])
        for entry in resp:
            player = entry.get("player") or {}
            stats_list = entry.get("statistics") or []
            s = stats_list[0] if stats_list else {}
            games = s.get("games") or {}
            goals = s.get("goals") or {}
            g = goals.get("total") or 0
            a = goals.get("assists") or 0
            rows.append({
                "player_id": player.get("id"),
                "name": player.get("name"),
                "photo": player.get("photo"),
                "nationality": player.get("nationality"),
                "team": (s.get("team") or {}).get("name"),
                "team_id": (s.get("team") or {}).get("id"),
                "team_logo": (s.get("team") or {}).get("logo"),
                "appearences": games.get("appearences") or 0,
                "goals": g,
                "assists": a,
                "ga": g + a,
            })
        paging = data.get("paging") or {}
        if paging.get("current", 1) >= paging.get("total", 1):
            break
        page += 1
        if page > 6:
            break
    key = sort if sort in ("goals", "assists", "ga") else "goals"
    rows.sort(key=lambda r: r[key], reverse=True)
    rows = rows[:max(1, min(limit, 60))]
    return {
        "season": season, "team": team, "sort": key, "count": len(rows), "players": rows,
        "note": "Ranking interno completo do elenco (todos os jogadores retornados pela API-Football pra esse clube/temporada/liga, incluindo 0 gols/assistências).",
    }


_AF_INDICE_JOGADORES: dict = {}
_AF_INDICE_TTL = 21600  # 6h — elenco não muda de hora em hora


def _sem_acento(s: str) -> str:
    """Compara nomes ignorando acento: 'Núñez' casa com 'nunez'."""
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


async def _af_indice_jogadores(season: int) -> list[dict]:
    """Elenco inteiro da SPL na temporada, com primeiro e último nome separados.

    Existe porque a busca da API-Football casa apenas pelo NOME DE EXIBIÇÃO. Procurar
    "Alexandre" devolve "Alexandre Mendy" mas não "A. Lacazette", cujo firstname é
    Alexandre — o mesmo motivo pelo qual "Ramiro" não achava "R. Enrique". Com o
    elenco indexado localmente dá pra casar por qualquer parte do nome."""
    cached = _AF_INDICE_JOGADORES.get(season)
    if cached and (time.time() - cached[0]) < _AF_INDICE_TTL:
        return cached[1]

    jogadores, page = [], 1
    while page <= 40:
        data, err = await _af_get("players", {"league": AF_LEAGUE_SPL, "season": season, "page": page})
        if err or not data:
            break
        for entry in data.get("response", []):
            p = entry.get("player") or {}
            if not p.get("id"):
                continue
            s = (entry.get("statistics") or [{}])[0]
            completo = " ".join(filter(None, [p.get("firstname"), p.get("lastname")])).strip()
            jogadores.append({
                "player_id": p.get("id"),
                "name": p.get("name"),
                "firstname": p.get("firstname"),
                "lastname": p.get("lastname"),
                # Nome por extenso: o "name" da API vem abreviado ("A. Lacazette"),
                # e é justamente o nome completo que identifica o jogador na busca.
                "full_name": completo or p.get("name"),
                "photo": p.get("photo"),
                "team": (s.get("team") or {}).get("name"),
                "team_id": (s.get("team") or {}).get("id"),
                "team_logo": (s.get("team") or {}).get("logo"),
            })
        paging = data.get("paging") or {}
        if paging.get("current", 1) >= paging.get("total", 1):
            break
        page += 1

    if jogadores:  # nunca cacheia índice vazio (falha transitória não vira busca quebrada)
        _AF_INDICE_JOGADORES[season] = (time.time(), jogadores)
    elif cached:
        return cached[1]
    return jogadores


# Bolinhas de cor de cada clube, como o Vini usa nos posts. Chaveado pelo nome que a
# API-Football devolve, pra não depender do encurtamento dar certo.
TEAM_CORES = {
    "Al-Hilal Saudi FC": "🔵⚪️", "Al Riyadh": "⚫️🔴", "Al-Ittihad FC": "⚫️🟡",
    "Al-Nassr": "🟡🔵", "Damac": "🔴🟤", "Al-Fayha": "🟠🔵",
    "Al Khaleej Saihat": "🟢🟡", "Al Kholood": "🔴🟢", "Al Okhdood": "🔵⚫️",
    "Al Shabab": "⚪️⚫️", "Al-Ettifaq": "🟢🔴", "Al-Fateh": "🔵🟢",
    "Al-Ahli Jeddah": "🟢⚪️", "Al Taawon": "🟡⚪️", "Al-Qadisiyah FC": "🔴🟡",
    "NEOM": "🔵🟣", "Al-Hazm": "🟡🟡", "Al Najma": "🟢⚫️",
    "Al-Faisaly FC": "🔴⚪️", "Al Diriyah": "🟤⚪️", "Abha": "🔵🔴",
}

TEAM_CURTO = {
    "Al Khaleej Saihat": "Khaleej", "Al Kholood": "Kholood", "Al Najma": "Najmah",
    "Al Okhdood": "Okhdood", "Al Riyadh": "Riyadh", "Al Shabab": "Shabab",
    "Al Taawon": "Taawoun", "Al-Ahli Jeddah": "Ahli", "Al-Ettifaq": "Ettifaq",
    "Al-Fateh": "Fateh", "Al-Fayha": "Fayha", "Al-Hazm": "Hazem",
    "Al-Hilal Saudi FC": "Hilal", "Al-Ittihad FC": "Ittihad", "Al-Nassr": "Nassr",
    "Al-Qadisiyah FC": "Qadsiah", "Damac": "Damac", "NEOM": "Neom",
    "Al-Faisaly FC": "Faisaly", "Al Diriyah": "Diriyah", "Abha": "Abha",
}


def _time_curto(nome: str) -> str:
    if nome in TEAM_CURTO:
        return TEAM_CURTO[nome]
    limpo = re.sub(r"^Al[-\s]+", "", nome or "").strip()
    return re.sub(r"\s+(FC|SC|Club|Saudi FC)$", "", limpo).strip() or (nome or "")


def _nome_artilheiro(nome: str) -> str:
    """Tira a inicial abreviada: 'M. Dembele' -> 'Dembele'.

    É como o Vini escreve nos posts. Quando ele quiser manter a inicial (caso do
    'R. Messi', pra não confundir com o Lionel), é um ajuste rápido na hora de postar."""
    return re.sub(r"^[A-Z]\.\s+", "", (nome or "").strip())


_FIM_JOGO_CACHE: dict = {}  # {fixture_id: texto} — jogo encerrado não muda mais

NARRATIVA_SYSTEM = (
    "Você escreve a primeira linha de posts de fim de jogo do futebol saudita, no estilo "
    "de um perfil brasileiro de cobertura. UMA frase curta, direta, em português do Brasil.\n"
    "Exemplos do tom desejado:\n"
    "- \"Em jogo de muitos gols, o Ettifaq estreia com vitória contra o Riyadh.\"\n"
    "- \"Em jogo de 3 pênaltis, o Al Hilal toma susto mas estreia com vitória na Saudi Pro League.\"\n"
    "- \"Neom faz ótimo primeiro tempo, segura no segundo e começa a SPL com vitória!\"\n"
    "Use só os fatos informados. Não invente nome, lance nem contexto que não esteja nos dados. "
    "Não repita o placar em números. Responda apenas com a frase, sem aspas."
)


async def _narrativa_do_jogo(dados: dict) -> str:
    """Sugestão de frase de abertura. Falha nunca derruba o resto do texto."""
    from processor import call_claude, CLAUDE_MODEL_TRIAGEM
    g = dados
    resumo = (
        f"{g['casa']} {g['gols_casa']} x {g['gols_fora']} {g['fora']}, {g['rodada']} da Saudi Pro League.\n"
        f"Intervalo: {g['ht_casa']} x {g['ht_fora']}.\n"
        f"Gols: " + "; ".join(g["linha_gols"]) + ".\n"
        f"Pênaltis convertidos no jogo: {g['penaltis']}. Gols contra: {g['gols_contra']}.\n"
        f"Virada: {'sim' if g['virada'] else 'não'}. Empate: {'sim' if g['gols_casa']==g['gols_fora'] else 'não'}."
    )
    try:
        async with httpx.AsyncClient() as client:
            frase = await call_claude(resumo, NARRATIVA_SYSTEM, client,
                                      max_tokens=120, model=CLAUDE_MODEL_TRIAGEM)
        return frase.strip().strip('"')
    except Exception as e:
        print(f"   ⚠️  Narrativa falhou: {type(e).__name__}: {e}")
        return ""


async def _montar_fim_de_jogo(fixture_id: int) -> dict:
    """Texto pronto de FIM DE JOGO no formato usado nos posts."""
    if fixture_id in _FIM_JOGO_CACHE:
        return _FIM_JOGO_CACHE[fixture_id]

    fx, err = await _af_get("fixtures", {"id": fixture_id}, ttl=_AF_TTL_AO_VIVO)
    if err or not fx or not fx.get("response"):
        return {"erro": err or "partida não encontrada"}
    f = fx["response"][0]
    status = ((f.get("fixture") or {}).get("status") or {}).get("short")
    times = f.get("teams") or {}
    casa, fora = times.get("home") or {}, times.get("away") or {}
    gols = f.get("goals") or {}
    score = f.get("score") or {}
    ht = score.get("halftime") or {}
    pen = score.get("penalty") or {}

    ev, e2 = await _af_get("fixtures/events", {"fixture": fixture_id, "type": "Goal"},
                           ttl=_AF_TTL_AO_VIVO)
    eventos = (ev or {}).get("response", []) if not e2 else []

    def _linha(e):
        """Formata o evento. Devolve None pro que não vira linha de gol."""
        det = e.get("detail")
        if det == "Missed Penalty":
            return None
        autor = _nome_artilheiro((e.get("player") or {}).get("name"))
        if det == "Own Goal":
            return f"⚽ {autor} (gc)"
        if det == "Penalty":
            return f"⚽ {autor} (p)"
        ajuda = (e.get("assist") or {}).get("name")
        if ajuda:
            return f"⚽ {autor} ({_nome_artilheiro(ajuda)})"
        return f"⚽ {autor}"

    id_casa, id_fora = casa.get("id"), fora.get("id")
    gc, gf = gols.get("home") or 0, gols.get("away") or 0

    def _montar_listas(inverter_gc: bool):
        """inverter_gc=True credita o gol contra ao time que MARCOU o ponto,
        não ao time do jogador que fez. Qual das duas convenções a API usa é
        decidido logo abaixo comparando com o placar oficial — não por suposição."""
        lc, lf = [], []
        for e in eventos:
            linha = _linha(e)
            if linha is None:
                continue
            tid = (e.get("team") or {}).get("id")
            if inverter_gc and e.get("detail") == "Own Goal":
                tid = id_fora if tid == id_casa else id_casa
            (lc if tid == id_casa else lf).append(linha)
        return lc, lf

    tem_gc = any(e.get("detail") == "Own Goal" for e in eventos)
    l_casa, l_fora = _montar_listas(inverter_gc=tem_gc)
    # O placar oficial é o árbitro da atribuição: se a convenção escolhida não
    # bate com ele e há gol contra em jogo, tenta a outra antes de desistir.
    if tem_gc and (len(l_casa) != gc or len(l_fora) != gf):
        alt_c, alt_f = _montar_listas(inverter_gc=False)
        if len(alt_c) == gc and len(alt_f) == gf:
            l_casa, l_fora = alt_c, alt_f

    # Eventos podem ainda não ter sido publicados nos minutos seguintes ao apito
    # final — é exatamente quando o post é gerado. Sem esta checagem o texto sai
    # sem os gols e (pior) fica cacheado assim pra sempre.
    completo = (len(l_casa) == gc and len(l_fora) == gf)

    nome_casa, nome_fora = _time_curto(casa.get("name")), _time_curto(fora.get("name"))
    cor_casa = TEAM_CORES.get(casa.get("name"), "")
    cor_fora = TEAM_CORES.get(fora.get("name"), "")
    htc, htf = ht.get("home") or 0, ht.get("away") or 0

    dados = {
        "casa": nome_casa, "fora": nome_fora, "gols_casa": gc, "gols_fora": gf,
        "ht_casa": htc, "ht_fora": htf,
        "rodada": (f.get("league") or {}).get("round") or "",
        "linha_gols": [f"{(e.get('time') or {}).get('elapsed')}' {_nome_artilheiro((e.get('player') or {}).get('name'))} ({_time_curto((e.get('team') or {}).get('name'))})" for e in eventos],
        "penaltis": sum(1 for e in eventos if e.get("detail") == "Penalty"),
        "gols_contra": sum(1 for e in eventos if e.get("detail") == "Own Goal"),
        "virada": (htc > htf and gc < gf) or (htf > htc and gf < gc),
    }
    encerrado = status in ("FT", "AET", "PEN")
    # Sem os gols na mão, a narrativa sairia baseada em dados incompletos.
    narrativa = await _narrativa_do_jogo(dados) if (encerrado and completo) else ""

    placar = f"{gc}x{gf}"
    if status == "PEN" and pen.get("home") is not None:
        placar += f" ({pen.get('home')}x{pen.get('away')} nos pênaltis)"

    cabecalho = "⏱️ FIM DE JOGO" if encerrado else "⏱️ FIM DE JOGO (parcial)"

    partes = [cabecalho, ""]
    if narrativa:
        partes += [narrativa, ""]
    partes.append(f"{cor_casa} {nome_casa} {placar} {nome_fora} {cor_fora}".strip())
    if l_casa:
        partes += [""] + l_casa
    if l_fora:
        partes += [""] + l_fora

    resultado = {
        "fixture": fixture_id, "status": status, "encerrado": encerrado,
        "completo": completo,
        "casa": nome_casa, "fora": nome_fora, "placar": placar,
        "narrativa": narrativa, "texto": "\n".join(partes),
    }
    if not completo:
        resultado["aviso"] = (
            f"a API ainda não publicou todos os gols ({len(l_casa)+len(l_fora)} de {gc+gf}) — "
            "atualize em instantes"
        )
    # Só congela no cache quando o jogo acabou E os gols conferem com o placar.
    if encerrado and completo:
        _FIM_JOGO_CACHE[fixture_id] = resultado
    return resultado


@app.get("/api/numeros/fim-de-jogo")
async def api_fim_de_jogo(fixture: int):
    """Texto pronto pra copiar do post de fim de jogo."""
    return await _montar_fim_de_jogo(fixture)


@app.get("/api/numeros/jogos-do-dia")
async def api_jogos_do_dia(dias: int = 1):
    """Jogos da SPL de hoje (e dos últimos dias), com status ao vivo.

    Serve pra tela de fim de jogo: assim que uma partida encerra, ela aparece aqui
    com o texto pronto — sem precisar procurar rodada nem partida."""
    hoje = datetime.now(timezone.utc).date()
    jogos = []
    for delta in range(dias):
        d = (hoje - timedelta(days=delta)).isoformat()
        data, err = await _af_get("fixtures", {"league": AF_LEAGUE_SPL,
                                              "season": _af_temporada_corrente(), "date": d},
                                  ttl=_AF_TTL_AO_VIVO)
        if err or not data:
            continue
        for f in data.get("response", []):
            fx = f.get("fixture") or {}
            st = (fx.get("status") or {})
            t = f.get("teams") or {}
            g = f.get("goals") or {}
            jogos.append({
                "fixture": fx.get("id"),
                "data": (fx.get("date") or "")[:16].replace("T", " "),
                "status": st.get("short"), "minuto": st.get("elapsed"),
                "encerrado": st.get("short") in ("FT", "AET", "PEN"),
                "casa": _time_curto((t.get("home") or {}).get("name")),
                "fora": _time_curto((t.get("away") or {}).get("name")),
                "cor_casa": TEAM_CORES.get((t.get("home") or {}).get("name"), ""),
                "cor_fora": TEAM_CORES.get((t.get("away") or {}).get("name"), ""),
                "gols_casa": g.get("home"), "gols_fora": g.get("away"),
            })
    jogos.sort(key=lambda x: x["data"], reverse=True)
    return {"jogos": jogos}


@app.get("/api/numeros/debug-af")
async def api_numeros_debug_af(path: str, q: str = ""):
    """Proxy cru pra API-Football. path='fixtures', q='league=307&season=2026'."""
    params = {}
    for part in q.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    data, err = await _af_get(path, params)
    if err:
        return {"error": err, "path": path, "params": params}
    return {"path": path, "params": params, "results": data.get("results"),
            "response": data.get("response")}


@app.get("/api/numeros/player-search")
async def api_numeros_player_search(q: str, season: int = 2025, team: int = 0):
    """Busca jogador por qualquer parte do nome, escopada à Saudi Pro League.

    Combina duas fontes: a busca da própria API (boa pro nome de exibição) e um
    índice local do elenco (que permite achar pelo primeiro nome, coisa que a API
    não faz). Filtro de clube é opcional."""
    q = (q or "").strip()
    if len(q) < 3:
        return {"error": "Digite ao menos 3 caracteres para buscar.", "players": []}

    encontrados: dict = {}

    # 1) Busca da API — exige 4+ caracteres, então só vale a partir daí.
    if len(q) >= 4:
        params = {"search": q, "league": AF_LEAGUE_SPL, "season": season}
        if team:
            params["team"] = team
        data, err = await _af_get("players", params)
        if not err and data:
            for entry in data.get("response", []):
                p = entry.get("player") or {}
                s = (entry.get("statistics") or [{}])[0]
                if p.get("id"):
                    completo = " ".join(filter(None, [p.get("firstname"), p.get("lastname")])).strip()
                    encontrados[p["id"]] = {
                        "player_id": p.get("id"), "name": p.get("name"), "photo": p.get("photo"),
                        "full_name": completo or p.get("name"),
                        "team": (s.get("team") or {}).get("name"),
                        "team_id": (s.get("team") or {}).get("id"),
                        "team_logo": (s.get("team") or {}).get("logo"),
                    }

    # 2) Índice local — pega o que a API não pega (primeiro nome, sobrenome composto).
    alvo = _sem_acento(q)
    for j in await _af_indice_jogadores(season):
        if team and j.get("team_id") != team:
            continue
        campos = " ".join(filter(None, [j.get("name"), j.get("firstname"), j.get("lastname")]))
        if alvo in _sem_acento(campos):
            encontrados.setdefault(j["player_id"], {
                "player_id": j["player_id"], "name": j.get("name"), "photo": j.get("photo"),
                "full_name": j.get("full_name"),
                "team": j.get("team"), "team_id": j.get("team_id"), "team_logo": j.get("team_logo"),
            })

    # O índice tem o nome por extenso; completa quem veio da busca da API sem ele.
    _por_id = {j["player_id"]: j for j in await _af_indice_jogadores(season)}
    for pid, p in encontrados.items():
        if not p.get("full_name") and pid in _por_id:
            p["full_name"] = _por_id[pid].get("full_name")

    players = sorted(encontrados.values(), key=lambda x: (x.get("name") or ""))
    return {"query": q, "count": len(players), "players": players}


@app.get("/api/numeros/standings")
async def api_numeros_standings(season: int = 2025):
    data, err = await _af_get("standings", {"league": AF_LEAGUE_SPL, "season": season})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    resp = data.get("response", [])
    if not resp:
        return {"season": season, "table": []}
    table_raw = resp[0]["league"]["standings"][0]
    table = [
        {
            "rank": row["rank"],
            "team": row["team"]["name"],
            "team_logo": row["team"]["logo"],
            "points": row["points"],
            "played": row["all"]["played"],
            "wins": row["all"]["win"],
            "draws": row["all"]["draw"],
            "losses": row["all"]["lose"],
            "goals_diff": row["goalsDiff"],
            "goals_for": row["all"]["goals"]["for"],
            "goals_against": row["all"]["goals"]["against"],
        }
        for row in table_raw
    ]
    return {"season": season, "league": "Saudi Pro League", "table": table}


@app.get("/api/numeros/fixtures")
async def api_numeros_fixtures(team: int, season: int = 2025):
    data, err = await _af_get("fixtures", {"league": AF_LEAGUE_SPL, "season": season, "team": team})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    fixtures = []
    for f in data.get("response", []):
        fx = f.get("fixture", {})
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        fixtures.append({
            "fixture_id": fx.get("id"),
            "date": (fx.get("date") or "")[:10],
            "round": (f.get("league") or {}).get("round"),
            "status": (fx.get("status") or {}).get("short"),
            "home": (teams.get("home") or {}).get("name"),
            "away": (teams.get("away") or {}).get("name"),
            "goals_home": goals.get("home"),
            "goals_away": goals.get("away"),
        })
    fixtures.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"season": season, "team": team, "fixtures": fixtures}


@app.get("/api/numeros/fixture-player")
async def api_numeros_fixture_player(fixture: int, player: int):
    """Estatísticas de UM jogador em UMA partida específica."""
    data, err = await _af_get("fixtures/players", {"fixture": fixture})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    found = None
    team_name = None
    for team_block in data.get("response", []):
        for pl in team_block.get("players", []):
            if pl.get("player", {}).get("id") == player:
                found = pl
                team_name = (team_block.get("team") or {}).get("name")
                break
        if found:
            break
    if not found:
        return JSONResponse({"error": "Jogador não encontrado nesta partida (não participou ou não foi relacionado)."}, status_code=404)
    s = (found.get("statistics") or [{}])[0]
    def g(*keys):
        d = s
        for k in keys[:-1]:
            d = (d or {}).get(k, {})
        return (d or {}).get(keys[-1])
    return {
        "player_id": player,
        "name": found.get("player", {}).get("name"),
        "photo": found.get("player", {}).get("photo"),
        "team": team_name,
        "minutes": g("games", "minutes"),
        "position": g("games", "position"),
        "rating": g("games", "rating"),
        "goals": g("goals", "total"),
        "assists": g("goals", "assists"),
        "goals_conceded": g("goals", "conceded"),
        "saves": g("goals", "saves"),
        "shots_total": g("shots", "total"),
        "shots_on": g("shots", "on"),
        "passes_total": g("passes", "total"),
        "passes_accuracy": g("passes", "accuracy"),
        "tackles": g("tackles", "total"),
        "interceptions": g("tackles", "interceptions"),
        "duels_total": g("duels", "total"),
        "duels_won": g("duels", "won"),
        "dribbles_success": g("dribbles", "success"),
        "fouls_drawn": g("fouls", "drawn"),
        "fouls_committed": g("fouls", "committed"),
        "yellow_cards": g("cards", "yellow"),
        "red_cards": g("cards", "red"),
    }


@app.get("/api/numeros/player-fixtures")
async def api_numeros_player_fixtures(player: int, team: int, season: int = 2025):
    """Retorna SÓ as partidas em que o jogador participou ou foi relacionado (evita
    listar o calendário inteiro do time, que inclui jogos em que ele nem esteve no banco).
    Cruza /fixtures (calendário do time) com /fixtures/players (elenco relacionado por
    partida), com concorrência limitada — cada partida fica cacheada em _af_get depois
    da primeira consulta, então buscas repetidas (outro jogador do mesmo time) ficam rápidas."""
    data, err = await _af_get("fixtures", {"league": AF_LEAGUE_SPL, "season": season, "team": team})
    if err:
        return JSONResponse({"error": err}, status_code=502)
    fixtures_raw = data.get("response", [])
    sem = asyncio.Semaphore(5)

    async def check(f):
        fx = f.get("fixture", {})
        fid = fx.get("id")
        async with sem:
            d2, e2 = await _af_get("fixtures/players", {"fixture": fid})
        if e2 or not d2:
            return None
        for team_block in d2.get("response", []):
            for pl in team_block.get("players", []):
                if pl.get("player", {}).get("id") == player:
                    teams = f.get("teams", {})
                    goals = f.get("goals", {})
                    return {
                        "fixture_id": fid,
                        "date": (fx.get("date") or "")[:10],
                        "round": (f.get("league") or {}).get("round"),
                        "status": (fx.get("status") or {}).get("short"),
                        "home": (teams.get("home") or {}).get("name"),
                        "away": (teams.get("away") or {}).get("name"),
                        "goals_home": goals.get("home"),
                        "goals_away": goals.get("away"),
                    }
        return None

    results = await asyncio.gather(*[check(f) for f in fixtures_raw])
    fixtures = [r for r in results if r]
    fixtures.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"season": season, "team": team, "player": player, "fixtures": fixtures}


@app.get("/api/admin/varrer-competicoes")
async def api_varrer_competicoes(seasons: str = "", so_detectar: int = 0):
    """Apura e guarda as competições que a API não cobre por jogador.

    so_detectar=1 mostra o que seria varrido, sem gastar requisição de partida.
    seasons vazio = janela completa; ou "2025,2026" pra limitar."""
    anos = [int(s) for s in seasons.split(",") if s.strip().isdigit()] or _af_player_scan_seasons()
    if so_detectar:
        return {"seasons": anos, "alvos": await _af_competicoes_a_apurar(anos)}
    # Em background de propósito: varrer um campeonato inteiro (a Division 1 tem
    # centenas de partidas) leva minutos, e preso ao request o cliente desconecta
    # antes do fim — aí o FastAPI cancela a varredura no meio, deixando dado parcial.
    asyncio.create_task(_af_varrer_tudo(anos))
    return {"status": "started", "seasons": anos, "acompanhe": "/api/admin/stats-apuradas"}


@app.get("/api/categorias-ativas")
async def api_get_categorias_ativas():
    """Categorias que hoje passam pela tradução. Vazio = todas."""
    from database import get_categorias_ativas, TODAS_CATEGORIAS
    ativas = get_categorias_ativas()
    return {"ativas": ativas or TODAS_CATEGORIAS, "filtro_ligado": bool(ativas),
            "todas": TODAS_CATEGORIAS}


@app.post("/api/categorias-ativas")
async def api_set_categorias_ativas(request: Request):
    """Liga/desliga categorias sem deploy — o valor fica no banco."""
    from database import set_categorias_ativas, TODAS_CATEGORIAS
    body = await request.json()
    salvas = set_categorias_ativas(body.get("ativas") or [])
    return {"ok": True, "ativas": salvas or TODAS_CATEGORIAS, "filtro_ligado": bool(salvas)}


TRIAGEM_SYSTEM = (
    "Você classifica notícias de futebol saudita em UMA categoria. "
    "Responda SOMENTE com JSON, sem texto extra.\n"
    "Categorias:\n"
    "- mercado: transferências, sondagens, rumores, negociações, renovações, contratações, saídas, salários de contrato\n"
    "- lesao: machucados, cirurgias, recuperação, desfalques por questão médica\n"
    "- competicao: resultados, placares, tabela, jogos, sorteios, arbitragem\n"
    "- entrevista: declarações de jogador, técnico ou dirigente\n"
    "- treino: pré-temporada, amistosos, sessões de treino\n"
    "- financas: dívidas, receitas, patrocínio, fair play financeiro, gestão do clube\n"
    "- geral: qualquer outro assunto\n"
    "Na dúvida entre mercado e outra categoria, escolha mercado. "
    "Na dúvida entre lesao e outra categoria, escolha lesao."
)


@app.get("/api/admin/testar-triagem")
async def api_testar_triagem(n: int = 60, chars: int = 300):
    """Mede se o Haiku classifica tão bem quanto o Sonnet, usando artigos reais.

    A referência é a categoria que o Sonnet já gravou. Não é verdade absoluta, mas é
    exatamente a decisão que hoje custa caro — se o Haiku reproduz, a triagem barata
    serve. O que importa mais é o RECALL de mercado/lesão: pular uma notícia de
    transferência de verdade é o erro caro; classificar algo a mais é só ruído."""
    from processor import call_claude, CLAUDE_MODEL_TRIAGEM
    import json as _json

    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT id, title_orig, body_orig, category
            FROM articles
            WHERE category IS NOT NULL AND title_orig IS NOT NULL AND is_duplicate = 0
            ORDER BY collected_at DESC LIMIT %s
        """, (n,))
        arts = [dict(r) for r in c.fetchall()]
    if not arts:
        return {"erro": "sem artigos com categoria"}

    LOTE = 20
    previsto = {}
    async with httpx.AsyncClient() as client:
        for i in range(0, len(arts), LOTE):
            lote = arts[i:i + LOTE]
            itens = ""
            for idx, a in enumerate(lote):
                texto = (a.get("body_orig") or "")[:chars]
                itens += f'\n{idx+1}) {a.get("title_orig","")[:150]}\n{texto}\n'
            prompt = (
                'Classifique cada item. Responda: {"cats": ["categoria1", "categoria2", ...]} '
                f'com exatamente {len(lote)} itens, na ordem.\n{itens}'
            )
            try:
                raw = (await call_claude(prompt, TRIAGEM_SYSTEM, client,
                                         max_tokens=500, model=CLAUDE_MODEL_TRIAGEM)).strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                cats = _json.loads(raw.strip()).get("cats", [])
                for idx, a in enumerate(lote):
                    if idx < len(cats):
                        previsto[a["id"]] = str(cats[idx]).strip().lower()
            except Exception as e:
                return {"erro": f"{type(e).__name__}: {e}", "classificados_ate_agora": len(previsto)}

    ALVO = {"mercado", "lesao"}
    igual = vp = vn = fp = fn = 0
    divergencias = []
    for a in arts:
        p = previsto.get(a["id"])
        if p is None:
            continue
        real = (a["category"] or "").lower()
        if p == real:
            igual += 1
        manter_real, manter_prev = real in ALVO, p in ALVO
        if manter_real and manter_prev:
            vp += 1
        elif not manter_real and not manter_prev:
            vn += 1
        elif manter_prev and not manter_real:
            fp += 1
        else:
            fn += 1
            divergencias.append({"titulo": (a["title_orig"] or "")[:110],
                                 "sonnet": real, "haiku": p})
    total = vp + vn + fp + fn
    return {
        "artigos_testados": total,
        "concordancia_categoria_exata": f"{igual/total*100:.1f}%" if total else None,
        "decisao_manter_ou_pular": {
            "acerto": f"{(vp+vn)/total*100:.1f}%" if total else None,
            "recall_mercado_lesao": f"{vp/(vp+fn)*100:.1f}%" if (vp+fn) else "s/ casos",
            "precisao_mercado_lesao": f"{vp/(vp+fp)*100:.1f}%" if (vp+fp) else "s/ casos",
            "perdidos_por_engano": fn,
            "traduzidos_a_mais": fp,
        },
        "amostra_do_que_seria_perdido": divergencias[:10],
    }


@app.get("/api/admin/stats-apuradas")
async def api_stats_apuradas_resumo():
    """Quanto já foi apurado e guardado, por competição e temporada."""
    with get_conn() as conn:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("""
            SELECT league_id, league_name, season,
                   COUNT(*) AS jogadores,
                   SUM(appearences) AS jogos_somados,
                   SUM(goals) AS gols,
                   MAX(updated_at) AS atualizado_em
            FROM stats_apuradas
            GROUP BY league_id, league_name, season
            ORDER BY league_name, season
        """)
        return {"competicoes": [dict(r) for r in c.fetchall()]}


@app.get("/api/numeros/player-facets")
async def api_numeros_player_facets(player: int):
    """Universo real de combinações clube × competição × temporada do jogador.

    Devolve não só as listas de opções, mas TODAS as combinações que de fato existem
    (`combos`). Isso é o que permite os filtros da guia Jogador se restringirem
    mutuamente nos dois sentidos: escolher o NEOM reduz as temporadas e competições
    às que existem no NEOM, e escolher a Pro League reduz os clubes aos que jogaram
    aquela competição. Sem essa lista o front teria que adivinhar (ou pedir ao
    servidor a cada clique) quais cruzamentos são válidos.

    Uma requisição só: a carreira inteira já vem normalizada de _af_player_rows
    (sem linhas de competição não identificável, temporada pelo ano de início real)."""
    _, rows, _sem_dados, _reconstruidas = await _af_player_rows(player)
    clubs: dict = {}
    leagues: dict = {}
    combos = []
    for r in rows:
        s = r["stat"]
        team = s.get("team") or {}
        lg = s.get("league") or {}
        tid, lid, season = team.get("id"), lg.get("id"), r["real_season"]
        if tid is None or lid is None or season is None:
            continue
        clubs.setdefault(tid, {"id": tid, "name": team.get("name"), "logo": team.get("logo")})
        leagues.setdefault(lid, {"id": lid, "name": lg.get("name")})
        combos.append({"team": tid, "league": lid, "season": season})
    return {
        "player": player,
        "clubs": sorted(clubs.values(), key=lambda c: c["name"] or ""),
        "leagues": sorted(leagues.values(), key=lambda x: x["name"] or ""),
        "seasons": sorted({c["season"] for c in combos}, reverse=True),
        "combos": combos,
    }


@app.get("/api/numeros/player-stats")
async def api_numeros_player_stats(player: int, teams: str = "", seasons: str = "", league: str = ""):
    """Endpoint ÚNICO e consistente pra estatísticas de jogador — os 3 filtros
    (clube, temporada, competição) são sempre aplicados JUNTOS da mesma forma.
    Isso substitui os antigos /player-season (que ignorava o clube ao casar por
    nome de competição — causava bug real: casava o "King's Cup" de OUTRO clube
    do jogador na mesma temporada) e /player-club-career (que ignorava a
    competição). Nunca soma duas linhas de estatística de times diferentes.
    - teams: IDs de time separados por vírgula. Vazio = qualquer time (todos os
      times que o jogador já teve estatística, incluindo seleção nacional).
    - seasons: anos separados por vírgula. Vazio = todas as temporadas disponíveis.
    - league: id da competição (como string). Vazio = todas as competições.

    Toda a leitura vem de _af_player_rows, que já descarta linhas sem competição
    identificável e normaliza a temporada pelo ano de início real. Por isso os três
    filtros operam sobre a mesma lista e sempre significam a mesma coisa."""
    season_filter = {int(s) for s in seasons.split(",") if s.strip().lstrip("-").isdigit()}
    team_filter = {int(t) for t in teams.split(",") if t.strip().isdigit()}
    league_filter = league.strip()

    player_info, all_rows, descartadas, reconstruidas = await _af_player_rows(player)
    player_info = player_info or {}

    total_app = total_min = total_goals = total_assists = total_yellow = total_red = 0
    rating_sum = 0.0
    rating_weight = 0
    seasons_hit = []
    teams_hit: dict = {}
    leagues_hit: dict = {}
    name = player_info.get("name")
    photo = player_info.get("photo")
    nationality = player_info.get("nationality")

    for r in all_rows:
        s = r["stat"]
        real_season = r["real_season"]
        team = s.get("team") or {}
        lg = s.get("league") or {}

        if team_filter and team.get("id") not in team_filter:
            continue
        if season_filter and real_season not in season_filter:
            continue
        if league_filter and str(lg.get("id")) != league_filter:
            continue

        seasons_hit.append(real_season)
        if team.get("id"):
            teams_hit[team["id"]] = team.get("name")
        if lg.get("id") is not None:
            leagues_hit[lg.get("id")] = lg.get("name")
        games = s.get("games") or {}
        goals = s.get("goals") or {}
        cards = s.get("cards") or {}
        a = games.get("appearences") or 0
        total_app += a
        total_min += games.get("minutes") or 0
        total_goals += goals.get("total") or 0
        total_assists += goals.get("assists") or 0
        total_yellow += cards.get("yellow") or 0
        total_red += cards.get("red") or 0
        rt = games.get("rating")
        if rt is not None:
            try:
                rf = float(rt)
                w = a if a > 0 else 1
                rating_sum += rf * w
                rating_weight += w
            except (TypeError, ValueError):
                pass

    if not seasons_hit:
        return JSONResponse(
            {"error": "Nenhum dado encontrado pra essa combinação de clube/temporada/competição."},
            status_code=404,
        )

    avg_rating = (rating_sum / rating_weight) if rating_weight > 0 else None
    seasons_hit = sorted(set(seasons_hit))

    titles = []
    titles_note = None
    if True:  # títulos são cruzados por temporada + competição plausível, não dependem
              # do filtro de clube estar preenchido (vazio agora significa "todos")
        trophies_data, terr = await _af_get("trophies", {"player": player})
        if not terr and trophies_data:
            year_tokens = set()
            for s in seasons_hit:
                year_tokens.add(str(s))
                year_tokens.add(str(s + 1))

            def plausibly_this_club(tr: dict) -> bool:
                country = (tr.get("country") or "").strip().lower()
                lgn = (tr.get("league") or "").strip().lower()
                if country in ("saudi arabia", "saudi-arabia"):
                    return True
                continental_allow = {
                    "afc champions league", "afc champions league elite", "afc champions league two",
                    "afc cup", "arab club champions cup", "gcc champions league",
                    "fifa intercontinental cup", "fifa club world cup", "islamic solidarity cup",
                }
                if country in ("asia", "world") and lgn in continental_allow:
                    return True
                return False

            for tr in trophies_data.get("response", []):
                if not plausibly_this_club(tr):
                    continue
                t_season = str(tr.get("season") or "")
                if any(y and y in t_season for y in year_tokens):
                    titles.append({
                        "league": tr.get("league"), "country": tr.get("country"),
                        "season": tr.get("season"), "place": tr.get("place"),
                    })
        titles_note = "Cruzamento por temporada + competição plausível pro clube (a API de troféus não informa o clube do título) — reduz falsos positivos, mas não é uma certeza absoluta."

    return {
        "player_id": player, "name": name, "photo": photo, "nationality": nationality,
        "teams": list(teams_hit.values()), "team_ids": list(teams_hit.keys()),
        "leagues": [{"id": k, "name": v} for k, v in leagues_hit.items()],
        "seasons": seasons_hit,
        "stats": {
            "appearences": total_app, "minutes": total_min, "rating": avg_rating,
            "goals": total_goals, "assists": total_assists, "ga": total_goals + total_assists,
            "yellow_cards": total_yellow, "red_cards": total_red,
        },
        "titles": titles,
        "titles_note": titles_note,
        # Competições que a fonte cita pro jogador mas sem dado utilizável (ver
        # _af_player_rows). Vão como aviso, nunca somadas — preferimos dizer
        # "não temos" a exibir número inventado.
        # Exclui as que ENTRARAM na conta por outra linha (válida): o mesmo jogador
        # pode ter uma linha corrompida e uma boa da mesma competição, e avisar que
        # falta o que já está somado seria contraditório.
        "competicoes_sem_dados": sorted({
            d["league"] for d in descartadas
            if d.get("league")
            and d["league"] not in set(leagues_hit.values())
            and (not team_filter or d.get("team_id") in team_filter)
        }),
        # Competições cujos números NÓS contamos a partir de escalações e eventos,
        # porque a fonte não publica estatística por jogador nelas. Vai explícito:
        # o usuário precisa saber que ali o número é apuração nossa, não da API.
        "competicoes_reconstruidas": sorted({
            r["league"] for r in reconstruidas
            if r.get("league")
            and r["league"] in set(leagues_hit.values())
            and (not team_filter or r.get("team_id") in team_filter)
        }),
    }


_AF_WINDOW_CACHE: dict = {"data": None, "ts": 0.0}
_JANELA_SCRAPING = False

async def _bg_janela_scrape():
    """Roda janela_scraper em background (evita timeout HTTP)."""
    global _JANELA_SCRAPING
    if _JANELA_SCRAPING:
        return
    _JANELA_SCRAPING = True
    try:
        from janela_scraper import run_janela_scrape
        await run_janela_scrape()
    finally:
        _JANELA_SCRAPING = False

@app.get("/api/img-proxy")
async def img_proxy(url: str = ""):
    """Proxy para imagens (TM hotlink protegido, API-Football). Aceita URL completa via ?url=..."""
    allowed = (
        "https://img.a.transfermarkt.technology/",
        "https://tmssl.akamaized.net/",
        "https://media.api-sports.io/",
    )
    if not url or not any(url.startswith(p) for p in allowed):
        return Response(status_code=403)
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={
            "Referer": "https://www.transfermarkt.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }) as client:
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "image/jpeg")
                return Response(content=r.content, media_type=ct,
                                headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        pass
    return Response(status_code=404)


# Compat: proxy antigo por player_id (sem lm param — pode falhar para alguns players)
@app.get("/api/tm-photo/{player_id}")
async def tm_photo_proxy(player_id: str):
    url = f"https://img.a.transfermarkt.technology/portrait/small/{player_id}.jpg"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={
            "Referer": "https://www.transfermarkt.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }) as client:
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        pass
    return Response(status_code=404)


@app.get("/api/janela/inspecionar-tm")
async def api_janela_inspecionar_tm(caminho: str):
    """TEMPORÁRIO — devolve um resumo estrutural de uma página do Transfermarkt.

    Existe só porque o ambiente onde escrevo o parser não alcança o TM; o Railway
    alcança. Aceita apenas o caminho (nunca uma URL completa), então não vira um
    proxy aberto. Remover assim que o parser de treinadores estiver validado."""
    import httpx as _hx
    from bs4 import BeautifulSoup as _BS
    from janela_scraper import TM_BASE, TM_HEADERS
    if "://" in caminho or ".." in caminho:
        return {"erro": "informe apenas o caminho, sem domínio"}
    url = TM_BASE.rstrip("/") + "/" + caminho.lstrip("/")
    try:
        async with _hx.AsyncClient(timeout=30.0, follow_redirects=True, headers=TM_HEADERS) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return {"url": url, "http": r.status_code}
        soup = _BS(r.text, "lxml")
        def _celula(td):
            d = {"txt": td.get_text(" ", strip=True)[:70]}
            ls = [{"t": a.get_text(strip=True)[:40], "h": (a.get("href") or "")[:70]}
                  for a in td.select("a[href]")]
            if ls:
                d["links"] = ls
            ims = [i.get("title") or i.get("alt") for i in td.select("img") if (i.get("title") or i.get("alt"))]
            if ims:
                d["imgs"] = ims[:4]
            return d

        caixas = []
        for box in soup.select(".box")[:12]:
            h2 = box.select_one("h2")
            tabelas = []
            for t in box.select("table")[:6]:
                ths = [th.get_text(strip=True) for th in t.select("thead th")]
                # só detalha a tabela que interessa; as outras ficam no resumo
                detalhar = any("Sucessor" in x for x in ths)
                linhas = []
                corpo = t.find("tbody")
                # tr/td DIRETOS: o TM aninha tabelas dentro das células, e o select
                # recursivo misturava as linhas internas com as de verdade.
                trs = corpo.find_all("tr", recursive=False) if corpo else []
                for tr in trs[:(5 if detalhar else 1)]:
                    tds = tr.find_all("td", recursive=False)
                    linhas.append([_celula(td) for td in tds] if detalhar
                                  else [td.get_text(" ", strip=True)[:40] for td in tds])
                tabelas.append({"cabecalho": ths, "linhas": linhas})
            caixas.append({"titulo": (h2.get_text(strip=True) if h2 else None)[:80] if h2 else None,
                           "tabelas": tabelas})
        bandeiras = [{"cls": " ".join(i.get("class") or []), "title": i.get("title") or i.get("alt"),
                      "src": (i.get("src") or i.get("data-src") or "")[:70]}
                     for i in soup.select("img")
                     if "flagge" in ((i.get("src") or "") + (i.get("data-src") or "") + " ".join(i.get("class") or []))]
        return {"url": url, "http": 200, "titulo_pagina": (soup.title.string or "").strip() if soup.title else None,
                "qtd_box": len(soup.select(".box")), "bandeiras": bandeiras[:12], "caixas": caixas}
    except Exception as e:
        return {"url": url, "erro": f"{type(e).__name__}: {e}"}


@app.get("/api/af-window-transfers")
async def api_af_window_transfers(refresh: bool = False, background_tasks: BackgroundTasks = None):
    """
    Retorna transferências da janela SPL scrapeadas do Transfermarkt.
    refresh=true dispara novo scrape em background (retorna dados atuais imediatamente).
    """
    if refresh and not _JANELA_SCRAPING:
        background_tasks.add_task(_bg_janela_scrape)
    rows = get_window_transfers()
    data = [
        {
            "player_id":    r["player_id"],
            "player_name":  r["player_name"],
            "photo":        r["photo"],
            "age":          r["age"],
            "position":     r["position"],
            "market_value": r["market_value"],
            "type":         r["fee"] or "N/A",
            "team_in":      {"name": r["team_in_name"],  "logo": r["team_in_logo"]},
            "team_out":     {"name": r["team_out_name"], "logo": r["team_out_logo"]},
            "direction":    r["direction"],
            "nationality":  r.get("nationality") or "",
            "flag_url":     r.get("flag_url") or "",
            "date":         (r.get("transfer_date") or None),
        }
        for r in rows
    ]
    resp = JSONResponse(data)
    if _JANELA_SCRAPING or refresh:
        resp.headers["X-Janela-Scraping"] = "true"
    return resp


@app.post("/api/admin/scrape-janela")
async def api_admin_scrape_janela(background_tasks: BackgroundTasks):
    """Dispara scrape manual da janela em background (retorna imediatamente)."""
    if not _JANELA_SCRAPING:
        background_tasks.add_task(_bg_janela_scrape)
    return {"started": not _JANELA_SCRAPING, "already_running": _JANELA_SCRAPING}


@app.get("/api/admin/janela-status")
async def api_janela_status():
    """Status do scrape da janela: chave AF configurada, scraping em curso, fotos no cache."""
    import os
    from database import get_janela_player_photos
    af_key_set = bool(os.environ.get("API_FOOTBALL_KEY", ""))
    photos = get_janela_player_photos()
    return {
        "af_key_set": af_key_set,
        "scraping": _JANELA_SCRAPING,
        "cached_photos": len(photos),
    }


@app.get("/api/admin/test-af")
async def api_test_af(name: str = "Neymar", league: int = 307, season: int = 2025):
    """Testa uma busca na API-Football com league + season. Ex: ?name=Ronaldo&league=307&season=2025"""
    af_key = os.environ.get("API_FOOTBALL_KEY", "")
    if not af_key:
        return {"error": "API_FOOTBALL_KEY não configurada"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://v3.football.api-sports.io/players",
                headers={"x-apisports-key": af_key},
                params={"search": name, "league": league, "season": season},
            )
            data = r.json()
            return {
                "http_status": r.status_code,
                "remaining": r.headers.get("x-ratelimit-requests-remaining"),
                "params": {"search": name, "league": league, "season": season},
                "results": data.get("results", 0),
                "errors": data.get("errors", {}),
                "first_name": (data.get("response") or [{}])[0].get("player", {}).get("name"),
                "first_photo": (data.get("response") or [{}])[0].get("player", {}).get("photo"),
            }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/admin/debug-secao")
async def api_debug_secao(url: str = "https://arriyadiyah.com/news/section/2", n: int = 8):
    """Diagnóstico do coletor da seção do arriyadiyah: mostra o que o servidor
    realmente recebe e onde o parser está falhando (fetch, âncoras ou regex)."""
    from bs4 import BeautifulSoup
    from collector import (
        HEADERS, _ARR_LINK_RE, _ARR_ITEM_RE, parse_arriyadiyah_section,
    )
    out = {"url": url}
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            r = await client.get(url, headers=HEADERS)
        out["status"] = r.status_code
        out["html_len"] = len(r.text)
        out["final_url"] = str(r.url)
        if r.status_code != 200:
            out["html_sample"] = r.text[:500]
            return out
        soup = BeautifulSoup(r.text, "lxml")
        todas = soup.find_all("a", href=True)
        out["ancoras_total"] = len(todas)
        # Amostra crua de hrefs — foi o que revelou que os links são relativos.
        out["hrefs_crus"] = [a["href"][:70] for a in todas[:12]]
        ancoras = [a for a in todas if _ARR_LINK_RE.match(a["href"])]
        out["ancoras_de_artigo"] = len(ancoras)
        amostras = []
        for a in ancoras[:n]:
            txt = a.get_text(" ", strip=True)
            amostras.append({
                "href": a["href"][:90],
                "texto_len": len(txt),
                "texto": txt[:220],
                "casou_regex": bool(_ARR_ITEM_RE.match(txt)),
            })
        out["amostras"] = amostras
        out["total_casaram"] = sum(
            1 for a in ancoras if _ARR_ITEM_RE.match(a.get_text(" ", strip=True))
        )
        artigos = parse_arriyadiyah_section(r.text, "debug", "A")
        out["artigos_parseados"] = len(artigos)
        out["artigos"] = [
            {"titulo": x["title_orig"][:70], "publicado": x["published_at"],
             "pendente": x["pending_relevance"], "score": x["relevance_score"],
             "url": x["url"][:80]}
            for x in artigos[:n]
        ]
    except Exception as e:
        out["erro"] = f"{type(e).__name__}: {e}"
    return out


@app.get("/api/admin/debug-rss")
async def api_debug_rss(url: str = "https://news.google.com/rss/search?q=site:arriyadiyah.com&hl=ar&gl=SA&ceid=SA:ar", n: int = 3, titles_only: int = 0):
    """Inspeciona um feed RSS bruto: link real, summary, e o que o scraper consegue extrair dele."""
    import feedparser
    from scraper import fetch_article_content, extract_urls, should_skip, resolve_google_news_url
    HEADERS_DBG = {"User-Agent": "Mozilla/5.0 (compatible; SaudiFootballMonitor/1.0)"}
    out = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS_DBG)
            feed = feedparser.parse(resp.text)
            if titles_only:
                # Modo leve: só o que o feed anuncia, sem resolver redirect nem raspar.
                # Serve pra responder "essa notícia chegou a aparecer no feed?" sem
                # baixar dezenas de artigos.
                return {
                    "feed_url": url,
                    "total_no_feed": len(feed.entries),
                    "entries": [
                        {"title": getattr(e, "title", ""),
                         "published": getattr(e, "published", "")}
                        for e in feed.entries[:n]
                    ],
                }
            for entry in feed.entries[:n]:
                link = getattr(entry, "link", "") or ""
                summary = getattr(entry, "summary", "") or ""
                item = {
                    "title": getattr(entry, "title", ""),
                    "link": link,
                    "summary_len": len(summary),
                    "summary_sample": summary[:200],
                }
                try:
                    r2 = await client.get(link, headers=HEADERS_DBG, timeout=10)
                    item["resolved_url"] = str(r2.url)
                    item["resolved_status"] = r2.status_code
                    item["resolved_content_type"] = r2.headers.get("content-type", "")
                    item["resolved_html_len"] = len(r2.text)
                    item["should_skip"] = should_skip(str(r2.url))
                except Exception as e:
                    item["resolve_error"] = f"{type(e).__name__}: {e}"
                try:
                    real_url = await resolve_google_news_url(link, client)
                    item["resolved_real_url"] = real_url
                    if real_url:
                        content, img = await fetch_article_content(real_url, client)
                        item["scraped_content_len"] = len(content)
                        item["scraped_content_sample"] = content[:300]
                except Exception as e:
                    item["scrape_error"] = f"{type(e).__name__}: {e}"
                out.append(item)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"feed_url": url, "entries": out}


@app.post("/api/admin/reset-janela-photos")
async def api_reset_janela_photos(background_tasks: BackgroundTasks):
    """Zera fotos TM antigas no DB e dispara enriquecimento via AF em background."""
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE window_transfers SET photo = NULL")
            rows = c.rowcount
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not _JANELA_SCRAPING:
        background_tasks.add_task(_bg_janela_scrape)
    return {"photos_cleared": rows, "scrape_started": not _JANELA_SCRAPING}


@app.get("/api/debug-tm")
async def api_debug_tm(club_id: str = "583", season: int = 2025):
    """Debug: retorna resposta RAW da Transfermarkt API para um clube."""
    TM_BASE = "https://transfermarkt-api.fly.dev"
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r_clubs = await client.get(f"{TM_BASE}/competitions/SA1/clubs",
            params={"season_id": str(season)})
        clubs_raw = r_clubs.json()
        r_tr = await client.get(f"{TM_BASE}/clubs/{club_id}/transfers",
            params={"season_id": str(season)})
        tr_raw = r_tr.json()
    return {"clubs_sample": clubs_raw, "transfers_raw": tr_raw}


@app.get("/janela", response_class=HTMLResponse)
async def janela_page():
    hdr = _header("/janela")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Janela de Transferências · IARABÃO</title>
{_THEME_INIT_SCRIPT}
<style>
{_HEADER_CSS}
:root{{
  --bg:var(--c-bg);--surface:var(--c-bg-card);--surface2:var(--c-bg-soft);--border:var(--c-border);
  --text:var(--c-text);--text2:var(--c-muted-3);--accent:#4f9cf9;
  --green:#22c55e;--blue:#3b82f6;--amber:#f59e0b;--red:#ef4444;--purple:#a855f7;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
.main{{max-width:900px;margin:0 auto;padding:20px 16px}}
.page-title{{font-size:22px;font-weight:700;margin-bottom:4px}}
.page-sub{{font-size:13px;color:var(--text2);margin-bottom:20px}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;align-items:center}}
.filter-btn{{padding:6px 14px;border-radius:20px;border:1px solid var(--border);background:var(--surface);color:var(--text2);font-size:13px;cursor:pointer;transition:all .15s;white-space:nowrap}}
.filter-btn.active,.filter-btn:hover{{background:var(--accent);border-color:var(--accent);color:#fff}}
.search-box{{margin-left:auto;padding:6px 12px;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:13px;outline:none;width:200px}}
.search-box:focus{{border-color:var(--accent)}}
.cards{{display:flex;flex-direction:column;gap:8px}}
.card{{display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--surface);border:1px solid var(--border);border-radius:12px;position:relative;overflow:hidden;transition:border-color .15s}}
.card:hover{{border-color:#444}}
.card-rank{{font-size:12px;color:var(--text2);width:24px;text-align:center;flex-shrink:0;font-weight:600}}
.player-photo{{width:44px;height:44px;border-radius:50%;object-fit:cover;background:var(--surface2);flex-shrink:0;border:2px solid var(--border)}}
.player-initials{{width:44px;height:44px;border-radius:50%;background:var(--surface2);flex-shrink:0;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:var(--text2);letter-spacing:.5px}}
.clubs{{display:flex;align-items:center;gap:6px;flex-shrink:0}}
.club-logo{{width:28px;height:28px;object-fit:contain;border-radius:4px}}
.arrow{{color:var(--text2);font-size:14px}}
.card-body{{flex:1;min-width:0}}
.player-name{{font-size:16px;font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.transfer-meta{{display:flex;gap:5px;align-items:center;margin-top:3px;flex-wrap:wrap}}
.badge{{padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}}
.badge-in{{background:rgba(34,197,94,.15);color:#22c55e;border:1px solid rgba(34,197,94,.3)}}
.badge-out{{background:rgba(239,68,68,.15);color:#ef4444;border:1px solid rgba(239,68,68,.3)}}
.badge-loan{{background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid rgba(245,158,11,.3)}}
.badge-free{{background:rgba(148,163,184,.15);color:#94a3b8;border:1px solid rgba(148,163,184,.3)}}
.badge-paid{{background:rgba(79,156,249,.15);color:#4f9cf9;border:1px solid rgba(79,156,249,.3)}}
.player-meta-line{{font-size:11px;color:var(--text2);margin:2px 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;gap:4px}}
.flag-img{{width:16px;height:12px;object-fit:cover;border-radius:1px;flex-shrink:0}}
.transfer-date{{font-size:12px;color:var(--text2)}}
.card-side{{margin-left:auto;flex-shrink:0;text-align:right}}
.type-label{{font-size:10px;font-weight:600;color:var(--text2)}}
.type-value{{font-size:10px;font-weight:600;color:var(--text2)}}
.state{{text-align:center;padding:60px 20px;color:var(--text2)}}
.state-icon{{font-size:40px;margin-bottom:12px}}
.refresh-btn{{padding:8px 20px;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:13px;cursor:pointer;margin-top:16px}}
.refresh-btn:hover{{background:var(--border)}}
.count-label{{font-size:13px;color:var(--text2)}}
.club-strip{{display:flex;gap:6px;overflow-x:auto;padding:4px 0 12px;margin-bottom:4px;scrollbar-width:none}}
.club-strip::-webkit-scrollbar{{display:none}}
.club-chip{{flex-shrink:0;width:52px;height:52px;border-radius:12px;background:var(--surface);border:2px solid var(--border);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:border-color .15s,background .15s;padding:5px}}
.club-chip:hover{{border-color:var(--text2);background:var(--surface2)}}
.club-chip.active{{border-color:var(--accent);background:rgba(79,156,249,.12)}}
.club-chip img{{width:100%;height:100%;object-fit:contain}}
</style>
</head>
<body>
{hdr}
<div class="main">
  <div class="page-title">Janela de Transferências</div>
  <div class="page-sub" id="subTitle">Carregando…</div>

  <div class="club-strip" id="clubStrip">
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/1114.png"    onclick="setClub(this)" title="Al-Hilal SFC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/1114.png"    alt="Al-Hilal"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/18544.png"   onclick="setClub(this)" title="Al-Nassr FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/18544.png"   alt="Al-Nassr"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/8023.png"    onclick="setClub(this)" title="Al-Ittihad Club"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/8023.png"    alt="Al-Ittihad"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/18487.png"   onclick="setClub(this)" title="Al-Ahli SFC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/18487.png"   alt="Al-Ahli"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/40039.png"   onclick="setClub(this)" title="Abha Club"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/40039.png"   alt="Abha"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/52358.png"   onclick="setClub(this)" title="Al-Diriyah FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/52358.png"   alt="Al-Diriyah"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/7732.png"    onclick="setClub(this)" title="Al-Ettifaq FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/7732.png"    alt="Al-Ettifaq"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/28848.png"   onclick="setClub(this)" title="Al-Faisaly FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/28848.png"   alt="Al-Faisaly"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/27221.png"   onclick="setClub(this)" title="Al-Fateh SC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/27221.png"   alt="Al-Fateh"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/50531.png"   onclick="setClub(this)" title="Al-Fayha FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/50531.png"   alt="Al-Fayha"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/9131.png"    onclick="setClub(this)" title="Al-Hazem SC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/9131.png"    alt="Al-Hazem"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/6070.png"    onclick="setClub(this)" title="Al-Khaleej FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/6070.png"    alt="Al-Khaleej"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/91427.png"   onclick="setClub(this)" title="Al-Kholood Club"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/91427.png"   alt="Al-Kholood"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/26069.png"   onclick="setClub(this)" title="Al-Qadsiah FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/26069.png"   alt="Al-Qadsiah"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/31008.png"   onclick="setClub(this)" title="Al-Riyadh SC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/31008.png"   alt="Al-Riyadh"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/9840.png"    onclick="setClub(this)" title="Al-Shabab FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/9840.png"    alt="Al-Shabab"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/28844.png"   onclick="setClub(this)" title="Al-Taawoun FC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/28844.png"   alt="Al-Taawoun"></div>
    <div class="club-chip" data-logo="https://tmssl.akamaized.net//images/wappen/homepageSmall/34911.png"   onclick="setClub(this)" title="NEOM SC"><img src="https://tmssl.akamaized.net//images/wappen/homepageSmall/34911.png"   alt="NEOM"></div>
  </div>

  <div class="filters">
    <button class="filter-btn active" onclick="setDir('all',this)">Todos</button>
    <button class="filter-btn" onclick="setDir('in',this)">Entradas ↓</button>
    <button class="filter-btn" onclick="setDir('out',this)">Saídas ↑</button>
    <button class="filter-btn" onclick="setDir('loan',this)">Empréstimos</button>
    <button class="filter-btn" onclick="setDir('fimloan',this)">Fim de Empréstimo</button>
    <input class="search-box" type="text" placeholder="Buscar jogador ou clube…" oninput="applyFilters()" id="searchBox">
    <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text2);cursor:pointer;white-space:nowrap;padding:4px 10px;border-radius:20px;border:1px solid var(--border);background:var(--surface);transition:all .15s" onmouseenter="this.style.borderColor='var(--accent)'" onmouseleave="this.style.borderColor='var(--border)'">
      <input type="checkbox" id="foreignOnly" onchange="applyFilters()" style="width:14px;height:14px;accent-color:var(--accent);cursor:pointer;">
      Estrangeiros
    </label>
  </div>

  <div id="cards" class="cards">
    <div class="state"><div class="state-icon">⏳</div><div>Carregando transferências da janela…</div></div>
  </div>
</div>

<script>
let ALL = [];
let currentDir = 'all';
let currentClub = null; // logo URL do clube filtrado, ou null para todos

function showToast(msg, duration) {{
  let t = document.getElementById('janela-toast');
  if (!t) {{
    t = document.createElement('div');
    t.id = 'janela-toast';
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--c-text);color:var(--c-bg);font-size:0.72rem;font-weight:700;padding:10px 20px;border-radius:99px;z-index:999;opacity:0;transition:opacity .3s;white-space:nowrap;';
    document.body.appendChild(t);
  }}
  t.textContent = msg;
  t.style.opacity = '1';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => {{ t.style.opacity = '0'; }}, duration || 8000);
}}

async function load(refresh) {{
  try {{
    const url = '/api/af-window-transfers' + (refresh ? '?refresh=true' : '');
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const scraping = r.headers.get('X-Janela-Scraping') === 'true';
    ALL = await r.json();
    if (!Array.isArray(ALL)) {{
      ALL = [];
      document.getElementById('cards').innerHTML = '<div class="state"><div class="state-icon">⚠️</div><div>' + JSON.stringify(ALL) + '</div></div>';
      return;
    }}
    applyFilters();
    if (scraping) {{
      showToast('⏳ Buscando fotos... recarregue a página em ~5 min', 12000);
    }}
  }} catch(e) {{
    document.getElementById('cards').innerHTML = '<div class="state"><div class="state-icon">❌</div><div>' + e.message + '</div><button class="refresh-btn" onclick="load(true)">Tentar novamente</button></div>';
  }}
}}

function setClub(el) {{
  const logo = el.dataset.logo;
  if (currentClub === logo) {{
    currentClub = null;
    el.classList.remove('active');
  }} else {{
    currentClub = logo;
    document.querySelectorAll('.club-chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
  }}
  applyFilters();
}}

function setDir(dir, btn) {{
  currentDir = dir;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

function applyFilters() {{
  const q = (document.getElementById('searchBox').value || '').toLowerCase();
  let items = ALL;
  const isFimLoan = t => (t.type||'').toLowerCase().startsWith('fim');
  if (currentDir === 'in')       items = items.filter(t => t.direction === 'in'  && !isFimLoan(t));
  else if (currentDir === 'out') items = items.filter(t => t.direction === 'out' && !isFimLoan(t));
  else if (currentDir === 'loan') items = items.filter(t => (t.type||'').toLowerCase() === 'empr\u00e9stimo');
  else if (currentDir === 'fimloan') items = items.filter(t => isFimLoan(t));
  if (currentClub) {{
    // Se há filtro direcional, o clube deve ser o lado correto da transferência
    if (currentDir === 'in')  items = items.filter(t => t.team_in?.logo  === currentClub);
    else if (currentDir === 'out') items = items.filter(t => t.team_out?.logo === currentClub);
    else items = items.filter(t => t.team_in?.logo === currentClub || t.team_out?.logo === currentClub);
  }}
  if (q) items = items.filter(t =>
    (t.player_name||'').toLowerCase().includes(q) ||
    (t.team_in?.name||'').toLowerCase().includes(q) ||
    (t.team_out?.name||'').toLowerCase().includes(q)
  );
  if (document.getElementById('foreignOnly')?.checked)
    items = items.filter(t => !(t.nationality||'').toLowerCase().includes('saudi'));

  const total = ALL.length;
  const shown = items.length;
  const date = ALL.length ? ALL[0].date?.slice(0,7) : '';
  document.getElementById('subTitle').textContent =
    `${{shown}} transferência${{shown!==1?'s':''}} · janela ${{date || 'atual'}}` +
    (shown !== total ? ` (de ${{total}})` : '');

  if (!items.length) {{
    document.getElementById('cards').innerHTML = '<div class="state"><div class="state-icon">🔍</div><div>Nenhuma transferência encontrada</div></div>';
    return;
  }}

  document.getElementById('cards').innerHTML = items.map((t, i) => cardHtml(t, i+1)).join('');
}}

function typeClass(t) {{
  const v = (t.type||'').toLowerCase();
  if (v.includes('loan') || v.includes('empr')) return 'badge-loan';
  if (v === 'free' || v === 'n/a' || v.includes('custo zero') || v.includes('livre') || !t.type) return 'badge-free';
  return 'badge-paid';
}}
function typeLabel(t) {{
  const v = t.type || 'N/A';
  const vl = v.toLowerCase();
  if (vl.includes('fim') && vl.includes('empr')) return 'Fim Emp.';
  if (vl === 'loan' || vl.includes('empr')) return 'Emp.';
  if (vl === 'free' || vl.includes('custo zero') || vl.includes('livre')) return 'Livre';
  if (v === 'N/A') return '';
  return v;
}}
function dirBadge(t) {{
  return t.direction === 'in'
    ? '<span class="badge badge-in" title="Entrada">▷</span>'
    : '<span class="badge badge-out" title="Saída">◁</span>';
}}
const POS_ABBR = {{'Goleiro':'GL','Lateral Dir.':'LD','Lateral Direito':'LD','Lateral Esq.':'LE','Lateral Esquerdo':'LE','Zagueiro':'ZG','Volante':'VL','Meia Central':'MC','Meia Ofensivo':'MO','Meia Atacante':'MA','Meia':'MC','Ponta Direita':'PD','Ponta Esquerda':'PE','Centroavante':'CA','Atacante':'AT','Segundo Atacante':'SA','2º Atacante':'SA','Ala Direito':'AD','Ala Esquerdo':'AE','Defensor Central':'ZG','Meio-campista':'MC','Meia-Atacante':'MA','Extremo Direito':'PD','Extremo Esquerdo':'PE'}};
function posAbbr(pos) {{ return POS_ABBR[pos] || (pos||'').slice(0,2).toUpperCase() || ''; }}

const NAT_FLAG = {{'Brasil':'br','Arábia Saudita':'sa','Argentina':'ar','França':'fr','Portugal':'pt','Espanha':'es','Alemanha':'de','Holanda':'nl','Bélgica':'be','Marrocos':'ma','Senegal':'sn','Costa do Marfim':'ci','Nigéria':'ng','Egito':'eg','Gana':'gh','Camarões':'cm','Tunísia':'tn','Argélia':'dz','Mali':'ml','Guiné':'gn','Burkina Faso':'bf','Guiné-Bissau':'gw','Serra Leoa':'sl','Gabão':'ga','Gâmbia':'gm','Togo':'tg','Benin':'bj','Comores':'km','Guiné Equatorial':'gq','Angola':'ao','Congo':'cg','República Democrática do Congo':'cd','Uganda':'ug','Ruanda':'rw','Tanzânia':'tz','Moçambique':'mz','Zâmbia':'zm','Zimbábue':'zw','Quênia':'ke','Etiópia':'et','Sudão':'sd','Líbia':'ly','Mauritânia':'mr','Uruguai':'uy','Colômbia':'co','Chile':'cl','Peru':'pe','Equador':'ec','Bolívia':'bo','Paraguai':'py','Venezuela':'ve','México':'mx','Costa Rica':'cr','Honduras':'hn','Guatemala':'gt','El Salvador':'sv','Panamá':'pa','Cuba':'cu','República Dominicana':'do','Haiti':'ht','Jamaica':'jm','Estados Unidos':'us','Canadá':'ca','Inglaterra':'gb-eng','Escócia':'gb-sct','País de Gales':'gb-wls','Irlanda do Norte':'gb-nir','Irlanda':'ie','Itália':'it','Grécia':'gr','Turquia':'tr','Sérvia':'rs','Croácia':'hr','Polônia':'pl','Dinamarca':'dk','Suécia':'se','Noruega':'no','Finlândia':'fi','Suíça':'ch','Áustria':'at','República Tcheca':'cz','Eslováquia':'sk','Hungria':'hu','Romênia':'ro','Bósnia e Herzegovina':'ba','Montenegro':'me','Macedônia do Norte':'mk','Albânia':'al','Kosovo':'xk','Rússia':'ru','Ucrânia':'ua','Bielorrússia':'by','Geórgia':'ge','Armênia':'am','Azerbaijão':'az','Cazaquistão':'kz','Japão':'jp','Coreia do Sul':'kr','China':'cn','Austrália':'au','Iraque':'iq','Jordânia':'jo','Emirados Árabes Unidos':'ae','Kuwait':'kw','Bahrein':'bh','Omã':'om','Qatar':'qa','Iêmen':'ye','Síria':'sy','Líbano':'lb','Israel':'il','Irã':'ir','Paquistão':'pk','Índia':'in','África do Sul':'za'}};

function showInitials(el, text) {{
  const d = document.createElement('div');
  d.className = 'player-initials';
  d.textContent = text;
  el.parentNode && el.parentNode.replaceChild(d, el);
}}

function flagUrl(nat) {{
  const code = NAT_FLAG[nat];
  if (!code) return '';
  return `https://flagcdn.com/16x12/${{code}}.png`;
}}

function cardHtml(t, rank) {{
  const inLogo  = t.team_in?.logo  ? `<img class="club-logo" src="${{t.team_in.logo}}"  onerror="this.style.opacity=.3" alt="${{t.team_in?.name||''}}">` : '<div class="club-logo"></div>';
  const outLogo = t.team_out?.logo ? `<img class="club-logo" src="${{t.team_out.logo}}" onerror="this.style.opacity=.3" alt="${{t.team_out?.name||''}}">` : '<div class="club-logo"></div>';
  const _code = (NAT_FLAG[t.nationality||''] || '').toUpperCase();
  const _flagEmoji = _code.length === 2
    ? String.fromCodePoint(0x1F1E6 + _code.charCodeAt(0) - 65, 0x1F1E6 + _code.charCodeAt(1) - 65)
    : '';
  const tLabel  = typeLabel(t);
  const tClass  = typeClass(t);
  const outName = t.team_out?.name || '';
  const inName  = t.team_in?.name  || '';
  return `<div class="card" style="flex-wrap:wrap">
    <div class="clubs">${{outLogo}}<span class="arrow">→</span>${{inLogo}}</div>
    <div class="card-body">
      <div class="player-name">${{t.player_name || '—'}}</div>
    </div>
    <div class="transfer-meta" style="width:100%;padding:3px 0 0;justify-content:space-between">
      <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
        ${{dirBadge(t)}}
        ${{_flagEmoji ? `<span class="badge" style="background:var(--surface2);border:1px solid var(--border);padding:2px 5px">${{_flagEmoji}}</span>` : ''}}
        ${{t.position ? `<span class="badge" style="background:var(--surface2);color:var(--text2);border:1px solid var(--border)">${{posAbbr(t.position)}}</span>` : ''}}
        ${{t.age ? `<span class="badge" style="background:var(--surface2);color:var(--text2);border:1px solid var(--border)">${{t.age}}</span>` : ''}}
        ${{tLabel ? `<span class="badge ${{tClass}}">${{tLabel}}</span>` : ''}}
      </div>
      <div style="font-size:9px;color:var(--text2);text-align:right;white-space:nowrap;align-self:flex-end">${{[outName,inName].filter(Boolean).join(' → ')}}</div>
    </div>
  </div>`;
}}

load(false);
</script>
</body>
</html>""")
