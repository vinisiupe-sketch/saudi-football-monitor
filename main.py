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
_ICO_INJURY  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>'
_ICO_JANELA  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16V4m0 0L3 8m4-4 4 4"/><path d="M17 8v12m0 0 4-4m-4 4-4-4"/></svg>'

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
        ("/janela",          _ICO_JANELA,    "Janela",          ""),
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




# ─── Janela de Transferências (API Football) ─────────────────────────────────

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
<style>
:root{{
  --bg:#0d0d0d;--surface:#161616;--surface2:#1e1e1e;--border:#2a2a2a;
  --text:#e8e8e8;--text2:#999;--accent:#4f9cf9;
  --green:#22c55e;--blue:#3b82f6;--amber:#f59e0b;--red:#ef4444;--purple:#a855f7;
}}
[data-theme=light]{{
  --bg:#f4f4f5;--surface:#fff;--surface2:#f0f0f0;--border:#e0e0e0;
  --text:#111;--text2:#666;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
header{{display:flex;align-items:center;gap:6px;padding:10px 16px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100}}
.brand{{font-weight:700;font-size:13px;letter-spacing:.08em;color:var(--text);text-decoration:none;margin-right:4px}}
.nav-icon{{display:flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:8px;color:var(--text2);text-decoration:none;border:none;background:none;cursor:pointer;transition:background .15s,color .15s}}
.nav-icon:hover,.nav-icon.active{{background:var(--surface2);color:var(--text)}}
.nav-icon.active{{color:var(--accent)}}
.token-dot{{width:7px;height:7px;border-radius:50%;background:#444;margin-right:2px;flex-shrink:0}}
.token-dot.ok{{background:#22c55e}}.token-dot.broken{{background:#ef4444}}
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
    ? '<span class="badge badge-in" title="Entrada">➜</span>'
    : '<span class="badge badge-out" title="Saída">✕</span>';
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
    <div class="transfer-meta" style="width:100%;padding:3px 0 0;margin-left:28px;justify-content:space-between">
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
