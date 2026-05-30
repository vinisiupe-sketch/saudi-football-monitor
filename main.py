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

# Servir fontes e máscaras para o gerador de posts
app.mount("/fonts", StaticFiles(directory="public/fonts"), name="fonts")
app.mount("/masks", StaticFiles(directory="public/masks"), name="masks")


# ─── Dashboard ───────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    articles = get_recent_articles(hours=24, limit=50)
    articles = [a for a in articles if a.get("relevance_score", 0) >= 0.34]

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
        title = a.get("title_pt") or a.get("title_orig") or "—"
        body  = (a.get("body_pt") or a.get("body_orig") or "")[:280]
        if len(body) == 280:
            body += "…"
        image_url = a.get("image_url") or ""
        category = a.get("category")
        copy_text = f"{title}\\n\\n{a.get('body_pt') or a.get('body_orig') or ''}".replace("`", "'")
        post_url = f"/gerador?texto={quote(title + chr(10) + chr(10) + (a.get('body_pt') or a.get('body_orig') or ''))}"
        collected = (a.get("collected_at") or "")[:16].replace("T", " ")
        category = category or "geral"
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
            </div>
            <a href="{a['url']}" target="_blank" class="card-title">{title}</a>
            <p class="card-text">{body}</p>
            <div class="card-footer">
              <span class="card-date">{collected}</span>
              <div style="display:flex;gap:6px;">
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
    a.copy-btn {{ background: #f0fdf4; color: #15803d; }}
    a.copy-btn:hover {{ background: #dcfce7; }}
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

    prompt_texto = (
        "Traduza e resuma o texto jornalístico abaixo para o português. Siga exatamente o formato do exemplo.\n\n"
        "EXEMPLO DE INPUT: \"Ben Jacobs: Jurgen Klopp is a dream target for Al-Ittihad...\"\n\n"
        "EXEMPLO DE OUTPUT ESPERADO: \"Jürgen Klopp é visto como o alvo dos sonhos do Al-Ittihad...\n\nFonte: Ben Jacobs\"\n\n"
        "Regras: apenas texto corrido, sem emojis, sem hashtags, sem exclamações, sem títulos, sem negrito, "
        "sem formatação de qualquer tipo. Somente parágrafos simples. Ao final, \"Fonte:\" seguido do autor ou veículo identificável no texto original."
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
