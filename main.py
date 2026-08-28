"""
Saudi Football Monitor — FastAPI app principal.
"""
import os
import base64
import secrets
from zoneinfo import ZoneInfo

# Agrupar a agenda por dia exige um fuso do lado do servidor: o seu "sábado"
# começa à meia-noite de Brasília, não à meia-noite UTC.
# Testei os horários reais: jogo saudita à noite e jogo asiático de manhã caem
# no mesmo dia nos dois fusos, então na maior parte do tempo isso não muda
# nada. A diferença aparece na faixa 00h–03h UTC, que em Brasília ainda é o dia
# anterior — é lá que agrupar por UTC jogaria o jogo para o dia errado.
BRT = ZoneInfo("America/Sao_Paulo")
import re
import shutil
import subprocess
import tempfile
import unicodedata
import asyncio
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
import httpx
from database import init_db, get_recent_articles, get_low_score_articles, get_collection_logs, set_flag, get_all_flags, get_trashed_articles, get_flagged_articles, cleanup_old_trash, get_conn, get_state, set_state, get_token_status, set_token_status, get_injuries, get_window_transfers, get_window_transfers_last_scraped, upsert_window_transfers, enfileirar_post, listar_posts, obter_post, atualizar_texto_post, marcar_post, reservar_post_para_publicar, contar_publicados_hoje, salvar_clube_extra, obter_escudo_extra, expirar_posts_vencidos, tem_escudo_extra, status_das_chaves, registrar_gol, gols_vistos, criar_pedido_clipe, clipes_a_cortar, mudar_estado_clipe, entregar_clipe, ajustar_clipe, texto_do_clipe, clipe_publicado, erro_no_clipe, clipes_recentes, video_do_clipe, um_clipe, redefinir_janela, registrar_escalacao, escalacoes_vistas, listar_lives, remover_live, titulo_da_live, lives_disponiveis, salvar_disponiveis, adicionar_live_do_canal, CANAL, MAX_LIVES, tamanho_do_banco_mb, LIMITE_BANCO_MB, guardar_clipe, descartar_clipes, marcar_corte, criar_usuario, usuario_por_email, marcar_acesso, trocar_senha, listar_usuarios, tem_algum_usuario, cruzar_api_football, congelar_elenco, elenco_congelado, resumo_do_congelamento, salvar_jogadores, listar_jogadores, contar_jogadores, cruzar_transfermarkt, padronizar_clubes_gravados, registrar_convite, convite_valido, queimar_convite, listar_convites, papel_do_usuario, mudar_papel, salvar_previa, previas_do_dia, dias_com_previa, previa_com_escalacao, salvar_arbitragem, arbitragem_do_dia, dias_com_arbitragem, nomes_de_arbitros, traducoes_de_arbitros, definir_nome_de_arbitro, marcar_transmissao, transmissao_do_jogo, transmissoes, jogos_com_transmissao
import psycopg2.extras
from scheduler import run_pipeline, create_scheduler
import fim_sportmonks as sm
import clubs
import glossary
import ajustes
import contas
from sources import SOURCE_MOON
import elenco_tm
import x_client
from janela_scraper import TM_HEADERS as _TM_H
TM_HEADERS_UA = _TM_H.get("User-Agent", "Mozilla/5.0")
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


# Se a subida falhar, guardo o motivo aqui para /api/diag/banco poder contar.
_FALHA_NA_SUBIDA: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    # O init_db() ESCREVE (cria tabelas, altera colunas). Num banco que não
    # aceita escrita — disco cheio, por exemplo — ele levanta, o lifespan
    # morre junto, e o app inteiro não sobe.
    #
    # Foi o que aconteceu hoje: o app rodou o dia todo devolvendo 500 nas
    # páginas que leem dados, e no primeiro reinício não voltou mais. Ficamos
    # sem app E sem as rotas de diagnóstico, que são justamente as que diriam
    # o que houve. O remédio ficou trancado do lado de dentro do problema.
    #
    # Agora ele sobe mesmo assim. As telas vão dar erro — e devem — mas as
    # rotas que não dependem do banco continuam de pé, e /api/diag/banco pode
    # contar o que está acontecendo.
    for etapa, fn in (("init_db", init_db),
                      ("cleanup_old_trash", cleanup_old_trash),
                      ("limpar_posts", _limpar_posts_de_competicao_removida),
                      ("transmissoes", _mudar_transmissoes_para_tabela),
                      ("clubes", padronizar_clubes_gravados)):
        try:
            fn()
        except Exception as e:
            _FALHA_NA_SUBIDA.append(f"{etapa}: {type(e).__name__}: {str(e)[:300]}")
            print(f"[SUBIDA] {etapa} falhou: {type(e).__name__}: {e}", flush=True)
    try:
        scheduler = create_scheduler()
        scheduler.start()
        asyncio.create_task(run_pipeline())
        # Em segundo plano, e não na fila de cima, porque é async e porque
        # raspar 18 elencos leva tempo — o app não pode ficar esperando isso
        # para começar a responder. Roda uma vez só; ver congelar_elencos_do_tm.
        asyncio.create_task(congelar_elencos_do_tm())
    except Exception as e:
        _FALHA_NA_SUBIDA.append(f"agendador: {type(e).__name__}: {str(e)[:300]}")
        print(f"[SUBIDA] agendador falhou: {type(e).__name__}: {e}", flush=True)
    yield
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown()
    except Exception:
        pass


app = FastAPI(title="Saudi Football Monitor", lifespan=lifespan)


@app.get("/manifest.webmanifest")
async def manifest():
    """Diz ao celular o nome, o ícone e como abrir. É o que separa um atalho
    comum de um app de tela de início."""
    return JSONResponse({
        "name": "IARABÃO",
        "short_name": "IARABÃO",
        "description": "Notícias, números e posts do futebol saudita.",
        "start_url": "/",
        "scope": "/",
        # standalone: abre sem a barra do Safari, como app.
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#08080E",
        "theme_color": "#08080E",
        "lang": "pt-BR",
        "icons": [
            {"src": "/pwa/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/pwa/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/pwa/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        # Atalhos no toque longo do ícone. O primeiro é o que tem pressa.
        "shortcuts": [
            {"name": "Fim de jogo", "url": "/fim-de-jogo"},
            {"name": "Agendamentos", "url": "/posts"},
            {"name": "Números", "url": "/numeros"},
        ],
    }, media_type="application/manifest+json")


# Service worker deliberadamente sem cache de página. Um app de placar ao vivo
# que serve HTML guardado mostraria jogo antigo como se fosse de agora — o pior
# defeito possível aqui. Ele existe só para o navegador considerar o site
# instalável, e é onde o push entraria se um dia quisermos alerta de fim de jogo.
_SW_JS = """self.addEventListener('install', function(){ self.skipWaiting(); });
self.addEventListener('activate', function(e){ e.waitUntil(self.clients.claim()); });
"""


@app.get("/sw.js")
async def service_worker():
    # Precisa sair da raiz para valer no site inteiro, e sem cache para que uma
    # correção aqui não fique presa no aparelho.
    return Response(content=_SW_JS, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})

# Servir fontes e máscaras para o gerador de posts
app.mount("/pwa", StaticFiles(directory="public/pwa"), name="pwa")
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
_ICO_POSTS   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/></svg>'
_ICO_ELENCOS = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
_ICO_INJURY  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>'
_ICO_CLIPE   = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M3 8h18v11a2 2 0 0 1-2 2H5a2 2 0 0 '
                '1-2-2V8Z"/><path d="m3 8 2.5-4h13L21 8"/><path d="m8 4-2 4"/>'
                '<path d="m13 4-2 4"/><path d="m18 4-2 4"/></svg>')
_ICO_APITO   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
_ICO_ARBITRO = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M13 8h6a3 3 0 0 1 0 6h-1.2A6 6 0 1 1 13 8Z"/>'
                '<circle cx="9" cy="11" r="2"/><path d="M13 8 9.5 4.5"/></svg>')
_ICO_PREVIA  = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M4 4h11l5 5v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"/>'
                '<path d="M14 4v6h6"/><path d="M8 14h7M8 17.5h5"/></svg>')
_ICO_MAIS    = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>'
_ICO_JANELA  = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16V4m0 0L3 8m4-4 4 4"/><path d="M17 8v12m0 0 4-4m-4 4-4-4"/></svg>'

# ══════════════════════════════════════════════════════════════════════════
# A PALETA
#
# Vem da referência que você mandou: preto quase puro, verde-limão gritante,
# âmbar e vermelho. É uma paleta de contraste alto, feita para telas escuras —
# e o app passa a nascer escuro por causa disso.
#
# Os nomes dizem a FUNÇÃO, não a cor. "--c-acento" e não "--c-limao": se um
# dia a marca mudar de verde para laranja, muda aqui e o app inteiro segue,
# em vez de eu ter de caçar "limão" em quinze telas.
#
#   #08080E  o fundo, preto com um toque de azul
#   #B6FF00  o acento — o que você deve olhar primeiro
#   #FFBE5D  atenção, algo esperando
#   #FD5D5D  negativo, recusado, erro
PALETA = {
    "acento": "#B6FF00",
    "alerta": "#FFBE5D",
    "negativo": "#FD5D5D",
    "fundo": "#08080E",
}

_THEME_VARS_CSS = (
    # Claro: mesma família de acentos, mas o limão vira PREENCHIMENTO com
    # texto escuro em cima. Limão como cor de texto sobre branco é ilegível —
    # e é assim que a referência usa, aliás: bloco verde, letra preta.
    "    :root { --c-bg:#f2f2ef; --c-bg-card:#ffffff; --c-bg-soft:#fafaf8; "
    "--c-text:#08080E; --c-muted-1:#8a8a92; --c-muted-2:#9a9aa2; "
    "--c-muted-3:#6b6b73; --c-muted-4:#4a4a52; --c-muted-5:#5a5a62; "
    "--c-muted-6:#3a3a42; --c-line:#d8d8d2; --c-border:rgba(8,8,14,.10); "
    "--c-border-2:rgba(8,8,14,.18); --c-hover-tint:rgba(8,8,14,.05); "
    "--c-success:#4d7c00; --c-error:#d33b3b; "
    "--c-acento:#B6FF00; --c-acento-texto:#08080E; "
    "--c-alerta:#FFBE5D; --c-negativo:#FD5D5D; }\n"
    "    :root[data-theme=\"dark\"] { --c-bg:#08080E; --c-bg-card:#14141B; "
    "--c-bg-soft:#1C1C25; --c-text:#F2F2F5; --c-muted-1:#7a7a86; "
    "--c-muted-2:#8a8a96; --c-muted-3:#9a9aa6; --c-muted-4:#c4c4cc; "
    "--c-muted-5:#b0b0ba; --c-muted-6:#d8d8e0; --c-line:#2A2A35; "
    "--c-border:rgba(255,255,255,.08); --c-border-2:rgba(255,255,255,.16); "
    "--c-hover-tint:rgba(182,255,0,.08); "
    "--c-success:#B6FF00; --c-error:#FD5D5D; "
    "--c-acento:#B6FF00; --c-acento-texto:#08080E; "
    "--c-alerta:#FFBE5D; --c-negativo:#FD5D5D; }\n"
)

_HEADER_CSS = _THEME_VARS_CSS + (
    # TODAS as classes daqui levam o prefixo "iar-".
    #
    # Não é preciosismo. A barra de baixo se chamava ".barra", e as telas de
    # Posts e Elencos já tinham uma ".barra" delas — uma fileira de botões.
    # O CSS da página carrega DEPOIS deste, então a definição delas vencia e a
    # pílula flutuante virava uma bolha esparramada. O mesmo valia para ".topo"
    # e ".marca".
    #
    # Um prefixo resolve a classe inteira de problema de uma vez, em vez de eu
    # renomear uma por uma toda vez que alguém criar um ".card" novo.
    "    .iar-topo { background: var(--c-bg); padding: 12px 14px; display: flex;\n"
    "      align-items: center; justify-content: space-between; position: sticky;\n"
    "      top: 0; z-index: 20; gap: 10px; }\n"
    "    .iar-lado { display: flex; align-items: center; gap: 8px; min-width: 44px; }\n"
    "    .iar-lado.dir { justify-content: flex-end; }\n"
    "    .iar-marca { font-family: 'Bebas Neue', system-ui, sans-serif;\n"
    "      font-size: 1.45rem; letter-spacing: .05em; color: var(--c-acento);\n"
    "      text-decoration: none; line-height: 1; white-space: nowrap;\n"
    "      overflow: hidden; text-overflow: ellipsis; }\n"
    "    .iar-btn { width: 38px; height: 38px; flex: 0 0 38px; border-radius: 12px;\n"
    "      display: flex; align-items: center; justify-content: center;\n"
    "      background: var(--c-bg-card); border: 1px solid var(--c-border);\n"
    "      color: var(--c-muted-4); cursor: pointer; text-decoration: none;\n"
    "      padding: 0; }\n"
    "    .iar-btn:hover, .iar-btn.ativo { color: var(--c-acento);\n"
    "      border-color: var(--c-acento); }\n"
    # ── A BARRA DE BAIXO ──────────────────────────────────────────────────
    # A rolagem fica no MIOLO, não na pílula. Overflow cria contexto de
    # recorte, e o menu de reticências é posicionado em relação à pílula: com
    # overflow nela, o menu abria e ficava cortado, invisível. O botão parecia
    # não funcionar — e funcionava.
    "    .iar-nav { position: fixed; left: 50%; transform: translateX(-50%);\n"
    "      bottom: max(12px, env(safe-area-inset-bottom)); z-index: 30;\n"
    "      display: flex; align-items: center; padding: 6px; gap: 4px;\n"
    "      border-radius: 999px; background: var(--c-bg-card);\n"
    "      border: 1px solid var(--c-border-2);\n"
    "      box-shadow: 0 8px 30px rgba(0,0,0,.45);\n"
    "      max-width: calc(100vw - 20px); }\n"
    "    .iar-rolo { display: flex; align-items: center; gap: 2px;\n"
    "      overflow-x: auto; scrollbar-width: none; }\n"
    "    .iar-rolo::-webkit-scrollbar { display: none; }\n"
    "    .iar-icon { width: 42px; height: 42px; flex: 0 0 42px; border-radius: 999px;\n"
    "      display: flex; align-items: center; justify-content: center;\n"
    "      color: var(--c-muted-3); text-decoration: none; position: relative;\n"
    "      background: transparent; border: none; cursor: pointer; padding: 0; }\n"
    "    .iar-icon:hover { color: var(--c-text); }\n"
    "    .iar-icon.ativo { background: var(--c-acento);\n"
    "      color: var(--c-acento-texto) !important; }\n"
    "    .iar-badge { position: absolute; top: 5px; right: 6px; min-width: 15px;\n"
    "      height: 15px; padding: 0 3px; border-radius: 99px;\n"
    "      background: var(--c-negativo); color: #fff; font-size: .58rem;\n"
    "      font-weight: 800; display: flex; align-items: center;\n"
    "      justify-content: center; }\n"
    "    body { padding-bottom: 88px; }\n"
    # ── O MENU DE RETICÊNCIAS ─────────────────────────────────────────────
    # Fixo, e não absoluto: assim nenhum overflow de ancestral consegue
    # recortá-lo, que foi exatamente o que aconteceu.
    "    .iar-mais { flex: 0 0 auto; display: flex; }\n"
    "    .iar-menu { position: fixed; right: 14px;\n"
    "      bottom: calc(max(12px, env(safe-area-inset-bottom)) + 62px);\n"
    "      min-width: 196px; background: var(--c-bg-card);\n"
    "      border: 1px solid var(--c-border-2); border-radius: 14px; padding: 6px;\n"
    "      display: none; flex-direction: column; gap: 2px;\n"
    "      box-shadow: 0 10px 34px rgba(0,0,0,.55); z-index: 40; }\n"
    "    .iar-menu.aberto { display: flex; }\n"
    "    .iar-menu a { display: flex; align-items: center; gap: 10px;\n"
    "      padding: 9px 11px; border-radius: 10px; color: var(--c-muted-4);\n"
    "      text-decoration: none; font-size: .8rem; font-weight: 600;\n"
    "      font-family: 'Inter', system-ui, sans-serif; }\n"
    "    .iar-menu a:hover { background: var(--c-hover-tint); color: var(--c-text); }\n"
)

# Tags que transformam o site em app de tela de início no iPhone. Vão no <head>
# de todas as páginas: o iOS lê essas tags da página que estiver aberta na hora
# do "Adicionar à Tela de Início", então deixar de fora uma única página faria
# a instalação sair sem ícone dependendo de onde você estivesse.
_PWA_HEAD = (
    '<link rel="manifest" href="/manifest.webmanifest">'
    '<link rel="apple-touch-icon" href="/pwa/apple-touch-icon.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="IARABÃO">'
    # black-translucent faria o conteúdo passar por baixo do relógio e da
    # bateria; "black" mantém a barra de status legível sobre o fundo escuro.
    '<meta name="apple-mobile-web-app-status-bar-style" content="black">'
    '<meta name="theme-color" content="#08080E">'
    '<script>if("serviceWorker" in navigator)'
    'addEventListener("load",function(){navigator.serviceWorker.register("/sw.js")});</script>'
)

_THEME_INIT_SCRIPT = '<script>document.documentElement.setAttribute("data-theme","dark");</script>'

# Tudo que TODA página precisa no <head>. Existe como uma coisa só porque as
# 12 páginas já injetavam o tema num ponto fixo — pendurar o PWA aqui garante
# que nenhuma fique de fora, e esquecer uma delas faria a instalação no iPhone
# sair sem ícone dependendo de qual estivesse aberta.
_HEAD_COMUM = _THEME_INIT_SCRIPT + _PWA_HEAD

# As seis do dia a dia ficam na barra; o resto vai para o menu de reticências.
# Eram dez ícones lado a lado, o que estourava a largura no celular.
_ICO_INICIO  = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 '
                '2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/></svg>')

_ICO_MERCADO = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="m11 17 2 2a1 1 0 1 0 3-3"/>'
                '<path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0'
                'l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 '
                '2 0 0 0 1.42.25L21 4"/><path d="m21 3 1 11h-2"/>'
                '<path d="M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3"/><path d="M3 4h8"/></svg>')

_ICO_JORNAL  = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 '
                '0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1'
                '.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/>'
                '<path d="M10 6h8v4h-8V6Z"/></svg>')

_ICO_ASPAS   = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M10 11H6a2 2 0 0 1-2-2V7a2 2 0 0 1 '
                '2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4"/><path d="M20 11h-4a2 2 0 0 1-2-2V7a2 '
                '2 0 0 1 2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4"/></svg>')

_ICO_SAIR    = ('<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 '
                '1 2-2h4"/><polyline points="16 17 21 12 16 7"/>'
                '<line x1="21" x2="9" y1="12" y2="12"/></svg>')

_ICO_VOLTAR = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
               'stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>')

_ICO_CONFIG = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
               'stroke-linejoin="round"><circle cx="12" cy="12" r="3"/>'
               '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 '
               '2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 '
               '2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 '
               '2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 '
               '2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 '
               '0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 '
               '1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 '
               '1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 '
               '1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>')

_NAV_PRINCIPAIS = [
    ("/",         _ICO_INICIO, "Início",   "home", ""),
    ("/noticias", _ICO_JORNAL, "Notícias", "",     ""),
    ("/mercado",  _ICO_MERCADO, "Mercado",  "",     ""),
    ("/aspas",    _ICO_ASPAS,   "Aspas",    "",     ""),
    ("/lesoes",  _ICO_INJURY,  "Lesões",  "",     "#FD5D5D"),
    ("/janela",  _ICO_JANELA,  "Janela",  "",     "#B6FF00"),
    ("/elencos", _ICO_ELENCOS, "Elencos", "",     "#B6FF00"),
    ("/posts",   _ICO_POSTS,   "Agendamentos", "", "#1d9bf0"),
    # Entrou por último para não bagunçar a ordem que você pediu. Fica na barra,
    # e não no menu, porque é a única tela com pressa: o texto serve nos minutos
    # seguintes ao apito.
    ("/fim-de-jogo", _ICO_APITO, "Fim de jogo", "", "#B6FF00"),
    # A tela mais urgente de todas: o gol acabou de sair e o clipe tem prazo.
    # Fica na barra, e o contador aparece quando há clipe esperando você.
    ("/clipes", _ICO_CLIPE, "Clipes", "clipes", "#B6FF00"),
    # A escala do dia. Fica na barra porque é consulta diária, e porque a
    # janela de captura é curta: o SAFF publica e tira do ar.
    ("/arbitragem", _ICO_ARBITRO, "Arbitragem", "", "#FFBE5D"),
    # Sua preparação para o ar. Fica ao lado de Arbitragem porque as duas
    # são telas de dia de jogo, consultadas com o jogo prestes a começar.
    ("/previa", _ICO_PREVIA, "Prévia", "", "#B6FF00"),
]
_NAV_EXTRAS = [
    # Saiu da barra quando a Prévia entrou. O limite de doze é meu próprio
    # teste, e ele existe porque barra que rola demais vira caça ao ícone.
    # Números é tela de consulta, não de dia de jogo — foi a que menos
    # sofre indo para cá. Se eu errei, é uma linha para desfazer.
    ("/numeros",     _ICO_NUMEROS, "Números",     "", "#B6FF00"),
    ("/descartadas", _ICO_ARCHIVE, "Descartadas", "", "#FFBE5D"),
    ("/lixeira",     _ICO_TRASH2,  "Lixeira",     "", "#FFBE5D"),
    ("/analise",     _ICO_ANALISE, "Análise",     "", "#FFBE5D"),
    # Fontes não foi citada na lista, mas também não estava entre as seis do
    # dia a dia. Deixo aqui em vez de sumir com ela sem avisar.
    ("/fontes",      _ICO_SOURCES, "Fontes",      "", "#FFBE5D"),
]


# Existe conta cadastrada? Com cache, porque isto é perguntado no cabeçalho
# de TODA página e a cada requisição do middleware — uma consulta por
# renderização para uma resposta que muda uma vez na vida do app.
#
# Uma vez que vira True, nunca mais volta: conta não desaparece sozinha, e
# ficar perguntando seria gastar consulta para confirmar o que já sei.
_LOGIN_LIGADO = {"sim": False, "quando": 0.0}


def _login_ligado() -> bool:
    if _LOGIN_LIGADO["sim"]:
        return True
    if time.time() - _LOGIN_LIGADO["quando"] < 30:
        return False
    _LOGIN_LIGADO["quando"] = time.time()
    _LOGIN_LIGADO["sim"] = tem_algum_usuario()
    return _LOGIN_LIGADO["sim"]


def _header(active: str) -> str:
    rolaveis = ""
    for href, ico, label, badge_tab, color in _NAV_PRINCIPAIS:
        cls = "iar-icon" + (" ativo" if href == active else "")
        badge = (f'<span class="iar-badge" data-tab="{badge_tab}" style="display:none"></span>'
                 if badge_tab else "")
        rolaveis += f'<a class="{cls}" href="{href}" title="{label}">{ico}{badge}</a>'

    # O botão herda a cor da página aberta quando ela está escondida no menu —
    # senão não haveria pista nenhuma de onde você está.
    aberto_no_menu = next((p for p in _NAV_EXTRAS if p[0] == active), None)
    cls_mais = "iar-icon" + (" ativo" if aberto_no_menu else "")
    estilo_mais = ""
    opcoes = ""
    for href, ico, label, _b, color in _NAV_EXTRAS:
        marca = ' aria-current="page"' if href == active else ""
        cor = 'style="color:var(--c-acento)"' if href == active else ""
        opcoes += f'<a href="{href}"{marca} {cor}>{ico}<span>{label}</span></a>'
    items = (
        '<div class="iar-mais">'
        f'<button type="button" class="{cls_mais}" id="btnMais" '
        'aria-haspopup="true" aria-expanded="false" title="Mais">' + _ICO_MAIS + '</button>'
        '</div>'
    )
    menu_script = """<script>
(function(){
  var bt = document.getElementById('btnMais');
  var menu = document.getElementById('navMenu');
  if(!bt || !menu) return;
  function fechar(){
    menu.classList.remove('aberto');
    bt.setAttribute('aria-expanded','false');
  }
  bt.addEventListener('click', function(ev){
    ev.stopPropagation();          // senão o clique de fora fecha na mesma hora
    var vai = !menu.classList.contains('aberto');
    menu.classList.toggle('aberto', vai);
    bt.setAttribute('aria-expanded', vai ? 'true' : 'false');
  });
  // Clicar fora e Esc fecham. Sem isso, no celular o menu ficaria preso aberto
  // por cima do conteúdo, já que não há hover para revelar que ele está ali.
  document.addEventListener('click', function(ev){
    if(!menu.contains(ev.target)) fechar();
  });
  document.addEventListener('keydown', function(ev){
    if(ev.key === 'Escape') fechar();
  });
})();
</script>"""
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
  function mostrarAvisoBanco(d){
    if(!d || !d.banco_aviso) return;
    if(document.getElementById('avisoBanco')) return;
    var b = document.createElement('div');
    b.id = 'avisoBanco';
    b.style.cssText = 'padding:9px 14px;font:700 .74rem/1.4 system-ui;'
      + 'text-align:center;color:#111;background:'
      + (d.banco_aviso === 'grave' ? '#FD5D5D' : '#FFBE5D');
    b.textContent = 'Banco em ' + d.banco_pct + '% (' + d.banco_mb + ' MB de '
      + d.banco_limite_mb + ' MB). '
      + (d.banco_aviso === 'grave'
         ? 'Quando encher, o app inteiro para. Aumente o volume no Railway.'
         : 'Vale olhar antes que aperte.');
    document.body.insertBefore(b, document.body.firstChild);
  }

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
      mostrarAvisoBanco(d);
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
    # ── o topo ────────────────────────────────────────────────────────────
    # Três coisas e mais nada: voltar à esquerda, a marca no meio reduzida a
    # "IA", e configurações à direita. O nome inteiro comia metade da largura
    # no celular e não dizia nada que o ícone não diga.
    #
    # O "voltar" só aparece fora da tela inicial. Botão de voltar na primeira
    # tela é botão que mente.
    voltar = ("" if active == "/" else
              '<button type="button" class="iar-btn" onclick="history.back()" '
              'title="Voltar" aria-label="Voltar">' + _ICO_VOLTAR + '</button>')
    cfg_ativa = " ativo" if active == "/config" else ""
    # O "sair" só existe quando há login ligado. Botão de sair num app sem
    # porta é só um botão que confunde.
    sair = ('<a class="iar-btn" href="/sair" title="Sair" aria-label="Sair">'
            + _ICO_SAIR + '</a>') if _login_ligado() else ""
    topo = (
        '<header class="iar-topo">'
        f'<div class="iar-lado">{voltar}</div>'
        '<a class="iar-marca" href="/" title="IARABÃO">IARABÃO</a>'
        f'<div class="iar-lado dir">{token_dot}'
        f'<a class="iar-btn{cfg_ativa}" href="/config" title="Configurações" '
        f'aria-label="Configurações">{_ICO_CONFIG}</a>{sair}</div>'
        '</header>'
    )
    # Esconder é conforto, não proteção. Quem chamar /config direto continua
    # barrado pelo middleware, com ou sem este script. O que ele evita é o
    # botão que existe, você aperta e leva um empurrão de volta — que parece
    # defeito, não permissão.
    perfil_script = """<script>
(function(){
  fetch('/api/meu-perfil').then(function(r){return r.json();}).then(function(p){
    if (!p.papel) return;
    if (!p.pode_configurar)
      document.querySelectorAll('a[href="/config"]').forEach(function(e){e.remove();});
    if (!p.pode_home) {
      document.querySelectorAll('.iar-icon[href="/"]').forEach(function(e){e.remove();});
      var marca = document.querySelector('.iar-marca');
      if (marca) marca.setAttribute('href', p.casa || '/noticias');
    }
  }).catch(function(){});
})();
</script>"""
    return (topo
            + f'<nav class="iar-nav"><div class="iar-rolo">{rolaveis}</div>{items}</nav>'
            + f'<div class="iar-menu" id="navMenu">{opcoes}</div>'
            + f'{menu_script}{badge_script}{theme_script}{token_script}'
            + f'{perfil_script}')



# ─── Dashboard ───────────────────────────────
# A marca que você põe arrastando o card para a direita, ou no ✓.
#
# O VALOR guardado é "publicado", e não "separado", por um motivo chato: já
# existem centenas de linhas marcadas assim no banco. Renomear o valor exigiria
# migrar todas, e uma migração que erra aqui apaga a sua peneira inteira.
#
# Então o valor fica, e o SIGNIFICADO é este: "separei, quero usar". O rótulo
# do botão na tela diz Separado. Esta constante existe para que ninguém
# (inclusive eu daqui a três meses) leia a string "publicado" no meio de um
# `if` e conclua que a home está listando o que já foi ao ar.
MARCA_SEPARADA = "publicado"

# A janela de notícias que a guia mostra. A home TEM que usar a mesma.
#
# Ela usava 24h enquanto a guia mostrava 48h, e o efeito era perverso: você
# separava uma notícia de ontem à tarde, ela ficava marcada na guia, e
# simplesmente não chegava na home. Sem erro, sem aviso — o card verde na guia
# dizia que tinha dado certo.
HORAS_DE_NOTICIA = 48


async def _pagina_de_noticias(categoria: str = "", rota: str = "/noticias"):
    """A antiga home, agora servindo três telas.

    MERCADO leva as de transferência, ASPAS leva as de entrevista, e NOTÍCIAS
    leva o resto. A separação usa a categoria que o pipeline já atribuía — a
    peneira existia desde sempre, só não tinha tela própria.

    Uma função com um parâmetro, e não três cópias: são setecentas linhas, e
    cópias divergiriam na primeira correção que alguém fizesse só numa delas.

    categoria vazia significa "tudo que não é mercado nem entrevista".
    """
    articles = get_recent_articles(hours=HORAS_DE_NOTICIA, limit=80)
    _deleted_sources = {h.upper() for h, ov in load_source_overrides().items() if ov.get("deleted")}
    articles = [
        a for a in articles
        if a.get("relevance_score", 0) >= 0.45
        and a.get("source_name", "").lstrip("@").upper() not in _deleted_sources
        and not _is_selecao_article(a)
        and _is_actually_saudi_football(a)
        and (a.get("category") == categoria if categoria
             else a.get("category") not in ("mercado", "entrevista"))
    ]
    articles.sort(key=lambda a: a.get("collected_at") or "", reverse=True)

    CATEGORY_EMOJI = {
        "mercado":       ("🔀", "#dbeafe", "#1d4ed8"),
        "financas":      ("💰", "#fdf4ff", "#7e22ce"),
        "entrevista":    ("🎙️", "#fef3c7", "#b45309"),
        "competicao":    ("🏆", "#FFBE5D26", "#a16207"),
        "treino":        ("🏋️", "#f0fdf4", "#B6FF00"),
        "lesao":         ("🩺", "#FD5D5D1f", "#FD5D5D"),
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
              <button class="flag-circle pub-btn"   onclick="toggleFlag('{art_id}','publicado')"  title="Separado — vai para a tela inicial">{ICO_CHECK}</button>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IARABÃO</title>
  {_HEAD_COMUM}
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
    .fs-analise   {{ border-color: #FFBE5D33; color: #92400e; }}
    .fs-publicado {{ border-color: #B6FF0033; color: var(--c-success); }}
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
    .card.flag-visto     {{ background: #FFBE5D1a; }}
    .card.flag-publicado {{ background: #B6FF001f; }}
    .card.flag-visto, .card.flag-publicado {{
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
    .cat-mercado    {{ background: rgba(34,197,94,.18);  color: #B6FF00; }}
    .cat-competicao {{ background: rgba(234,179,8,.18);  color: #a16207; }}
    .cat-lesao      {{ background: rgba(239,68,68,.18);  color: #FD5D5D; }}
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
  {_header(rota)}
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


@app.get("/noticias", response_class=HTMLResponse)
async def pagina_noticias():
    """Tudo que não é transferência nem entrevista."""
    return await _pagina_de_noticias("", "/noticias")


@app.get("/mercado", response_class=HTMLResponse)
async def pagina_mercado():
    """Só transferências: sondagens, negociações, renovações, saídas."""
    return await _pagina_de_noticias("mercado", "/mercado")





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
        "competicao":    ("🏆", "#FFBE5D26", "#a16207"),
        "treino":        ("🏋️", "#f0fdf4", "#B6FF00"),
        "lesao":         ("🩺", "#FD5D5D1f", "#FD5D5D"),
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
              <button class="flag-circle pub-btn"   onclick="toggleFlag('{art_id}','publicado')"  title="Separado — vai para a tela inicial">{ICO_CHECK}</button>
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
  {_HEAD_COMUM}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--c-bg); color: var(--c-text); }}
    {_HEADER_CSS}
    .topbar {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 14px 24px 8px; }}
    .count {{ color: var(--c-muted-1); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.07em; }}
    .selecao-badge {{ background: #B6FF00; color: white; font-size: 0.6rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; text-transform: uppercase; letter-spacing: 0.06em; }}
    .flag-summary {{ display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }}
    .fs-badge {{ font-size: 0.62rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; cursor: pointer; user-select: none; transition: all .15s; text-transform: uppercase; letter-spacing: 0.05em; border: 1.5px solid transparent; }}
    .fs-total     {{ border-color: var(--c-line); color: var(--c-muted-1); }}
    .fs-analise   {{ border-color: #FFBE5D33; color: #92400e; }}
    .fs-publicado {{ border-color: #B6FF0033; color: var(--c-success); }}
    .fs-descarte  {{ border-color: #fca5a5; color: var(--c-error); }}
    .fs-badge:hover {{ opacity: .7; }}
    .fs-badge.active-filter {{ background: var(--c-text); color: var(--c-bg); border-color: var(--c-text); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; padding: 10px 24px 80px; align-items: start; }}
    .card {{ background: var(--c-bg-card); border-radius: 16px; display: flex; flex-direction: column; transition: background .2s; }}
    .card.flag-analise   {{ display: none; }}
    .card.flag-visto     {{ background: #FFBE5D1a; }}
    .card.flag-publicado {{ background: #B6FF001f; }}
    .card.flag-visto, .card.flag-publicado {{
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
    """Status do token do X e, junto, o quanto o banco está ocupando.

    O tamanho pega carona aqui porque esta rota já é chamada no cabeçalho de
    TODA página. É o único lugar do app que aparece em todas — e o defeito de
    ontem não foi o banco encher, foi encher em silêncio.
    """
    d = dict(get_token_status() or {})
    mb = tamanho_do_banco_mb()
    if mb is not None:
        pct = round(100 * mb / max(1, LIMITE_BANCO_MB))
        d["banco_mb"] = mb
        d["banco_pct"] = pct
        d["banco_limite_mb"] = LIMITE_BANCO_MB
        # 75% ainda dá tempo de agir com calma; 90% já é hoje.
        d["banco_aviso"] = ("grave" if pct >= 90 else
                            "atencao" if pct >= 75 else "")
    return d


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
  {_HEAD_COMUM}
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
{_HEAD_COMUM}
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
.error-state {{ color: #FD5D5D; }}

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
  {_HEAD_COMUM}
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
    .btn-del:hover {{ background: #FD5D5D1f; }}
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
  {_HEAD_COMUM}
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
      background: #FD5D5D1f;
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
    .cat-competicao {{ background:#FFBE5D26; color:#a16207; }}
    .cat-treino     {{ background:#f0fdf4; color:#B6FF00; }}
    .cat-lesao      {{ background:#FD5D5D1f; color:#FD5D5D; }}
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
    .restore-circ {{ border-color: #FD5D5D; color: #FD5D5D; }}
    .restore-circ:hover {{ background: #FD5D5D; color: #fff; border-color: #FD5D5D; }}
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
    btn.style.background = '#B6FF00';
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
  {_HEAD_COMUM}
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
      background:#FFBE5D1a; border-radius:16px; display:flex; flex-direction:column; transition:background .2s;
    }}
    .card-body {{ padding:20px; display:flex; flex-direction:column; }}
    .card-top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }}
    .card-flags {{ display:flex; gap:7px; }}
    .cat-badge {{ display:inline-flex; align-items:center; gap:4px; font-size:0.6rem; font-weight:700; padding:3px 9px; border-radius:99px; text-transform:uppercase; letter-spacing:0.05em; background:#f1f5f9; color:#475569; }}
    .cat-mercado    {{ background:#dbeafe; color:#1d4ed8; }}
    .cat-financas   {{ background:#fdf4ff; color:#7e22ce; }}
    .cat-entrevista {{ background:#fef3c7; color:#b45309; }}
    .cat-competicao {{ background:#FFBE5D26; color:#a16207; }}
    .cat-treino     {{ background:#f0fdf4; color:#B6FF00; }}
    .cat-lesao      {{ background:#FD5D5D1f; color:#FD5D5D; }}
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
    btn.style.background='#B6FF00'; btn.style.color='#fff';
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
  {_HEAD_COMUM}
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
.timeline-dot.status-lesionado      {{ background: #FD5D5D; }}
.timeline-dot.status-em_recuperacao {{ background: #FFBE5D; }}
.timeline-dot.status-retornando     {{ background: #B6FF00; }}
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
.status-em_recuperacao {{ background: #FFBE5D1a; color: #92400e; }}
.status-retornando     {{ background: #f0fdf4; color: #B6FF00; }}
.status-recuperado     {{ background: var(--c-muted-2); color: var(--c-muted-3); }}
[data-theme=dark] .status-lesionado      {{ background: #3f1212; color: #fca5a5; }}
[data-theme=dark] .status-em_recuperacao {{ background: #3f2d00; color: #FFBE5D33; }}
[data-theme=dark] .status-retornando     {{ background: #052e16; color: #B6FF0033; }}
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
    # Mesma regra do BOLA ROLANDO: cores nas competições sauditas, bandeiras nas
    # internacionais. Antes lia TEAM_CORES direto, então um adversário asiático
    # saía sem marca nenhuma ao lado do nome.
    liga_id = (f.get("league") or {}).get("id")
    cor_casa, cor_fora = await _marcas_do_jogo(liga_id, casa, fora)
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


async def _ligas_jogando_em(datas: set[str]) -> dict[int, str]:
    """Quais competições têm jogo nestas datas, pela tabela cheia da temporada.

    Existe para não consultar as cinco competições ao vivo a cada atualização
    de tela. A tabela da temporada fica 6h em cache e já diz quem joga hoje;
    só essas recebem a consulta ao vivo, que tem cache de 30s. Num dia comum
    isso é 1 ou 2 chamadas por atualização em vez de 5 por dia pedido.
    """
    import posts_gerador as pg
    inicio = _af_temporada_corrente()
    saida: dict[int, str] = {}
    for liga_id, nome in pg.COMPETICOES.items():
        season = await _season_da_liga(liga_id, inicio)
        data, err = await _af_get("fixtures", {"league": liga_id, "season": season},
                                  ttl=6 * 3600)
        if err:
            # Sem a tabela, consulta assim mesmo: é melhor gastar uma chamada
            # do que sumir com um jogo encerrado bem na hora de postar.
            saida[liga_id] = nome
            continue
        for f in (data or {}).get("response", []):
            if ((f.get("fixture") or {}).get("date") or "")[:10] in datas:
                saida[liga_id] = nome
                break
    return saida


@app.get("/api/numeros/jogos-do-dia")
async def api_jogos_do_dia(dias: int = 1):
    """Jogos de hoje (e dos últimos dias) em TODAS as competições que viram post.

    Antes só olhava a Liga Saudita, então um jogo de Copa do Rei ou da AFC
    simplesmente não aparecia aqui — mesmo o texto de fim de jogo funcionando
    para qualquer partida, porque ele busca pelo id e não pela liga.
    """
    hoje = datetime.now(timezone.utc).date()
    datas = {(hoje - timedelta(days=d)).isoformat() for d in range(dias)}
    ligas = await _ligas_jogando_em(datas)

    jogos = []
    for liga_id, nome_comp in ligas.items():
        season = await _season_da_liga(liga_id, _af_temporada_corrente())
        for d in sorted(datas, reverse=True):
            data, err = await _af_get("fixtures", {"league": liga_id, "season": season,
                                                   "date": d}, ttl=_AF_TTL_AO_VIVO)
            if err or not data:
                continue
            for f in data.get("response", []):
                fx = f.get("fixture") or {}
                st = (fx.get("status") or {})
                t = f.get("teams") or {}
                g = f.get("goals") or {}
                cor_casa, cor_fora = await _marcas_do_jogo(
                    liga_id, t.get("home") or {}, t.get("away") or {})
                jogos.append({
                    "fixture": fx.get("id"),
                    "data": (fx.get("date") or "")[:16].replace("T", " "),
                    "status": st.get("short"), "minuto": st.get("elapsed"),
                    "encerrado": st.get("short") in ("FT", "AET", "PEN"),
                    "competicao": nome_comp,
                    "casa": _time_curto((t.get("home") or {}).get("name")),
                    "fora": _time_curto((t.get("away") or {}).get("name")),
                    "cor_casa": cor_casa, "cor_fora": cor_fora,
                    "gols_casa": g.get("home"), "gols_fora": g.get("away"),
                })
    jogos.sort(key=lambda x: x["data"], reverse=True)
    return {"jogos": jogos}


_FIMJOGO_CSS = '''    .fj-topo { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
    .fj-info { font-size:0.72rem; color:var(--c-muted-4); }
    .fj-refresh { background:transparent; border:1.5px solid var(--c-border-2); border-radius:99px; padding:5px 14px; font-size:0.65rem; font-weight:700; color:var(--c-muted-4); cursor:pointer; }
    .fj-refresh:hover { border-color:var(--c-text); color:var(--c-text); }
    .fj-status { font-size:0.66rem; color:var(--c-muted-4); }
    .fj-card { margin-bottom:12px; }
    .fj-cab { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
    .fj-conf { font-weight:800; font-size:0.95rem; }
    .fj-selo { font-size:0.6rem; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; border:1.5px solid var(--c-border-2); border-radius:99px; padding:3px 9px; color:var(--c-muted-4); }
    .fj-selo.fj-vivo { border-color:#B6FF00; color:#B6FF00; }
    .fj-selo.fj-fim { border-color:var(--c-text); color:var(--c-text); }
    .fj-texto { white-space:pre-wrap; font-family:inherit; font-size:0.9rem; line-height:1.6; margin:0; padding:12px 14px; border-radius:10px; background:var(--c-bg-soft); }
    .fj-aguardando { font-size:0.75rem; color:var(--c-muted-4); padding:6px 0; }'''

_FIMJOGO_JS = r'''// ── FIM DE JOGO ───────────────────────────────────────────────────────────
// A tela se atualiza sozinha, mas NÃO em intervalo fixo. Antes eram 60s o dia
// inteiro, inclusive de madrugada sem ninguém em campo, e o texto de um jogo
// encerrado há horas era refeito a cada volta. Agora o ritmo segue o minuto da
// partida (ver proximaChecagem) e texto já pronto não é buscado de novo.
let _fjTimer = null;

// Momentos em que vale olhar antes da reta final: meio e fim do 1º tempo,
// meio do 2º. Do 85 em diante passa a ser de 20 em 20 segundos.
const FJ_PARADAS = [23, 45, 68, 85];
const FJ_TEMPO_REAL = 85;
const FJ_INTERVALO_FINAL = 20;      // segundos, do minuto 85 até o apito
// O maior salto entre paradas é 23min (do 45 ao 68), então o teto precisa ser
// maior que isso ou ele atropela as paradas e vira checagem periódica.
// Dormir até a próxima parada é seguro: o relógio da partida nunca anda mais
// rápido que o relógio real, então esperar (alvo - minuto) minutos sempre
// chega em cima ou antes do alvo — nunca depois. Acréscimo e intervalo só
// fazem chegar mais cedo, e aí a conta é refeita.
const FJ_TETO_EM_JOGO = 25 * 60;
const FJ_TETO_PARADO = 15 * 60;     // nem mais que isso sem jogo nenhum

// Texto já fechado não muda mais. Guardar aqui evita refazer a chamada a cada
// atualização para partidas que acabaram horas atrás — era a maior parte do
// desperdício, porque a lista traz também os jogos de ontem.
const FJ_PRONTOS = {};

function fjEmCampo(j) {
  return !j.encerrado && j.minuto !== null && j.minuto !== undefined;
}

// Segundos até a próxima checagem, olhando o jogo mais urgente da tela.
function proximaChecagem(jogos) {
  const vivos = jogos.filter(fjEmCampo);
  if (vivos.length) {
    let menor = FJ_TETO_EM_JOGO;
    vivos.forEach(function (j) {
      let s;
      if (j.minuto >= FJ_TEMPO_REAL) {
        s = FJ_INTERVALO_FINAL;
      } else {
        const alvo = FJ_PARADAS.find(function (p) { return p > j.minuto; });
        // Um minuto de jogo ≈ um minuto de relógio. Acréscimos e intervalo
        // desviam disso, e é por isso que a conta é refeita a cada volta em
        // vez de agendar tudo de uma vez no começo da partida.
        s = Math.max(FJ_INTERVALO_FINAL, (alvo - j.minuto) * 60);
      }
      if (s < menor) menor = s;
    });
    return menor;
  }
  // Ninguém em campo: dorme até perto do próximo apito inicial.
  const agora = Date.now();
  const proximos = jogos
    .filter(function (j) { return !j.encerrado && j.data; })
    .map(function (j) { return Date.parse(j.data.replace(' ', 'T') + ':00Z'); })
    .filter(function (t) { return !isNaN(t) && t > agora; });
  if (!proximos.length) return FJ_TETO_PARADO;
  const faltam = (Math.min.apply(null, proximos) - agora) / 1000 - 60;
  return Math.min(Math.max(faltam, 60), FJ_TETO_PARADO);
}

function fjLegenda(seg, jogos) {
  const hora = new Date().toLocaleTimeString('pt-BR').slice(0, 5);
  const vivos = jogos.filter(fjEmCampo);
  if (vivos.length && Math.min.apply(null, vivos.map(function (j) { return j.minuto; })) >= FJ_TEMPO_REAL) {
    return hora + ' · reta final, olhando a cada ' + seg + 's';
  }
  const quando = seg < 90 ? seg + 's' : Math.round(seg / 60) + 'min';
  return hora + ' · próxima checagem em ' + quando;
}

async function preencherTexto(j) {
  const box = document.getElementById('fj-txt-' + j.fixture);
  if (!box) return;
  const b = document.getElementById('fj-btn-' + j.fixture);
  const liberar = function (texto) {
    if (b) { b.style.display = ''; b.onclick = function () { copyBlock(b, texto); }; }
  };
  // Enquanto durar a comparação, não uso o cache: quero ver as duas fontes
  // do mesmo instante toda vez, senão a comparação fica velha de um lado.
  try {
    // As duas fontes na mesma chamada, para a comparação ser do MESMO instante.
    const d = await fetchJSON('/api/fim/comparar?fixture=' + j.fixture);
    const af = d.api_football || {};
    const sm = d.sportmonks || {};
    box.innerHTML = '';
    box.appendChild(caixaFonte('API-Football', af, '#B6FF00'));
    box.appendChild(caixaFonte('Sportmonks', sm, '#B6FF00'));
    box.className = 'duas';
    // O botão de copiar segue a API-Football, que é a que está no ar hoje.
    if (af.texto && af.completo) {
      liberar(af.texto);
      if (j.encerrado) FJ_PRONTOS[j.fixture] = af.texto;
    }
  } catch (e) {}
}

function caixaFonte(rotulo, r, cor) {
  const d = document.createElement('div');
  d.className = 'fonte';
  const h = document.createElement('h4');
  h.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:'
              + cor + ';display:inline-block"></span>' + rotulo;
  d.appendChild(h);
  const p = document.createElement('pre');
  if (r.erro) {
    p.textContent = '— ' + r.erro;
    p.style.color = 'var(--c-muted-3)';
  } else {
    p.textContent = (r.texto || '—') + (r.aviso ? '\n\n⚠️ ' + r.aviso : '');
  }
  d.appendChild(p);
  if (r.texto) {
    const b = document.createElement('button');
    b.className = 'copy-btn';
    b.style.marginTop = '8px';
    b.textContent = '📋 Copiar';
    b.onclick = function () { copyBlock(b, r.texto); };
    d.appendChild(b);
  }
  return d;
}

// ── Sub-abas: Fim de jogo | Alertas de gol ────────────────────────────────
// As duas coisas viviam empilhadas na mesma rolagem e viravam bagunça: o
// alerta de gol no topo empurrava as partidas para baixo. Separadas, cada uma
// ocupa a tela inteira. O contador na aba de alertas existe para você não ter
// que trocar de aba só para descobrir se tem gol novo lá.
function mostrarAba(qual) {
  ['fim', 'gols', 'esc'].forEach(function (k) {
    const p = document.getElementById('painel-' + k);
    const b = document.getElementById('aba-' + k);
    if (p) p.style.display = (k === qual) ? '' : 'none';
    if (b) b.classList.toggle('ativa', k === qual);
  });
}

function marcarGols(n) {
  const p = document.getElementById('abaGolsN');
  if (!p) return;
  p.textContent = n > 0 ? String(n) : '';
  p.classList.toggle('tem', n > 0);
}

// ── Alerta de GOL, com o carimbo de cada fonte ────────────────────────────
async function carregarGols() {
  const alvo = document.getElementById('fjGols');
  if (!alvo) return;
  let d;
  try {
    const r = await fetch('/api/gols/ao-vivo?horas=8&_=' + Date.now());
    const bruto = await r.text();
    if (!r.ok) throw new Error('HTTP ' + r.status + ' — ' + bruto.slice(0, 300));
    d = JSON.parse(bruto);
  } catch (e) {
    // Antes isto era um "return" mudo, e o painel ficava vazio sem dizer nada.
    // Um erro invisível é pior que um erro feio: eu passei duas rodadas
    // chutando porque a tela não me contava que a chamada estava falhando.
    alvo.innerHTML = '<div class="result-card"><pre class="fj-texto" '
      + 'style="font-size:.76rem;color:#FD5D5D">Falha ao carregar o alerta de gol:\n'
      + esc(e.message || String(e)) + '</pre></div>';
    return;
  }
  if (!d.sportmonks_configurada) {
    alvo.innerHTML = '<div class="result-card"><div class="loading-state">'
      + 'Falta a SPORTMONKS_TOKEN no Railway para a comparação funcionar.</div></div>';
    return;
  }
  if (!(d.gols || []).length) {
    marcarGols(0);
    // Não basta dizer "nenhum": preciso saber SE o coletor rodou e o que viu.
    const g = d.diagnostico || {};
    const q = g.quando ? new Date(g.quando)
      .toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo'}) : 'nunca';
    let txt = 'Nenhum gol carimbado. Última coleta às ' + q
      + ' — Sportmonks: ' + (g.sm_jogos || 0) + ' jogo(s), ' + (g.sm_gols || 0) + ' gol(s)'
      + ' · API-Football: ' + (g.af_jogos || 0) + ' jogo(s), ' + (g.af_gols || 0) + ' gol(s)'
      + ' · no banco: ' + (d.carimbos_no_banco || 0);
    if ((g.erros || []).length) txt += '\n⚠️ ' + g.erros.join(' | ');
    alvo.innerHTML = '<div class="result-card"><pre class="fj-texto" '
      + 'style="font-size:.76rem">' + esc(txt) + '</pre></div>';
    return;
  }
  marcarGols(d.gols.length);
  alvo.innerHTML = '';
  d.gols.forEach(function (g) {
    const linha = document.createElement('div');
    linha.className = 'gol-linha';
    const cab = document.createElement('div');
    cab.className = 'gol-cab';
    let selo = '<span class="dif">só uma fonte</span>';
    if (g.diferenca_seg !== null && g.diferenca_seg !== undefined) {
      const s = g.diferenca_seg;
      const quem = s < 0 ? 'sm' : (s > 0 ? 'af' : '');
      const txt = s === 0 ? 'empate'
                : (s < 0 ? 'Sportmonks ' + Math.abs(s) + 's antes'
                         : 'API-Football ' + s + 's antes');
      selo = '<span class="dif ' + quem + '">' + txt + '</span>';
    }
    cab.innerHTML = '<span class="gol-min">' + (g.minuto || '?') + "'</span>"
      + '<span>' + esc(g.autor || '') + '</span>'
      + (g.assistente ? '<span class="conta">🅰️ ' + esc(g.assistente) + '</span>' : '')
      + '<span class="fj-selo">' + esc(g.placar || '') + '</span>' + selo;
    linha.appendChild(cab);
    const duas = document.createElement('div');
    duas.className = 'duas';
    [['API-Football', g.api_football, '#B6FF00'],
     ['Sportmonks', g.sportmonks, '#B6FF00']].forEach(function (par) {
      const c = document.createElement('div');
      c.className = 'fonte';
      const quando = par[1] ? new Date(par[1].visto_em)
        .toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo'}) : '—';
      c.innerHTML = '<h4><span style="width:8px;height:8px;border-radius:50%;background:'
        + par[2] + ';display:inline-block"></span>' + par[0]
        + '<span style="margin-left:auto;font-weight:400">' + quando + '</span></h4>';
      const p = document.createElement('pre');
      p.textContent = par[1] ? (par[1].texto || '') : 'não publicou este gol';
      if (!par[1]) p.style.color = 'var(--c-muted-3)';
      c.appendChild(p);
      if (par[1] && par[1].texto) {
        const b = document.createElement('button');
        b.className = 'copy-btn';
        b.style.marginTop = '8px';
        b.textContent = '📋 Copiar';
        b.onclick = function () { copyBlock(b, par[1].texto); };
        c.appendChild(b);
      }
      duas.appendChild(c);
    });
    linha.appendChild(duas);
    alvo.appendChild(linha);
  });
}

async function carregarJogosDoDia() {
  const lista = document.getElementById('fjLista');
  const st = document.getElementById('fjStatus');
  st.textContent = 'atualizando…';
  let jogos = [];
  try {
    const d = await fetchJSON('/api/numeros/jogos-do-dia?dias=2&_=' + Date.now());
    jogos = d.jogos || [];
    if (!jogos.length) {
      lista.innerHTML = '<div class="result-card"><div class="loading-state">Nenhum jogo hoje nem ontem em nenhuma das competições.</div></div>';
    } else {
      lista.innerHTML = jogos.map(cardDoJogo).join('');
      // Encerrado e em andamento: você pediu o texto já formatado também
      // durante a partida, para não ter que esperar o apito para ver o formato.
      jogos.filter(function (j) { return j.encerrado || fjEmCampo(j); }).forEach(preencherTexto);
    }
    // .catch explícito: sem ele, qualquer erro dentro de carregarGols vira
    // promise rejeitada sem dono e some — foi assim que o esc() faltando
    // ficou invisível.
    carregarGols().catch(function (err) {
      const g = document.getElementById('fjGols');
      if (g) g.innerHTML = '<div class="result-card"><pre class="fj-texto" '
        + 'style="font-size:.76rem;color:#FD5D5D">Erro no alerta de gol: '
        + (err && err.message ? err.message : String(err)) + '</pre></div>';
    });
    const seg = proximaChecagem(jogos);
    st.textContent = jogos.length ? fjLegenda(seg, jogos) : '';
    clearTimeout(_fjTimer);
    _fjTimer = setTimeout(carregarJogosDoDia, seg * 1000);
  } catch (e) {
    lista.innerHTML = '<div class="result-card"><div class="error-state">' + e.message + '</div></div>';
    st.textContent = '';
    clearTimeout(_fjTimer);
    _fjTimer = setTimeout(carregarJogosDoDia, 120000);   // erro: espera mais
  }
}

function cardDoJogo(j) {
  const placar = (j.gols_casa === null || j.gols_casa === undefined) ? 'x' : j.gols_casa + 'x' + j.gols_fora;
  let selo;
  if (j.encerrado) selo = '<span class="fj-selo fj-fim">encerrado</span>';
  else if (fjEmCampo(j)) selo = '<span class="fj-selo fj-vivo">' + j.minuto + "'</span>";
  else selo = '<span class="fj-selo">' + (j.data || '').slice(11) + '</span>';
  return '<div class="result-card fj-card">' +
    '<div class="fj-cab">' + selo +
      '<span class="fj-conf">' + j.cor_casa + ' ' + j.casa + ' ' + placar + ' ' + j.fora + ' ' + j.cor_fora + '</span>' +
      (j.competicao ? '<span class="fj-selo">' + j.competicao + '</span>' : '') +
      '<button class="copy-btn" id="fj-btn-' + j.fixture + '" style="display:none">📋 Copiar</button>' +
    '</div>' +
    (j.encerrado || fjEmCampo(j)
      ? '<pre class="fj-texto" id="fj-txt-' + j.fixture + '">gerando texto…</pre>'
      : '<div class="fj-aguardando">Ainda não começou — o texto aparece quando a bola rolar.</div>') +
  '</div>';
}


// ── ESCALAÇÕES ────────────────────────────────────────────────────────────

let _escTimer = null;

// A diferença só é confiável até a resolução do coletor, que passa de 40 em
// 40 segundos. Se as duas fontes já tinham a escalação quando ele passou, o
// que sobra é a ordem em que eu consultei — e não quem publicou antes. Mostrar
// "-2s" como se fosse medição seria inventar precisão que não existe.
const ESC_RESOLUCAO_SEG = 40;

function escHora(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo',
                                                     hour: '2-digit', minute: '2-digit',
                                                     second: '2-digit'});
  } catch (e) { return ''; }
}

async function carregarEscalacoes() {
  const alvo = document.getElementById('fjEsc');
  if (!alvo) return;
  let d;
  try {
    const r = await fetch('/api/escalacoes?horas=12&_=' + Date.now());
    const bruto = await r.text();
    if (!r.ok) throw new Error('HTTP ' + r.status + ' — ' + bruto.slice(0, 200));
    d = JSON.parse(bruto);
  } catch (e) {
    alvo.innerHTML = '<div class="result-card"><pre class="fj-texto" '
      + 'style="font-size:.76rem;color:#FD5D5D">Falha ao carregar as escalações:\n'
      + esc(e.message || String(e)) + '</pre></div>';
    return;
  }

  const lista = d.escalacoes || [];
  const p = document.getElementById('abaEscN');
  if (p) {
    p.textContent = lista.length ? String(lista.length) : '';
    p.classList.toggle('tem', lista.length > 0);
  }

  if (!lista.length) {
    const g = d.diagnostico || {};
    const q = g.quando ? escHora(g.quando) : 'nunca';
    let txt = 'Nenhuma escalação ainda. Última olhada às ' + q
      + ' — Sportmonks: ' + (g.sm_jogos || 0) + ' jogo(s) na janela, '
      + (g.sm_com || 0) + ' com escalação'
      + ' · API-Football: ' + (g.af_jogos || 0) + ' jogo(s), '
      + (g.af_com || 0) + ' com escalação.';
    if (!d.sportmonks_configurada) txt += '\n⚠️ SPORTMONKS_TOKEN não configurada.';
    if ((g.erros || []).length) txt += '\n⚠️ ' + g.erros.join(' | ');
    alvo.innerHTML = '<div class="result-card"><pre class="fj-texto" '
      + 'style="font-size:.76rem">' + esc(txt) + '</pre></div>';
    return;
  }

  alvo.innerHTML = '';
  lista.forEach(function (j) {
    alvo.appendChild(cartaoEscalacao(j));
  });
}

function cartaoEscalacao(j) {
  const d = document.createElement('div');
  d.className = 'gol-linha';

  const cab = document.createElement('div');
  cab.className = 'gol-cab';
  let selo = '<span class="dif">só uma fonte</span>';
  if (j.diferenca_seg !== null && j.diferenca_seg !== undefined) {
    const s = j.diferenca_seg;
    // A Sportmonks publica uma PROVÁVEL antes da oficial. Enquanto ela não
    // confirmar, comparar as duas seria dar vantagem a quem chutou primeiro,
    // então digo que a corrida ainda não terminou em vez de mostrar número.
    if (j.diferenca_de !== 'oficial') {
      selo = '<span class="dif">a Sportmonks ainda não confirmou — sem corrida</span>';
    } else if (Math.abs(s) < ESC_RESOLUCAO_SEG) {
      // Honestidade sobre o que a medição alcança.
      selo = '<span class="dif">as duas já tinham (diferença menor que a '
           + 'passagem do coletor)</span>';
    } else {
      const quem = s < 0 ? 'sm' : 'af';
      const txt = s < 0 ? 'Sportmonks ' + Math.abs(s) + 's antes'
                        : 'API-Football ' + s + 's antes';
      selo = '<span class="dif ' + quem + '">' + txt + '</span>';
    }
  }
  cab.innerHTML = '<span>' + esc(j.jogo || '?') + '</span>'
    + (j.comeca_em ? '<span class="conta">apito ' + esc(escHora(j.comeca_em)) + '</span>' : '')
    + selo;
  d.appendChild(cab);

  const duas = document.createElement('div');
  duas.className = 'duas';
  [['API-Football', j.api_football, '#B6FF00', null],
   ['Sportmonks', j.sportmonks, '#B6FF00', j.sportmonks_oficial]].forEach(function (par) {
    const c = document.createElement('div');
    c.className = 'fonte';
    // Etiqueta do que está ali. A Sportmonks manda uma escalação PROVÁVEL
    // antes da oficial — feita com histórico, lesões e suspensões — e troca
    // pela de verdade perto do apito. Sem dizer isso na tela, a provável
    // passa por oficial e parece só uma escalação errada que chegou cedo.
    let etiq = '';
    if (par[0] === 'Sportmonks') {
      const conf = ((par[1] || {}).escalacao || {}).confirmada;
      if (par[3]) etiq = '<span class="marca ok">oficial</span>';
      else if (conf === false) etiq = '<span class="marca prov">provável</span>';
      else if (par[1] && conf === undefined) etiq = '<span class="marca">sem marca de confirmação</span>';
    }
    let quando = par[1] ? escHora(par[1].visto_em) : '—';
    if (par[3] && par[1] && par[3].visto_em !== par[1].visto_em) {
      quando = escHora(par[1].visto_em) + ' → oficial ' + escHora(par[3].visto_em);
    }
    c.innerHTML = '<h4><span style="width:8px;height:8px;border-radius:50%;background:'
      + par[2] + ';display:inline-block"></span>' + par[0] + etiq
      + '<span style="margin-left:auto;font-weight:400">'
      + esc(quando) + '</span></h4>';
    if (!par[1]) {
      const p = document.createElement('pre');
      p.textContent = 'ainda não publicou';
      p.style.color = 'var(--c-muted-3)';
      c.appendChild(p);
    } else {
      const fonte_esc = (par[3] || par[1]).escalacao || {};
      (fonte_esc.times || []).forEach(function (t) {
        const bloco = document.createElement('pre');
        bloco.className = 'fj-texto';
        bloco.style.marginTop = '8px';
        const linhas = [t.nome + (t.formacao ? '  (' + t.formacao + ')' : '')];
        (t.titulares || []).forEach(function (p) {
          linhas.push('  ' + (p.camisa ? String(p.camisa).padStart(2, ' ') : ' -')
                      + '  ' + p.nome);
        });
        if ((t.banco || []).length) {
          linhas.push('  banco: ' + t.banco.map(function (p) { return p.nome; }).join(', '));
        }
        bloco.textContent = linhas.join('\n');
        c.appendChild(bloco);
      });
    }
    duas.appendChild(c);
  });
  d.appendChild(duas);
  return d;
}

function cicloEscalacoes() {
  carregarEscalacoes().catch(function (err) {
    const a = document.getElementById('fjEsc');
    if (a) a.innerHTML = '<div class="result-card"><pre class="fj-texto" '
      + 'style="font-size:.76rem;color:#FD5D5D">Erro nas escalações: '
      + (err && err.message ? err.message : String(err)) + '</pre></div>';
  });
  clearTimeout(_escTimer);
  _escTimer = setTimeout(cicloEscalacoes, 20000);
}
cicloEscalacoes();
'''


_FIMJOGO_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fim de Jogo · IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
*{box-sizing:border-box}
body{margin:0;background:var(--c-bg);color:var(--c-text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:18px 16px 60px}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--c-muted-3);font-size:.8rem;margin:0 0 16px}
.result-card{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:12px;padding:14px 16px}
.loading-state,.error-state{font-size:.8rem;color:var(--c-muted-3);text-align:center;padding:18px 0}
.error-state{color:#FD5D5D}
.copy-btn{margin-left:auto;background:transparent;border:1.5px solid var(--c-border-2);
  border-radius:99px;padding:5px 14px;font-size:.65rem;font-weight:700;
  color:var(--c-muted-4);cursor:pointer}
.copy-btn:hover{border-color:var(--c-text);color:var(--c-text)}
.copy-btn.copied{border-color:#B6FF00;color:#B6FF00}
__FJ_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Fim de Jogo</h1>
  <p class="sub">Jogos de hoje e ontem em todas as competições que viram post.
     Quando a partida encerra, o texto aparece pronto — é só copiar.</p>
  <div class="fj-topo">
    <button class="fj-refresh" onclick="carregarJogosDoDia()">Atualizar</button>
    <span id="fjStatus" class="fj-status"></span>
  </div>
  <div class="abas">
    <button class="aba ativa" id="aba-fim" onclick="mostrarAba('fim')">⏱️ Fim de jogo</button>
    <button class="aba" id="aba-gols" onclick="mostrarAba('gols')">⚽ Alertas<span
      class="pilula" id="abaGolsN"></span></button>
    <button class="aba" id="aba-esc" onclick="mostrarAba('esc')">📋 Escalações<span
      class="pilula" id="abaEscN"></span></button>
  </div>

  <div id="painel-fim">
    <div id="fjLista"><div class="result-card"><div class="loading-state">Carregando jogos…</div></div></div>
  </div>

  <div id="painel-gols" style="display:none">
    <p class="sub" style="margin:0 0 12px">Cada gol carimbado com o instante em que cada
       fonte o publicou. Diferença negativa = a Sportmonks chegou antes.</p>
    <div id="fjGols"></div>
  </div>

  <div id="painel-esc" style="display:none">
    <p class="sub" style="margin:0 0 12px">Escalações dos jogos que começam nas
       próximas 3 horas, com o instante em que cada fonte publicou.
       Diferença negativa = a Sportmonks chegou antes.</p>
    <div id="fjEsc"><div class="result-card"><div class="loading-state">Carregando…</div></div></div>
  </div>

</div>
<script>
async function fetchJSON(url) {
  const r = await fetch(url);
  const d = await r.json();
  if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}

// Escapa texto que vai para innerHTML. Estava faltando NESTA página — eu a
// copiei da guia Posts, que tem a sua. O alerta de gol chamava esc() cinco
// vezes e estourava ReferenceError; como carregarGols é async e ninguém dá
// await, a exceção virava promise rejeitada e morria calada. Resultado: painel
// vazio, sem erro na tela, e eu perdendo três rodadas atrás disso.
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function copyBlock(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = '✅ Copiado!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 1800);
  });
}

__FJ_JS__


carregarJogosDoDia();
</script>
</body>
</html>"""


def _cores_sm(f: dict) -> dict:
    """Mapa {id do time na Sportmonks: emoji} usando o TEAM_CORES que já existe.

    Os nomes deles são um pouco diferentes ("Al Hilal" x "Al-Hilal Saudi FC"),
    então caso por palavra significativa em vez de igualdade — foi o que fez o
    casamento de clubes funcionar 18 de 18 na sondagem."""
    fora_da_chave = {"al", "fc", "sc", "saudi", "jeddah", "saihat", "club"}
    # Grafias que os dois catálogos escrevem diferente. Sem isto, Al Draih,
    # Al-Qadsiah e Al Taawoun ficavam sem cor — testei e eram exatamente 3.
    VARIANTES = {"draih": "diriyah", "diraiyah": "diriyah",
                 "qadsiah": "qadisiyah", "qadisiya": "qadisiyah",
                 "taawoun": "taawon", "tawoun": "taawon",
                 "hazem": "hazm", "nasr": "nassr", "khalij": "khaleej"}

    def tokens(nome):
        limpo = re.sub(r"[^a-z ]", " ", (nome or "").lower().replace("-", " "))
        return {VARIANTES.get(p, p) for p in limpo.split()
                if p and p not in fora_da_chave}

    tab = [(tokens(k), v) for k, v in TEAM_CORES.items()]
    saida = {}
    for p in (f.get("participants") or []):
        alvo = tokens(p.get("name"))
        for toks, cor in tab:
            if alvo & toks:
                saida[p.get("id")] = cor
                break
    return saida


async def _fim_sportmonks(fixture_sm: int) -> dict:
    f, err = await sm.partida(fixture_sm)
    if err or not f:
        return {"fonte": "sportmonks", "erro": err or "partida não encontrada"}
    return sm.texto_fim_de_jogo(f, _cores_sm(f))


# Guarda o resultado da última coleta. Sem isto, quando nada aparece na tela
# eu não tenho como saber SE o coletor rodou, se achou jogo, ou se falhou —
# foi exatamente o que aconteceu duas vezes seguidas.
_ULTIMA_COLETA: dict = {"quando": None, "novos": 0, "sm_jogos": 0, "sm_gols": 0,
                        "af_jogos": 0, "af_gols": 0, "erros": []}


async def coletar_gols_ao_vivo() -> dict:
    """Carimba, para cada fonte, o instante em que ela publicou cada gol.

    Roda de minuto em minuto pelo agendador. É isto que permite dizer qual das
    duas chega antes — sem carimbo, a comparação seria impressão."""
    novos = []
    diag = {"quando": datetime.now(timezone.utc).isoformat(), "novos": 0,
            "sm_jogos": 0, "sm_gols": 0, "af_jogos": 0, "af_gols": 0, "erros": []}

    # ── Sportmonks ────────────────────────────────────────────────────────
    if not sm.configurado():
        diag["erros"].append("SPORTMONKS_TOKEN ausente")
    else:
        jogos, err = await sm.ao_vivo()
        if err:
            diag["erros"].append(f"sportmonks ao_vivo: {err[:120]}")
        diag["sm_jogos"] = len(jogos)
        for f in jogos:
            diag["sm_gols"] += len(sm.gols_da_partida(f))
            cores = _cores_sm(f)
            for ev in sm.gols_da_partida(f):
                chave = f"{f.get('id')}|{sm.chave_do_gol(ev)}"
                if registrar_gol("sportmonks", chave,
                                 minuto=ev.get("minute"),
                                 autor=sm._autor(ev),
                                 assistente=sm._assistente(ev) or None,
                                 placar=ev.get("result"),
                                 texto=sm.texto_do_gol(f, ev, cores),
                                 fixture_sm=f.get("id")):
                    novos.append(("sportmonks", chave))

    # ── API-Football ──────────────────────────────────────────────────────
    hoje = datetime.now(timezone.utc).date().isoformat()
    for liga_id in (AF_LEAGUE_SPL, 504, 826, 17, 18):
        season = await _season_da_liga(liga_id, _af_temporada_corrente())
        data, err = await _af_get("fixtures", {"league": liga_id, "season": season,
                                               "date": hoje}, ttl=_AF_TTL_AO_VIVO)
        if err or not data:
            continue
        for fx in data.get("response", []):
            st = ((fx.get("fixture") or {}).get("status") or {}).get("short")
            # Inclui FT: o gol do fim do jogo tem que ser carimbado mesmo que a
            # partida encerre entre uma passagem e outra do coletor.
            if st not in ("1H", "2H", "HT", "ET", "P", "BT", "FT", "AET", "PEN"):
                continue
            diag["af_jogos"] += 1
            fid = (fx.get("fixture") or {}).get("id")
            ev, e2 = await _af_get("fixtures/events",
                                   {"fixture": fid, "type": "Goal"},
                                   ttl=_AF_TTL_AO_VIVO)
            if e2:
                diag["erros"].append(f"af eventos {fid}: {str(e2)[:80]}")
                continue
            diag["af_gols"] += len((ev or {}).get("response", []))
            times = fx.get("teams") or {}
            casa, fora = times.get("home") or {}, times.get("away") or {}
            gc = gf = 0
            for g in (ev or {}).get("response", []):
                if (g.get("detail") or "") == "Missed Penalty":
                    continue
                dono = (g.get("team") or {}).get("id")
                marcou_casa = dono == casa.get("id")
                if (g.get("detail") or "") == "Own Goal":
                    marcou_casa = not marcou_casa
                if marcou_casa:
                    gc += 1
                else:
                    gf += 1
                autor = _nome_artilheiro((g.get("player") or {}).get("name"))
                minuto = (g.get("time") or {}).get("elapsed")
                # MESMA chave da Sportmonks, para os dois lados casarem.
                chave = f"{fid}|{minuto}|{autor}|{gc}-{gf}"
                assist = _nome_artilheiro((g.get("assist") or {}).get("name") or "")
                cor = (TEAM_CORES.get(casa.get("name"), "") if marcou_casa
                       else TEAM_CORES.get(fora.get("name"), ""))
                # Pela tabela, e não pelo que a API mandou: ela escreve
                # "Al-Qadisiyah FC" onde a Sportmonks escreve "Al Qadsiah",
                # e o post não pode mudar conforme quem carimbou primeiro.
                nc = glossary.nome_para_card(casa.get("name"))
                nf = glossary.nome_para_card(fora.get("name"))
                marca = ""
                if (g.get("detail") or "") == "Penalty":
                    marca = " (p)"
                elif (g.get("detail") or "") == "Own Goal":
                    marca = " (gc)"
                linhas = [f"{cor} {glossary.GRITO_DE_GOL}".strip(), "",
                          f"⏰ {minuto}' {nc} {gc} x {gf} {nf}",
                          f"⚽ {autor}{marca}"]
                if assist:
                    linhas.append(f"🅰️ {assist}")
                if registrar_gol("api_football", chave, minuto=minuto, autor=autor,
                                 assistente=assist or None, placar=f"{gc}-{gf}",
                                 texto="\n".join(linhas), fixture_af=fid):
                    novos.append(("api_football", chave))

    diag["novos"] = len(novos)
    _ULTIMA_COLETA.update(diag)
    return {"novos": len(novos), "detalhe": novos, "diagnostico": diag}


# ══════════════════════════════════════════════════════════════════════════
# CLIPE DE GOL
# ══════════════════════════════════════════════════════════════════════════

# Quanto tempo passa entre o gol acontecer e você conseguir apertar o botão.
# Sem descontar isso, a janela de "10 segundos antes" viraria "6 antes", e o
# clipe começaria com a bola já entrando. É estimativa, e é por isso que
# existem os botões de ajuste.
# REACAO_SEG, ANTES_SEG, DEPOIS_SEG, PASSO_AJUSTE e HORAS_ATE_DESCARTE
# viraram ajustes na guia de Configurações. Ficarem aqui como constante
# seria manter uma segunda verdade, e um dia as duas discordariam.

# A janela do clipe. Passou por 10/5 (curto demais: pegava o chute e a
# comemoração, mas cortava a construção da jogada) e por 20/8. Depois de
# clipar jogo de verdade, ficou em 12/10.

# De quanto em quanto os botões de ajuste movem a janela. Era 5; com o clipe
# em 12/10, cinco segundos mal tiravam o clipe do lugar.

# Quanto tempo um clipe não guardado sobrevive depois que o jogo sai do ar.

# ATRASO DA TRANSMISSÃO — quantos segundos a live do YouTube está ATRÁS do
# que você está assistindo quando aperta o botão.
#
# Isto não é detalhe fino: é a diferença entre o clipe pegar o gol e pegar a
# jogada anterior. Você vê o lance na sua tela, aperta; nesse instante a live
# que eu gravo ainda está mostrando o que aconteceu meia dúzia de segundos
# antes. Sem descontar isso, eu corto cedo demais, todas as vezes.
#
# Medi o que dava para medir sozinho: o ffmpeg começa com uns +5s de conteúdo
# já baixado (mediana de 22 gravações suas). Mas o resto depende de ONDE você
# assiste — TV, outro site, a própria live — e isso eu não tenho como medir
# daqui. Por isso o número é ajustável na tela, e não uma constante que só eu
# posso mudar.
#
# O valor inicial vem da sua medição: clique às 15:04:42, corte devia começar
# às 15:04:52. Com a janela de 12s antes, isso põe o instante do lance 22s
# depois do clique — 26s à frente de onde eu estava colocando.
CHAVE_ATRASO = "clipe_atraso_transmissao"
ATRASO_PADRAO_SEG = 26
ATRASO_MAX_SEG = 120

# Cache curto porque isto é lido em toda tela de clipe e a cada consulta do
# gravador. Cinco segundos é rápido o bastante para você mexer na guia de
# configurações e ver o efeito no clipe seguinte.
_CACHE_AJUSTE: dict = {}


def ajuste(chave: str):
    """O valor configurado, ou o padrão. Nunca levanta."""
    a = ajustes.POR_CHAVE.get(chave)
    if not a:
        return None
    guardado = _CACHE_AJUSTE.get(chave)
    if guardado and time.time() - guardado[0] < 5:
        return guardado[1]
    valor = a["padrao"]
    try:
        bruto = get_state(chave)
        if bruto is not None:
            limpo = ajustes.limpar(chave, bruto)
            if limpo is not None:
                valor = limpo
    except Exception:
        pass
    _CACHE_AJUSTE[chave] = (time.time(), valor)
    return valor


def _atraso_transmissao() -> int:
    return int(ajuste("clipe_atraso_transmissao"))

# Fonte preferida para a legenda. A API-Football tem se mostrado mais rápida
# nas medições, e legenda que chega tarde não serve para clipe ao vivo.
FONTE_LEGENDA = "api_football"


def _legenda_do_gol(alvo_iso: str) -> tuple[str, int | None]:
    """Acha o alerta de gol mais próximo do instante do clipe.

    A fonte publica o gol DEPOIS de ele acontecer, então procuro numa janela
    torta de propósito: pouco para trás e bastante para frente. Um alerta que
    chegou três minutos depois do seu toque ainda é o gol que você clipou; um
    que chegou dois minutos ANTES é outro gol.
    """
    try:
        alvo = datetime.fromisoformat(alvo_iso)
    except Exception:
        return "", None
    melhor, menor = None, None
    for l in gols_vistos(3):
        if l.get("fonte") != FONTE_LEGENDA or not l.get("texto"):
            continue
        try:
            visto = datetime.fromisoformat(l["visto_em"])
        except Exception:
            continue
        d = (visto - alvo).total_seconds()
        if not (-60 <= d <= 300):
            continue
        if menor is None or abs(d) < menor:
            melhor, menor = l, abs(d)
    return ((melhor or {}).get("texto") or ""), ((melhor or {}).get("id"))


def _com_legenda(c: dict) -> dict:
    """Preenche a legenda a partir do alerta de gol, se você ainda não escreveu.

    Só em clipe de gol. Num clipe de defesa ou de cartão, colar o texto de um
    gol que saiu por perto seria pior que deixar em branco.
    """
    if c.get("tipo") == "outro":
        return c
    if not c.get("texto"):
        texto, gol_id = _legenda_do_gol(c.get("alvo_em") or "")
        if texto:
            c["texto"] = texto
            c["texto_sugerido"] = True
            c["gol_id"] = gol_id
    return c


def _agente_autorizado(request: Request) -> bool:
    """O agente de casa precisa provar quem é.

    Sem isso, qualquer um na internet poderia enfiar um vídeo na sua fila de
    publicação — e o vídeo é o que vai para o ar em nome do seu acordo com o
    detentor dos direitos. As outras rotas do app são abertas, mas essa aqui
    aceita conteúdo de fora, e isso é outro patamar de risco.
    """
    esperado = os.environ.get("CLIPE_TOKEN", "").strip()
    if not esperado:
        return False
    enviado = (request.headers.get("X-Clipe-Token")
               or request.query_params.get("token") or "")
    return secrets.compare_digest(enviado, esperado)


CHAVE_GRAVADOR = "clipe_gravador"

# A versão do gravador que este servidor espera. Quando o gravador reporta
# outra, a tela avisa para fechar e reabrir o gravador.bat.
#
# Sem isso, um gravador antigo rodando na memória entrega clipes com defeitos
# já corrigidos, e nada na tela denuncia. Aconteceu: três horas de clipes com
# o áudio adiantado depois de o defeito estar consertado no arquivo.
VERSAO_GRAVADOR = "2026-08-26a"


def _gravador_estado() -> dict:
    """O que o gravador reportou da última vez, e há quanto tempo.

    O campo 'gravando' é um dicionário {live_id: hora de início}: com quatro
    jogos possíveis, saber que "está gravando" não basta — a tela precisa
    dizer qual jogo está de pé e qual não começou.
    """
    try:
        d = json.loads(get_state(CHAVE_GRAVADOR) or "{}")
    except Exception:
        return {}
    try:
        visto = datetime.fromisoformat(d.get("visto_em", ""))
        d["ha_segundos"] = int((datetime.now(timezone.utc) - visto).total_seconds())
    except Exception:
        d["ha_segundos"] = None
    # Ele consulta de 4 em 4 segundos. Um minuto sem dar sinal é a janela do
    # gravador fechada, o computador dormindo, ou a internet caída.
    d["online"] = d.get("ha_segundos") is not None and d["ha_segundos"] < 60
    d["versao_esperada"] = VERSAO_GRAVADOR
    d["atualizado"] = (d.get("versao") or "") == VERSAO_GRAVADOR
    return d


# ══════════════════════════════════════════════════════════════════════════
# ESCALAÇÕES — qual fonte publica primeiro
# ══════════════════════════════════════════════════════════════════════════

_ULTIMA_ESCALACAO = {"quando": None, "sm_jogos": 0, "sm_com": 0,
                     "af_jogos": 0, "af_com": 0, "novos": 0, "erros": []}

# A escalação sai perto de uma hora antes. Consulto nesta janela e paro depois
# do apito inicial — insistir o dia todo gastaria chamada à toa.
ESC_ANTES_MIN = 180
ESC_DEPOIS_MIN = 20

# Nome de fonte usado só para o carimbo da escalação OFICIAL da Sportmonks.
# A fonte "sportmonks" continua carimbando a primeira publicação, que costuma
# ser a provável. Duas fontes em vez de uma coluna nova: a tabela já está em
# uso e a chave única dela é (fonte, chave).
FONTE_SM_OFICIAL = "sportmonks_oficial"


# variante em minúsculas -> chave do clube. Montada uma vez, na subida.
_CLUBES_POR_VARIANTE = {
    chave: {re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", v.lower())).strip()
            for v in variantes}
    for chave, variantes in clubs.ALL_CLUBS.items()
}


def _token_clube(nome: str) -> str:
    """Chave canônica do clube, para o mesmo jogo casar entre as duas fontes.

    Uso a lista do clubs.py, que já tem as variantes de transliteração —
    okhdood/akhdoud, qadsiah/qadisiyah, damac/damak, khaleej/khalij. Tentei
    antes um normalizador fonético e ele fez Al-Hilal e Al-Ahli virarem o
    mesmo token, o que pareava jogos diferentes em silêncio. Lista fechada é
    o que funciona aqui, e já estava pronta.

    Clube fora da lista devolve um token próprio, com um prefixo que nunca
    casa com nada: prefiro mostrar o jogo separado nas duas fontes a juntar
    dois jogos diferentes.
    """
    n = re.sub(r"[^a-z ]", " ", (nome or "").lower())
    n = re.sub(r"\s+", " ", n).strip()
    if not n:
        return "?"
    for chave, variantes in _CLUBES_POR_VARIANTE.items():
        if n in variantes:
            return chave
    # tenta sem os sufixos que só uma das fontes usa
    curto = re.sub(r"\b(fc|sc|club|saudi|jeddah)\b", " ", n)
    curto = re.sub(r"\s+", " ", curto).strip()
    for chave, variantes in _CLUBES_POR_VARIANTE.items():
        if curto in variantes:
            return chave
    return "desconhecido:" + curto.replace(" ", "")


def _chave_escalacao(comeca_iso: str, casa: str) -> str:
    """Identidade do jogo, igual nas duas fontes.

    Hora do apito inicial mais o time da casa. Só a hora não bastaria: numa
    rodada final os jogos começam todos no mesmo minuto.
    """
    quando = (comeca_iso or "")[:16]
    return f"{quando}|{_token_clube(casa)}"


def _esc_af(resposta: list) -> dict:
    """Converte a escalação da API-Football para a MESMA forma da Sportmonks.

    Sem isso a tela teria que saber ler dois formatos, e a comparação — que é
    o motivo desta guia — ficaria enterrada em condicional.
    """
    times = []
    for t in (resposta or []):
        titulares = [{"nome": ((j.get("player") or {}).get("name") or "?"),
                      "camisa": (j.get("player") or {}).get("number")}
                     for j in (t.get("startXI") or [])]
        banco = [{"nome": ((j.get("player") or {}).get("name") or "?"),
                  "camisa": (j.get("player") or {}).get("number")}
                 for j in (t.get("substitutes") or [])]
        if not titulares and not banco:
            continue
        times.append({"nome": ((t.get("team") or {}).get("name") or "")
                              .replace("-", " ").upper(),
                      "titulares": titulares, "banco": banco,
                      "formacao": t.get("formation") or ""})
    # Mesma regra da Sportmonks: sem titular, a escalação não saiu.
    if not any(t["titulares"] for t in times):
        return {}
    return {"times": times, "quantos": sum(len(t["titulares"]) + len(t["banco"])
                                           for t in times)}


async def coletar_escalacoes() -> dict:
    """Carimba, para cada fonte, o instante em que ela publicou a escalação.

    Só olha jogos na janela em torno do apito inicial. A escalação sai perto de
    uma hora antes; insistir o dia inteiro gastaria chamada à toa.
    """
    agora = datetime.now(timezone.utc)
    diag = {"quando": agora.isoformat(), "novos": 0, "sm_jogos": 0, "sm_com": 0,
            "af_jogos": 0, "af_com": 0, "erros": []}
    novos = []

    def na_janela(quando: datetime | None) -> bool:
        if quando is None:
            return False
        falta = (quando - agora).total_seconds() / 60
        return -ESC_DEPOIS_MIN <= falta <= ESC_ANTES_MIN

    # já carimbados: não gasto chamada para reconsultar o que já sei
    ja = {(l.get("fonte"), l.get("chave")) for l in escalacoes_vistas(24)}

    # ── Sportmonks: uma chamada traz o dia inteiro ────────────────────────
    if not sm.configurado():
        diag["erros"].append("SPORTMONKS_TOKEN ausente")
    else:
        for dia in (agora.date().isoformat(),
                    (agora + timedelta(days=1)).date().isoformat()):
            jogos, err = await sm.com_escalacao(dia)
            if err:
                diag["erros"].append(f"sportmonks {dia}: {str(err)[:100]}")
                continue
            for f in jogos:
                quando = _quando_sm(f)
                if not na_janela(quando):
                    continue
                diag["sm_jogos"] += 1
                casa, fora = sm._lados(f)
                chave = _chave_escalacao(
                    quando.isoformat() if quando else "", casa.get("name") or "")
                confirmada = sm.escalacao_confirmada(f)
                # Duas fontes para a mesma casa: uma carimba a PRIMEIRA vez que
                # ela publicou qualquer coisa, a outra a primeira vez que ela
                # disse que era oficial. Assim os dois instantes ficam
                # guardados sem precisar mexer na tabela que já está em uso —
                # e a comparação de velocidade passa a usar o certo.
                faltam = [("sportmonks", chave)]
                if confirmada:
                    faltam.append((FONTE_SM_OFICIAL, chave))
                faltam = [p for p in faltam if p not in ja]
                if not faltam:
                    diag["sm_com"] += 1
                    continue
                esc = sm.escalacao_da_partida(f)
                if not esc:
                    continue
                diag["sm_com"] += 1
                if confirmada is not None:
                    esc["confirmada"] = bool(confirmada)
                jogo = (f"{sm._nome_card(casa.get('name'))} x "
                        f"{sm._nome_card(fora.get('name'))}")
                for fonte, ch in faltam:
                    if registrar_escalacao(fonte, ch, jogo=jogo,
                                           comeca_em=quando,
                                           conteudo=json.dumps(esc, ensure_ascii=False),
                                           fixture_sm=f.get("id")):
                        novos.append((fonte, ch))

    # ── API-Football: uma chamada por jogo que ainda falta ────────────────
    for dia in (agora.date().isoformat(),
                (agora + timedelta(days=1)).date().isoformat()):
        for liga_id in (AF_LEAGUE_SPL, 504, 826, 17, 18):
            season = await _season_da_liga(liga_id, _af_temporada_corrente())
            data, err = await _af_get("fixtures", {"league": liga_id,
                                                   "season": season, "date": dia},
                                      ttl=120)
            if err or not data:
                if err:
                    diag["erros"].append(f"af fixtures {liga_id}: {str(err)[:80]}")
                continue
            for fx in data.get("response", []):
                quando = _quando_af(fx)
                if not na_janela(quando):
                    continue
                diag["af_jogos"] += 1
                times = fx.get("teams") or {}
                casa = (times.get("home") or {}).get("name") or ""
                fora = (times.get("away") or {}).get("name") or ""
                chave = _chave_escalacao(
                    quando.isoformat() if quando else "", casa)
                if ("api_football", chave) in ja:
                    diag["af_com"] += 1
                    continue
                fid = (fx.get("fixture") or {}).get("id")
                lin, e2 = await _af_get("fixtures/lineups", {"fixture": fid}, ttl=60)
                if e2:
                    diag["erros"].append(f"af lineups {fid}: {str(e2)[:80]}")
                    continue
                esc = _esc_af((lin or {}).get("response") or [])
                if not esc:
                    continue
                diag["af_com"] += 1
                jogo = (f"{casa.replace('-', ' ').upper()} x "
                        f"{fora.replace('-', ' ').upper()}")
                if registrar_escalacao("api_football", chave, jogo=jogo,
                                       comeca_em=quando,
                                       conteudo=json.dumps(esc, ensure_ascii=False),
                                       fixture_af=fid):
                    novos.append(("api_football", chave))

    diag["novos"] = len(novos)
    _ULTIMA_ESCALACAO.update(diag)
    return diag


def _quando_sm(f: dict) -> datetime | None:
    for campo in ("starting_at", "start_at"):
        bruto = f.get(campo)
        if not bruto:
            continue
        try:
            return datetime.fromisoformat(
                str(bruto).replace(" ", "T").replace("Z", "+00:00")
            ).replace(tzinfo=timezone.utc) if "+" not in str(bruto) else \
                datetime.fromisoformat(str(bruto).replace(" ", "T"))
        except Exception:
            continue
    return None


def _quando_af(fx: dict) -> datetime | None:
    bruto = (fx.get("fixture") or {}).get("date")
    if not bruto:
        return None
    try:
        d = datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@app.get("/api/escalacoes")
async def api_escalacoes(horas: int = 12, coletar: int = 1):
    """As duas fontes lado a lado, com o horário em que cada uma publicou."""
    if coletar:
        try:
            await coletar_escalacoes()
        except Exception as e:
            _ULTIMA_ESCALACAO["erros"] = [f"coleta: {type(e).__name__}: {e}"]
    linhas = escalacoes_vistas(horas)
    por_jogo: dict = {}
    for l in linhas:
        d = por_jogo.setdefault(l.get("chave"), {
            "jogo": l.get("jogo") or "", "comeca_em": l.get("comeca_em")})
        if not d.get("jogo"):
            d["jogo"] = l.get("jogo") or ""
        try:
            conteudo = json.loads(l.get("conteudo") or "{}")
        except Exception:
            conteudo = {}
        d[l["fonte"]] = {"visto_em": l.get("visto_em"), "escalacao": conteudo}
    saida = []
    for chave, d in por_jogo.items():
        a, s = d.get("api_football"), d.get("sportmonks")
        oficial = d.get(FONTE_SM_OFICIAL)
        # A corrida é entre escalações OFICIAIS. Comparar a provável da
        # Sportmonks com a da API-Football daria vantagem a quem chuta antes,
        # que é o contrário do que a medição quer dizer.
        lado_sm = oficial or s
        dif, comparei = None, None
        if a and lado_sm:
            try:
                dif = round((datetime.fromisoformat(lado_sm["visto_em"])
                             - datetime.fromisoformat(a["visto_em"])).total_seconds())
                comparei = "oficial" if oficial else "primeira"
            except Exception:
                pass
        saida.append({"chave": chave, "jogo": d.get("jogo"),
                      "comeca_em": d.get("comeca_em"),
                      "api_football": a, "sportmonks": s,
                      "sportmonks_oficial": oficial,
                      "diferenca_seg": dif, "diferenca_de": comparei})
    saida.sort(key=lambda x: (x.get("comeca_em") or ""), reverse=True)
    return {"escalacoes": saida, "diagnostico": _ULTIMA_ESCALACAO,
            "sportmonks_configurada": sm.configurado()}


@app.get("/api/clipe/lives")
async def api_clipe_lives():
    """O que está sendo gravado, e o que o canal está transmitindo agora."""
    return {"lives": listar_lives(), "disponiveis": lives_disponiveis(),
            "gravador": _gravador_estado(), "canal": CANAL, "max": MAX_LIVES,
            "atraso": _atraso_transmissao()}


@app.post("/api/clipe/lives")
async def api_clipe_live_add(request: Request):
    """Põe um jogo do canal para gravar.

    Recebe o id do vídeo, não uma URL. Assim não existe caminho para gravar
    algo fora do canal — nem por engano, nem por link montado à mão.
    """
    corpo = await request.json()
    ok, motivo = adicionar_live_do_canal((corpo.get("id") or "").strip())
    if not ok:
        return JSONResponse({"erro": motivo}, 400)
    return {"ok": True, "lives": listar_lives()}


@app.post("/api/clipe/lives/{live_id}/remover")
async def api_clipe_live_remover(live_id: str):
    if not remover_live(live_id):
        return JSONResponse({"erro": "esse jogo não está na lista"}, 404)
    return {"ok": True, "lives": listar_lives()}


@app.post("/api/clipe/pedir")
async def api_clipe_pedir(request: Request):
    """O botão. Carimba a hora e põe na fila do gravador."""
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    live_id = (corpo.get("live_id") or "").strip()
    tipo = "outro" if corpo.get("tipo") == "outro" else "gol"
    lives = listar_lives()
    if not lives:
        return JSONResponse({"erro": "nenhum jogo sendo gravado"}, 400)
    if not live_id:
        # Com um jogo só, não faz sentido exigir escolha. Com dois ou mais,
        # exijo: adivinhar qual jogo você quis clipar seria pior que perguntar.
        if len(lives) > 1:
            return JSONResponse({"erro": "diga de qual jogo é o clipe"}, 400)
        live_id = lives[0].get("id") or ""
    elif not any(l.get("id") == live_id for l in lives):
        return JSONResponse({"erro": "esse jogo não está sendo gravado"}, 400)
    # O instante do lance NA GRAVAÇÃO, que não é o instante do seu clique:
    # somo o atraso da transmissão (ela está atrás do que você vê) e desconto
    # o seu tempo de reação (você aperta um pouco depois de ver).
    atraso = _atraso_transmissao()
    reacao = int(ajuste("clipe_reacao_seg"))
    alvo = datetime.now(timezone.utc) + timedelta(seconds=atraso - reacao)
    cid = criar_pedido_clipe(alvo, int(ajuste("clipe_antes_seg")),
                             int(ajuste("clipe_depois_seg")), live_id, tipo)
    if not cid:
        return JSONResponse({"erro": "não consegui registrar o pedido"}, 500)
    return {"id": cid, "alvo_em": alvo.isoformat(), "live_id": live_id,
            "tipo": tipo, "reacao_descontada": reacao, "atraso": atraso}


@app.get("/api/ajustes")
async def api_ajustes_ler():
    """Todos os ajustes com o valor de agora, o padrão e a explicação."""
    saida = []
    for a in ajustes.AJUSTES:
        d = dict(a)
        d["valor"] = ajuste(a["chave"])
        d["no_padrao"] = d["valor"] == a["padrao"]
        saida.append(d)
    return {"ajustes": saida, "grupos": ajustes.grupos()}


@app.post("/api/ajustes")
async def api_ajustes_gravar(request: Request):
    """Grava um ajuste. Recusa valor fora da faixa em vez de torcer."""
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    chave = (corpo.get("chave") or "").strip()
    if chave not in ajustes.POR_CHAVE:
        return JSONResponse({"erro": "não conheço esse ajuste"}, 400)
    a = ajustes.POR_CHAVE[chave]
    if corpo.get("padrao"):
        valor = a["padrao"]
    else:
        valor = ajustes.limpar(chave, corpo.get("valor"))
        if valor is None:
            faixa = (f"entre {a['min']} e {a['max']}" if a["tipo"] == "int"
                     else "uma das opções da lista")
            return JSONResponse({"erro": f"valor inválido — precisa ser {faixa}"}, 400)
    set_state(chave, str(valor))
    _CACHE_AJUSTE.pop(chave, None)
    return {"ok": True, "chave": chave, "valor": valor,
            "no_padrao": valor == a["padrao"]}


@app.post("/api/clipe/pendentes")
async def api_clipe_pendentes(request: Request):
    """Uma chamada só, e o gravador resolve tudo nela.

    Ele manda o que está gravando e o que achou no canal; recebe a lista de
    jogos para gravar e os cortes pendentes. Três rotas separadas seriam três
    requisições de 4 em 4 segundos para dizer a mesma coisa.
    """
    if not _agente_autorizado(request):
        return JSONResponse({"erro": "token do agente ausente ou errado"}, 403)
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    try:
        set_state(CHAVE_GRAVADOR, json.dumps({
            "visto_em": datetime.now(timezone.utc).isoformat(),
            "versao": corpo.get("versao") or "",
            # O nome da máquina e o último erro sobem junto para você poder
            # olhar a guia Clipes do celular em vez de perguntar no WhatsApp
            # para quem está com o computador ligado.
            "nome": str(corpo.get("nome") or "")[:40],
            "ultimo_erro": str(corpo.get("ultimo_erro") or "")[:300],
            "gravando": corpo.get("gravando") or {}}))
    except Exception:
        pass          # o batimento não pode derrubar a entrega dos clipes
    if isinstance(corpo.get("disponiveis"), list):
        salvar_disponiveis(corpo["disponiveis"])
    for t in (corpo.get("titulos") or []):
        if isinstance(t, dict):
            titulo_da_live(t.get("id") or "", t.get("titulo") or "")
    # Os ajustes vão na mesma resposta. É isto que faz a máquina que grava
    # obedecer à guia de Configurações sem ninguém atualizar nada lá.
    return {"clipes": clipes_a_cortar(), "lives": listar_lives(), "canal": CANAL,
            "versao_esperada": VERSAO_GRAVADOR,
            "ajustes": {a["chave"]: ajuste(a["chave"])
                        for a in ajustes.AJUSTES
                        if a["chave"].startswith("gravador_")}}


@app.get("/api/gravador/codigo", response_class=PlainTextResponse)
async def api_gravador_codigo(request: Request):
    """O código do gravador, para ele se atualizar sozinho.

    Exige o mesmo token do agente. Não é segredo — está no GitHub — mas uma
    rota aberta que devolve arquivo do servidor é o tipo de coisa que um dia
    devolve o arquivo errado.
    """
    if not _agente_autorizado(request):
        return PlainTextResponse("token do agente ausente ou errado", 403)
    try:
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "gravador.py")
        with open(caminho, encoding="utf-8") as f:
            return PlainTextResponse(f.read())
    except Exception as e:
        return PlainTextResponse(f"não consegui ler o gravador: {e}", 500)


@app.post("/api/clipe/{clipe_id}/entregar")
async def api_clipe_entregar(clipe_id: int, request: Request):
    """O gravador devolve o mp4, como bytes crus no corpo.

    Bytes crus e não multipart de propósito: multipart exigiria a biblioteca
    python-multipart, que não está instalada aqui e que eu teria descoberto
    que faltava só no deploy.
    """
    if not _agente_autorizado(request):
        return JSONResponse({"erro": "token do agente ausente ou errado"}, 403)
    dados = await request.body()
    if not dados:
        erro_no_clipe(clipe_id, "o gravador mandou corpo vazio")
        return JSONResponse({"erro": "corpo vazio"}, 400)
    if len(dados) > 60 * 1024 * 1024:
        erro_no_clipe(clipe_id, f"clipe de {len(dados)//1024//1024} MB é grande demais")
        return JSONResponse({"erro": "clipe grande demais"}, 413)
    if dados[4:8] != b"ftyp":
        erro_no_clipe(clipe_id, "o que chegou não parece um mp4")
        return JSONResponse({"erro": "não parece mp4"}, 400)
    if not entregar_clipe(clipe_id, dados):
        return JSONResponse({"erro": "clipe não está em estado de receber corte"}, 409)
    return {"ok": True, "bytes": len(dados)}


@app.post("/api/clipe/{clipe_id}/falhou")
async def api_clipe_falhou(clipe_id: int, request: Request):
    """O gravador avisa que não conseguiu cortar."""
    if not _agente_autorizado(request):
        return JSONResponse({"erro": "token do agente ausente ou errado"}, 403)
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    erro_no_clipe(clipe_id, corpo.get("erro") or "o gravador não explicou")
    return {"ok": True}


@app.get("/api/clipes")
async def api_clipes(horas: int = 8):
    lives = listar_lives()
    nomes = {l.get("id"): (l.get("titulo") or "") for l in lives}
    clipes = []
    for c in clipes_recentes(horas):
        c["jogo"] = nomes.get(c.get("live_id")) or ""
        clipes.append(_com_legenda(c))
    return {"clipes": clipes,
            "agente_configurado": bool(os.environ.get("CLIPE_TOKEN", "").strip()),
            "lives": lives, "disponiveis": lives_disponiveis(),
            "gravador": _gravador_estado(), "canal": CANAL, "max": MAX_LIVES,
            "atraso": _atraso_transmissao()}


# ══════════════════════════════════════════════════════════════════════════
# O CORTE DA FITA
#
# Antes, mexer nos punhos mandava o gravador refazer o clipe a partir da
# gravação original: melhor qualidade, mas você ficava esperando o arquivo ir
# e voltar. Agora a fita só ANOTA o trecho, e o corte acontece aqui, no
# servidor, no instante em que o vídeo vai sair — publicar ou baixar.
#
# O preço é uma recodificação a mais: o gravador já codificou uma vez, e este
# corte codifica de novo. Num clipe de vinte segundos a olho nu não se vê, e
# vale a troca — você deixou claro que esperar é o que incomoda.
#
# Se o ffmpeg não estiver na imagem, o corte não acontece e eu digo isso em
# vez de publicar o vídeo inteiro fingindo que cortei.
def _tem_ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


def _corte_pedido(c: dict) -> tuple[float, float] | None:
    """O trecho escolhido, ou None quando é o clipe inteiro."""
    ini, fim = c.get("corte_ini"), c.get("corte_fim")
    if ini is None or fim is None:
        return None
    ini, fim = float(ini), float(fim)
    dur = float((c.get("antes_seg") or 0) + (c.get("depois_seg") or 0))
    # Margem de meio segundo: punho encostado na ponta é "clipe inteiro", e
    # recodificar à toa só piora a imagem.
    if ini <= 0.5 and (dur - fim) <= 0.5:
        return None
    if fim - ini < 1:
        return None
    return ini, fim


def _cortar_video(dados: bytes, ini: float, fim: float) -> tuple[bytes, str]:
    """Devolve (bytes cortados, erro). Nunca levanta."""
    ffmpeg = _tem_ffmpeg()
    if not ffmpeg:
        return b"", ("este servidor está sem ffmpeg, então não consigo aplicar "
                     "o corte da fita")
    pasta = tempfile.mkdtemp(prefix="corte_")
    entrada = os.path.join(pasta, "entra.mp4")
    saida = os.path.join(pasta, "sai.mp4")
    try:
        with open(entrada, "wb") as f:
            f.write(dados)
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{ini:.2f}",
             "-i", entrada, "-t", f"{max(0.5, fim - ini):.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
             "-pix_fmt", "yuv420p", "-b:v", "5M",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", saida],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not os.path.exists(saida):
            return b"", f"o corte falhou: {(r.stderr or '')[:200]}"
        with open(saida, "rb") as f:
            cortado = f.read()
        if len(cortado) < 10000:
            return b"", "o corte saiu vazio"
        return cortado, ""
    except Exception as e:
        return b"", f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _video_pronto(clipe_id: int, c: dict) -> tuple[bytes, str]:
    """O mp4 como ele deve sair: já com o corte da fita aplicado."""
    dados = video_do_clipe(clipe_id)
    if not dados:
        return b"", "o clipe não tem vídeo"
    corte = _corte_pedido(c)
    if not corte:
        return dados, ""
    return _cortar_video(dados, corte[0], corte[1])


def _nome_do_arquivo(clipe_id: int, c: dict | None) -> str:
    """Nome de arquivo que diz qual jogo é, sem acento e sem espaço.

    Vinte clipes chamados clipe_1.mp4 na pasta de Downloads não servem para
    nada. O nome sai como AL_HILAL_x_AL_NASSR_1742.mp4.
    """
    c = c or {}
    bruto = (c.get("jogo") or "").strip()
    # Só letras, números e espaço; o resto vira nada. Acento cai na conversão.
    limpo = unicodedata.normalize("NFKD", bruto).encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^A-Za-z0-9 ]+", " ", limpo)
    limpo = "_".join(limpo.split())[:60]
    hora = ""
    try:
        hora = datetime.fromisoformat(c["alvo_em"]).astimezone(
            ZoneInfo("America/Sao_Paulo")).strftime("%H%M")
    except Exception:
        pass
    partes = [p for p in (limpo, hora) if p] or [f"clipe_{clipe_id}"]
    return "_".join(partes) + ".mp4"


@app.get("/api/clipe/{clipe_id}/video")
async def api_clipe_video(clipe_id: int, baixar: int = 0):
    """O mp4. Na tela vai inteiro; para baixar, vai com o corte aplicado.

    Inteiro na tela de propósito: a prévia da fita é o próprio player tocando
    só o trecho escolhido, e isso é instantâneo. Se eu cortasse aqui, cada
    arrastada de punho recodificaria o vídeo e a fita voltaria a ser lenta —
    que é justamente o que a gente está tirando do caminho.
    """
    if not baixar:
        dados = video_do_clipe(clipe_id)
        if not dados:
            return JSONResponse({"erro": "sem vídeo"}, 404)
        return Response(content=dados, media_type="video/mp4",
                        headers={"Cache-Control": "no-store"})
    c = um_clipe(clipe_id)
    if not c:
        return JSONResponse({"erro": "clipe não existe"}, 404)
    dados, erro = _video_pronto(clipe_id, c)
    if erro:
        return PlainTextResponse(erro, status_code=409)
    nome = _nome_do_arquivo(clipe_id, c)
    return Response(content=dados, media_type="video/mp4", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{nome}"'})


@app.post("/api/clipe/{clipe_id}/ajustar")
async def api_clipe_ajustar(clipe_id: int, delta: int = 0):
    if not delta:
        return JSONResponse({"erro": "diga de quantos segundos é o ajuste"}, 400)
    if abs(delta) > 60:
        return JSONResponse({"erro": "ajuste de no máximo 60s por vez"}, 400)
    if not ajustar_clipe(clipe_id, delta):
        return JSONResponse({"erro": "não deu para ajustar este clipe"}, 409)
    return {"ok": True, "clipe": _com_legenda(um_clipe(clipe_id) or {})}


@app.post("/api/clipe/{clipe_id}/corte")
async def api_clipe_corte(clipe_id: int, request: Request):
    """Anota o trecho da fita. Não recorta nada aqui — por isso é instantâneo."""
    c = um_clipe(clipe_id)
    if not c:
        return JSONResponse({"erro": "clipe não existe"}, 404)
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    if corpo.get("ini") is None and corpo.get("fim") is None:
        marcar_corte(clipe_id, None, None)
        return {"ok": True, "corte": None}
    try:
        ini, fim = float(corpo.get("ini")), float(corpo.get("fim"))
    except Exception:
        return JSONResponse({"erro": "trecho inválido"}, 400)
    dur = float((c.get("antes_seg") or 0) + (c.get("depois_seg") or 0))
    ini = max(0.0, min(ini, dur))
    fim = max(0.0, min(fim, dur))
    if fim - ini < 3:
        return JSONResponse({"erro": "o clipe ficaria com menos de 3 segundos"}, 400)
    if not marcar_corte(clipe_id, ini, fim):
        return JSONResponse({"erro": "não deu para anotar o corte"}, 500)
    return {"ok": True, "corte": [ini, fim], "duracao": round(fim - ini, 1)}


@app.post("/api/clipe/{clipe_id}/janela")
async def api_clipe_janela(clipe_id: int, request: Request):
    """A fita de corte. Recebe a janela nova e manda o gravador refazer.

    Refazer do arquivo original, e não recortar o mp4 que já está aqui, por
    dois motivos: recortar um recorte recodifica duas vezes e piora a imagem,
    e a partir do original os punhos podem AUMENTAR o trecho, não só encurtar.
    """
    corpo = await request.json()
    try:
        antes = int(round(float(corpo.get("antes"))))
        depois = int(round(float(corpo.get("depois"))))
    except Exception:
        return JSONResponse({"erro": "janela inválida"}, 400)
    dur = antes + depois
    if dur < 3:
        return JSONResponse({"erro": "o clipe ficaria com menos de 3 segundos"}, 400)
    if dur > 140:
        return JSONResponse({"erro": f"{dur}s passa do limite de 140s do X"}, 400)
    if not redefinir_janela(clipe_id, antes, depois):
        return JSONResponse({"erro": "não deu para mudar este clipe"}, 409)
    return {"ok": True, "clipe": _com_legenda(um_clipe(clipe_id) or {})}


@app.post("/api/clipe/{clipe_id}/texto")
async def api_clipe_texto(clipe_id: int, request: Request):
    corpo = await request.json()
    texto_do_clipe(clipe_id, (corpo.get("texto") or "").strip())
    return {"ok": True}


@app.post("/api/clipe/{clipe_id}/publicar")
async def api_clipe_publicar(clipe_id: int, request: Request):
    """Sobe o vídeo e publica. Só a partir de um clique seu."""
    c = um_clipe(clipe_id)
    if not c:
        return JSONResponse({"erro": "clipe não existe"}, 404)
    if c.get("estado") == "publicado":
        return JSONResponse({"erro": "este clipe já foi publicado"}, 409)
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    # A caixa de texto da tela manda o valor atual junto: sem isso, uma edição
    # não salva publicaria a legenda antiga. Já me queimei exatamente assim na
    # guia Posts.
    texto = (corpo.get("texto") or c.get("texto") or "").strip()
    if not texto:
        return JSONResponse({"erro": "sem legenda"}, 400)
    texto_do_clipe(clipe_id, texto)
    dados, erro = _video_pronto(clipe_id, c)
    if erro:
        return JSONResponse({"erro": erro}, 409)
    if not mudar_estado_clipe(clipe_id, c.get("estado") or "pronto", "publicando"):
        return JSONResponse({"erro": "o clipe mudou de estado; recarregue"}, 409)
    try:
        media_id = await x_client.subir_video(dados)
        r = await x_client.publicar(texto, media_ids=[media_id],
                                    publicados_hoje=contar_publicados_hoje())
    except Exception as e:
        erro_no_clipe(clipe_id, f"{type(e).__name__}: {e}")
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"}, 502)
    clipe_publicado(clipe_id, media_id, r.get("id") or "")
    return {"ok": True, "post_id": r.get("id"), "custo": r.get("custo"),
            "url": f"https://x.com/i/status/{r.get('id')}" if r.get("id") else ""}


@app.post("/api/clipe/{clipe_id}/guardar")
async def api_clipe_guardar(clipe_id: int, guardar: int = 1):
    """Salva o clipe para ele não ser descartado, ou desfaz isso."""
    c = um_clipe(clipe_id)
    if not c:
        return JSONResponse({"erro": "clipe não existe"}, 404)
    ok, aviso = guardar_clipe(clipe_id, bool(guardar))
    if not ok:
        return JSONResponse({"erro": aviso or "não deu para salvar"}, 409)
    return {"ok": True, "guardado": bool(guardar), "aviso": aviso}


@app.post("/api/clipe/descartar")
async def api_clipe_descartar():
    """Faz agora a limpeza que o agendador faria sozinho."""
    r = descartar_clipes([l.get("id") for l in listar_lives()],
                         int(ajuste("clipe_horas_descarte")))
    if r.get("erro"):
        return JSONResponse({"erro": r["erro"]}, 500)
    return {"ok": True, "apagados": r["apagados"], "ids": r["ids"]}


@app.get("/api/diag/banco", response_class=PlainTextResponse)
async def api_diag_banco():
    """Diz o que há com o banco — inclusive quando a resposta é "está fora".

    Existe porque quase todas as funções do database.py devolvem lista vazia
    quando dão erro. Isso protege as telas de quebrar, mas apaga a diferença
    entre "não tem clipe" e "não consigo falar com o banco". Hoje a home deu
    500 enquanto a guia Clipes dizia serenamente que não havia nada — as duas
    coisas eram o mesmo banco fora do ar, e só uma delas contou.

    Não imprime a senha: o endereço sai com a credencial trocada por ***.
    """
    import psycopg2
    linhas = []
    url = os.environ.get("DATABASE_URL", "") or os.environ.get("DATABASE_PUBLIC_URL", "")
    if not url:
        return "DATABASE_URL não está configurada no Railway."
    seguro = re.sub(r"//[^@]+@", "//***:***@", url)
    linhas.append(f"endereço : {seguro}")
    ff = _tem_ffmpeg()
    linhas.append(f"ffmpeg   : {ff or 'AUSENTE — a fita de corte não funciona'}")
    if _FALHA_NA_SUBIDA:
        linhas.append("")
        linhas.append("NA ÚLTIMA SUBIDA DO APP (não é agora):")
        for f in _FALHA_NA_SUBIDA:
            linhas.append(f"  {f}")
        linhas.append("")
    t0 = time.time()
    try:
        conn = psycopg2.connect(url, connect_timeout=8)
    except Exception as e:
        linhas.append(f"conexão  : FALHOU depois de {time.time()-t0:.1f}s")
        linhas.append(f"           {type(e).__name__}: {str(e)[:300]}")
        linhas.append("")
        linhas.append("Se fala em 'could not connect' ou 'timeout', o serviço do")
        linhas.append("Postgres está parado ou fora do ar. Se fala em 'no space",)
        linhas.append("left', o disco encheu — e o que enche é a coluna de vídeo.")
        return "\n".join(linhas)
    linhas.append(f"conexão  : ok em {time.time()-t0:.2f}s")
    try:
        c = conn.cursor()
        c.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        linhas.append(f"tamanho  : {c.fetchone()[0]}")
        c.execute("""SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid))
                       FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname = 'public' AND c.relkind = 'r'
                      ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 8""")
        linhas.append("")
        linhas.append("maiores tabelas:")
        for nome, tam in c.fetchall():
            linhas.append(f"  {nome:24} {tam}")
        c.execute("SELECT count(*), COALESCE(sum(tamanho),0) FROM clipe WHERE video IS NOT NULL")
        n, bytes_ = c.fetchone()
        linhas.append("")
        linhas.append(f"clipes com vídeo guardado: {n} "
                      f"({(bytes_ or 0)/1048576:.0f} MB)")
    except Exception as e:
        linhas.append(f"consulta : FALHOU — {type(e).__name__}: {str(e)[:300]}")
    finally:
        conn.close()
    return "\n".join(linhas)


@app.post("/api/diag/liberar-espaco", response_class=PlainTextResponse)
async def api_diag_liberar_espaco(confirmar: str = ""):
    """Tira do banco os VÍDEOS antigos, guardando a lista de clipes.

    Duas etapas, e as duas são necessárias:

      UPDATE video = NULL   marca as linhas antigas como mortas, mas NÃO
                            devolve um byte — o Postgres só marca.
      VACUUM FULL clipe     reescreve a tabela sem os mortos. É este que
                            devolve o espaço, e ele precisa de disco livre
                            para reescrever. Enquanto o volume estava em 99%
                            não havia como rodar; com 5 GB, há.

    A lista de clipes continua na tela. O que some é o mp4 dos antigos, que
    já foram publicados ou baixados. Os novos nem passam mais por aqui.
    """
    if confirmar != "sim":
        return ("Isto apaga o VÍDEO dos clipes antigos que ainda estão dentro\n"
                "do banco. A lista de clipes continua; o que some é o arquivo\n"
                "dos que já foram publicados ou baixados.\n\n"
                "Se é isso mesmo, chame de novo com  ?confirmar=sim")
    import psycopg2
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return "DATABASE_URL não está configurada."
    linhas = []
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
        conn.autocommit = True
        c = conn.cursor()
        c.execute("SELECT pg_size_pretty(pg_database_size(current_database())), "
                  "       pg_size_pretty(pg_total_relation_size('clipe'))")
        antes_bd, antes_tab = c.fetchone()
        linhas.append(f"antes  : banco {antes_bd}, tabela de clipes {antes_tab}")
        c.execute("UPDATE clipe SET video = NULL WHERE video IS NOT NULL")
        linhas.append(f"vídeos : {c.rowcount} apagados")
        c.execute("VACUUM FULL clipe")
        c.execute("SELECT pg_size_pretty(pg_database_size(current_database())), "
                  "       pg_size_pretty(pg_total_relation_size('clipe'))")
        depois_bd, depois_tab = c.fetchone()
        linhas.append(f"depois : banco {depois_bd}, tabela de clipes {depois_tab}")
        conn.close()
    except Exception as e:
        linhas.append(f"FALHOU: {type(e).__name__}: {str(e)[:300]}")
    return "\n".join(linhas)


@app.get("/api/diag/geo-x", response_class=PlainTextResponse)
async def api_diag_geo_x(executar: str = ""):
    """Descobre o formato do geo_restrictions do X. Ver diag_geo_x.py.

    Mora no servidor, e não numa sondagem local, porque as chaves do X vivem
    aqui nas variáveis do Railway — assim ninguém precisa manusear credencial.

    Exige ?executar=sim de propósito: a sondagem gasta créditos (uns US$ 0,04),
    e uma rota que gasta dinheiro não pode disparar porque alguém abriu o link
    sem querer ou porque um pré-carregador do navegador tocou nela.
    """
    if executar != "sim":
        return ("Esta sondagem gasta uns US$ 0,04 em créditos do X.\n"
                "Para rodar de verdade, acrescente  ?executar=sim  na URL.\n\n"
                "Ela sobe um vídeo preto de 4 KB, testa formatos de\n"
                "geo_restrictions e NÃO publica nada.")
    try:
        import diag_geo_x
        return await diag_geo_x.sondar()
    except Exception as e:
        # Relatório de sondagem não pode virar 500 mudo: o erro É o resultado.
        import traceback
        return (f"A sondagem explodiu: {type(e).__name__}: {e}\n\n"
                + traceback.format_exc()[:3000])


@app.get("/api/fim/comparar")
async def api_fim_comparar(fixture: int, fixture_sm: int = 0):
    """Mesmo jogo pelas duas fontes, lado a lado."""
    af = await _montar_fim_de_jogo(fixture)
    saida = {"api_football": af, "sportmonks": None}
    if not sm.configurado():
        saida["sportmonks"] = {"erro": "SPORTMONKS_TOKEN não configurada no Railway"}
        return saida
    alvo = fixture_sm
    if not alvo:
        # Sem o id do lado deles, acho o jogo do dia pelos nomes dos times.
        jogos, err = await sm.do_dia(datetime.now(timezone.utc).date().isoformat())
        alvos = {(af.get("casa") or "").lower(), (af.get("fora") or "").lower()}
        for f in jogos:
            nomes = {sm._nome_curto(p.get("name")).lower()
                     for p in (f.get("participants") or [])}
            if nomes & alvos:
                alvo = f.get("id")
                break
    if not alvo:
        saida["sportmonks"] = {"erro": "não achei esta partida no catálogo da Sportmonks"}
        return saida
    saida["sportmonks"] = await _fim_sportmonks(alvo)
    return saida


@app.get("/api/gols/ao-vivo")
async def api_gols_ao_vivo(horas: int = 6, coletar: int = 1):
    """Gols carimbados pelas duas fontes, com o horário da descoberta.

    Coleta na hora por padrão. O agendador também coleta de 45 em 45s, mas
    depender só dele significa que uma falha silenciosa dele deixa a tela vazia
    sem explicação — e foi o que aconteceu."""
    if coletar:
        try:
            await coletar_gols_ao_vivo()
        except Exception as e:
            _ULTIMA_COLETA["erros"] = [f"coleta: {type(e).__name__}: {e}"]
    try:
        linhas = gols_vistos(horas)
    except Exception as e:
        return {"gols": [], "sportmonks_configurada": sm.configurado(),
                "carimbos_no_banco": 0,
                "diagnostico": {**_ULTIMA_COLETA,
                                "erros": [f"leitura do banco: {type(e).__name__}: {e}"]}}
    # agrupa o MESMO gol das duas fontes para mostrar a diferença de tempo
    por_gol: dict[str, dict] = {}
    for l in linhas:
        # a chave já começa com o fixture de cada fonte; caso pelo resto
        resto = "|".join((l.get("chave_gol") or "").split("|")[1:])
        d = por_gol.setdefault(resto, {"minuto": l.get("minuto"),
                                       "autor": l.get("autor"),
                                       "assistente": l.get("assistente"),
                                       "placar": l.get("placar")})
        d[l["fonte"]] = {"visto_em": l.get("visto_em"), "texto": l.get("texto")}
    saida = []
    for resto, d in por_gol.items():
        a, s = d.get("api_football"), d.get("sportmonks")
        dif = None
        if a and s:
            try:
                ta = datetime.fromisoformat(a["visto_em"])
                ts = datetime.fromisoformat(s["visto_em"])
                dif = round((ts - ta).total_seconds())
            except Exception:
                pass
        saida.append({**{k: v for k, v in d.items()
                         if k not in ("api_football", "sportmonks")},
                      "api_football": a, "sportmonks": s,
                      "diferenca_seg": dif})
    try:
        saida.sort(key=lambda x: ((x.get("api_football") or x.get("sportmonks") or {})
                                  .get("visto_em") or ""), reverse=True)
    except Exception:
        pass
    return {"gols": saida, "sportmonks_configurada": sm.configurado(),
            "diagnostico": _ULTIMA_COLETA, "carimbos_no_banco": len(linhas)}


_CLIPES_CSS = """
body{margin:0;background:var(--c-bg);color:var(--c-text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:18px 16px 80px}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--c-muted-3);font-size:.8rem;margin:0 0 16px}
.titulo-secao{font-size:.6rem;font-weight:800;letter-spacing:.08em;
  text-transform:uppercase;color:var(--c-muted-3);margin:22px 0 9px}

.ponto{width:7px;height:7px;border-radius:50%;background:var(--c-muted-2);flex-shrink:0}
.ponto.ok{background:#B6FF00}
.ponto.alerta{background:#FFBE5D}
.linha-estado{display:flex;align-items:center;gap:7px;font-size:.72rem;
  color:var(--c-muted-4);line-height:1.45}

/* Um cartão por jogo. O botão do gol é o maior elemento do cartão porque é o
   que você aperta com pressa, no celular, olhando a partida. */
.jogo{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:12px;padding:14px;margin-bottom:12px}
.jogo-topo{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px}
.jogo-nome{font-weight:800;font-size:.95rem;line-height:1.35;flex:1;min-width:0}
.jogo-x{background:none;border:none;color:var(--c-muted-2);cursor:pointer;
  font-size:1.1rem;line-height:1;padding:0 2px;flex-shrink:0}
.jogo-x:hover{color:#FD5D5D}
.jogo-acoes{display:flex;gap:9px}
.bt-gol{flex:1;padding:20px 16px;border:none;border-radius:12px;cursor:pointer;
  background:#B6FF00;color:#fff;font-family:inherit;font-size:1rem;
  font-weight:800;letter-spacing:.08em;text-transform:uppercase;line-height:1;
  display:flex;align-items:center;justify-content:center;gap:10px;
  box-shadow:0 3px 12px rgba(22,163,74,.26);
  transition:transform .07s,background .18s,box-shadow .18s}
.bt-gol:hover{background:#B6FF00}
.bt-gol:active{transform:scale(.985)}
.bt-gol.carregando{background:#B6FF00;box-shadow:none;cursor:default}
.bt-gol.pronto{background:#0f766e;box-shadow:none;cursor:default}
.bt-outro{padding:20px 18px;border-radius:12px;cursor:pointer;flex-shrink:0;
  background:transparent;border:1.5px solid var(--c-border-2);color:var(--c-muted-4);
  font-family:inherit;font-weight:800;font-size:.68rem;letter-spacing:.08em;
  text-transform:uppercase;transition:border-color .15s,color .15s}
.bt-outro:hover:not(:disabled){border-color:var(--c-text);color:var(--c-text)}
.bt-outro:disabled,.bt-gol.carregando{cursor:default}
.roda{width:15px;height:15px;border:2.5px solid rgba(255,255,255,.35);
  border-top-color:#fff;border-radius:50%;animation:gira .7s linear infinite;
  display:none;flex-shrink:0}
.bt-gol.carregando .roda{display:block}
@keyframes gira{to{transform:rotate(360deg)}}
.jogo .linha-estado{margin-top:10px}

/* Transmissões do canal que você ainda não pôs para gravar. */
.disp{display:flex;align-items:center;gap:10px;padding:11px 13px;
  border:1px dashed var(--c-border-2);border-radius:10px;margin-bottom:8px}
.disp-nome{flex:1;min-width:0;font-size:.86rem;line-height:1.35}
.disp button{padding:8px 15px;border-radius:99px;flex-shrink:0;
  background:transparent;border:1.5px solid var(--c-border-2);color:var(--c-muted-4);
  font-family:inherit;font-weight:700;font-size:.65rem;text-transform:uppercase;
  letter-spacing:.06em;cursor:pointer}
.disp button:hover:not(:disabled){border-color:#B6FF00;color:#B6FF00}
.disp button:disabled{opacity:.4;cursor:default}

.vazio{text-align:center;padding:36px 20px;color:var(--c-muted-3)}
.vazio p{margin:0;font-size:.8rem;line-height:1.7}

.clipe{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:12px;overflow:hidden;margin-bottom:12px}
.clipe-etiqueta{padding:10px 14px 0;font-weight:800;font-size:.8rem;
  line-height:1.35;color:var(--c-text)}
.clipe-topo{display:flex;align-items:center;gap:9px;padding:9px 14px 11px;flex-wrap:wrap}
.clipe-hora{font-weight:800;font-size:.9rem}
.clipe-jogo{font-size:.72rem;color:var(--c-muted-3);min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:42%}
.selo{font-size:.6rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;
  border:1.5px solid var(--c-border-2);border-radius:99px;padding:3px 9px;
  color:var(--c-muted-4)}
.selo.s-pronto{border-color:#B6FF00;color:#B6FF00}
.selo.s-publicado{border-color:var(--c-text);color:var(--c-text)}
.selo.s-erro{border-color:#FD5D5D;color:#FD5D5D}
.tam{margin-left:auto;font-size:.66rem;color:var(--c-muted-3)}
.clipe video{width:100%;display:block;background:#000;max-height:56vh}
.clipe-corpo{padding:14px}
.clipe textarea{width:100%;min-height:126px;padding:12px 14px;box-sizing:border-box;
  border:1px solid var(--c-border-2);border-radius:10px;background:var(--c-bg-soft);
  color:var(--c-text);font-family:inherit;font-size:.9rem;line-height:1.6;
  resize:vertical}
.clipe textarea:focus{outline:none;border-color:#B6FF00}
.fita-caixa{margin-top:12px}
.fita{position:relative;height:34px;border-radius:8px;background:var(--c-bg-soft);
  border:1px solid var(--c-border-2);touch-action:none;user-select:none}
.fita-sel{position:absolute;top:0;bottom:0;background:rgba(22,163,74,.22);
  border-top:2px solid #B6FF00;border-bottom:2px solid #B6FF00}
.punho{position:absolute;top:-4px;bottom:-4px;width:16px;margin-left:-8px;
  border-radius:5px;background:#B6FF00;cursor:ew-resize;touch-action:none;
  box-shadow:0 1px 4px rgba(0,0,0,.3)}
.punho::after{content:'';position:absolute;left:6px;top:50%;width:4px;height:14px;
  margin-top:-7px;border-left:1px solid rgba(255,255,255,.65);
  border-right:1px solid rgba(255,255,255,.65)}
.fita-info{font-size:.68rem;color:var(--c-muted-3);margin-top:7px;text-align:center}
.fita-info.curto{color:#FD5D5D;font-weight:700}
.fita-acoes{display:flex;gap:8px;margin-top:9px}
.fita-acoes button{flex:1;padding:9px;border-radius:99px;background:transparent;
  border:1.5px solid var(--c-border-2);color:var(--c-muted-4);font-family:inherit;
  font-weight:700;font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;
  cursor:pointer}
.fita-acoes button:hover:not(:disabled){border-color:#B6FF00;color:#B6FF00}
.fita-acoes button:disabled{opacity:.45;cursor:default}
.conta-letras{font-size:.64rem;color:var(--c-muted-3);text-align:right;margin-top:6px}
.conta-letras.demais{color:#FD5D5D;font-weight:700}
.nota{font-size:.72rem;color:var(--c-muted-3);line-height:1.6;margin-top:8px}
.nota.ruim{color:#FD5D5D}
.acoes{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.acoes button{padding:7px 14px;border-radius:99px;background:transparent;
  border:1.5px solid var(--c-border-2);color:var(--c-muted-4);font-family:inherit;
  font-weight:700;font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;
  cursor:pointer}
.acoes button:hover:not(:disabled){border-color:var(--c-text);color:var(--c-text)}
/* O link de baixar é <a>, não <button>, então precisa das mesmas regras. */
.acoes .baixar{padding:7px 14px;border-radius:99px;background:transparent;
  border:1.5px solid var(--c-border-2);color:var(--c-muted-4);font-family:inherit;
  font-weight:700;font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;
  cursor:pointer;text-decoration:none;line-height:1.4}
.acoes .baixar:hover{border-color:var(--c-text);color:var(--c-text)}
.atraso-caixa{margin:14px 0 4px;padding:12px 14px;border-radius:12px;
  background:var(--c-bg-soft);border:1px solid var(--c-border-2)}
.atraso-caixa label{display:block;font-size:.62rem;font-weight:800;
  text-transform:uppercase;letter-spacing:.08em;color:var(--c-muted-3)}
.atraso-linha{display:flex;gap:9px;align-items:center;margin-top:8px;flex-wrap:wrap}
.atraso-linha input{width:78px;padding:7px 10px;border-radius:9px;
  background:var(--surface2);border:1.5px solid var(--c-border-2);
  color:var(--c-text);font-family:inherit;font-size:.95rem;font-weight:700;
  text-align:center}
.atraso-linha span{font-size:.72rem;color:var(--c-muted-3)}
.atraso-linha button{padding:7px 14px;border-radius:99px;background:transparent;
  border:1.5px solid var(--c-border-2);color:var(--c-muted-4);font-family:inherit;
  font-weight:700;font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;
  cursor:pointer}
.atraso-linha button:hover{border-color:var(--c-text);color:var(--c-text)}
.atraso-ok{color:#B6FF00;font-weight:700}
.atraso-nota{margin:9px 0 0;font-size:.7rem;line-height:1.6;color:var(--c-muted-3)}
.acoes .guardar.on{border-color:#FFBE5D;color:#FFBE5D}
.selo.s-guardado{background:#FFBE5D22;color:#FFBE5D}
.acoes .publicar{margin-left:auto;background:#1d9bf0;border-color:#1d9bf0;color:#fff}
.acoes .publicar:hover:not(:disabled){background:#1a8cd8;border-color:#1a8cd8}
.acoes button:disabled{opacity:.45;cursor:default}
.lembrete{padding:11px 13px;border-radius:10px;background:var(--c-bg-soft);
  font-size:.75rem;line-height:1.6;color:var(--c-muted-4)}
.lembrete b{color:var(--c-text)}
.lembrete a{color:#1d9bf0}
"""


_CLIPES_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clipes — IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
__CLIPES_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Clipes</h1>
  <p class="sub">Saiu o lance, aperta o botão do jogo. O clipe chega abaixo.</p>

  <div class="linha-estado" id="estadoGravador">
    <span class="ponto"></span><span>verificando…</span>
  </div>
  <div class="nota ruim" id="erroGravador" style="display:none"></div>

  <p class="atraso-nota" style="margin:0 0 12px">Janela do clipe, atraso da
    transmissão e descarte agora ficam em <a href="/config">Configurações</a>.</p>

  <div id="jogos"></div>

  <div class="titulo-secao" id="tituloDisp" style="display:none">No ar no canal</div>
  <div id="disponiveis"></div>

  <div class="titulo-secao">Clipes</div>
  <p class="atraso-nota" style="margin:0 0 10px">Clipe sem ★ é apagado 2h depois
    que o jogo sai do ar. Para ficar com um, clique em Salvar.</p>
  <div id="lista"></div>
</div>
<script>
__CLIPES_JS__
</script>
</body>
</html>"""


_CLIPES_JS = r'''
const PASSO = __PASSO_AJUSTE__;   // quanto os botões movem a janela

// O X pesa cada ponto de código: latim e pontuação valem 1, todo o resto vale
// 2 — emoji, árabe, e o "𝑮𝑶𝑶…𝑳", que é feito de símbolos matemáticos. Um texto
// de 200 símbolos pode passar de 280 no X. Contar aqui igual ao servidor
// evita descobrir isso só na hora de publicar, com o jogo andando.
function pesoX(t) {
  let n = 0;
  for (const ch of String(t || '')) {
    const c = ch.codePointAt(0);
    const leve = (c <= 4351) || (c >= 8192 && c <= 8205)
              || (c >= 8208 && c <= 8223) || (c >= 8242 && c <= 8247);
    n += leve ? 1 : 2;
  }
  return n;
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let _timer = null;
let _editando = null;     // id do clipe cuja caixa está com o cursor
const _pedindo = {};      // live_id -> travado, para o susto do gol não virar 5 clipes

function hora(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo'});
  } catch (e) { return ''; }
}

function estado(alvo, tipo, texto) {
  if (!alvo) return;
  alvo.innerHTML = '<span class="ponto ' + (tipo || '') + '"></span><span>'
    + esc(texto) + '</span>';
}

// ── jogos ─────────────────────────────────────────────────────────────────

async function pedir(liveId, tipo, botao) {
  if (_pedindo[liveId]) return;
  _pedindo[liveId] = true;
  const original = botao.innerHTML;
  botao.classList.add('carregando');
  const rotulo = botao.querySelector('.rotulo');
  if (rotulo) rotulo.textContent = 'PEDINDO…';
  else botao.textContent = 'PEDINDO…';
  try {
    const r = await fetch('/api/clipe/pedir', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({live_id: liveId, tipo: tipo})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    botao.classList.remove('carregando');
    botao.classList.add('pronto');
    const t = botao.querySelector('.rotulo') || botao;
    t.textContent = hora(d.alvo_em);
    carregar();
  } catch (e) {
    botao.classList.remove('carregando');
    alert('não deu: ' + (e.message || e));
  }
  setTimeout(function () {
    _pedindo[liveId] = false;
    botao.classList.remove('carregando', 'pronto');
    botao.innerHTML = original;
  }, 4000);
}

function cartaoJogo(j, grav) {
  const d = document.createElement('div');
  d.className = 'jogo';
  d.id = 'jogo-' + j.id;

  const topo = document.createElement('div');
  topo.className = 'jogo-topo';
  const nome = document.createElement('div');
  nome.className = 'jogo-nome';
  nome.textContent = j.titulo || j.id;
  const x = document.createElement('button');
  x.className = 'jogo-x';
  x.textContent = '✕';
  x.title = 'parar de gravar este jogo';
  x.onclick = function () { removerJogo(j, x); };
  topo.appendChild(nome);
  topo.appendChild(x);
  d.appendChild(topo);

  const acoes = document.createElement('div');
  acoes.className = 'jogo-acoes';

  const gol = document.createElement('button');
  gol.className = 'bt-gol';
  gol.innerHTML = '<span class="roda"></span><span class="rotulo">GOL</span>';
  gol.onclick = function () { pedir(j.id, 'gol', gol); };

  const outro = document.createElement('button');
  outro.className = 'bt-outro';
  outro.textContent = 'Clipar';
  outro.title = 'para lances que não são gol — a legenda vem em branco';
  outro.onclick = function () { pedir(j.id, 'outro', outro); };

  acoes.appendChild(gol);
  acoes.appendChild(outro);
  d.appendChild(acoes);

  const linha = document.createElement('div');
  linha.className = 'linha-estado';
  d.appendChild(linha);
  const desde = (grav || {})[j.id];
  if (desde) estado(linha, 'ok', 'gravando desde ' + hora(desde));
  else estado(linha, 'alerta', 'ainda não está gravando este jogo');
  return d;
}

async function removerJogo(j, botao) {
  if (!confirm('Parar de gravar "' + (j.titulo || j.id) + '"?')) return;
  botao.disabled = true;
  try {
    const r = await fetch('/api/clipe/lives/' + encodeURIComponent(j.id) + '/remover',
                          {method: 'POST'});
    if (!r.ok) throw new Error((await r.json()).erro || 'HTTP ' + r.status);
    carregar();
  } catch (e) {
    alert('não deu: ' + (e.message || e));
    botao.disabled = false;
  }
}

async function adicionarJogo(id, botao) {
  botao.disabled = true;
  botao.textContent = 'ligando…';
  try {
    const r = await fetch('/api/clipe/lives', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    carregar();
  } catch (e) {
    alert('não deu: ' + (e.message || e));
    botao.disabled = false;
    botao.textContent = 'Gravar';
  }
}

// ── ciclo ─────────────────────────────────────────────────────────────────

function rotulo(e) {
  return {pedido: 'na fila', cortando: 'cortando', pronto: 'pronto',
          publicando: 'publicando', publicado: 'publicado',
          erro: 'erro'}[e] || e;
}

async function carregar() {
  let d;
  try {
    const r = await fetch('/api/clipes?horas=8&_=' + Date.now());
    const bruto = await r.text();
    if (!r.ok) throw new Error('HTTP ' + r.status + ' — ' + bruto.slice(0, 200));
    d = JSON.parse(bruto);
  } catch (e) {
    estado(document.getElementById('estadoGravador'), 'alerta',
           'sem contato com o servidor');
    return;
  }

  const g = d.gravador || {};
  const lives = d.lives || [];
  const grav = g.gravando || {};
  const est = document.getElementById('estadoGravador');
  if (!d.agente_configurado) {
    estado(est, 'alerta', 'falta a variável CLIPE_TOKEN no Railway');
  } else if (!g.online) {
    estado(est, 'alerta', 'gravador desligado — abra o gravador.bat no computador');
  } else if (g.atualizado === false) {
    // Editar o arquivo não muda um processo que já está rodando. Sem este
    // aviso, um gravador antigo entrega clipes com defeitos já corrigidos e
    // nada na tela denuncia — foi o que aconteceu com o áudio adiantado.
    estado(est, 'alerta', 'gravador desatualizado (' + esc(g.versao || 'sem versão')
      + ') — feche e abra o gravador.bat de novo');
  } else {
    const n = Object.keys(grav).length;
    const onde = g.nome ? ' em ' + esc(g.nome) : '';
    estado(est, 'ok', (n ? ('gravando ' + n + (n > 1 ? ' jogos' : ' jogo'))
                         : 'gravador ligado, nenhum jogo gravando') + onde);
  }
  // O último erro da máquina que grava aparece aqui, mesmo quando ela está
  // online. Sem isso, saber o que houve dependia de perguntar a quem está
  // com o computador — e ele pode estar dormindo.
  const cxErro = document.getElementById('erroGravador');
  if (cxErro) {
    cxErro.textContent = g.ultimo_erro || '';
    cxErro.style.display = g.ultimo_erro ? '' : 'none';
  }

  pintarJogos(lives, grav);
  pintarDisponiveis(d.disponiveis || [], lives, d.max || 4, g.online);
  pintarClipes(d.clipes || []);
}

function pintarJogos(lives, grav) {
  const alvo = document.getElementById('jogos');
  if (!alvo) return;
  if (!lives.length) {
    alvo.innerHTML = '<div class="vazio"><p>Nenhum jogo sendo gravado.<br>'
      + 'Escolha abaixo entre as transmissões do canal.</p></div>';
    return;
  }
  const vistos = {};
  lives.forEach(function (j) {
    vistos[j.id] = true;
    const assin = (j.titulo || '') + '|' + ((grav || {})[j.id] || '');
    const atual = document.getElementById('jogo-' + j.id);
    if (atual && atual.dataset.assin === assin) return;
    // Não recrio o cartão enquanto o botão está no meio de um pedido: perderia
    // o "PEDINDO…" e você não saberia se o toque pegou.
    if (atual && _pedindo[j.id]) return;
    const novo = cartaoJogo(j, grav);
    novo.dataset.assin = assin;
    if (atual) { atual.replaceWith(novo); } else { alvo.appendChild(novo); }
  });
  Array.prototype.slice.call(alvo.querySelectorAll('.jogo')).forEach(function (el) {
    if (!vistos[el.id.replace('jogo-', '')]) el.remove();
  });
  const v = alvo.querySelector('.vazio');
  if (v) v.remove();
}

function pintarDisponiveis(disp, lives, max, online) {
  const alvo = document.getElementById('disponiveis');
  const titulo = document.getElementById('tituloDisp');
  if (!alvo || !titulo) return;
  const jaTem = {};
  lives.forEach(function (l) { jaTem[l.id] = true; });
  const livres = disp.filter(function (x) { return !jaTem[x.id]; });
  if (!livres.length) {
    titulo.style.display = 'none';
    alvo.innerHTML = !lives.length && online
      ? '<div class="vazio"><p>O canal não está transmitindo nada agora.</p></div>'
      : '';
    return;
  }
  titulo.style.display = '';
  alvo.innerHTML = '';
  const cheio = lives.length >= max;
  livres.forEach(function (x) {
    const d = document.createElement('div');
    d.className = 'disp';
    const n = document.createElement('div');
    n.className = 'disp-nome';
    n.textContent = x.titulo || x.id;
    const b = document.createElement('button');
    b.textContent = 'Gravar';
    b.disabled = cheio;
    if (cheio) b.title = 'já são ' + max + ' jogos, o máximo';
    b.onclick = function () { adicionarJogo(x.id, b); };
    d.appendChild(n);
    d.appendChild(b);
    alvo.appendChild(d);
  });
}

function pintarClipes(clipes) {
  const alvo = document.getElementById('lista');
  if (!alvo) return;
  if (!clipes.length) {
    if (!alvo.querySelector('.vazio')) {
      alvo.innerHTML = '<div class="vazio"><p>Nenhum clipe ainda.</p></div>';
    }
    return;
  }
  const v = alvo.querySelector('.vazio');
  if (v) v.remove();

  // Redesenhar tudo apagaria o que você digita e o ponto do vídeo. Só recrio
  // o card que MUDOU, e nunca o que está com o cursor dentro.
  const vistos = {};
  clipes.forEach(function (c) {
    vistos[c.id] = true;
    const card = document.getElementById('clipe-' + c.id);
    const assin = c.estado + '|' + (c.tamanho || 0) + '|' + (c.post_id || '');
    if (card && card.dataset.assin === assin) return;
    if (card && _editando === c.id) return;
    const novo = montar(c, assin);
    if (card) { card.replaceWith(novo); } else { alvo.prepend(novo); }
  });
  Array.prototype.slice.call(alvo.querySelectorAll('.clipe')).forEach(function (el) {
    if (!vistos[el.dataset.id]) el.remove();
  });

  // Reordeno para bater com a lista do servidor, que já vem do mais novo para
  // o mais velho. Sem isto, o prepend percorrendo essa lista invertia tudo: o
  // 7 entrava, o 6 entrava na frente dele, o 5 na frente do 6 — e o clipe mais
  // velho terminava no topo, que é o contrário do que serve.
  clipes.forEach(function (c) {
    const el = document.getElementById('clipe-' + c.id);
    if (el) alvo.appendChild(el);
  });
}

function montar(c, assin) {
  const d = document.createElement('div');
  d.className = 'clipe';
  d.id = 'clipe-' + c.id;
  d.dataset.id = c.id;
  d.dataset.assin = assin;

  // O jogo vai numa linha só dele, acima e em destaque: com quatro partidas
  // ao mesmo tempo, saber de qual é o clipe importa mais que a hora dele.
  if (c.jogo) {
    const et = document.createElement('div');
    et.className = 'clipe-etiqueta';
    et.textContent = c.jogo;
    d.appendChild(et);
  }
  const topo = document.createElement('div');
  topo.className = 'clipe-topo';
  topo.innerHTML = '<span class="clipe-hora">' + esc(hora(c.alvo_em)) + '</span>'
    + '<span class="selo s-' + esc(c.estado) + '">' + esc(rotulo(c.estado)) + '</span>'
    + (c.tipo === 'outro' ? '<span class="selo">lance</span>' : '')
    + (c.guardado ? '<span class="selo s-guardado">★ salvo</span>' : '')
    + (c.tamanho ? '<span class="tam">' + (c.tamanho / 1048576).toFixed(1) + ' MB</span>' : '');
  d.appendChild(topo);

  const corpo = document.createElement('div');
  corpo.className = 'clipe-corpo';

  if (c.estado === 'pedido' || c.estado === 'cortando') {
    corpo.innerHTML = '<div class="nota">O gravador pega este pedido em alguns '
      + 'segundos. Se ficar parado aqui, confira se a janela do gravador está '
      + 'aberta no computador.</div>';
    d.appendChild(corpo);
    return d;
  }

  if (c.estado === 'erro') {
    corpo.innerHTML = '<div class="nota ruim">' + esc(c.erro || 'deu erro e ninguém explicou') + '</div>';
    corpo.appendChild(botoesAjuste(c));
    d.appendChild(corpo);
    return d;
  }

  if (c.estado === 'publicado') {
    const l = document.createElement('div');
    l.className = 'lembrete';
    l.innerHTML = '<b>Falta o geoblock.</b> Abra o Media Studio, ache este vídeo '
      + 'e marque Content Restrictions → Include → Brasil.'
      + (c.post_id ? ' · <a href="https://x.com/i/status/'
          + encodeURIComponent(c.post_id) + '">ver o post</a>' : '');
    corpo.appendChild(l);
    const ap = document.createElement('div');
    ap.className = 'acoes';
    ap.appendChild(botaoBaixar(c));
    ap.appendChild(botaoGuardar(c));
    corpo.appendChild(ap);
    d.appendChild(corpo);
    return d;
  }

  const v = document.createElement('video');
  v.controls = true;
  v.preload = 'metadata';
  v.playsInline = true;
  v.src = '/api/clipe/' + c.id + '/video';
  d.appendChild(v);

  const t = document.createElement('textarea');
  t.value = c.texto || '';
  t.placeholder = c.tipo === 'outro'
    ? 'Escreva a legenda deste lance.'
    : 'Sem alerta de gol ainda — escreva ou espere alguns segundos.';
  const conta = document.createElement('div');
  conta.className = 'conta-letras';
  function atualizaConta() {
    const n = pesoX(t.value);
    conta.textContent = n + ' / 280';
    conta.classList.toggle('demais', n > 280);
  }
  t.oninput = atualizaConta;
  t.onfocus = function () { _editando = c.id; };
  t.onblur = function () {
    _editando = null;
    fetch('/api/clipe/' + c.id + '/texto', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: t.value})
    }).catch(function () {});
  };
  corpo.appendChild(t);
  corpo.appendChild(conta);
  atualizaConta();

  if (c.texto_sugerido) {
    const n = document.createElement('div');
    n.className = 'nota';
    n.textContent = 'Legenda do alerta de gol da API-Football. Edite à vontade.';
    corpo.appendChild(n);
  }

  corpo.appendChild(fitaDeCorte(c, v));

  const acoes = botoesAjuste(c);
  const pub = document.createElement('button');
  pub.className = 'publicar';
  pub.textContent = c.estado === 'publicando' ? 'publicando…' : 'Publicar no X';
  pub.disabled = c.estado === 'publicando';
  pub.onclick = function () { publicar(c.id, t, pub); };
  acoes.appendChild(botaoBaixar(c));
  acoes.appendChild(botaoGuardar(c));
  acoes.appendChild(pub);
  corpo.appendChild(acoes);
  d.appendChild(corpo);
  return d;
}

function fitaDeCorte(c, video) {
  // A fita mostra o clipe que existe. Arrastar os punhos NÃO recorta nada
  // aqui: a prévia é o próprio player tocando só o trecho escolhido, o que é
  // instantâneo e não gasta processamento. Só ao aplicar o gravador refaz o
  // corte, e refaz do arquivo original — recortar um recorte recodificaria
  // duas vezes e a imagem pioraria.
  const cx = document.createElement('div');
  cx.className = 'fita-caixa';

  const dur = (c.antes_seg || 20) + (c.depois_seg || 0);
  let ini = (c.corte_ini === null || c.corte_ini === undefined) ? 0 : c.corte_ini;
  let fim = (c.corte_fim === null || c.corte_fim === undefined) ? dur : c.corte_fim;

  const barra = document.createElement('div');
  barra.className = 'fita';
  const sel = document.createElement('div');
  sel.className = 'fita-sel';
  const pIni = document.createElement('div');
  pIni.className = 'punho punho-ini';
  const pFim = document.createElement('div');
  pFim.className = 'punho punho-fim';
  barra.appendChild(sel);
  barra.appendChild(pIni);
  barra.appendChild(pFim);
  cx.appendChild(barra);

  const info = document.createElement('div');
  info.className = 'fita-info';
  cx.appendChild(info);
  let marca = '';

  // Salva sozinho quando você solta o punho. Não recorta nada: só anota o
  // trecho, e o corte de verdade acontece no servidor na hora de publicar ou
  // baixar. É isso que faz a fita responder na hora.
  let _salvando = null;
  function salvarCorte() {
    clearTimeout(_salvando);
    _salvando = setTimeout(function () {
      const inteiro = ini <= 0.5 && (dur - fim) <= 0.5;
      marca = 'salvando…';
      pintar();
      fetch('/api/clipe/' + c.id + '/corte', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(inteiro ? {ini: null, fim: null} : {ini: ini, fim: fim})
      }).then(function (r) { return r.json().then(function (j) { return {r: r, j: j}; }); })
        .then(function (x) {
          if (!x.r.ok) throw new Error(x.j.erro || ('HTTP ' + x.r.status));
          // Atualizo o clipe em memória para a tela não voltar o punho no
          // próximo ciclo de recarga.
          c.corte_ini = inteiro ? null : ini;
          c.corte_fim = inteiro ? null : fim;
          marca = inteiro ? 'clipe inteiro' : 'pronto para publicar';
          pintar();
        })
        .catch(function (e) { marca = 'não salvou: ' + (e.message || e); pintar(); });
    }, 350);
  }

  function pintar() {
    const a = (ini / dur) * 100, b = (fim / dur) * 100;
    sel.style.left = a + '%';
    sel.style.width = (b - a) + '%';
    pIni.style.left = a + '%';
    pFim.style.left = b + '%';
    const d = fim - ini;
    info.textContent = d.toFixed(1) + 's  ·  do segundo ' + ini.toFixed(1)
      + ' ao ' + fim.toFixed(1) + (marca ? '  ·  ' + marca : '');
    info.classList.toggle('curto', d < 3);
  }
  pintar();

  // Prévia: o player só toca o trecho escolhido.
  video.addEventListener('timeupdate', function () {
    if (video.currentTime > fim + 0.05) { video.currentTime = ini; video.pause(); }
    if (video.currentTime < ini - 0.05) video.currentTime = ini;
  });

  function arrastar(punho, qual) {
    punho.addEventListener('pointerdown', function (ev) {
      ev.preventDefault();
      punho.setPointerCapture(ev.pointerId);
      const mover = function (e) {
        const r = barra.getBoundingClientRect();
        let t = ((e.clientX - r.left) / r.width) * dur;
        t = Math.max(0, Math.min(dur, t));
        // Os punhos não se cruzam, e sobra sempre 1s entre eles: fita de
        // largura zero não dá para agarrar de volta.
        if (qual === 'ini') ini = Math.min(t, fim - 1);
        else fim = Math.max(t, ini + 1);
        pintar();
        video.currentTime = (qual === 'ini') ? ini : Math.max(ini, fim - 0.3);
      };
      const soltar = function (e) {
        punho.releasePointerCapture(ev.pointerId);
        window.removeEventListener('pointermove', mover);
        window.removeEventListener('pointerup', soltar);
        salvarCorte();
      };
      window.addEventListener('pointermove', mover);
      window.addEventListener('pointerup', soltar);
    });
  }
  arrastar(pIni, 'ini');
  arrastar(pFim, 'fim');

  const acoes = document.createElement('div');
  acoes.className = 'fita-acoes';
  const inteiro = document.createElement('button');
  inteiro.textContent = 'Clipe inteiro';
  inteiro.title = 'desfaz o corte';
  inteiro.onclick = function () {
    ini = 0; fim = dur; pintar(); video.currentTime = 0; salvarCorte();
  };
  acoes.appendChild(inteiro);
  cx.appendChild(acoes);
  return cx;
}

function botaoBaixar(c) {
  // <a download> em vez de fetch + blob: o navegador cuida do arquivo sozinho,
  // e no celular isso é o que faz o vídeo cair na galeria em vez de ficar
  // preso numa aba. O nome do arquivo quem decide é o servidor, pelo
  // Content-Disposition, para não haver dois lugares inventando nome.
  const a = document.createElement('a');
  a.className = 'baixar';
  a.textContent = '⬇ Baixar';
  a.href = '/api/clipe/' + c.id + '/video?baixar=1';
  a.setAttribute('download', '');
  a.title = 'salva o mp4 no aparelho';
  return a;
}

function botaoGuardar(c) {
  const b = document.createElement('button');
  b.className = 'guardar' + (c.guardado ? ' on' : '');
  b.textContent = c.guardado ? '★ Salvo' : '☆ Salvar';
  b.title = c.guardado
    ? 'este fica; clique para soltar e deixar que ele seja descartado'
    : 'sem isto ele some 2h depois que o jogo sair do ar';
  b.onclick = function () { guardar(c.id, !c.guardado, b); };
  return b;
}

async function guardar(id, ligar, botao) {
  botao.disabled = true;
  try {
    const r = await fetch('/api/clipe/' + id + '/guardar?guardar=' + (ligar ? 1 : 0),
                          {method: 'POST'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    if (d.aviso) alert(d.aviso);
    carregar();
  } catch (e) {
    alert('não deu para salvar: ' + (e.message || e));
    botao.disabled = false;
  }
}

function botoesAjuste(c) {
  const a = document.createElement('div');
  a.className = 'acoes';
  [['◀ ' + PASSO + 's antes', -PASSO], [PASSO + 's depois ▶', PASSO]].forEach(function (par) {
    const b = document.createElement('button');
    b.textContent = par[0];
    b.title = 'move a janela do corte e o gravador refaz';
    b.onclick = function () { ajustar(c.id, par[1], b); };
    a.appendChild(b);
  });
  return a;
}

async function ajustar(id, delta, botao) {
  botao.disabled = true;
  try {
    const r = await fetch('/api/clipe/' + id + '/ajustar?delta=' + delta, {method: 'POST'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    carregar();
  } catch (e) {
    alert('não deu para ajustar: ' + (e.message || e));
    botao.disabled = false;
  }
}

async function publicar(id, caixa, botao) {
  const texto = (caixa.value || '').trim();
  if (!texto) { alert('escreva a legenda antes'); return; }
  const peso = pesoX(texto);
  if (peso > 280) { alert('o texto ocupa ' + peso + ' dos 280 caracteres do X '
    + '(o \u{1D46E}\u{1D476}\u{1D476}\u2026\u{1D473} e os emoji contam dois cada)'); return; }
  if (!confirm('Publicar no X?\n\n' + texto)) return;
  botao.disabled = true;
  botao.textContent = 'publicando…';
  try {
    // Mando o texto da CAIXA, não o salvo: uma edição sem sair do campo ainda
    // não foi para o banco. Foi assim que a guia Posts publicou a versão velha.
    const r = await fetch('/api/clipe/' + id + '/publicar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: texto})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
    carregar();
  } catch (e) {
    alert('não publicou: ' + (e.message || e));
    botao.disabled = false;
    botao.textContent = 'Publicar no X';
    carregar();
  }
}

function ciclo() {
  carregar().catch(function (err) {
    estado(document.getElementById('estadoGravador'), 'alerta',
           'erro: ' + (err && err.message ? err.message : String(err)));
  });
  clearTimeout(_timer);
  _timer = setTimeout(ciclo, 5000);
}
ciclo();
'''


_CONFIG_CSS = """
body{background:var(--c-bg);color:var(--c-text);font-family:'Inter',system-ui,
  -apple-system,'Segoe UI',sans-serif;margin:0}
.wrap{max-width:760px;margin:0 auto;padding:20px 16px 70px}
h1{font-family:'Bebas Neue',sans-serif;font-size:2rem;letter-spacing:.02em;
  margin:0 0 4px}
.sub{color:var(--c-muted-3);font-size:.8rem;line-height:1.6;margin:0 0 22px}
.grupo{font-family:'Bebas Neue',sans-serif;font-size:1.15rem;letter-spacing:.04em;
  color:var(--c-muted-4);margin:26px 0 10px;padding-bottom:6px;
  border-bottom:1px solid var(--c-border-2)}
.item{padding:14px 0;border-bottom:1px solid var(--c-border-2)}
.item:last-child{border-bottom:none}
.linha{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.rotulo{font-weight:700;font-size:.9rem;flex:1;min-width:180px}
.campo{display:flex;gap:7px;align-items:center}
.campo input,.campo select{width:96px;padding:8px 10px;border-radius:9px;
  background:var(--surface2);border:1.5px solid var(--c-border-2);
  color:var(--c-text);font-family:inherit;font-size:.95rem;font-weight:700;
  text-align:center}
.campo select{width:132px}
.campo .un{font-size:.75rem;color:var(--c-muted-3)}
.ajuda{margin:8px 0 0;font-size:.75rem;line-height:1.65;color:var(--c-muted-3)}
.estado{font-size:.68rem;font-weight:800;text-transform:uppercase;
  letter-spacing:.06em;min-height:14px;margin-top:6px}
.estado.ok{color:#B6FF00}
.estado.ruim{color:#FD5D5D}
.padrao{font-size:.68rem;color:var(--c-muted-3);background:none;border:none;
  cursor:pointer;text-decoration:underline;padding:0;font-family:inherit}
.mudado{font-size:.6rem;font-weight:800;text-transform:uppercase;
  letter-spacing:.05em;color:#FFBE5D;border:1px solid #FFBE5D;border-radius:99px;
  padding:2px 7px;margin-left:6px}
"""

_CONFIG_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Configuracoes - IARABAO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
__CONFIG_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Configura&ccedil;&otilde;es</h1>
  <p class="sub">Os n&uacute;meros que d&aacute; para mexer sem tocar em c&oacute;digo.
    Valem na hora: o app usa no clipe seguinte, e a m&aacute;quina que grava pega
    na pr&oacute;xima consulta.</p>
  <div id="lista">carregando...</div>

  <div class="grupo">Jogadores</div>
  <div id="elenco">carregando...</div>

  <div class="grupo">Convidar</div>
  <div id="convites">carregando...</div>

  <div class="grupo">Quem entra</div>
  <div id="contas">carregando...</div>
</div>
<script>
__CONFIG_JS__
</script>
</body>
</html>"""

_CONFIG_JS = r"""
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function carregar() {
  const alvo = document.getElementById('lista');
  let d;
  try {
    const r = await fetch('/api/ajustes?_=' + Date.now());
    d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
  } catch (e) {
    alvo.innerHTML = '<p class="ajuda" style="color:#FD5D5D">Nao consegui ler os '
      + 'ajustes: ' + esc(e.message || String(e)) + '</p>';
    return;
  }
  alvo.innerHTML = '';
  (d.grupos || []).forEach(function (g) {
    const t = document.createElement('div');
    t.className = 'grupo';
    t.textContent = g;
    alvo.appendChild(t);
    (d.ajustes || []).filter(function (a) { return a.grupo === g; })
      .forEach(function (a) { alvo.appendChild(cartao(a)); });
  });
}

function cartao(a) {
  const d = document.createElement('div');
  d.className = 'item';

  const linha = document.createElement('div');
  linha.className = 'linha';
  const rot = document.createElement('div');
  rot.className = 'rotulo';
  rot.textContent = a.rotulo;
  if (!a.no_padrao) {
    const m = document.createElement('span');
    m.className = 'mudado';
    m.textContent = 'mudado';
    m.title = 'o padrao e ' + a.padrao;
    rot.appendChild(m);
  }
  linha.appendChild(rot);

  const campo = document.createElement('div');
  campo.className = 'campo';
  let entrada;
  if (a.tipo === 'escolha') {
    entrada = document.createElement('select');
    (a.opcoes || []).forEach(function (o) {
      const op = document.createElement('option');
      op.value = o;
      op.textContent = o;
      if (o === a.valor) op.selected = true;
      entrada.appendChild(op);
    });
  } else {
    entrada = document.createElement('input');
    entrada.type = 'number';
    entrada.min = a.min;
    entrada.max = a.max;
    entrada.step = 1;
    entrada.inputMode = 'numeric';
    entrada.value = a.valor;
  }
  campo.appendChild(entrada);
  if (a.unidade) {
    const un = document.createElement('span');
    un.className = 'un';
    un.textContent = a.unidade;
    campo.appendChild(un);
  }
  linha.appendChild(campo);
  d.appendChild(linha);

  const ajuda = document.createElement('p');
  ajuda.className = 'ajuda';
  ajuda.textContent = a.ajuda;
  d.appendChild(ajuda);

  const estado = document.createElement('div');
  estado.className = 'estado';
  d.appendChild(estado);

  const voltar = document.createElement('button');
  voltar.className = 'padrao';
  voltar.textContent = 'voltar ao padrao (' + a.padrao + ')';
  voltar.onclick = function () { salvar(a, entrada, estado, true); };
  d.appendChild(voltar);

  // Salva ao sair do campo, e nao a cada tecla: digitar "1" no caminho de
  // "12" gravaria um valor que voce nunca quis.
  entrada.onchange = function () { salvar(a, entrada, estado, false); };
  entrada.onblur = function () { salvar(a, entrada, estado, false); };
  return d;
}

async function salvar(a, entrada, estado, padrao) {
  const valor = padrao ? a.padrao : entrada.value;
  if (!padrao && String(valor) === String(a.valor)) return;
  estado.className = 'estado';
  estado.textContent = 'salvando...';
  try {
    const r = await fetch('/api/ajustes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({chave: a.chave, valor: valor, padrao: padrao})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
    a.valor = j.valor;
    entrada.value = j.valor;
    estado.className = 'estado ok';
    estado.textContent = 'salvo';
    setTimeout(carregar, 1200);
  } catch (e) {
    estado.className = 'estado ruim';
    estado.textContent = e.message || String(e);
    entrada.value = a.valor;
  }
}

carregar();
carregarContas();
carregarConvites();
carregarElenco();

async function carregarContas() {
  const alvo = document.getElementById('contas');
  if (!alvo) return;
  let d;
  try {
    const r = await fetch('/api/usuarios');
    d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
  } catch (e) {
    alvo.innerHTML = '<p class="ajuda" style="color:#FD5D5D">' + esc(e.message) + '</p>';
    return;
  }
  alvo.innerHTML = '';

  if (!(d.liberados || []).length) {
    const av = document.createElement('p');
    av.className = 'ajuda';
    av.style.color = 'var(--c-alerta)';
    av.textContent = 'Ninguem esta liberado a criar conta. Configure '
      + 'EMAILS_LIBERADOS no Railway, com os e-mails separados por virgula. '
      + 'Enquanto isso o app fica aberto, sem pedir senha.';
    alvo.appendChild(av);
  } else {
    const l = document.createElement('p');
    l.className = 'ajuda';
    l.textContent = 'Liberados a criar conta: ' + d.liberados.join(', ');
    alvo.appendChild(l);
  }

  if (!d.sessao_fixa) {
    const av = document.createElement('p');
    av.className = 'ajuda';
    av.style.color = 'var(--c-alerta)';
    av.textContent = 'SESSAO_SECRETA nao esta configurada no Railway. Sem ela, '
      + 'todo mundo e deslogado a cada reinicio do app, porque a chave que '
      + 'assina a sessao muda junto. Ponha qualquer texto longo e aleatorio.';
    alvo.appendChild(av);
  }

  (d.usuarios || []).forEach(function (u) {
    const item = document.createElement('div');
    item.className = 'item';
    const linha = document.createElement('div');
    linha.className = 'linha';
    const rot = document.createElement('div');
    rot.className = 'rotulo';
    rot.textContent = (u.nome || u.email);
    if (u.temporaria) {
      const m = document.createElement('span');
      m.className = 'mudado';
      m.textContent = 'senha temporaria';
      rot.appendChild(m);
    }
    linha.appendChild(rot);
    // O papel fica ao lado do nome porque e a informacao que decide o que
    // essa pessoa alcanca. Escondida num submenu, ninguem confere.
    const sel = document.createElement('select');
    sel.className = 'padrao';
    [['adm','Administrador'],['gerente','Gerente'],['leitor','Leitor']]
      .forEach(function (par) {
        const o = document.createElement('option');
        o.value = par[0]; o.textContent = par[1];
        if ((u.papel || 'leitor') === par[0]) o.selected = true;
        sel.appendChild(o);
      });
    sel.onchange = function () { trocarPapel(u.email, sel); };
    linha.appendChild(sel);
    const b = document.createElement('button');
    b.className = 'padrao';
    b.textContent = 'gerar senha temporaria';
    b.onclick = function () { gerarSenha(u.email, item); };
    linha.appendChild(b);
    item.appendChild(linha);
    const a = document.createElement('p');
    a.className = 'ajuda';
    a.textContent = u.email + (u.ultimo_acesso
      ? ' - ultimo acesso ' + new Date(u.ultimo_acesso).toLocaleString('pt-BR')
      : ' - nunca entrou');
    item.appendChild(a);
    alvo.appendChild(item);
  });

  if (!(d.usuarios || []).length) {
    const p = document.createElement('p');
    p.className = 'ajuda';
    p.textContent = 'Nenhuma conta criada ainda. Enquanto for assim, o app '
      + 'continua aberto, sem pedir senha.';
    alvo.appendChild(p);
  }
}

async function trocarPapel(email, sel) {
  const antes = sel.dataset.antes || sel.value;
  try {
    const r = await fetch('/api/usuarios/papel', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: email, papel: sel.value})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
    sel.dataset.antes = sel.value;
  } catch (e) {
    // Volta ao que era. Um seletor que mostra um papel e guardou outro e a
    // pior forma de errar aqui: parece certo na tela e esta errado no banco.
    sel.value = antes;
    alert('nao deu: ' + (e.message || e));
  }
}

async function gerarSenha(email, onde) {
  if (!confirm('Gerar uma senha temporaria para ' + email + '?\n\n'
             + 'A senha atual dele para de funcionar na hora.')) return;
  try {
    const r = await fetch('/api/usuarios/senha-temporaria', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: email})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
    // A senha aparece UMA VEZ. Nao fica guardada em texto em lugar nenhum:
    // o que foi para o banco ja e o hash.
    const cx = document.createElement('p');
    cx.className = 'ajuda';
    cx.style.color = 'var(--c-acento)';
    cx.textContent = 'Senha temporaria: ' + j.senha
      + '   (anote agora, ela nao aparece de novo)';
    onde.appendChild(cx);
  } catch (e) {
    alert('nao deu: ' + (e.message || e));
  }
}

// ── Convites ──────────────────────────────────────────────────────────────
// O codigo aparece UMA vez, aqui, e nunca mais. O banco guarda so o resumo,
// entao nem eu consigo recuperar um convite ja criado. Perdeu, gera outro.
const PAPEL_AJUDA = {
  gerente: 'Faz tudo que voce faz, menos Configuracoes e contas.',
  leitor: 'Ve as guias. Nao entra na tela inicial de aprovacao e nao aprova, '
        + 'publica nem manda gerar relatorio.'
};

async function carregarConvites() {
  const alvo = document.getElementById('convites');
  if (!alvo) return;
  let d;
  try {
    const r = await fetch('/api/convites');
    d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
  } catch (e) {
    alvo.innerHTML = '<p class="ajuda" style="color:#FD5D5D">' + esc(e.message) + '</p>';
    return;
  }
  alvo.innerHTML = '';

  (d.papeis || []).forEach(function (p) {
    const item = document.createElement('div');
    item.className = 'item';
    const linha = document.createElement('div');
    linha.className = 'linha';
    const rot = document.createElement('div');
    rot.className = 'rotulo';
    rot.textContent = p.rotulo;
    linha.appendChild(rot);
    const b = document.createElement('button');
    b.className = 'padrao';
    b.textContent = 'gerar convite';
    b.onclick = function () { gerarConvite(p.chave, item, b); };
    linha.appendChild(b);
    item.appendChild(linha);
    const a = document.createElement('p');
    a.className = 'ajuda';
    a.textContent = PAPEL_AJUDA[p.chave] || '';
    item.appendChild(a);
    alvo.appendChild(item);
  });

  const usados = (d.convites || []).filter(function (c) { return c.usado_em; }).length;
  const abertos = (d.convites || []).length - usados;
  const resumo = document.createElement('p');
  resumo.className = 'ajuda';
  resumo.textContent = abertos + ' convite(s) esperando alguem, ' + usados
    + ' ja usado(s). Cada um serve uma vez so e vence em 7 dias.';
  alvo.appendChild(resumo);
}

async function gerarConvite(papel, onde, botao) {
  botao.disabled = true;
  try {
    const r = await fetch('/api/convites', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({papel: papel})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
    const link = location.origin + j.link;
    const cx = document.createElement('p');
    cx.className = 'ajuda';
    cx.style.color = 'var(--c-acento)';
    cx.style.wordBreak = 'break-all';
    cx.textContent = link + '   (vale ' + j.dias + ' dias, uma pessoa so — '
                   + 'copie agora, nao aparece de novo)';
    onde.appendChild(cx);
    const copiar = document.createElement('button');
    copiar.className = 'padrao';
    copiar.textContent = 'copiar link';
    copiar.onclick = function () {
      navigator.clipboard.writeText(link).then(function () {
        copiar.textContent = 'copiado';
        setTimeout(function () { copiar.textContent = 'copiar link'; }, 1500);
      });
    };
    onde.appendChild(copiar);
  } catch (e) {
    alert('nao deu: ' + (e.message || e));
  }
  botao.disabled = false;
}

// ── Quem joga na liga ─────────────────────────────────────────────────────
// A varredura le a escalacao de cada partida ja disputada nos dois idiomas.
// Sao ~600 requisicoes numa API aberta, entao ela nao roda sozinha em toda
// subida: roda no agendamento semanal, ou aqui quando voce mandar.
async function carregarElenco() {
  const alvo = document.getElementById('elenco');
  if (!alvo) return;
  let d;
  try {
    const r = await fetch('/api/jogadores?limite=1');
    d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
  } catch (e) {
    alvo.innerHTML = '<p class="ajuda" style="color:#FD5D5D">' + esc(e.message) + '</p>';
    return;
  }
  const n = d.resumo || {};
  alvo.innerHTML = '';

  const item = document.createElement('div');
  item.className = 'item';
  const linha = document.createElement('div');
  linha.className = 'linha';
  const rot = document.createElement('div');
  rot.className = 'rotulo';
  rot.textContent = (n.total || 0) + ' jogador(es) em ' + (n.clubes || 0) + ' clube(s)';
  linha.appendChild(rot);

  const curto = document.createElement('button');
  curto.className = 'padrao';
  curto.textContent = 'varrer 5 jogos';
  curto.onclick = function () { varrer(5, item, curto); };
  linha.appendChild(curto);

  const tudo = document.createElement('button');
  tudo.className = 'padrao';
  tudo.textContent = 'varrer a temporada';
  tudo.onclick = function () {
    if (!confirm('Isso le a escalacao de TODAS as partidas ja disputadas, em '
               + 'dois idiomas. Sao centenas de requisicoes e leva alguns '
               + 'minutos. Seguir?')) return;
    varrer(0, item, tudo);
  };
  linha.appendChild(tudo);
  item.appendChild(linha);

  const a = document.createElement('p');
  a.className = 'ajuda';
  a.textContent = (n.com_arabe || 0) + ' com nome em arabe, '
    + (n.com_foto || 0) + ' com foto, '
    + (n.com_transfermarkt || 0) + ' com id do Transfermarkt. '
    + 'O nome nas duas escritas vem da propria liga, com o mesmo id — '
    + 'e a ponte que vai casar a noticia arabe com o jogador.';
  item.appendChild(a);
  alvo.appendChild(item);
}

async function varrer(jogos, onde, botao) {
  const antes = botao.textContent;
  botao.disabled = true;
  botao.textContent = 'varrendo...';
  try {
    const r = await fetch('/api/jogadores/varrer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({jogos: jogos})
    });
    const j = await r.json();
    if (!r.ok || j.erro) throw new Error(j.erro || ('HTTP ' + r.status));
    const p = document.createElement('p');
    p.className = 'ajuda';
    p.style.color = 'var(--c-acento)';
    p.textContent = j.jogos_lidos + ' jogo(s) lido(s), ' + j.pessoas
      + ' pessoa(s), ' + j.novos + ' nova(s) e ' + j.atualizados + ' atualizada(s).';
    onde.appendChild(p);
    setTimeout(carregarElenco, 1200);
  } catch (e) {
    alert('nao deu: ' + (e.message || e));
  }
  botao.disabled = false;
  botao.textContent = antes;
}
"""


# ══════════════════════════════════════════════════════════════════════════
# ENTRAR
#
# O app fica aberto enquanto não existir NENHUMA conta. Assim que a primeira
# nasce, ele passa a pedir senha. É o que impede eu te trancar do lado de fora
# no meio de uma reforma: a porta só fecha quando alguém já tem a chave.
#
# Quem pode criar conta: só os e-mails de EMAILS_LIBERADOS. Sem essa variável,
# ninguém cria. Este app decide o que sai no seu X — cadastro livre aqui seria
# deixar a chave na fechadura.

# Caminhos que continuam abertos mesmo com login ligado.
#
# /api/clipe/ e /api/gravador/ ficam de fora porque quem fala neles é o
# programa na máquina de quem grava, e ele se identifica com o token do
# agente, não com cookie de navegador. Exigir sessão ali derrubaria a
# gravação — e o pior é que derrubaria em silêncio, no meio de um jogo.
LIVRES = ("/entrar", "/cadastrar", "/api/entrar", "/api/cadastrar",
          "/api/clipe/", "/api/gravador/", "/api/diag/", "/manifest",
          "/static", "/favicon", "/sw.js", "/api/token-status")


def _quem_esta_logado(request: Request) -> str:
    return contas.ler_sessao(request.cookies.get(contas.COOKIE, ""))


def _papel_de_quem_pede(request: Request) -> str:
    email = _quem_esta_logado(request)
    return papel_do_usuario(email) if email else ""


@app.middleware("http")
async def exigir_login(request: Request, call_next):
    caminho = request.url.path
    if any(caminho.startswith(p) for p in LIVRES) or not _login_ligado():
        return await call_next(request)
    email = _quem_esta_logado(request)
    if not email:
        if caminho.startswith("/api/"):
            return JSONResponse({"erro": "não autenticado"}, 401)
        return RedirectResponse("/entrar")

    # A permissão é conferida AQUI, no meio do caminho, e não em cada rota.
    # Rota nova entra no app já protegida; se dependesse de eu lembrar de pôr
    # o decorador, a primeira que eu esquecesse ficaria aberta em silêncio.
    papel = papel_do_usuario(email)
    if not contas.pode_ver(papel, caminho):
        if caminho.startswith("/api/"):
            return JSONResponse(
                {"erro": "seu perfil não tem acesso a isso"}, 403)
        return RedirectResponse(contas.CASA_DO_PAPEL.get(papel, "/noticias"))
    return await call_next(request)


_ENTRAR_CSS = """
body{background:var(--c-bg);color:var(--c-text);margin:0;min-height:100vh;
  display:flex;align-items:center;justify-content:center;padding:24px;
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif}
.caixa{width:100%;max-width:340px}
.marca-grande{font-family:'Bebas Neue',sans-serif;font-size:2.6rem;
  letter-spacing:.06em;color:var(--c-acento);text-align:center;margin:0 0 6px}
.sub{text-align:center;color:var(--c-muted-3);font-size:.78rem;margin:0 0 26px}
label{display:block;font-size:.68rem;font-weight:800;text-transform:uppercase;
  letter-spacing:.07em;color:var(--c-muted-3);margin:14px 0 6px}
input{width:100%;box-sizing:border-box;padding:13px 14px;border-radius:12px;
  background:var(--c-bg-card);border:1.5px solid var(--c-border-2);
  color:var(--c-text);font-family:inherit;font-size:.95rem}
input:focus{outline:none;border-color:var(--c-acento)}
button.principal{width:100%;margin-top:20px;padding:14px;border-radius:12px;
  background:var(--c-acento);color:var(--c-acento-texto);border:none;
  font-family:inherit;font-weight:800;font-size:.8rem;text-transform:uppercase;
  letter-spacing:.07em;cursor:pointer}
button.principal:disabled{opacity:.5;cursor:default}
.recado{margin-top:14px;padding:11px 13px;border-radius:11px;font-size:.75rem;
  line-height:1.6;display:none}
.recado.ruim{display:block;background:#FD5D5D1f;color:var(--c-negativo)}
.recado.bom{display:block;background:#B6FF001f;color:var(--c-acento)}
.rodape{margin-top:22px;text-align:center;font-size:.74rem;color:var(--c-muted-3)}
.rodape a{color:var(--c-acento);text-decoration:none}
.esqueci{background:none;border:none;color:var(--c-muted-3);font-family:inherit;
  font-size:.72rem;text-decoration:underline;cursor:pointer;padding:0;
  margin-top:12px;display:block;width:100%;text-align:center}
"""

_ENTRAR_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__ - IARABAO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__THEME_VARS__
__ENTRAR_CSS__
</style>
</head>
<body>
<div class="caixa">
  <h1 class="marca-grande">IARABAO</h1>
  <p class="sub">__SUB__</p>
  <form id="form" autocomplete="on">
    __CAMPO_NOME__
    <label for="email">E-mail</label>
    <input id="email" name="email" type="email" autocomplete="email"
           inputmode="email" required>
    <label for="senha">Senha</label>
    <input id="senha" name="senha" type="password"
           autocomplete="__AUTOCOMPLETE__" required>
    <button class="principal" type="submit" id="enviar">__BOTAO__</button>
  </form>
  <div class="recado" id="recado"></div>
  __ESQUECI__
  <p class="rodape">__RODAPE__</p>
</div>
<script>
__ENTRAR_JS__
</script>
</body>
</html>"""

_ENTRAR_JS = r"""
const ROTA = "__ROTA__";

// O link do convite ja traz o codigo. Pedir para a pessoa copiar e colar um
// token de 24 caracteres do WhatsApp e pedir para ela errar.
(function () {
  const campo = document.getElementById('convite');
  const veio = new URLSearchParams(location.search).get('convite');
  if (campo && veio) campo.value = veio;
})();

const form = document.getElementById('form');
const recado = document.getElementById('recado');
const enviar = document.getElementById('enviar');

function dizer(texto, bom) {
  recado.className = 'recado ' + (bom ? 'bom' : 'ruim');
  recado.textContent = texto;
}

form.onsubmit = async function (ev) {
  ev.preventDefault();
  const nome = document.getElementById('nome');
  const corpo = {
    email: document.getElementById('email').value,
    senha: document.getElementById('senha').value
  };
  if (nome) corpo.nome = nome.value;
  const convite = document.getElementById('convite');
  if (convite) corpo.convite = convite.value;
  enviar.disabled = true;
  const antes = enviar.textContent;
  enviar.textContent = 'aguarde...';
  try {
    const r = await fetch(ROTA, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(corpo)
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
    window.location.href = j.ir_para || '/';
  } catch (e) {
    dizer(e.message || String(e), false);
    enviar.disabled = false;
    enviar.textContent = antes;
  }
};

const esqueci = document.getElementById('esqueci');
if (esqueci) {
  esqueci.onclick = function () {
    dizer('Peca ao Vini uma senha temporaria. Ele gera uma na guia de '
        + 'Configuracoes e te passa. Com ela voce entra e troca por outra.', true);
  };
}
"""


def _tela_de_entrada(modo: str) -> HTMLResponse:
    cadastro = modo == "cadastrar"
    html = (_ENTRAR_HTML
            .replace("__TITULO__", "Criar conta" if cadastro else "Entrar")
            .replace("__SUB__", "Crie sua conta para entrar."
                     if cadastro else "Entre para continuar.")
            .replace("__CAMPO_NOME__",
                     '<label for="nome">Nome</label>'
                     '<input id="nome" name="nome" type="text" autocomplete="name" '
                     'placeholder="como voce quer ser chamado">'
                     '<label for="convite">Convite</label>'
                     '<input id="convite" name="convite" type="text" '
                     'placeholder="o codigo que voce recebeu">' if cadastro else "")
            .replace("__AUTOCOMPLETE__", "new-password" if cadastro else "current-password")
            .replace("__BOTAO__", "Criar conta" if cadastro else "Entrar")
            .replace("__ESQUECI__", "" if cadastro else
                     '<button type="button" class="esqueci" id="esqueci">'
                     'Esqueci minha senha</button>')
            .replace("__RODAPE__",
                     'Ja tem conta? <a href="/entrar">Entrar</a>' if cadastro else
                     'Primeira vez? <a href="/cadastrar">Criar conta</a>')
            .replace("__THEME__", _HEAD_COMUM)
            .replace("__THEME_VARS__", _THEME_VARS_CSS)
            .replace("__ENTRAR_CSS__", _ENTRAR_CSS)
            .replace("__ENTRAR_JS__", _ENTRAR_JS.replace(
                "__ROTA__", "/api/cadastrar" if cadastro else "/api/entrar")))
    return HTMLResponse(html)


@app.get("/entrar", response_class=HTMLResponse)
async def pagina_entrar():
    return _tela_de_entrada("entrar")


@app.get("/cadastrar", response_class=HTMLResponse)
async def pagina_cadastrar():
    return _tela_de_entrada("cadastrar")


def _por_o_cookie(resposta, email: str):
    resposta.set_cookie(
        contas.COOKIE, contas.criar_sessao(email),
        max_age=contas.DIAS_DE_SESSAO * 86400,
        httponly=True,      # JavaScript nenhum consegue ler o cookie
        secure=True,        # só viaja por https
        samesite="lax",     # não vai junto em requisição de outro site
    )
    return resposta


@app.post("/api/cadastrar")
async def api_cadastrar(request: Request):
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    email = contas.normalizar_email(corpo.get("email"))
    senha = corpo.get("senha") or ""
    codigo = (corpo.get("convite") or "").strip()
    if not email or "@" not in email:
        return JSONResponse({"erro": "e-mail inválido"}, 400)

    # Sem nenhuma conta ainda, o primeiro cadastro é livre e vira adm. Exigir
    # convite aqui seria exigir que alguém convidasse — e não há ninguém para
    # convidar. É a única porta aberta, e ela se fecha sozinha no primeiro uso.
    primeiro = not tem_algum_usuario()
    convite = None
    if not primeiro:
        if not codigo:
            return JSONResponse({"erro": "é preciso um convite para criar conta"}, 403)
        convite = convite_valido(contas.resumo_do_convite(codigo))
        if not convite:
            # Mesma resposta para código errado, já usado e vencido: dizer qual
            # dos três seria contar a quem está tentando o que mudar na próxima.
            return JSONResponse({"erro": "convite inválido ou já usado"}, 403)

    fraca = contas.senha_fraca(senha)
    if fraca:
        return JSONResponse({"erro": fraca}, 400)

    papel = "adm" if primeiro else contas.papel_valido(convite.get("papel"))
    # Queimo o convite ANTES de criar a conta. Se falhar depois, sobra um
    # convite gasto sem usuário — chato. Na ordem inversa, duas pessoas com o
    # mesmo código poderiam criar duas contas, o que é bem pior.
    if convite and not queimar_convite(convite["resumo"], email):
        return JSONResponse({"erro": "convite inválido ou já usado"}, 403)

    ok, motivo = criar_usuario(email, corpo.get("nome") or "",
                               contas.guardar_senha(senha), papel)
    if not ok:
        return JSONResponse({"erro": motivo}, 409)
    marcar_acesso(email)
    destino = contas.CASA_DO_PAPEL.get(papel, "/noticias")
    return _por_o_cookie(JSONResponse({"ok": True, "ir_para": destino}), email)


@app.post("/api/entrar")
async def api_entrar(request: Request):
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    email = contas.normalizar_email(corpo.get("email"))
    u = usuario_por_email(email)
    # Uma mensagem só para e-mail que não existe e senha errada. Duas mensagens
    # diferentes contariam a um estranho quais e-mails têm conta aqui.
    if not u or not contas.senha_confere(corpo.get("senha") or "", u.get("senha") or ""):
        return JSONResponse({"erro": "e-mail ou senha não conferem"}, 401)
    marcar_acesso(email)
    return _por_o_cookie(JSONResponse({"ok": True, "ir_para": "/"}), email)


@app.get("/sair")
async def sair():
    r = RedirectResponse("/entrar")
    r.delete_cookie(contas.COOKIE)
    return r


@app.get("/api/eu")
async def api_eu(request: Request):
    """Quem está logado. A tela inicial usa para a saudação."""
    email = _quem_esta_logado(request)
    if not email:
        return {"logado": False, "exige_login": _login_ligado()}
    u = usuario_por_email(email) or {}
    return {"logado": True, "email": email,
            "nome": contas.primeiro_nome(email, u.get("nome") or ""),
            "senha_temporaria": bool(u.get("temporaria"))}


@app.get("/api/usuarios")
async def api_usuarios():
    """Quem tem conta, e quem está liberado a criar."""
    return {"usuarios": listar_usuarios(),
            "liberados": contas.emails_liberados(),
            "sessao_fixa": contas.segredo_configurado()}


@app.post("/api/usuarios/senha-temporaria")
async def api_senha_temporaria(request: Request):
    """Gera uma senha temporária para alguém que esqueceu a dela.

    É isto que substitui o "esqueci minha senha" por e-mail: o app não manda
    e-mail, então quem devolve o acesso é você, por um caminho que você já
    confia — WhatsApp, pessoalmente, o que for.

    A senha aparece UMA VEZ, na resposta. Não fica guardada em texto em lugar
    nenhum: o que vai para o banco já é o hash.
    """
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    email = contas.normalizar_email(corpo.get("email"))
    if not usuario_por_email(email):
        return JSONResponse({"erro": "não existe conta com esse e-mail"}, 404)
    nova = contas.senha_temporaria()
    if not trocar_senha(email, contas.guardar_senha(nova), temporaria=True):
        return JSONResponse({"erro": "não consegui trocar a senha"}, 500)
    return {"ok": True, "email": email, "senha": nova}


@app.post("/api/eu/senha")
async def api_trocar_minha_senha(request: Request):
    """Trocar a própria senha. Exige a senha atual."""
    email = _quem_esta_logado(request)
    if not email:
        return JSONResponse({"erro": "não autenticado"}, 401)
    corpo = {}
    try:
        corpo = await request.json()
    except Exception:
        pass
    u = usuario_por_email(email) or {}
    if not contas.senha_confere(corpo.get("atual") or "", u.get("senha") or ""):
        return JSONResponse({"erro": "a senha atual não confere"}, 401)
    nova = corpo.get("nova") or ""
    fraca = contas.senha_fraca(nova)
    if fraca:
        return JSONResponse({"erro": fraca}, 400)
    if not trocar_senha(email, contas.guardar_senha(nova), temporaria=False):
        return JSONResponse({"erro": "não consegui trocar a senha"}, 500)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
# A TELA INICIAL — APROVAÇÃO
#
# A ideia: sua rotina de posts vira um log de curadoria. O app junta o que
# está esperando decisão nas várias guias, mostra em números grandes quanto
# tem de cada tipo, e embaixo a lista com ✓ e ✗.
#
# Os números NÃO são estimativa. Cada um é uma contagem de coisa que existe e
# está esperando você: post na fila, clipe pronto, notícia que ainda não foi
# vista. Se um número mentir, é bug meu, não arredondamento.

# Cada categoria: chave, rótulo, ícone e onde ela mora.
CATEGORIAS_APROVACAO = [
    ("posts",   "Agendamentos", "/posts", "acento"),
    ("clipes",  "Clipes",    "/clipes",   "alerta"),
    ("mercado", "Mercado",   "/mercado",  "acento"),
    ("aspas",   "Aspas",     "/aspas",    "alerta"),
]


# Os únicos dois estados que ainda pedem alguma coisa de você. 'publicado',
# 'cancelado' e 'falho' são registro do que aconteceu — lugar de histórico, não
# de fila.
ESTADOS_ABERTOS = ("pendente", "aprovado")


def _posts_do_futuro(limite: int = 200) -> list[dict]:
    """Os posts que ainda vão acontecer.

    Duas peneiras, e as duas são necessárias. O estado tira o que já foi
    resolvido. O horário tira o que está aberto mas já perdeu a hora — um
    BOLA ROLANDO de um jogo que começou há 40 minutos continua 'pendente' até
    a varredura de expiração passar, e nesse intervalo ele fica na sua tela
    pedindo uma decisão que não existe mais.
    """
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc)
    abertos = []
    for p in listar_posts(limite=limite):
        if (p.get("status") or "") not in ESTADOS_ABERTOS:
            continue
        quando = p.get("agendado_para")
        if quando:
            try:
                if datetime.fromisoformat(quando) < agora:
                    continue
            except (TypeError, ValueError):
                # Data ilegível não é motivo para esconder o post: melhor ele
                # aparecer a mais e você decidir do que sumir em silêncio.
                pass
        abertos.append(p)
    return abertos


def _contar_para_aprovar() -> dict:
    """Quanto está esperando decisão em cada frente.

    Cada contagem vem de uma consulta de verdade. Onde eu não souber contar,
    devolvo None e a tela mostra um traço — melhor um traço honesto que um
    zero que faz você achar que não tem nada esperando.
    """
    saida = {}
    try:
        saida["posts"] = len([p for p in _posts_do_futuro()
                              if p.get("status") == "pendente"])
    except Exception:
        saida["posts"] = None
    try:
        saida["clipes"] = len([c for c in clipes_recentes(24)
                               if c.get("estado") == "pronto"])
    except Exception:
        saida["clipes"] = None
    # Só o que VOCÊ separou. Antes eram todas as notícias das últimas 24h, e a
    # home virava um espelho da coleta — número grande que não pedia decisão
    # nenhuma. Agora o número é o tamanho da sua pilha, e por isso ele
    # significa alguma coisa quando cresce.
    try:
        marcas = get_all_flags()
    except Exception:
        marcas = None
    for chave, categoria in (("mercado", "mercado"), ("aspas", "entrevista")):
        if marcas is None:
            saida[chave] = None
            continue
        try:
            saida[chave] = len([a for a in get_recent_articles(
                                    hours=HORAS_DE_NOTICIA, limit=300)
                                if a.get("category") == categoria
                                and a.get("title_pt")
                                and marcas.get(a.get("id")) == MARCA_SEPARADA])
        except Exception:
            saida[chave] = None
    return saida


def _log_de_entrada(limite: int = 40) -> list:
    """O que entrou, em ordem de chegada, com de onde veio e quando."""
    itens = []
    try:
        # Só o que ainda vai acontecer. A home listava a fila inteira, e post
        # publicado e cancelado ficavam empurrando para baixo os que ainda
        # pediam decisão — que é o oposto do que uma fila serve para fazer.
        import posts_gerador as pg
        try:
            marcados = transmissoes(jogos_com_transmissao())
        except Exception:
            marcados = {}
        for p in _posts_do_futuro(limite * 3):
            fid = pg.jogo_da_chave(p.get("chave_unica"))
            itens.append({
                "tipo": "posts", "titulo": (p.get("texto") or "")[:120],
                "texto": p.get("texto") or "",
                "fixture_id": fid,
                "canais": (marcados.get(fid) or []) if fid is not None else [],
                "canais_possiveis": pg.TRANSMISSOES,
                # Ordeno pelo HORÁRIO DO JOGO, não pela hora em que o post foi
                # criado. Todos nascem juntos, às 23h da véspera; ordenar pela
                # criação embaralharia a rodada inteira num empate só.
                "quando": (p.get("agendado_para") or p.get("criado_em") or ""),
                "estado": p.get("status") or "",
                "id": p.get("id"), "onde": "/posts",
            })
    except Exception:
        pass
    try:
        for c in clipes_recentes(24):
            itens.append({
                "tipo": "clipes",
                "titulo": (c.get("texto") or c.get("jogo") or "Clipe")[:120],
                "quando": c.get("atualizado_em") or c.get("pedido_em") or "",
                "estado": c.get("estado") or "", "id": c.get("id"), "onde": "/clipes",
            })
    except Exception:
        pass
    try:
        marcas = get_all_flags()
    except Exception:
        marcas = {}
    try:
        for a in get_recent_articles(hours=HORAS_DE_NOTICIA, limit=300):
            if not a.get("title_pt"):
                continue
            # Só entra o que você separou na guia — arrastando para a direita
            # ou no ✓. A home era uma lista de tudo que a coleta trouxe; agora
            # é a lista do que você escolheu, que é outra coisa.
            if marcas.get(a.get("id")) != MARCA_SEPARADA:
                continue
            cat = a.get("category") or "geral"
            itens.append({
                "tipo": "mercado" if cat == "mercado" else
                        "aspas" if cat == "entrevista" else "noticias",
                "titulo": (a.get("title_pt") or "")[:120],
                "texto": (a.get("body_pt") or "")[:900],
                "fonte": a.get("source_name") or "",
                "url": a.get("url") or "",
                "quando": a.get("collected_at") or "", "estado": "",
                "id": a.get("id"), "onde": "/mercado" if cat == "mercado" else
                        "/aspas" if cat == "entrevista" else "/noticias",
            })
    except Exception:
        pass
    try:
        # Uma linha por dia, não uma por jogo: a arbitragem chega toda de uma
        # vez, e seis linhas iguais empurrariam o resto do log para fora.
        for dia in (_dia_de_brasilia(), _dia_de_brasilia(-1)):
            jogos = arbitragem_do_dia(dia)
            if not jogos:
                continue
            itens.append({
                "tipo": "arbitragem",
                "titulo": f"Arbitragem de {dia[8:10]}/{dia[5:7]}: "
                          + ", ".join(f"{j.get('casa')} x {j.get('fora')}"
                                      for j in jogos[:3])
                          + ("…" if len(jogos) > 3 else ""),
                "quando": jogos[0].get("capturado_em") or "",
                "estado": "", "id": None, "onde": f"/arbitragem?dia={dia}",
            })
    except Exception:
        pass
    itens.sort(key=lambda i: str(i.get("quando") or ""), reverse=True)
    return itens[:limite]


@app.get("/api/aprovacao")
async def api_aprovacao():
    """Os números e o log da tela inicial."""
    return {"numeros": _contar_para_aprovar(), "log": _log_de_entrada(),
            "categorias": [{"chave": c[0], "rotulo": c[1], "onde": c[2],
                            "cor": c[3]} for c in CATEGORIAS_APROVACAO]}


@app.post("/api/aprovacao/{tipo}/{item_id}")
async def api_aprovacao_decidir(tipo: str, item_id: int, decisao: str = ""):
    """O ✓ e o ✗ da lista.

    Só sabe decidir o que tem decisão de verdade por trás. Post pendente vira
    aprovado ou cancelado. Para os outros tipos eu digo que não sei, em vez de
    fingir que registrei — botão que não faz nada é pior que botão ausente.
    """
    if decisao not in ("sim", "nao"):
        return JSONResponse({"erro": "diga sim ou nao"}, 400)
    if tipo != "posts":
        return JSONResponse(
            {"erro": f"ainda não sei aprovar '{tipo}' por aqui — abra a guia"}, 400)
    novo = "aprovado" if decisao == "sim" else "cancelado"
    if not marcar_post(item_id, novo):
        return JSONResponse({"erro": "não consegui mudar este post"}, 409)
    return {"ok": True, "estado": novo}


_HOME_CSS = """
body{background:var(--c-bg);color:var(--c-text);
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;margin:0}
.wrap{max-width:820px;margin:0 auto;padding:6px 16px 70px}
.ola{font-family:'Bebas Neue',sans-serif;font-size:2.1rem;letter-spacing:.02em;
  margin:8px 0 2px;line-height:1.05}
.ola small{display:block;font-family:'Inter',sans-serif;font-size:.76rem;
  font-weight:500;letter-spacing:0;color:var(--c-muted-3);margin-top:6px}
.numeros{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:20px 0 8px}
.bloco{border-radius:20px;padding:16px 16px 14px;text-decoration:none;
  display:flex;flex-direction:column;min-height:112px;border:1px solid transparent}
.bloco .rot{font-size:.74rem;font-weight:700;opacity:.75;margin-bottom:auto}
.bloco .num{font-family:'Bebas Neue',sans-serif;font-size:2.6rem;line-height:1;
  letter-spacing:.01em}
.bloco .ico{width:30px;height:30px;border-radius:10px;display:flex;
  align-items:center;justify-content:center;margin-bottom:10px}
.bloco.acento{background:var(--c-acento);color:var(--c-acento-texto)}
.bloco.acento .ico{background:rgba(8,8,14,.16)}
.bloco.alerta{background:var(--c-alerta);color:#08080E}
.bloco.alerta .ico{background:rgba(8,8,14,.16)}
.bloco.quieto{background:var(--c-bg-card);color:var(--c-text);
  border-color:var(--c-border)}
.bloco.quieto .ico{background:var(--c-bg-soft);color:var(--c-acento)}
.titulo-secao{display:flex;align-items:center;justify-content:space-between;
  margin:26px 0 10px}
.titulo-secao h2{font-family:'Bebas Neue',sans-serif;font-size:1.3rem;
  letter-spacing:.04em;margin:0}
.titulo-secao a{font-size:.72rem;color:var(--c-muted-3);text-decoration:none}
.item{display:flex;align-items:center;gap:12px;background:var(--c-bg-card);
  border:1px solid var(--c-border);border-radius:16px;padding:12px 14px;
  margin-bottom:8px}
.item .ico{width:34px;height:34px;flex:0 0 34px;border-radius:11px;
  display:flex;align-items:center;justify-content:center;
  background:var(--c-bg-soft);color:var(--c-acento)}
.item .meio{flex:1;min-width:0}
.item .tit{font-size:.82rem;font-weight:600;line-height:1.4;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden}
.item .sub{font-size:.68rem;color:var(--c-muted-3);margin-top:3px}
.item .acoes{display:flex;gap:6px;flex:0 0 auto}
.caixa{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:16px;margin-bottom:8px;overflow:hidden}
.caixa .item{background:none;border:none;border-radius:0;margin:0}
.corpo{display:none;padding:0 14px 12px 60px}
.corpo.aberto{display:block}
.corpo .texto{white-space:pre-wrap;font-size:.78rem;line-height:1.6;
  color:var(--c-muted-3);margin:0 0 10px}
.corpo .canais{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.corpo .canal{font-size:.68rem;padding:4px 9px;border-radius:20px;cursor:pointer;
  border:1px solid var(--c-border-2);color:var(--c-muted-3);user-select:none}
.corpo .canal.on{border-color:var(--c-acento);color:var(--c-acento-texto);
  background:var(--c-acento);font-weight:700}
.corpo .pe{display:flex;gap:14px;flex-wrap:wrap;font-size:.68rem;
  color:var(--c-muted-3)}
.corpo .pe a{color:var(--c-acento);text-decoration:none}
.dec{width:34px;height:34px;border-radius:11px;border:1px solid var(--c-border-2);
  background:transparent;color:var(--c-muted-3);cursor:pointer;display:flex;
  align-items:center;justify-content:center;padding:0}
.dec.sim:hover{background:var(--c-acento);border-color:var(--c-acento);
  color:var(--c-acento-texto)}
.dec.nao:hover{background:var(--c-negativo);border-color:var(--c-negativo);color:#fff}
.dec:disabled{opacity:.35;cursor:default}
.vazio{padding:34px 16px;text-align:center;color:var(--c-muted-3);
  font-size:.82rem;line-height:1.7}
@media (min-width:640px){.numeros{grid-template-columns:repeat(4,1fr)}}
"""

_HOME_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IARABAO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
__HOME_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1 class="ola" id="ola">Salamaleikum
    <small id="resumo">carregando...</small>
  </h1>
  <div class="numeros" id="numeros"></div>
  <div class="titulo-secao">
    <h2>Entrou agora</h2>
    <a href="/noticias">ver noticias</a>
  </div>
  <div id="log">carregando...</div>
</div>
<script>
__HOME_JS__
</script>
</body>
</html>"""

_HOME_JS = r"""
const ICONES = __ICONES_JSON__;

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function quando(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  if (isNaN(t)) return '';
  const min = Math.floor((Date.now() - t.getTime()) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return 'ha ' + min + ' min';
  if (min < 1440) return 'ha ' + Math.floor(min / 60) + 'h';
  return t.toLocaleDateString('pt-BR', {day: '2-digit', month: '2-digit'});
}

async function saudar() {
  try {
    const r = await fetch('/api/eu');
    const d = await r.json();
    const h = document.getElementById('ola');
    const nome = d.logado ? d.nome : '';
    h.childNodes[0].nodeValue = 'Salamaleikum' + (nome ? ', ' + nome : '') + ' ';
    if (d.senha_temporaria) {
      const av = document.createElement('small');
      av.style.color = 'var(--c-alerta)';
      av.textContent = 'Voce esta com uma senha temporaria. Troque quando puder.';
      h.appendChild(av);
    }
  } catch (e) { /* sem login ligado, a saudacao fica sem nome */ }
}
saudar();

async function carregar() {
  let d;
  try {
    const r = await fetch('/api/aprovacao?_=' + Date.now());
    d = await r.json();
    if (!r.ok) throw new Error(d.erro || ('HTTP ' + r.status));
  } catch (e) {
    document.getElementById('resumo').textContent =
      'nao consegui carregar: ' + (e.message || e);
    return;
  }

  const n = d.numeros || {};
  const total = Object.values(n).reduce(function (s, v) {
    return s + (typeof v === 'number' ? v : 0);
  }, 0);
  document.getElementById('resumo').textContent = total
    ? total + ' item(ns) esperando voce.'
    : 'Nada esperando decisao agora.';

  const cx = document.getElementById('numeros');
  cx.innerHTML = '';
  (d.categorias || []).forEach(function (c) {
    const v = n[c.chave];
    const a = document.createElement('a');
    // Sem nada esperando, o bloco fica quieto. Cor forte em tudo o tempo todo
    // faz voce parar de enxergar a cor forte.
    a.className = 'bloco ' + (v ? c.cor : 'quieto');
    a.href = c.onde;
    a.innerHTML = '<div class="ico">' + (ICONES[c.chave] || '') + '</div>'
      + '<div class="rot">' + esc(c.rotulo) + '</div>'
      + '<div class="num">' + (v === null || v === undefined ? '—' : v) + '</div>';
    cx.appendChild(a);
  });

  const alvo = document.getElementById('log');
  alvo.innerHTML = '';
  const log = d.log || [];
  if (!log.length) {
    alvo.innerHTML = '<div class="vazio">Nada entrou nas ultimas 24 horas.</div>';
    return;
  }
  log.forEach(function (i) { alvo.appendChild(linha(i)); });
}

function linha(i) {
  const caixa = document.createElement('div');
  caixa.className = 'caixa';

  const d = document.createElement('div');
  d.className = 'item';

  const ico = document.createElement('div');
  ico.className = 'ico';
  ico.innerHTML = ICONES[i.tipo] || ICONES.noticias || '';
  d.appendChild(ico);

  const meio = document.createElement('div');
  meio.className = 'meio';
  const t = document.createElement('div');
  t.className = 'tit';
  t.textContent = i.titulo || '(sem titulo)';
  const s = document.createElement('div');
  s.className = 'sub';
  s.textContent = [i.tipo, quando(i.quando), i.estado].filter(Boolean).join(' · ');
  meio.appendChild(t);
  meio.appendChild(s);
  d.appendChild(meio);

  const acoes = document.createElement('div');
  acoes.className = 'acoes';
  // O check e o X so aparecem onde existe decisao de verdade por tras. Botao
  // que nao faz nada e pior que botao ausente.
  if (i.tipo === 'posts' && i.estado === 'pendente') {
    acoes.appendChild(botao(i, 'sim', '✓'));
    acoes.appendChild(botao(i, 'nao', '✕'));
  }
  d.appendChild(acoes);

  // O corpo abre para baixo. Antes, tocar no card levava para a guia e voce
  // perdia o lugar na lista; agora a decisao inteira cabe aqui.
  const corpo = document.createElement('div');
  corpo.className = 'corpo';
  corpo.appendChild(detalhe(i));
  meio.style.cursor = 'pointer';
  meio.onclick = function () { corpo.classList.toggle('aberto'); };

  caixa.appendChild(d);
  caixa.appendChild(corpo);
  return caixa;
}

function detalhe(i) {
  const box = document.createElement('div');

  if (i.texto) {
    const p = document.createElement('p');
    p.className = 'texto';
    p.textContent = i.texto;
    box.appendChild(p);
  }

  // Post de BOLA ROLANDO: as emissoras ficam aqui, para voce marcar e aprovar
  // sem sair. Eram tres telas para uma decisao de um toque.
  if (i.tipo === 'posts' && Array.isArray(i.canais_possiveis)) {
    const linhaCanais = document.createElement('div');
    linhaCanais.className = 'canais';
    i.canais_possiveis.forEach(function (c) {
      const b = document.createElement('span');
      b.className = 'canal' + ((i.canais || []).indexOf(c) > -1 ? ' on' : '');
      b.textContent = c;
      b.onclick = function () {
        b.classList.toggle('on');
        salvarCanais(i, linhaCanais, box);
      };
      linhaCanais.appendChild(b);
    });
    box.appendChild(linhaCanais);
  }

  const pe = document.createElement('div');
  pe.className = 'pe';
  if (i.fonte) {
    const f = document.createElement('span');
    f.textContent = i.fonte;
    pe.appendChild(f);
  }
  const ir = document.createElement('a');
  ir.href = i.onde;
  ir.textContent = 'abrir na guia ›';
  pe.appendChild(ir);
  if (i.url) {
    const o = document.createElement('a');
    o.href = i.url;
    o.target = '_blank';
    o.rel = 'noopener';
    o.textContent = 'ver original ›';
    pe.appendChild(o);
  }
  box.appendChild(pe);
  return box;
}

async function salvarCanais(i, linhaCanais, box) {
  const marcados = [];
  linhaCanais.querySelectorAll('.canal.on').forEach(function (c) {
    marcados.push(c.textContent);
  });
  try {
    const r = await fetch('/api/posts/' + i.id + '/transmissao', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({canais: marcados})
    });
    const j = await r.json();
    if (j.erro) throw new Error(j.erro);
    i.canais = marcados;
    // O texto do post muda junto (a ultima linha e a transmissao). Atualizo o
    // que esta na tela, senao voce aprova olhando uma versao velha.
    if (j.texto) {
      i.texto = j.texto;
      const p = box.querySelector('.texto');
      if (p) p.textContent = j.texto;
    }
  } catch (e) {
    alert('nao deu para salvar a transmissao: ' + (e.message || e));
    carregar();
  }
}

function botao(i, decisao, rotulo) {
  const b = document.createElement('button');
  b.className = 'dec ' + decisao;
  b.textContent = rotulo;
  b.title = decisao === 'sim' ? 'aprovar' : 'recusar';
  b.onclick = async function () {
    b.disabled = true;
    try {
      const r = await fetch('/api/aprovacao/' + i.tipo + '/' + i.id
                            + '?decisao=' + decisao, {method: 'POST'});
      const j = await r.json();
      if (!r.ok) throw new Error(j.erro || ('HTTP ' + r.status));
      carregar();
    } catch (e) {
      alert('nao deu: ' + (e.message || e));
      b.disabled = false;
    }
  };
  return b;
}

carregar();
setInterval(carregar, 60000);
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    """A tela de curadoria: o que entrou e o que espera decisão."""
    icones = json.dumps({
        "posts": _ICO_POSTS, "clipes": _ICO_CLIPE, "mercado": _ICO_MERCADO,
        "aspas": _ICO_ASPAS, "noticias": _ICO_JORNAL,
        "arbitragem": _ICO_ARBITRO,
    })
    return HTMLResponse(
        _HOME_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__HOME_CSS__", _HOME_CSS)
        .replace("__HOME_JS__", _HOME_JS.replace("__ICONES_JSON__", icones))
        .replace("__HDR__", _header("/"))
    )


@app.get("/aspas", response_class=HTMLResponse)
async def pagina_aspas():
    """As notícias de entrevista, como notícia mesmo.

    Aqui havia um extrator que lia o texto e montava a citação sozinho, sem
    IA. Funcionava razoavelmente e errava o suficiente para incomodar — e a
    decisão de tratar uma declaração é sua, não minha. Então a guia virou a
    lista das entrevistas, e o tratamento acontece quando você toca a varinha
    num cartão, como já acontece nas outras telas.

    O aspas.py continua no projeto. Não apago porque ele pode voltar a servir
    como primeira leitura barata antes de gastar chamada de IA.
    """
    return await _pagina_de_noticias("entrevista", "/aspas")


@app.get("/config", response_class=HTMLResponse)
async def config_page():
    return HTMLResponse(
        _CONFIG_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__CONFIG_CSS__", _CONFIG_CSS)
        .replace("__CONFIG_JS__", _CONFIG_JS)
        .replace("__HDR__", _header("/config"))
    )


@app.get("/clipes", response_class=HTMLResponse)
async def clipes_page():
    return HTMLResponse(
        _CLIPES_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__CLIPES_CSS__", _CLIPES_CSS)
        .replace("__CLIPES_JS__", _CLIPES_JS)
        # O passo dos botões vem do servidor. Se eu escrevesse 8 na tela e 8
        # aqui, um dia mudaria um e não o outro, e o botão diria uma coisa
        # enquanto o corte fazia outra.
        .replace("__PASSO_AJUSTE__", str(ajuste("clipe_passo_ajuste")))
        .replace("__HDR__", _header("/clipes"))
    )


@app.get("/fim-de-jogo", response_class=HTMLResponse)
async def fim_de_jogo_page():
    return HTMLResponse(
        _FIMJOGO_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__FJ_CSS__", _FIMJOGO_CSS)
        .replace("__FJ_JS__", _FIMJOGO_JS)
        .replace("__HDR__", _header("/fim-de-jogo"))
    )

_ELENCOS_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elencos · IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
:root{
  --bg:var(--c-bg);--surface:var(--c-bg-card);--surface2:var(--c-bg-soft);
  --border:var(--c-border);--text:var(--c-text);--text2:var(--c-muted-3);--accent:var(--c-acento);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:18px 20px 60px}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--text2);font-size:.8rem;margin:0 0 16px}

.escudos{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.escudo{width:44px;height:44px;border-radius:10px;border:1px solid var(--border);
  background:var(--surface);display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:all .15s;padding:5px}
.escudo img{max-width:100%;max-height:100%;object-fit:contain}
.escudo:hover{border-color:var(--accent);transform:translateY(-2px)}
.escudo.active{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 18%,transparent)}

.barra{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.ctrl{padding:7px 12px;border-radius:8px;border:1px solid var(--border);
  background:var(--surface);color:var(--text);font-size:13px;cursor:pointer}
.chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text2);
  cursor:pointer;padding:6px 12px;border-radius:20px;border:1px solid var(--border);background:var(--surface)}
.chk input{width:14px;height:14px;accent-color:var(--accent);cursor:pointer}

.painel{display:grid;grid-template-columns:minmax(320px,460px) 1fr;gap:20px;align-items:start}
/* Sem isso a coluna do grid assume a largura da tabela (min-width:auto) e a
   página inteira estoura no celular, em vez de a tabela rolar por dentro. */
.painel>*{min-width:0}
@media(max-width:1100px){
  .painel{grid-template-columns:1fr}
  .campo-caixa{max-width:400px;margin:0 auto;width:100%}
  table{min-width:720px}
}
@media(max-width:520px){
  .wrap{padding:12px 10px 40px}
  /* Teto em vh também: só limitar a largura ainda deixava o campo alto demais. */
  .campo-caixa{max-width:min(340px,84vw)}
  .campo{max-height:62vh}
  .slot{width:54px}
  .slot .disco{width:36px;height:36px}
  .slot .band{width:15px;height:15px;font-size:.5rem}
  .slot .rot{font-size:.55rem}
}

/* ── campo ── */
.campo-caixa{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:12px}
.campo{position:relative;width:100%;aspect-ratio:68/100;border-radius:16px;
  background:linear-gradient(180deg,#15A15F 0%,#0E8B50 100%);overflow:hidden}
.campo .linha{position:absolute;border:2px solid rgba(255,255,255,.22)}
.c-borda{inset:3%}
.c-meio{left:3%;right:3%;top:50%;height:0;border-width:0;border-top:2px solid rgba(255,255,255,.22)}
.c-circulo{left:50%;top:50%;width:26%;aspect-ratio:1;transform:translate(-50%,-50%);border-radius:50%}
.c-area-b{left:22%;right:22%;bottom:3%;height:16%;border-bottom:none}
.c-area-c{left:22%;right:22%;top:3%;height:16%;border-top:none}

.slot{position:absolute;transform:translate(-50%,-50%);width:64px;
  display:flex;flex-direction:column;align-items:center;gap:5px;cursor:grab}
.slot .disco{position:relative;width:44px;height:44px;border-radius:50%;
  background:rgba(255,255,255,.22);border:2px dashed rgba(255,255,255,.55);
  display:flex;align-items:center;justify-content:center;
  font-size:.58rem;color:#fff;font-weight:800}
.slot.ocupado .disco{border-style:solid;border-color:#fff;background:#eef2f5;
  box-shadow:0 2px 8px rgba(0,0,0,.25)}
.slot .disco img.foto{width:100%;height:100%;border-radius:50%;object-fit:cover}
/* Bandeira como emoji: a imagem do TM exige a página dele; o emoji já vem
   pronto na resposta e não depende de rede. */
.slot .band{position:absolute;right:-4px;bottom:-2px;width:18px;height:18px;border-radius:50%;
  border:2px solid #fff;background:#fff;display:flex;align-items:center;justify-content:center;
  font-size:.6rem;line-height:1;overflow:hidden}
/* Uma linha só, com reticências: nome comprido encavalava no vizinho. */
.slot .rot{font-size:.64rem;color:#fff;font-weight:700;text-align:center;line-height:1.1;
  max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  text-shadow:0 1px 3px rgba(0,0,0,.45)}
.slot.alvo .disco{border-color:#fde047;box-shadow:0 0 0 4px rgba(253,224,71,.4)}

/* ── tabela ── */
.tab-caixa{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  overflow-x:auto;overflow-y:visible;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.78rem}
th,td{padding:7px 8px;text-align:left;white-space:nowrap}
thead th{position:sticky;top:0;background:var(--surface2);color:var(--text2);
  font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;cursor:pointer;user-select:none;z-index:2}
tbody tr{border-top:1px solid var(--border);cursor:grab}
tbody tr:hover{background:var(--surface2)}
tbody tr.escalado{background:color-mix(in srgb,var(--accent) 12%,transparent)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.jog{display:flex;align-items:center;gap:8px}
.jog img{width:26px;height:26px;border-radius:50%;object-fit:cover;background:var(--surface2)}
.vazio{color:var(--text2)}
.pos-tag{display:inline-block;padding:1px 6px;border-radius:5px;font-size:.62rem;font-weight:700}
.pos-G{background:#FFBE5D22;color:#FFBE5D}
.pos-D{background:#B6FF0022;color:#60a5fa}
.pos-M{background:#B6FF0022;color:#B6FF00}
.pos-A{background:#FD5D5D22;color:#FD5D5D}
.estado{padding:30px;text-align:center;color:var(--text2);font-size:.85rem}
.aviso{font-size:.72rem;color:#FFBE5D;margin:8px 0 0}
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Elencos</h1>
  <p class="sub">Dados do Transfermarkt: elenco, posição detalhada, pé preferido e números da temporada.
     Campos que a fonte não informa aparecem como “—”; nada é estimado.</p>

  <div id="escudos" class="escudos"></div>

  <div class="barra">
    <select id="formacao" class="ctrl" onchange="trocarFormacao()"></select>
    <button class="ctrl" onclick="voltarEscalacao()">⚽ Última escalação</button>
    <button class="ctrl" id="btnSalvar" onclick="salvarEscalacao()">💾 Salvar escalação</button>
    <button class="ctrl" id="btnDescartar" onclick="descartarSalva()" style="display:none">🗑️ Descartar salva</button>
    <button class="ctrl" onclick="limparCampo()">Limpar campo</button>
    <label class="chk"><input type="checkbox" id="soEstrangeiros" onchange="renderTabela()"> Só estrangeiros</label>
    <span id="contador" class="sub" style="margin:0"></span>
  </div>

  <div class="painel">
    <div class="campo-caixa">
      <div id="campo" class="campo">
        <div class="linha c-borda"></div><div class="linha c-meio"></div>
        <div class="linha c-circulo"></div><div class="linha c-area-b"></div><div class="linha c-area-c"></div>
      </div>
      <p id="infoJogo" class="sub" style="margin:8px 0 0"></p>
      <p class="sub" style="margin:4px 0 0">Arraste um jogador da lista para uma posição. Arraste entre posições para trocar. Clique numa posição ocupada para esvaziar.</p>
    </div>

    <div>
      <div class="tab-caixa"><div id="tabela"><div class="estado">Escolha um clube acima.</div></div></div>
      <p id="avisos" class="aviso" style="display:none"></p>
    </div>
  </div>
</div>

<script>
const FORMACOES = __FORMACOES__;
let ELENCO = [];        // jogadores do clube atual
// Cada casa do campo carrega a própria coordenada: assim o campinho pode mostrar
// a escalação REAL da última partida, cujas posições vêm da API e não batem
// necessariamente com nenhum dos moldes de formação daqui.
let SLOTS = [];         // [{x, y, g, id}]
let FORM = '4-3-3';
let ESCALACAO = null;   // última escalação carregada, pra poder voltar a ela
let SALVA = null;       // ajuste do usuário, que tem precedência ao abrir
let TIME_ATUAL = null;
let ordenarPor = null, ordemAsc = false;

// O setor (G/D/M/A) já vem pronto do backend, derivado da posição detalhada
// do TM — não há mais rótulo em inglês pra traduzir aqui.
const GRUPO_PT = {G:'GOL', D:'DEF', M:'MEI', A:'ATA'};

function na(v, suf){ return (v === null || v === undefined) ? '—' : (v + (suf || '')); }

// "Youssef En-Nesyri" -> "En-Nesyri"; "Farhah Al-Shamrani" -> "Al-Shamrani".
// O nome completo continua no title e na tabela.
function nomeCurto(n){
  const partes = (n || '').trim().split(/\s+/).filter(Boolean);
  return partes.length ? partes[partes.length - 1] : '';
}

// Foto direto do Transfermarkt; se falhar, cai no nosso proxy uma única vez.
// O endereço reserva vai num data-attribute e o tratador é ligado depois, em
// ligarReserva: escrever onerror inline exigiria aspas dentro de aspas dentro
// de string, e o escape se perdia entre as camadas.
function imgFoto(j, classe, alt){
  if (!j || !j.foto) return '';
  return '<img class="' + (classe || '') + '" src="' + j.foto + '" alt="' + (alt || '') + '"' +
         (j.foto_reserva ? ' data-res="' + j.foto_reserva + '"' : '') + '>';
}

function ligarReserva(raiz){
  if (!raiz || !raiz.querySelectorAll) return;
  raiz.querySelectorAll('img[data-res]').forEach(function(im){
    im.onerror = function(){ this.onerror = null; this.src = this.dataset.res; };
  });
}
function porId(id){ return ELENCO.find(function(j){ return j.id === id; }); }

// ── carga ──
async function carregarTimes(){
  const r = await fetch('/api/elencos/times');
  const d = await r.json();
  if (d.erro) {
    // O TM às vezes recusa a consulta por excesso de acessos; costuma liberar
    // sozinho, então o caminho aqui é oferecer nova tentativa, não travar.
    document.getElementById('escudos').innerHTML =
      '<div class="sub" style="max-width:640px">Não consegui carregar a lista de clubes agora: ' + d.erro +
      '<br>O Transfermarkt limita consultas seguidas. Espere alguns segundos e tente de novo. ' +
      '<button class="ctrl" style="margin-top:8px" onclick="carregarTimes()">Tentar de novo</button></div>';
    return;
  }
  document.getElementById('escudos').innerHTML = d.times.map(function(t){
    return '<div class="escudo" data-id="' + t.id + '" title="' + t.nome + '" onclick="selecionarTime(' + t.id + ',this)">' +
           '<img src="' + t.escudo + '" alt="' + t.nome + '"></div>';
  }).join('');
}

async function selecionarTime(id, el){
  TIME_ATUAL = id;
  document.querySelectorAll('.escudo').forEach(function(e){
    e.classList.toggle('active', Number(e.dataset.id) === id);
  });
  document.getElementById('tabela').innerHTML = '<div class="estado">Carregando elenco…</div>';
  document.getElementById('infoJogo').textContent = '';
  try {
    // Elenco e escalação em paralelo: a segunda é o que desenha o campo.
    const [rj, re, rs] = await Promise.all([
      fetch('/api/elencos/jogadores?team=' + id),
      fetch('/api/elencos/escalacao?team=' + id),
      fetch('/api/elencos/escalacao-salva?team=' + id)
    ]);
    const d = await rj.json();
    if (d.erro) throw new Error(d.erro);
    ELENCO = d.jogadores;
    const av = document.getElementById('avisos');
    if (d.avisos && d.avisos.length) { av.textContent = '⚠️ ' + d.avisos.join(' · '); av.style.display = ''; }
    else av.style.display = 'none';

    let esc = null, sv = null;
    try { esc = await re.json(); } catch(e) {}
    try { sv = await rs.json(); } catch(e) {}
    ESCALACAO = (esc && !esc.erro) ? esc : null;
    SALVA = (sv && sv.salva && (sv.salva.slots || []).length) ? sv.salva : null;

    mostrarBotaoDescartar();
    if (SALVA) aplicarSalva();
    else if (ESCALACAO) aplicarEscalacao();
    else {
      document.getElementById('infoJogo').textContent =
        'Escalação da última partida indisponível' + (esc && esc.erro ? ' (' + esc.erro + ')' : '') +
        ' — campo montado pela formação escolhida.';
      aplicarFormacao(FORM);
    }
    renderTabela();
  } catch(e) {
    document.getElementById('tabela').innerHTML = '<div class="estado">Erro: ' + e.message + '</div>';
  }
}

// Monta o campo a partir do grupo de cada jogador, quando a API não publica a
// grade tática da partida (caso do Al Diriyah). Mantém o XI real, só arruma.
function porGrupos(lista){
  const ordem = ['G','D','M','A'];
  const linhas = ordem.map(function(g){ return lista.filter(function(p){ return grupoDe(p) === g; }); })
                      .filter(function(l){ return l.length; });
  const slots = [];
  linhas.forEach(function(linha, i){
    const y = linhas.length <= 1 ? 92 : 92 - i * (76 / (linhas.length - 1));
    linha.forEach(function(p, k){
      slots.push({x: ((k + 1) / (linha.length + 1)) * 100, y: y,
                  g: grupoDe(p), id: p.id, rotulo: p.nome, numero: p.numero});
    });
  });
  return slots;
}

function grupoDe(p){
  if (p.grupo) return p.grupo;
  const j = porId(p.id);
  return (j && j.grupo) || 'M';
}

// Lado do campo a partir da posição detalhada do TM. A súmula lista os titulares
// do goleiro ao ataque, mas NÃO da esquerda para a direita dentro da linha —
// por isso Faris Abdi (lateral-esquerdo) aparecia como zagueiro e En-Nesyri
// (centroavante) saía na ponta. Com a posição em mãos, a linha é reordenada.
function ladoDaPosicao(pos){
  const p = (pos || '').toLowerCase();
  if (p.indexOf('esquerd') > -1) return 0;   // lateral/ponta/meia esquerda
  if (p.indexOf('direit') > -1)  return 2;   // lateral/ponta/meia direita
  return 1;                                   // zagueiro, volante, centroavante
}

// Reordena cada faixa horizontal do campo pela lateralidade. Empate mantém a
// ordem da súmula: sem informação de lado, inventar posição seria pior.
function ordenarPorLado(slots){
  const porFaixa = {};
  slots.forEach(function(s){ (porFaixa[s.y] = porFaixa[s.y] || []).push(s); });
  Object.keys(porFaixa).forEach(function(y){
    const faixa = porFaixa[y];
    if (faixa.length < 2) return;
    const xs = faixa.map(function(s){ return s.x; }).sort(function(a,b){ return a-b; });
    const comLado = faixa.map(function(s, i){
      const j = porId(s.id);
      return {slot:s, lado: ladoDaPosicao(j && j.posicao), ordem:i};
    });
    comLado.sort(function(a,b){ return a.lado - b.lado || a.ordem - b.ordem; });
    comLado.forEach(function(c, i){ c.slot.x = xs[i]; });
  });
  return slots;
}

function aplicarEscalacao(){
  const e = ESCALACAO;
  if (!e) return;
  SLOTS = e.sem_posicoes
    ? porGrupos(e.titulares)
    : ordenarPorLado(e.titulares.map(function(t){
        return {x: t.x, y: t.y, g: grupoDe(t), id: t.id};
      }));
  if (e.formacao) {
    FORM = e.formacao;
    const sel = document.getElementById('formacao');
    // A formação real pode não estar entre os moldes — entra na lista pra aparecer.
    if (!Array.prototype.some.call(sel.options, function(o){ return o.value === e.formacao; })) {
      const op = document.createElement('option');
      op.value = e.formacao; op.textContent = e.formacao + ' (do jogo)';
      sel.insertBefore(op, sel.firstChild);
    }
    sel.value = e.formacao;
  }
  document.getElementById('infoJogo').textContent =
    'Escalação de ' + (e.mandante ? 'casa' : 'fora') + ' contra ' + (e.adversario || '?') +
    ' em ' + (e.data || '?') + ' (' + (e.placar || '') + ')' +
    (e.formacao ? ' · ' + e.formacao : '') +
    (e.sem_posicoes ? ' · a API não publicou as posições deste jogo; os 11 são os que atuaram, dispostos por setor' : '');
  renderCampo();
}

function aplicarSalva(){
  if (!SALVA) return;
  SLOTS = SALVA.slots.map(function(s){ return {x:s.x, y:s.y, g:s.g, id:s.id}; });
  if (SALVA.formacao) {
    FORM = SALVA.formacao;
    const sel = document.getElementById('formacao');
    if (!Array.prototype.some.call(sel.options, function(o){ return o.value === SALVA.formacao; })) {
      const op = document.createElement('option');
      op.value = SALVA.formacao; op.textContent = SALVA.formacao;
      sel.insertBefore(op, sel.firstChild);
    }
    sel.value = SALVA.formacao;
  }
  document.getElementById('infoJogo').textContent =
    'Sua escalação salva em ' + (SALVA.salvo_em || '').replace('T', ' ').slice(0, 16) +
    ' · use “Última escalação” e salve de novo para voltar à do jogo.';
  renderCampo(); renderTabela();
}

function mostrarBotaoDescartar(){
  document.getElementById('btnDescartar').style.display = SALVA ? '' : 'none';
}

async function descartarSalva(){
  if (!TIME_ATUAL || !SALVA) return;
  try {
    const r = await fetch('/api/elencos/escalacao-salva', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team: TIME_ATUAL, limpar: true})
    });
    const d = await r.json();
    if (d.erro) throw new Error(d.erro);
    SALVA = null;
    mostrarBotaoDescartar();
    if (ESCALACAO) { aplicarEscalacao(); renderTabela(); }
    else { document.getElementById('infoJogo').textContent = 'Escalação salva descartada.'; }
  } catch(e) {
    alert('Não consegui descartar: ' + e.message);
  }
}

async function salvarEscalacao(){
  if (!TIME_ATUAL) return;
  const btn = document.getElementById('btnSalvar');
  const orig = btn.textContent;
  btn.textContent = 'salvando…'; btn.disabled = true;
  try {
    const r = await fetch('/api/elencos/escalacao-salva', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team: TIME_ATUAL, formacao: FORM,
        slots: SLOTS.map(function(s){ return {id:s.id, x:s.x, y:s.y, g:s.g}; })})
    });
    const d = await r.json();
    if (d.erro) throw new Error(d.erro);
    SALVA = {formacao: FORM, slots: SLOTS.map(function(s){ return {id:s.id,x:s.x,y:s.y,g:s.g}; }),
             salvo_em: d.salvo_em};
    mostrarBotaoDescartar();
    document.getElementById('infoJogo').textContent =
      'Sua escalação salva em ' + (d.salvo_em || '').replace('T', ' ').slice(0, 16) +
      ' · use “Última escalação” e salve de novo para voltar à do jogo.';
    btn.textContent = '✅ Salva!';
    setTimeout(function(){ btn.textContent = orig; btn.disabled = false; }, 1600);
    return;
  } catch(e) {
    alert('Não consegui salvar: ' + e.message);
  }
  btn.textContent = orig; btn.disabled = false;
}

function voltarEscalacao(){
  if (ESCALACAO) { aplicarEscalacao(); renderTabela(); }
  else { preencherAuto(); }
}

// ── campo ──
function trocarFormacao(){
  const escolhida = document.getElementById('formacao').value;
  // Se voltou pra formação do jogo, restaura as posições reais em vez do molde.
  if (ESCALACAO && escolhida === ESCALACAO.formacao) { aplicarEscalacao(); renderTabela(); return; }
  aplicarFormacao(escolhida);
  preencherAuto();
}

function aplicarFormacao(nome){
  if (!FORMACOES[nome]) nome = '4-3-3';
  FORM = nome;
  SLOTS = FORMACOES[nome].map(function(c){ return {x:c.x, y:c.y, g:c.g, id:null}; });
}

function limparCampo(){
  SLOTS.forEach(function(s){ s.id = null; });
  renderCampo(); renderTabela();
}

function preencherAuto(){
  // Preenche por grupo, priorizando quem mais jogou. Sem minutagem (pré-temporada),
  // o desempate é o número da camisa, que já reflete a hierarquia do elenco.
  const usados = new Set();
  SLOTS.forEach(function(s){ s.id = null; });
  const disponiveis = function(g){
    return ELENCO.filter(function(j){ return j.grupo === g && !usados.has(j.id); })
      .sort(function(a,b){
        const ma = a.minutos || 0, mb = b.minutos || 0;
        if (mb !== ma) return mb - ma;
        return (a.numero || 99) - (b.numero || 99);
      });
  };
  SLOTS.forEach(function(s){
    const cand = disponiveis(s.g)[0];
    if (cand) { s.id = cand.id; usados.add(cand.id); }
  });
  renderCampo(); renderTabela();
}

function renderCampo(){
  const campo = document.getElementById('campo');
  campo.querySelectorAll('.slot').forEach(function(s){ s.remove(); });
  SLOTS.forEach(function(c, i){
    // Quem escalou pode não estar na lista do elenco (caso de clube sem elenco
    // publicado); nesse caso usa o nome que veio na própria escalação.
    const j = c.id ? (porId(c.id) || {id:c.id, nome:c.rotulo, numero:c.numero, foto:null}) : null;
    const el = document.createElement('div');
    el.className = 'slot' + (j ? ' ocupado' : '');
    el.style.left = c.x + '%';
    el.style.top = c.y + '%';
    el.draggable = true;
    el.dataset.slot = i;
    let disco = '<div class="disco">';
    if (j) {
      disco += j.foto ? imgFoto(j, 'foto', '') : '<span>' + GRUPO_PT[c.g] + '</span>';
      if (j.pais_bandeira) {
        disco += '<span class="band" title="' + (j.nacionalidade || '') + '">' + j.pais_bandeira + '</span>';
      }
    } else {
      disco += '<span>' + GRUPO_PT[c.g] + '</span>';
    }
    disco += '</div>';
    // Só o sobrenome, sem número: nome inteiro encavalava no vizinho no celular.
    const rot = j ? '<div class="rot" title="' + (j.nome || '') + '">' +
                    nomeCurto(j.nome) + '</div>' : '';
    el.innerHTML = disco + rot;
    ligarReserva(el);
    el.addEventListener('dragstart', function(ev){
      ev.dataTransfer.setData('text/plain', JSON.stringify({de:'campo', slot:i}));
    });
    el.addEventListener('dragover', function(ev){ ev.preventDefault(); el.classList.add('alvo'); });
    el.addEventListener('dragleave', function(){ el.classList.remove('alvo'); });
    el.addEventListener('drop', function(ev){
      ev.preventDefault(); el.classList.remove('alvo');
      soltarEm(i, ev.dataTransfer.getData('text/plain'));
    });
    el.addEventListener('click', function(){ if (SLOTS[i].id) { SLOTS[i].id = null; renderCampo(); renderTabela(); } });
    campo.appendChild(el);
  });
}

function soltarEm(slot, carga){
  let d; try { d = JSON.parse(carga); } catch(e) { return; }
  if (d.de === 'campo') {
    const t = SLOTS[slot].id; SLOTS[slot].id = SLOTS[d.slot].id; SLOTS[d.slot].id = t;   // troca
    const r = SLOTS[slot].rotulo; SLOTS[slot].rotulo = SLOTS[d.slot].rotulo; SLOTS[d.slot].rotulo = r;
  } else {
    SLOTS.forEach(function(s){ if (s.id === d.id) { s.id = null; s.rotulo = null; } });  // ninguém joga em dois lugares
    SLOTS[slot].id = d.id;
    SLOTS[slot].rotulo = null;
  }
  renderCampo(); renderTabela();
}

// ── tabela ──
const COLUNAS = [
  {k:'numero',       t:'#',    num:true},
  {k:'nome',         t:'Jogador'},
  {k:'nacionalidade',t:'País'},
  {k:'idade',        t:'Idade', num:true},
  {k:'altura',       t:'Alt.',  num:true},
  {k:'pe',           t:'Pé'},
  {k:'posicao',      t:'Posição'},
  {k:'jogos',        t:'J',     num:true},
  {k:'gols',         t:'G',     num:true},
  {k:'assistencias', t:'A',     num:true},
  {k:'amarelos',     t:'🟨',    num:true},
  {k:'vermelhos',    t:'🟥',    num:true},
  {k:'minutos',      t:'Min',   num:true},
];

function ordenar(k){
  if (ordenarPor === k) ordemAsc = !ordemAsc; else { ordenarPor = k; ordemAsc = false; }
  renderTabela();
}

function renderTabela(){
  const soEstr = document.getElementById('soEstrangeiros').checked;
  let lista = ELENCO.slice();
  if (soEstr) lista = lista.filter(function(j){ return j.estrangeiro === true; });
  if (ordenarPor) {
    lista.sort(function(a,b){
      const va = a[ordenarPor], vb = b[ordenarPor];
      // ausência vai sempre pro fim, independente da direção
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (va === vb) return 0;
      return (va > vb ? 1 : -1) * (ordemAsc ? 1 : -1);
    });
  }
  document.getElementById('contador').textContent =
    lista.length + ' de ' + ELENCO.length + ' jogadores' +
    (soEstr ? ' (estrangeiros)' : '');

  if (!lista.length) {
    document.getElementById('tabela').innerHTML = '<div class="estado">Nenhum jogador com esse filtro.</div>';
    return;
  }
  let h = '<table><thead><tr>';
  COLUNAS.forEach(function(c){
    h += '<th onclick="ordenar(\\'' + c.k + '\\')"' + (c.num ? ' style="text-align:right"' : '') + '>' +
         c.t + (ordenarPor === c.k ? (ordemAsc ? ' ↑' : ' ↓') : '') + '</th>';
  });
  h += '</tr></thead><tbody>';
  lista.forEach(function(j){
    const escalado = SLOTS.some(function(s){ return s.id === j.id; });
    h += '<tr draggable="true" data-id="' + j.id + '"' + (escalado ? ' class="escalado"' : '') + '>';
    h += '<td class="num">' + (j.numero !== null ? j.numero : '<span class="vazio">—</span>') + '</td>';
    h += '<td><div class="jog">' + (j.foto ? imgFoto(j, '', '') : '<img alt="">') +
         '<span>' + (j.nome || '—') + (j.lesionado ? ' 🤕' : '') + '</span></div></td>';
    // Se o emoji não sair (código fora do ISO de 2 letras), usa a imagem da
    // bandeira que a API fornece — melhor que a linha ficar sem sinal nenhum.
    const marcaPais = j.pais_bandeira ? j.pais_bandeira + ' '
      : (j.pais_flag_url ? '<img src="' + j.pais_flag_url + '" style="width:16px;height:11px;object-fit:cover;vertical-align:-1px;margin-right:4px">' : '');
    h += '<td>' + marcaPais +
         (j.nacionalidade ? j.nacionalidade : '<span class="vazio">não informado</span>') + '</td>';
    h += '<td class="num">' + na(j.idade) + '</td>';
    h += '<td class="num">' + (na(j.altura) === '—' ? '<span class="vazio">—</span>' : j.altura + ' cm') + '</td>';
    h += '<td>' + (j.pe ? j.pe : '<span class="vazio">—</span>') + '</td>';
    h += '<td>' + (j.grupo ? '<span class="pos-tag pos-' + j.grupo + '">' + GRUPO_PT[j.grupo] + '</span> ' : '') +
         (j.posicao ? j.posicao : '<span class="vazio">—</span>') + '</td>';
    ['jogos','gols','assistencias','amarelos','vermelhos'].forEach(function(k){
      h += '<td class="num">' + na(j[k]) + '</td>';
    });
    h += '<td class="num">' + (na(j.minutos) === '—' ? '<span class="vazio">—</span>' : j.minutos + "'") + '</td>';
    h += '</tr>';
  });
  h += '</tbody></table>';
  const cont = document.getElementById('tabela');
  cont.innerHTML = h;
  ligarReserva(cont);
  cont.querySelectorAll('tbody tr').forEach(function(tr){
    tr.addEventListener('dragstart', function(ev){
      ev.dataTransfer.setData('text/plain', JSON.stringify({de:'lista', id:Number(tr.dataset.id)}));
    });
  });
}

// ── início ──
document.getElementById('formacao').innerHTML =
  Object.keys(FORMACOES).map(function(f){
    return '<option value="' + f + '"' + (f === FORM ? ' selected' : '') + '>' + f + '</option>';
  }).join('');
aplicarFormacao(FORM);
renderCampo();
carregarTimes();
</script>
</body>
</html>
"""

# ── Página de Elencos ────────────────────────────────────────────────────────
# Escrita como string simples (sem f-string) de propósito: o CSS e o JS desta
# tela são grandes e, num f-string, cada chave precisaria ser duplicada — origem
# recorrente de erro neste arquivo. Os trechos dinâmicos entram por replace.

# Cada casa do campo: x e y em %, e o grupo (G/D/M/A) que guia o preenchimento
# automático. y=92 é a área do goleiro, y=14 é o ataque.
_ELENCOS_FORMACOES = {
    "4-3-3":   [(50,92,"G"),(12,74,"D"),(37,77,"D"),(63,77,"D"),(88,74,"D"),
                (30,54,"M"),(50,60,"M"),(70,54,"M"),(15,24,"A"),(50,16,"A"),(85,24,"A")],
    "4-2-3-1": [(50,92,"G"),(12,74,"D"),(37,77,"D"),(63,77,"D"),(88,74,"D"),
                (36,60,"M"),(64,60,"M"),(15,36,"M"),(50,38,"M"),(85,36,"M"),(50,16,"A")],
    "4-4-2":   [(50,92,"G"),(12,74,"D"),(37,77,"D"),(63,77,"D"),(88,74,"D"),
                (12,52,"M"),(38,56,"M"),(62,56,"M"),(88,52,"M"),(38,18,"A"),(62,18,"A")],
    "4-1-4-1": [(50,92,"G"),(12,74,"D"),(37,77,"D"),(63,77,"D"),(88,74,"D"),
                (50,62,"M"),(12,42,"M"),(38,44,"M"),(62,44,"M"),(88,42,"M"),(50,16,"A")],
    "3-5-2":   [(50,92,"G"),(27,77,"D"),(50,79,"D"),(73,77,"D"),
                (8,55,"M"),(34,55,"M"),(50,60,"M"),(66,55,"M"),(92,55,"M"),(38,18,"A"),(62,18,"A")],
    "3-4-3":   [(50,92,"G"),(27,77,"D"),(50,79,"D"),(73,77,"D"),
                (10,55,"M"),(38,58,"M"),(62,58,"M"),(90,55,"M"),
                (15,24,"A"),(50,16,"A"),(85,24,"A")],
    "5-3-2":   [(50,92,"G"),(8,66,"D"),(27,78,"D"),(50,80,"D"),(73,78,"D"),(92,66,"D"),
                (30,52,"M"),(50,57,"M"),(70,52,"M"),(38,18,"A"),(62,18,"A")],
}


@app.get("/elencos", response_class=HTMLResponse)
async def elencos_page():
    return HTMLResponse(
        _ELENCOS_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__HDR__", _header("/elencos"))
        .replace("__FORMACOES__", json.dumps(
            {k: [{"x": x, "y": y, "g": g} for x, y, g in v]
             for k, v in _ELENCOS_FORMACOES.items()}, ensure_ascii=False))
    )


_POSTS_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agendamentos · IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
:root{--bg:var(--c-bg);--surface:var(--c-bg-card);--surface2:var(--c-bg-soft);
  --border:var(--c-border);--text:var(--c-text);--text2:var(--c-muted-3);--accent:var(--c-acento)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:18px 16px 60px}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--text2);font-size:.8rem;margin:0 0 14px}
.barra{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.ctrl{padding:7px 12px;border-radius:8px;border:1px solid var(--border);
  background:var(--surface);color:var(--text);font-size:13px;cursor:pointer}
.ctrl:disabled{opacity:.5;cursor:default}
.selo{font-size:.7rem;padding:2px 8px;border-radius:20px;font-weight:700}
.s-pendente{background:#FFBE5D22;color:#FFBE5D}
.s-publicado{background:#B6FF0022;color:#B6FF00}
.s-cancelado{background:#6b728022;color:#9ca3af}
.s-publicando{background:#B6FF0022;color:#60a5fa}
.s-aprovado{background:#1d9bf022;color:#60c8f0}
.canais{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.canal{font-size:.72rem;padding:5px 10px;border-radius:20px;border:1px solid var(--border);
  background:var(--surface2);color:var(--text2);cursor:pointer;user-select:none}
.canal.on{border-color:var(--accent);background:#1d9bf022;color:#8ed0f7;font-weight:700}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:14px;margin-bottom:12px}
.topo{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.quando{font-size:.75rem;color:var(--text2)}
textarea{width:100%;background:var(--surface2);color:var(--text);border:1px solid var(--border);
  border-radius:10px;padding:10px;font-family:inherit;font-size:.85rem;line-height:1.5;
  min-height:120px;resize:vertical}
.agenda{display:flex;gap:8px;overflow-x:auto;padding:4px 2px 12px;-webkit-overflow-scrolling:touch}
.dia-bt{min-width:74px;flex-shrink:0;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:8px 6px;text-align:center;cursor:pointer;transition:.15s}
.dia-bt:hover{border-color:var(--accent)}
.dia-bt.sel{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent)}
.dia-sem{font-size:.6rem;text-transform:uppercase;letter-spacing:.07em;color:var(--text2)}
.dia-num{font-size:1.3rem;font-weight:700;line-height:1.2}
.dia-qtd{font-size:.6rem;color:var(--text2);margin-top:2px;min-height:.9em}
.dia-bt.vazio{opacity:.42}
.dia-bt.hoje .dia-num{color:var(--accent)}
.jogos{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:4px 12px;margin-bottom:16px}
.jogo{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:.82rem;
  border-bottom:1px solid var(--border);flex-wrap:wrap}
.jogo:last-child{border-bottom:none}
.jogo-hora{font-variant-numeric:tabular-nums;color:var(--text2);min-width:44px}
.jogo-nome{flex:1;min-width:150px}
.tag{font-size:.6rem;padding:2px 8px;border-radius:20px;border:1px solid var(--border);color:var(--text2)}
.tag.ok{border-color:var(--accent);color:var(--accent)}
.escudos{display:flex;gap:8px;margin:10px 0;flex-wrap:wrap}
.escudo-vazio{width:44px;height:44px;border-radius:8px;border:1px dashed var(--border);
  background:var(--surface2);display:flex;align-items:center;justify-content:center;
  cursor:pointer;color:var(--text2);font-size:1.35rem;line-height:1}
.escudo-vazio:hover{border-color:var(--accent);color:var(--accent)}
.abas{display:flex;gap:8px;margin:16px 0 14px;border-bottom:1px solid var(--c-border)}
.aba{background:none;border:none;border-bottom:2px solid transparent;color:var(--c-muted-3);
  font-size:.82rem;font-weight:700;padding:8px 14px 10px;cursor:pointer;
  display:flex;align-items:center;gap:7px;margin-bottom:-1px;
  font-family:inherit;transition:color .15s,border-color .15s}
.aba:hover{color:var(--c-text)}
.aba.ativa{color:var(--c-text);border-bottom-color:#B6FF00}
.pilula{background:#B6FF00;color:#06210f;font-size:.6rem;font-weight:800;
  border-radius:99px;padding:1px 7px;display:none}
.pilula.tem{display:inline-block}
.duas{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:760px){.duas{grid-template-columns:1fr}}
.fonte{border:1px solid var(--c-border);border-radius:10px;padding:10px 12px;
  background:var(--c-bg-soft)}
.fonte h4{margin:0 0 8px;font-size:.66rem;text-transform:uppercase;
  letter-spacing:.08em;color:var(--c-muted-3);display:flex;align-items:center;gap:8px}
.fonte pre{white-space:pre-wrap;font-family:inherit;font-size:.86rem;
  line-height:1.55;margin:0}
.gol-linha{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:12px;padding:12px 14px;margin-bottom:10px}
.gol-cab{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.gol-min{font-weight:800;font-size:.95rem}
.dif{font-size:.66rem;font-weight:800;border-radius:99px;padding:3px 10px;
  border:1.5px solid var(--c-border-2);color:var(--c-muted-4)}
.dif.af{border-color:#B6FF00;color:#B6FF00}
.dif.sm{border-color:#B6FF00;color:#B6FF00}
/* Etiqueta de provável/oficial no cabeçalho de cada fonte. */
.marca{font-size:.6rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;
  border-radius:99px;padding:2px 7px;margin-left:7px;border:1px solid var(--c-border-2);
  color:var(--c-muted-4)}
.marca.ok{border-color:#B6FF00;color:#B6FF00}
.marca.prov{border-color:#FFBE5D;color:#FFBE5D}
.escudos img{width:44px;height:44px;object-fit:contain;background:var(--surface2);
  border-radius:8px;padding:3px}
.acoes{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.conta{font-size:.72rem;color:var(--text2)}
.erro{font-size:.75rem;color:#FD5D5D;margin-top:6px}
.aviso{background:#FFBE5D18;border:1px solid #FFBE5D55;color:#FFBE5D;
  border-radius:10px;padding:10px;font-size:.8rem;margin-bottom:14px}
.estado{padding:30px;text-align:center;color:var(--text2);font-size:.85rem}
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Agendamentos</h1>
  <p class="sub">Clique num dia para montar a fila dele e ver só os posts daquele dia.
     Clicar de novo não duplica: confere escudos e cores. Você marca a transmissão e aprova —
     aí o post sai sozinho no horário do apito. Sem aprovação, nada é publicado.</p>
  <div id="statusX"></div>
  <div class="barra">
    <button class="ctrl" onclick="carregar()">↻ Atualizar</button>
    <select id="filtro" class="ctrl" onchange="carregar()">
      <option value="pendente">Pendentes</option>
      <option value="aprovado">Aprovados (saem no apito)</option>
      <option value="">Todos</option>
      <option value="publicado">Publicados</option>
      <option value="cancelado">Cancelados</option>
    </select>
    <span id="contador" class="conta"></span>
  </div>
  <div id="agenda" class="agenda"><div class="conta">Carregando a semana…</div></div>
  <div id="nota-dia" class="conta" style="margin:-4px 2px 10px"></div>
  <div id="dia"></div>

  <div id="lista"><div class="estado">Carregando…</div></div>
</div>

<script>
let CANAIS = [];
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
// Tudo na tela em horário de Brasília. O banco guarda em UTC, que é o certo
// para não depender do fuso do servidor, mas quem lê é você.
function hora(iso){
  if(!iso) return 'sem horário';
  try{
    return new Date(iso).toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo',
      day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) + ' (BRT)';
  }catch(e){ return iso.replace('T',' ').slice(0,16); }
}
function horaCurta(iso){
  if(!iso) return '';
  try{
    return new Date(iso).toLocaleTimeString('pt-BR', {timeZone:'America/Sao_Paulo',
      hour:'2-digit', minute:'2-digit'});
  }catch(e){ return ''; }
}

async function carregar(){
  const filtro = document.getElementById('filtro').value;
  const lista = document.getElementById('lista');
  try{
    const d = await (await fetch('/api/posts/fila?status=' + filtro +
      (DIA_SEL ? '&dia=' + DIA_SEL : '') + '&_=' + Date.now())).json();
    document.getElementById('statusX').innerHTML = d.x_configurado ? '' :
      '<div class="aviso">As credenciais do X ainda não estão no Railway (faltando: ' +
      esc((d.x_faltando||[]).join(', ')) + '). A fila funciona, mas publicar vai falhar.</div>';
    document.getElementById('contador').textContent =
      d.posts.length + ' post(s)' +
      (DIA_SEL ? ' em ' + diaCurto(DIA_SEL) : ' de todos os dias') +
      ' · ' + d.publicados_24h + ' publicados em 24h (teto ' + d.limite_diario + ')';
    if(!d.posts.length){ lista.innerHTML = '<div class="estado">Nada aqui.</div>'; return; }
    CANAIS = d.canais || [];
    lista.innerHTML = d.posts.map(cartao).join('');
  }catch(e){
    lista.innerHTML = '<div class="estado">Erro: ' + esc(e.message) + '</div>';
  }
}

function cartao(p){
  const pend = p.status === 'pendente';
  return '<div class="card" id="p' + p.id + '">' +
    '<div class="topo">' +
      '<span class="selo s-' + p.status + '">' + p.status + '</span>' +
      '<span class="quando">' + esc(p.tipo) + ' · ' + hora(p.agendado_para) + '</span>' +
    '</div>' +
    (pend ? '<textarea id="t' + p.id + '" oninput="contarTexto(' + p.id + ')">' + esc(p.texto) + '</textarea>'
          : '<div style="white-space:pre-wrap;font-size:.85rem;line-height:1.5">' + esc(p.texto) + '</div>') +
    (pend ? '<div class="conta" id="c' + p.id + '"></div>' : '') +
    (pend ? '<div class="canais">' + CANAIS.map(function(c){
        const on = Array.isArray(p.canais) && p.canais.indexOf(c) > -1;
        return '<span class="canal' + (on ? ' on' : '') + '" data-post="' + p.id +
               '" data-canal="' + esc(c) + '" onclick="alternarCanal(this)">' + esc(c) + '</span>';
      }).join('') + '</div>' : '') +
    linhaEscudos(p) +
    (p.erro ? '<div class="erro">⚠️ ' + esc(p.erro) + '</div>' : '') +
    (pend ? '<div class="acoes">' +
        '<button class="ctrl" onclick="salvar(' + p.id + ')">Salvar texto</button>' +
        '<button class="ctrl" style="border-color:var(--accent);color:var(--accent)" ' +
          'onclick="aprovar(' + p.id + ')">✅ Aprovar (sai no apito)</button>' +
        '<button class="ctrl" onclick="publicar(' + p.id + ')">Publicar agora</button>' +
        '<button class="ctrl" onclick="cancelar(' + p.id + ')">Cancelar</button>' +
      '</div>' : '') +
    (p.status === 'aprovado' ? '<div class="acoes">' +
        '<span class="conta">Sai sozinho às ' + horaCurta(p.agendado_para) + ' de Brasília.</span>' +
        '<button class="ctrl" onclick="desaprovar(' + p.id + ')">Voltar para pendente</button>' +
      '</div>' : '') +
  '</div>';
}


// O X pesa cada ponto de código: latim e pontuação valem 1, todo o resto vale
// 2 — emoji, árabe, e o "𝑮𝑶𝑶…𝑳", que é feito de símbolos matemáticos. Um texto
// de 200 símbolos pode passar de 280 no X. Contar aqui igual ao servidor
// evita descobrir isso só na hora de publicar, com o jogo andando.
function pesoX(t) {
  let n = 0;
  for (const ch of String(t || '')) {
    const c = ch.codePointAt(0);
    const leve = (c <= 4351) || (c >= 8192 && c <= 8205)
              || (c >= 8208 && c <= 8223) || (c >= 8242 && c <= 8247);
    n += leve ? 1 : 2;
  }
  return n;
}

function contarTexto(id){
  const t = document.getElementById('t' + id).value;
  const c = document.getElementById('c' + id);
  const link = /https?:\\/\\/|www\\./i.test(t);
  const peso = pesoX(t);
  c.textContent = peso + '/280' + (link ? ' · ATENÇÃO: tem link, custa 13x mais e será recusado' : '');
  c.style.color = (peso > 280 || link) ? '#FD5D5D' : '';
}

// Manda para o servidor o que está na caixa de texto AGORA.
// Aprovar e publicar chamam isto antes de agir: sem essa etapa, editar o texto
// e clicar direto em Aprovar perdia a edição em silêncio, e o Publicar agora
// chegava a mostrar o texto editado na confirmação e publicar o antigo.
async function salvarCaixa(id){
  const t = document.getElementById('t' + id);
  if(!t) return true;                       // post não editável, nada a salvar
  try{
    const d = await (await fetch('/api/posts/' + id + '/texto', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({texto: t.value})})).json();
    if(d.erro){ alert(d.erro); return false; }
  }catch(e){ alert('Não consegui salvar o texto.'); return false; }
  return true;
}

async function salvar(id){
  if(await salvarCaixa(id)) carregar();
}

async function publicar(id){
  const t = document.getElementById('t' + id);
  if(t && !confirm('Publicar este post agora na conta do X?\\n\\n' + t.value)) return;
  if(!await salvarCaixa(id)) return;        // publica o que você acabou de ver
  const d = await (await fetch('/api/posts/' + id + '/publicar', {method:'POST'})).json();
  if(d.erro) alert('Não publicou: ' + d.erro);
  carregar();
}

async function cancelar(id){
  if(!confirm('Cancelar este post? Ele sai da fila e não será publicado.')) return;
  await fetch('/api/posts/' + id + '/cancelar', {method:'POST'});
  carregar();
}

async function alternarCanal(el){
  const id = el.dataset.post;
  const marcados = [];
  document.querySelectorAll('.canal[data-post="' + id + '"]').forEach(function(c){
    if (c === el) c.classList.toggle('on');
    if (c.classList.contains('on')) marcados.push(c.dataset.canal);
  });
  const d = await (await fetch('/api/posts/' + id + '/transmissao', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({canais: marcados})})).json();
  if (d.erro) { alert(d.erro); return; }
  const t = document.getElementById('t' + id);
  if (t && d.texto) { t.value = d.texto; contarTexto(id); }
}

async function aprovar(id){
  if(!await salvarCaixa(id)) return;
  const d = await (await fetch('/api/posts/' + id + '/aprovar', {method:'POST'})).json();
  if (d.erro) alert(d.erro);
  carregar();
}

async function desaprovar(id){
  await fetch('/api/posts/' + id + '/desaprovar', {method:'POST'});
  carregar();
}

// Muda a cada upload para furar o cache do navegador. Sem isso, o escudo que
// você acabou de subir continuaria mostrando a versão 404 guardada.
let JANELA = Date.now();

// ── Escudos do post ────────────────────────────────────────────────────────
// O que falta vira quadrado clicável aqui mesmo, no post, em vez de imagem
// quebrada. O servidor manda p.escudos com um "tem" por escudo justamente
// para a tela não precisar adivinhar pelo erro de carregamento.
function linhaEscudos(p){
  const lista = p.escudos || (p.imagens||[]).map(function(i){ return {ref:i, tem:true}; });
  if(!lista.length) return '';
  return '<div class="escudos">' + lista.map(function(e){
    if(e.tem) return '<img src="/api/posts/imagem?p=' + encodeURIComponent(e.ref) +
                     '&v=' + JANELA + '" alt="">';
    return '<div class="escudo-vazio" data-chave="' + esc(e.chave||'') +
           '" title="Sem escudo — clique para enviar">+</div>';
  }).join('') + '</div>';
}

// ── Agenda dos 7 dias ──────────────────────────────────────────────────────
let AGENDA = [], DIA_SEL = null, PRIMEIRA = true;
const SEMANA = ['dom','seg','ter','qua','qui','sex','sáb'];

async function carregarAgenda(){
  try{
    const d = await (await fetch('/api/posts/agenda?_=' + Date.now())).json();
    AGENDA = d.dias || [];
  }catch(e){
    document.getElementById('agenda').innerHTML =
      '<div class="conta">Não consegui carregar a semana.</div>';
    return;
  }
  if(PRIMEIRA && AGENDA.length){ DIA_SEL = AGENDA[0].data; PRIMEIRA = false; }
  pintarAgenda();
}

// Só desenha, sem ir à rede: trocar de dia selecionado não muda os jogos da
// semana, e buscar de novo só para repintar um contorno seria desperdício.
function pintarAgenda(){
  const alvo = document.getElementById('agenda');
  alvo.innerHTML = '';
  AGENDA.forEach(function(dia, i){
    // A data vem como AAAA-MM-DD; monto com Date(ano, mes, dia) para o
    // navegador não interpretar como UTC e mostrar o dia anterior.
    const pt = dia.data.split('-').map(Number);
    const dt = new Date(pt[0], pt[1]-1, pt[2]);
    const n = dia.jogos.length;
    const bt = document.createElement('div');
    bt.className = 'dia-bt' + (n ? '' : ' vazio') + (i === 0 ? ' hoje' : '') +
                   (dia.data === DIA_SEL ? ' sel' : '');
    bt.innerHTML = '<div class="dia-sem">' + SEMANA[dt.getDay()] + '</div>' +
                   '<div class="dia-num">' + pt[2] + '</div>' +
                   '<div class="dia-qtd">' + (n ? n + (n>1?' jogos':' jogo') : '—') + '</div>';
    // Clicar no dia JÁ monta a fila dele. Não separo em dois botões porque a
    // montagem é idempotente: clicar de novo não duplica, só repõe escudo e
    // cor de post que já estava lá.
    bt.addEventListener('click', function(){ escolherDia(dia.data); });
    alvo.appendChild(bt);
  });
  // Chip de escape: sem ele, com o clique no dia virando montagem, não haveria
  // como voltar a ver a fila inteira — post de ontem ou de daqui a duas
  // semanas ficaria invisível.
  const todos = document.createElement('div');
  todos.className = 'dia-bt' + (DIA_SEL === null ? ' sel' : '');
  todos.innerHTML = '<div class="dia-sem">ver</div>' +
                    '<div class="dia-num" style="font-size:.95rem;padding:.2em 0">todos</div>' +
                    '<div class="dia-qtd">sem montar</div>';
  todos.addEventListener('click', function(){
    DIA_SEL = null;
    document.getElementById('nota-dia').textContent = '';
    pintarAgenda();
    carregar();
  });
  alvo.appendChild(todos);

  mostrarDia();
}

// Escolher um dia = filtrar a fila por ele E montar o que falta. O aviso fica
// numa linha discreta em vez de alert, porque agora isso roda a cada clique.
async function escolherDia(data){
  DIA_SEL = data;
  pintarAgenda();
  carregar();
  const nota = document.getElementById('nota-dia');
  nota.textContent = 'Montando a fila…';
  try{
    const d = await (await fetch('/api/posts/gerar', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({data: data})})).json();
    nota.textContent = d.erro ? ('Erro: ' + d.erro)
      : (d.novos + ' montado(s), ' + d.ja_estavam + ' já estavam' +
         (d.consertados ? ', ' + d.consertados + ' corrigido(s)' : '') + '.' +
         ((d.avisos||[]).length ? ' ⚠️ ' + d.avisos.join(' · ') : ''));
  }catch(e){
    nota.textContent = 'Não consegui montar a fila deste dia.';
  }
  await carregarAgenda();
  carregar();
}

function diaCurto(iso){
  const p = iso.split('-');
  return p[2] + '/' + p[1];
}

function mostrarDia(){
  const alvo = document.getElementById('dia');
  const dia = AGENDA.find(function(x){ return x.data === DIA_SEL; });
  alvo.innerHTML = '';
  if(!dia) return;
  const cx = document.createElement('div');
  cx.className = 'jogos';
  if(!dia.jogos.length){
    cx.innerHTML = '<div class="jogo"><span class="conta">Nenhum jogo neste dia.</span></div>';
    alvo.appendChild(cx); return;
  }
  dia.jogos.forEach(function(j){
    const l = document.createElement('div');
    l.className = 'jogo';
    let tag = '<span class="tag">a montar</span>';
    if(j.status === 'publicado')      tag = '<span class="tag ok">publicado</span>';
    else if(j.status === 'aprovado')  tag = '<span class="tag ok">aprovado</span>';
    else if(j.status === 'pendente')  tag = '<span class="tag ok">na fila</span>';
    else if(j.status === 'cancelado') tag = '<span class="tag">cancelado</span>';
    else if(j.passou)                 tag = '<span class="tag">já começou</span>';
    l.innerHTML = '<span class="jogo-hora">' + esc(j.hora) + '</span>' +
                  '<span class="jogo-nome">' + esc(j.casa) + ' vs ' + esc(j.fora) + '</span>' +
                  '<span class="tag">' + esc(j.competicao) + '</span>' + tag;
    cx.appendChild(l);
  });
  alvo.appendChild(cx);
}


function escolherImagem(chave){
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = 'image/*';
  inp.addEventListener('change', function(){
    if(inp.files && inp.files[0]) enviarImagem(chave, inp.files[0]);
  });
  inp.click();
}

// Redimensiona no navegador para 512px PNG. Assim o servidor nao precisa de
// biblioteca de imagem (o projeto nao tem Pillow) e o escudo sai no mesmo
// padrao dos 33 que ja vieram no pacote.
function enviarImagem(chave, arquivo){
  const leitor = new FileReader();
  leitor.onload = function(){
    const img = new Image();
    img.onload = async function(){
      const cv = document.createElement('canvas');
      cv.width = 512; cv.height = 512;
      const ctx = cv.getContext('2d');
      const escala = Math.min(512 / img.width, 512 / img.height);
      const w = img.width * escala, h = img.height * escala;
      ctx.drawImage(img, (512 - w) / 2, (512 - h) / 2, w, h);
      try{
        const d = await (await fetch('/api/clubes/extra', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({chave: chave, escudo_base64: cv.toDataURL('image/png')})})).json();
        if(d.erro){ alert(d.erro); return; }
      }catch(e){ alert('Falha ao enviar.'); return; }
      JANELA = Date.now();
      carregar();               // o quadrado vazio no post vira o escudo
    };
    img.onerror = function(){ alert('Nao consegui ler essa imagem.'); };
    img.src = leitor.result;
  };
  leitor.readAsDataURL(arquivo);
}

// Clique no quadrado vazio dentro do post: a lista é redesenhada inteira a
// cada carregamento, então escuto no contêiner em vez de em cada quadrado.
document.getElementById('lista').addEventListener('click', function(ev){
  const q = ev.target.closest('.escudo-vazio');
  if(q && q.dataset.chave) escolherImagem(q.dataset.chave);
});

// A agenda vem primeiro: é ela que decide o dia, e a fila é filtrada por ele.
// Invertido, o primeiro carregamento mostraria todos os dias por um instante.
carregarAgenda().then(carregar);
</script>
</body>
</html>
"""


@app.get("/posts", response_class=HTMLResponse)
async def posts_page():
    return HTMLResponse(
        _POSTS_HTML
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__HDR__", _header("/posts"))
    )


@app.post("/api/clubes/extra")
async def api_clubes_extra_salvar(request: Request):
    """Grava o escudo (PNG em base64) de um clube que não veio no pacote."""
    try:
        corpo = await request.json()
    except Exception:
        return {"erro": "corpo inválido"}
    chave = (corpo.get("chave") or "").strip().lower()
    if not chave:
        return {"erro": "clube não informado"}

    escudo = None
    b64 = corpo.get("escudo_base64") or ""
    if b64:
        try:
            if "," in b64:
                b64 = b64.split(",", 1)[1]      # tira o prefixo data:image/...
            bruto = base64.b64decode(b64)
            # A tela já entrega em 512px PNG, redimensionado no navegador. Fazer
            # isso no servidor exigiria Pillow, que o projeto não tem — e eu quase
            # subi um endpoint dependendo de biblioteca ausente.
            if len(bruto) > 3 * 1024 * 1024:
                return {"erro": "imagem acima de 3 MB mesmo depois do redimensionamento"}
            if not bruto.startswith(b"\x89PNG\r\n\x1a\n"):
                return {"erro": "a imagem precisa ser PNG"}
            escudo = bruto
        except Exception as e:
            return {"erro": f"não consegui ler a imagem: {type(e).__name__}"}

    if escudo is None:
        return {"erro": "nenhuma imagem enviada"}
    return {"ok": salvar_clube_extra(chave, corpo.get("nome"), escudo),
            "chave": chave}


@app.get("/api/posts/imagem")
async def api_posts_imagem(p: str):
    """Mostra na tela um escudo que já está no projeto."""
    dados = _bytes_da_imagem(p)
    if not dados:
        return Response(status_code=404)
    # Cache curto para o que veio do banco: você acabou de subir e quer ver.
    idade = 60 if p.startswith("db:") else 86400
    return Response(content=dados, media_type="image/png",
                    headers={"Cache-Control": f"public, max-age={idade}"})


# ── Fila de posts das redes ──────────────────────────────────────────────────

_PAISES_AF: tuple[float, dict] | None = None
_PAIS_DO_TIME: dict[int, str] = {}


async def _af_mapa_paises() -> dict:
    """{nome do país: código ISO}, vindo do endpoint /countries da própria API."""
    global _PAISES_AF
    if _PAISES_AF and (time.time() - _PAISES_AF[0]) < 86400:
        return _PAISES_AF[1]
    data, err = await _af_get("countries", {}, ttl=86400)
    if err or not data:
        return _PAISES_AF[1] if _PAISES_AF else {}
    mapa = {}
    for c in data.get("response", []):
        nome, code = c.get("name"), c.get("code")
        if nome and code:
            mapa[nome.lower()] = code
            mapa[nome.replace("-", " ").lower()] = code
    if mapa:
        _PAISES_AF = (time.time(), mapa)
    return mapa


def _bandeira_iso(code: str | None) -> str | None:
    c = (code or "").strip()
    if len(c) == 2 and c.isalpha():
        return "".join(chr(0x1F1E6 + ord(x) - ord("A")) for x in c.upper())
    if "-" in c:
        corpo = c.lower().replace("-", "")
        if corpo.isalnum():
            return "\U0001F3F4" + "".join(chr(0xE0000 + ord(x)) for x in corpo) + "\U000E007F"
    return None


async def _pais_do_time(team_id: int) -> str | None:
    """País do clube. Vem de /teams porque a resposta de fixtures não traz."""
    if team_id in _PAIS_DO_TIME:
        return _PAIS_DO_TIME[team_id]
    data, err = await _af_get("teams", {"id": team_id}, ttl=86400)
    if err or not data:
        return None
    resp = data.get("response") or []
    pais = ((resp[0].get("team") if resp else None) or {}).get("country")
    if pais:
        _PAIS_DO_TIME[team_id] = pais
    return pais


async def _marcas_do_jogo(liga_id: int, casa: dict, fora: dict) -> tuple[str, str]:
    """Cor do clube em competição nacional; bandeira do país nas internacionais.

    Na AFC o post fica '🇸🇦 Nassr vs Vissel Kobe 🇯🇵' — a cor do clube não diz
    nada quando o adversário é de outro país."""
    import posts_gerador as pg
    if liga_id not in pg.COMPETICOES_INTERNACIONAIS:
        saida = []
        for t in (casa, fora):
            nome = t.get("name") or ""
            # Sem cor conhecida o post sai sem emoji nessa posição, e você
            # completa à mão. O cadastro de cores foi tirado a pedido: a tela
            # dele existia só para isso, e editar o texto do post é mais rápido
            # do que manter um cadastro paralelo.
            saida.append(TEAM_CORES.get(nome, ""))
        return saida[0], saida[1]
    mapa = await _af_mapa_paises()
    marcas = []
    for t in (casa, fora):
        pais = await _pais_do_time(t.get("id")) if t.get("id") else None
        code = mapa.get((pais or "").lower()) if pais else None
        marcas.append(_bandeira_iso(code) or "")
    return marcas[0], marcas[1]


async def _season_da_liga(league_id: int, ano_inicio: int) -> int:
    """Rótulo que a API usa para a temporada que COMEÇA em ano_inicio.

    A Liga chama 2026/27 de 2026; a Copa do Rei chama de 2027. Consultar com o
    número errado devolve zero jogos em silêncio — foi o que aconteceu quando
    procurei a Copa do Rei de amanhã com season=2026."""
    mapa = await _af_league_start_years(league_id)
    for rotulo, inicio in (mapa or {}).items():
        if inicio == ano_inicio:
            return rotulo
    return ano_inicio


def _mudar_transmissoes_para_tabela() -> int:
    """Passa para a tabela o que hoje só existe escrito dentro dos posts.

    Roda uma vez e deixa recado no app_state. Não é caro nem perigoso repetir
    — é INSERT ... ON CONFLICT — mas repetir escreveria por cima de uma
    marcação feita à mão depois, e essa seria a única perda possível aqui.

    Só migra post com canal marcado. O "❌ Sem transmissão" NÃO entra, e este
    é o detalhe que quase passou: essa linha não é uma decisão sua, é o que o
    gerador escreve em todo post no momento em que ele nasce. Migrar o ❌ como
    [] carimbaria "olhei e não tem" em jogo nenhum que você tenha olhado —
    apagando na migração exatamente a diferença que a tabela existe para
    guardar. Daqui para frente o ❌ vale, porque aí ele veio de um clique seu.
    """
    import posts_gerador as pg
    if get_state("transmissao_migrada") == "sim":
        return 0
    movidos = 0
    try:
        for p in listar_posts(limite=1000):
            fid = pg.jogo_da_chave(p.get("chave_unica"))
            if fid is None:
                continue
            canais = pg.canais_da_linha(p.get("texto"))
            if not canais:      # None (sem linha) e [] (o ❌ de fábrica)
                continue
            if marcar_transmissao(fid, canais):
                movidos += 1
        set_state("transmissao_migrada", "sim")
    except Exception as e:
        # Sem marcar como migrada: se falhou no meio, a próxima subida termina.
        print(f"[SUBIDA] transmissões: {type(e).__name__}: {e}", flush=True)
        raise
    print(f"[SUBIDA] transmissões movidas para a tabela: {movidos}", flush=True)
    return movidos


def _limpar_posts_de_competicao_removida() -> int:
    """Cancela post ainda parado na fila de competição que saiu da lista.

    Tirar uma competição de posts_gerador.COMPETICOES impede novos posts, mas
    não apaga os que já estavam enfileirados — eles continuariam aparecendo
    para aprovação e poderiam até ser publicados. Roda na subida do app porque
    é exatamente aí que a lista pode ter mudado (um deploy).

    Só mexe em pendente e aprovado. Publicado e cancelado ficam como estão:
    neles o status já é o registro do que aconteceu.
    """
    import posts_gerador as pg
    validas = set(pg.COMPETICOES.values())
    n = 0
    for p in listar_posts(limite=300):
        if p.get("status") not in ("pendente", "aprovado"):
            continue
        # A competição vive na linha do troféu, no formato "🏆 rodada | nome".
        linha = next((l for l in (p.get("texto") or "").split("\n")
                      if l.startswith("🏆")), "")
        if "|" not in linha:
            continue
        comp = linha.split("|", 1)[1].strip()
        if comp and comp not in validas:
            marcar_post(p["id"], "cancelado",
                        erro=f"{comp} saiu da lista de competições que viram post")
            n += 1
    if n:
        print(f"🧹 {n} post(s) cancelado(s): competição fora da lista")
    return n


async def gerar_bola_rolando(data_iso: str | None = None) -> dict:
    """Enfileira um BOLA ROLANDO para cada jogo saudita da data (padrão: amanhã).

    Idempotente pela chave do jogo: pode rodar quantas vezes quiser que não
    duplica. É de propósito — assim um reinício do Railway não vira problema.
    """
    import posts_gerador as pg
    inicio = _af_temporada_corrente()
    alvo = data_iso or (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    novos = repetidos = consertados = 0
    sem_escudo: list[str] = []
    por_competicao: dict[str, int] = {}
    erros: list[str] = []

    for liga_id, nome_comp in pg.COMPETICOES.items():
        season = await _season_da_liga(liga_id, inicio)
        data, err = await _af_get("fixtures", {"league": liga_id, "season": season,
                                               "date": alvo}, ttl=1800)
        if err:
            erros.append(f"{nome_comp}: {err}")
            continue
        for f in (data or {}).get("response", []):
            times = f.get("teams") or {}
            casa, fora = times.get("home") or {}, times.get("away") or {}
            nome_casa, nome_fora = casa.get("name") or "", fora.get("name") or ""
            if not nome_casa or not nome_fora:
                continue
            quando = (f.get("fixture") or {}).get("date")
            # Jogo que já começou não vira BOLA ROLANDO. Sem esta guarda, pedir
            # uma data passada enfileira posts que nunca deveriam sair.
            if quando:
                try:
                    if datetime.fromisoformat(quando) <= datetime.now(timezone.utc):
                        continue
                except ValueError:
                    pass
            cor_casa, cor_fora = await _marcas_do_jogo(liga_id, casa, fora)
            texto = pg.montar_bola_rolando(
                _time_curto(nome_casa), _time_curto(nome_fora),
                cor_casa, cor_fora,
                (f.get("league") or {}).get("round"), competicao=nome_comp)
            imagens = []
            for n in (nome_casa, nome_fora):
                cam = pg.escudo_de(n)
                if cam:
                    imagens.append(cam)
                    continue
                chave = pg._chave_clube(n)
                # Guarda a referência do banco mesmo que o escudo ainda não
                # exista. Assim, se você subir a imagem depois que o post já
                # entrou na fila, ela entra no post do mesmo jeito — a
                # resolução só acontece na hora de publicar. Gravar o caminho
                # resolvido aqui congelaria a ausência.
                imagens.append(f"db:{chave}")
                if not obter_escudo_extra(chave):
                    sem_escudo.append(n)
            fid = (f.get("fixture") or {}).get("id")
            r = enfileirar_post("bola_rolando", pg.chave_do_jogo(fid), texto, imagens, quando)
            if r == "novo":
                novos += 1
                por_competicao[nome_comp] = por_competicao.get(nome_comp, 0) + 1
            elif r == "ja_existia":
                repetidos += 1
            elif r == "escudos_atualizados":
                consertados += 1

    avisos = []
    if sem_escudo:
        avisos.append("sem escudo no projeto: " + ", ".join(sorted(set(sem_escudo))))
    avisos.extend(erros)
    return {"data": alvo, "novos": novos, "ja_estavam": repetidos,
            "consertados": consertados,
            "por_competicao": por_competicao, "avisos": avisos}


async def publicar_aprovados() -> dict:
    """Publica os posts aprovados cujo horário de início já chegou.

    Só toca em quem você aprovou. A janela de 25 minutos evita que uma queda do
    Railway ressuscite um post de horas atrás, quando a bola já rolou faz tempo."""
    agora = datetime.now(timezone.utc)
    publicados = falhas = 0
    for p in listar_posts("aprovado", limite=100):
        quando = p.get("agendado_para")
        if quando:
            try:
                dt = datetime.fromisoformat(quando)
                if dt > agora:
                    continue                      # ainda não é hora
                if (agora - dt).total_seconds() > 25 * 60:
                    marcar_post(p["id"], "pendente",
                                erro="passou muito do horário; publique à mão se ainda fizer sentido")
                    continue
            except ValueError:
                pass
        if not reservar_post_para_publicar(p["id"], de="aprovado"):
            continue
        try:
            fotos = [b for b in (_bytes_da_imagem(i) for i in (p.get("imagens") or [])) if b]
            r = await x_client.publicar(p["texto"], fotos,
                                        publicados_hoje=contar_publicados_hoje())
            marcar_post(p["id"], "publicado", post_id=r.get("id"))
            publicados += 1
        except Exception as e:
            marcar_post(p["id"], "aprovado", erro=str(e)[:400])
            falhas += 1
    return {"publicados": publicados, "falhas": falhas}


def _bytes_da_imagem(ref: str) -> bytes | None:
    """Converte a referência guardada na fila em bytes da imagem.

    Duas origens: arquivo do projeto (escudos que vieram no pacote) e banco
    (os que você subiu). Resolver só na hora de publicar mantém a fila leve."""
    if not ref:
        return None
    if ref.startswith("db:"):
        return obter_escudo_extra(ref[3:])
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "public", "escudos"))
    caminho = os.path.abspath(ref)
    if caminho.startswith(base + os.sep) and os.path.exists(caminho):
        with open(caminho, "rb") as f:
            return f.read()
    return None


@app.get("/api/posts/fila")
async def api_posts_fila(status: str = "", dia: str = ""):
    # Varre a fila antes de mostrar: post de jogo que já começou some daqui
    # sozinho, em vez de ficar competindo com os de hoje na sua tela.
    expirar_posts_vencidos()
    ok_x, faltando = x_client.configurado()
    import posts_gerador as pg
    # Com um dia escolhido no calendário, a lista embaixo mostra só aquele dia.
    # O limite sobe junto: filtrar em Python uma página de 60 esconderia posts
    # de um dia cheio só porque outros dias ocuparam a página.
    posts = listar_posts(status or None, limite=300 if dia else 60)
    if dia:
        def _no_dia(p):
            q = p.get("agendado_para")
            if not q:
                return False
            try:
                return datetime.fromisoformat(q).astimezone(BRT).date().isoformat() == dia
            except ValueError:
                return False
        posts = [p for p in posts if _no_dia(p)]
    # Diz para a tela, escudo a escudo, se a imagem existe. Sem isso ela só
    # descobre pelo <img> quebrado — foi exatamente o que apareceu no Jabalain.
    cache: dict[str, bool] = {}
    for p in posts:
        detalhe = []
        for ref in (p.get("imagens") or []):
            if ref.startswith("db:"):
                chave = ref[3:]
                if chave not in cache:
                    cache[chave] = tem_escudo_extra(chave)
                detalhe.append({"ref": ref, "chave": chave, "tem": cache[chave]})
            else:
                detalhe.append({"ref": ref, "chave": None, "tem": True})
        p["escudos"] = detalhe
    # De onde a tela sabe quais canais estão acesos. Antes ela procurava o nome
    # do canal dentro do texto do post — e "Sportv" está dentro de "Sportv 2",
    # então marcar o 2 acendia os dois. Agora vem da tabela; o texto só entra
    # como rede para os posts que existiam antes desta tabela.
    ids = {}
    for p in posts:
        fid = pg.jogo_da_chave(p.get("chave_unica"))
        if fid is not None:
            ids[p["id"]] = fid
    guardados = transmissoes(list(ids.values()))
    for p in posts:
        fid = ids.get(p["id"])
        if fid is not None and fid in guardados:
            p["canais"] = guardados[fid]
        else:
            p["canais"] = pg.canais_da_linha(p.get("texto"))
    return {"posts": posts,
            "canais": pg.TRANSMISSOES,
            "x_configurado": ok_x, "x_faltando": faltando,
            "publicados_24h": contar_publicados_hoje(),
            "limite_diario": x_client.LIMITE_DIARIO}


@app.get("/api/posts/agenda")
async def api_posts_agenda():
    """Os jogos de hoje e dos 6 dias seguintes, agrupados por data de Brasília.

    Puxa a tabela inteira de cada competição em vez de perguntar dia a dia:
    seriam 7 datas x 6 competições = 42 chamadas por abertura de tela, contra
    6 bem cacheadas. Também não depende de nenhum parâmetro de intervalo de
    data da API-Football, que eu não teria como confirmar daqui."""
    import posts_gerador as pg
    inicio = _af_temporada_corrente()
    hoje = datetime.now(BRT).date()
    dias = [(hoje + timedelta(days=i)).isoformat() for i in range(7)]
    por_dia: dict[str, list] = {d: [] for d in dias}
    erros: list[str] = []

    for liga_id, nome_comp in pg.COMPETICOES.items():
        season = await _season_da_liga(liga_id, inicio)
        data, err = await _af_get("fixtures", {"league": liga_id, "season": season},
                                  ttl=6 * 3600)
        if err:
            erros.append(f"{nome_comp}: {err}")
            continue
        for f in (data or {}).get("response", []):
            quando = (f.get("fixture") or {}).get("date")
            if not quando:
                continue
            try:
                dt = datetime.fromisoformat(quando).astimezone(BRT)
            except ValueError:
                continue
            dia = dt.date().isoformat()
            if dia not in por_dia:
                continue
            times = f.get("teams") or {}
            casa = (times.get("home") or {}).get("name") or ""
            fora = (times.get("away") or {}).get("name") or ""
            if not casa or not fora:
                continue
            fid = (f.get("fixture") or {}).get("id")
            por_dia[dia].append({
                "hora": dt.strftime("%H:%M"), "quando": quando,
                "casa": _time_curto(casa), "fora": _time_curto(fora),
                "competicao": nome_comp, "chave": pg.chave_do_jogo(fid),
            })

    estados = status_das_chaves([j["chave"] for lista in por_dia.values() for j in lista])
    agora = datetime.now(timezone.utc)
    saida = []
    for d in dias:
        jogos = sorted(por_dia[d], key=lambda j: j["hora"])
        for j in jogos:
            j["status"] = estados.get(j["chave"])
            try:
                j["passou"] = datetime.fromisoformat(j["quando"]) <= agora
            except ValueError:
                j["passou"] = False
        saida.append({
            "data": d, "jogos": jogos,
            "na_fila": sum(1 for j in jogos if j["status"] in ("pendente", "aprovado")),
            "a_montar": sum(1 for j in jogos if not j["status"] and not j["passou"]),
        })
    return {"dias": saida, "avisos": erros}


@app.post("/api/posts/gerar")
async def api_posts_gerar(request: Request):
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    return await gerar_bola_rolando(corpo.get("data") or None)


@app.post("/api/posts/{post_id}/texto")
async def api_posts_texto(post_id: int, request: Request):
    try:
        corpo = await request.json()
    except Exception:
        return {"erro": "corpo inválido"}
    texto = (corpo.get("texto") or "").strip()
    if not texto:
        return {"erro": "texto vazio"}
    if len(texto) > 280:
        return {"erro": f"texto com {len(texto)} caracteres; o limite do X é 280"}
    if x_client.texto_tem_link(texto):
        return {"erro": "o texto tem link, que custa 13x mais no X. Remova antes de salvar."}
    return {"ok": atualizar_texto_post(post_id, texto)}


@app.post("/api/posts/{post_id}/transmissao")
async def api_posts_transmissao(post_id: int, request: Request):
    """Regrava só a linha de transmissão, preservando o resto do post."""
    import posts_gerador as pg
    try:
        corpo = await request.json()
    except Exception:
        return {"erro": "corpo inválido"}
    item = obter_post(post_id)
    if not item or item["status"] != "pendente":
        return {"erro": "só dá pra editar post pendente"}
    canais = [c for c in (corpo.get("canais") or []) if c in pg.TRANSMISSOES]
    # Grava o fato antes de desenhar a linha. Se o texto do post der problema
    # mais adiante, a marcação do jogo já está salva — e é dela que vive o
    # relatório de prévia, não do texto.
    fid = pg.jogo_da_chave(item.get("chave_unica"))
    if fid is not None:
        marcar_transmissao(fid, canais)
    linhas = item["texto"].split("\n")
    nova = pg.linha_transmissao(canais)
    # A transmissão é sempre a última linha; trocar por posição evita mexer no
    # que o usuário porventura editou à mão nas linhas de cima.
    if linhas and (linhas[-1].startswith("🖥️") or linhas[-1].startswith("❌")):
        linhas[-1] = nova
    else:
        linhas.append(nova)
    texto = "\n".join(linhas)
    return {"ok": atualizar_texto_post(post_id, texto), "texto": texto}


@app.post("/api/posts/{post_id}/aprovar")
async def api_posts_aprovar(post_id: int):
    """Aprova para publicar sozinho no horário do apito."""
    item = obter_post(post_id)
    if not item or item["status"] != "pendente":
        return {"erro": "só dá pra aprovar post pendente"}
    if x_client.texto_tem_link(item["texto"]):
        return {"erro": "o texto tem link, que custa 13x mais no X"}
    return {"ok": marcar_post(post_id, "aprovado")}


@app.post("/api/posts/{post_id}/desaprovar")
async def api_posts_desaprovar(post_id: int):
    item = obter_post(post_id)
    if not item or item["status"] != "aprovado":
        return {"erro": "este post não está aprovado"}
    return {"ok": marcar_post(post_id, "pendente")}


@app.post("/api/posts/{post_id}/cancelar")
async def api_posts_cancelar(post_id: int):
    return {"ok": marcar_post(post_id, "cancelado")}


@app.post("/api/posts/{post_id}/publicar")
async def api_posts_publicar(post_id: int):
    """Publica no X. Só sai daqui por clique — nada publica sozinho."""
    item = obter_post(post_id)
    if not item:
        return {"erro": "post não encontrado"}
    if item["status"] != "pendente":
        return {"erro": f"este post está como '{item['status']}', não pendente"}
    # Reserva antes de chamar a API: dois cliques rápidos publicariam duas vezes.
    if not reservar_post_para_publicar(post_id):
        return {"erro": "outro envio já está em andamento para este post"}
    try:
        fotos = [b for b in (_bytes_da_imagem(i) for i in (item.get("imagens") or [])) if b]
        r = await x_client.publicar(item["texto"], fotos,
                                    publicados_hoje=contar_publicados_hoje())
    except Exception as e:
        marcar_post(post_id, "pendente", erro=str(e)[:400])
        return {"erro": str(e)}
    marcar_post(post_id, "publicado", post_id=r.get("id"))
    return {"ok": True, "post_id": r.get("id"), "custo": r.get("custo")}


@app.get("/api/elencos/times")
async def api_elencos_times():
    """Clubes da Saudi Pro League, deduzidos do calendário do Transfermarkt."""
    try:
        times, aviso = await elenco_tm.clubes()
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}
    return {"season": elenco_tm.TM_SAISON, "times": times,
            "avisos": [aviso] if aviso else []}


def _elenco_pais(nacs: list[str]) -> dict:
    """Primeira nacionalidade é a que vale; as demais ficam como informação extra.

    O TM lista a nacionalidade esportiva primeiro — Bounou sai como Marrocos, não
    Canadá, onde nasceu. É justamente o que faltava na API-Football, que devolvia
    o país de nascimento e obrigou a corrigir Faris Abdi e Quiñones à mão."""
    principal = (nacs[0] if nacs else None)
    return {
        "nacionalidade": principal,
        "nacionalidades": nacs or [],
        "pais_bandeira": _janela_bandeira(principal) if principal else None,
        "estrangeiro": (principal.strip().lower() != "arábia saudita") if principal else None,
    }


@app.get("/api/elencos/jogadores")
async def api_elencos_jogadores(team: int):
    """Elenco completo do clube, cadastro e números, tudo do Transfermarkt."""
    # Sequencial de propósito: o TM bloqueia quem dispara em paralelo, e o
    # portão interno do módulo serializa mesmo se pedirmos junto.
    try:
        plantel, av1 = await elenco_tm.elenco(team)
        numeros, av2 = await elenco_tm.desempenho(team)
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}
    if not plantel:
        return {"erro": "o Transfermarkt não devolveu elenco para este clube"}

    sem_bandeira, sem_posicao = set(), set()
    jogadores = []
    for p in plantel:
        d = numeros.get(p["id"], {})
        pais = _elenco_pais(p.get("nacionalidades") or [])
        if pais["nacionalidade"] and not pais["pais_bandeira"]:
            sem_bandeira.add(pais["nacionalidade"])
        if p.get("posicao") and not p.get("grupo"):
            sem_posicao.add(p["posicao"])
        jogadores.append({
            "id": p["id"], "nome": p["nome"],
            # Direto do TM porque é mais rápido (medido: a URL abre sem referer),
            # com o proxy como reserva caso o TM passe a bloquear hotlink.
            "foto": p.get("foto_tm"),
            "foto_reserva": (f"/api/tm-img?u={quote(p['foto_tm'], safe='')}"
                             if p.get("foto_tm") else None),
            "numero": p["numero"], "posicao": p["posicao"], "grupo": p["grupo"],
            "idade": p["idade"], "nascimento": p["nascimento"],
            "altura": p["altura"], "pe": p["pe"],
            "valor": p.get("valor"), "contrato": p.get("contrato"),
            "jogos": d.get("jogos"), "gols": d.get("gols"),
            "assistencias": d.get("assistencias"), "amarelos": d.get("amarelos"),
            "vermelhos": d.get("vermelhos"), "segundo_amarelo": d.get("segundo_amarelo"),
            "minutos": d.get("minutos"),
            **pais,
        })

    ordem = {"G": 0, "D": 1, "M": 2, "A": 3}
    jogadores.sort(key=lambda j: (ordem.get(j["grupo"], 9), -(j["minutos"] or 0),
                                  j["numero"] if j["numero"] is not None else 999))
    avisos = [a for a in (av1, av2) if a]
    if sem_bandeira:
        avisos.append("nacionalidades sem bandeira mapeada: " + ", ".join(sorted(sem_bandeira)))
    if sem_posicao:
        avisos.append("posições sem setor definido: " + ", ".join(sorted(sem_posicao)))
    return {"season": elenco_tm.TM_SAISON, "team": team, "total": len(jogadores),
            "jogadores": jogadores, "avisos": avisos}


_ELENCO_SALVA_CHAVE = "elenco_escalacao_"


@app.get("/api/elencos/escalacao-salva")
async def api_elencos_escalacao_salva(team: int):
    """Escalação que o usuário ajustou e guardou para este clube."""
    try:
        bruto = get_state(f"{_ELENCO_SALVA_CHAVE}{team}")
        return {"salva": json.loads(bruto) if bruto else None}
    except Exception as e:
        return {"salva": None, "erro": f"{type(e).__name__}: {e}"}


@app.post("/api/elencos/escalacao-salva")
async def api_elencos_salvar_escalacao(request: Request):
    """Guarda a escalação ajustada à mão.

    Passa a ter precedência sobre a do último jogo ao abrir o clube — voltar à
    do jogo é uma ação explícita ("Última escalação" e salvar de novo)."""
    try:
        corpo = await request.json()
    except Exception:
        return {"erro": "corpo inválido"}
    try:
        team = int(corpo.get("team") or 0)
    except (TypeError, ValueError):
        team = 0
    if not team:
        return {"erro": "clube não informado"}

    # Descartar precisa existir: sem isso, uma escalação salva por engano fica
    # para sempre à frente da do jogo, e não há caminho de volta pela tela.
    if corpo.get("limpar"):
        try:
            set_state(f"{_ELENCO_SALVA_CHAVE}{team}", "")
        except Exception as e:
            return {"erro": f"não consegui descartar: {type(e).__name__}: {e}"}
        return {"ok": True, "limpou": True}

    # Sanear antes de gravar: coordenada fora do campo ou id estranho viraria
    # posição impossível na próxima abertura, e o defeito ficaria persistido.
    limpos = []
    for s in (corpo.get("slots") or [])[:11]:
        try:
            pid = s.get("id")
            limpos.append({
                "id": int(pid) if pid is not None else None,
                "x": round(max(0.0, min(100.0, float(s.get("x", 50)))), 1),
                "y": round(max(0.0, min(100.0, float(s.get("y", 50)))), 1),
                "g": (str(s.get("g") or "M")[:1]).upper(),
            })
        except (TypeError, ValueError):
            continue
    if not limpos:
        return {"erro": "nenhuma posição válida para salvar"}

    dados = {"formacao": (str(corpo.get("formacao") or "")[:12] or None),
             "slots": limpos,
             "salvo_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        set_state(f"{_ELENCO_SALVA_CHAVE}{team}", json.dumps(dados, ensure_ascii=False))
    except Exception as e:
        return {"erro": f"não consegui salvar: {type(e).__name__}: {e}"}
    return {"ok": True, "salvo_em": dados["salvo_em"], "total": len(limpos)}


@app.get("/api/elencos/escalacao")
async def api_elencos_escalacao(team: int):
    """Escalação e formação do último jogo encerrado, lidas da súmula do TM."""
    try:
        jogo, av1 = await elenco_tm.ultimo_jogo(team)
        if not jogo:
            return {"erro": av1 or "nenhuma partida encerrada nesta temporada"}
        times, av2 = await elenco_tm.escalacao(jogo["sumula"])
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}
    if not times:
        return {"erro": "a súmula não traz escalação", "sumula": jogo.get("sumula")}

    mandante = jogo["casa_id"] == team
    bloco = times[0] if mandante else (times[1] if len(times) > 1 else times[0])

    # Confere que a escalação é MESMO deste clube. Sem isso, um erro de leitura
    # da súmula entrega os 11 do adversário e a tela só mostra "undefined" —
    # foi o que aconteceu com todo time visitante em 16/08/2026.
    aviso_time = None
    try:
        plantel, _ = await elenco_tm.elenco(team)
        do_clube = {p["id"] for p in plantel}
        if do_clube:
            def pertence(b):
                return sum(1 for i in b["titulares"] if i in do_clube)
            if pertence(bloco) == 0:
                melhor = max(times, key=pertence)
                if pertence(melhor) > 0:
                    bloco = melhor
                else:
                    return {"erro": "a escalação lida não corresponde ao elenco deste clube",
                            "sumula": jogo["sumula"]}
            faltam = [i for i in bloco["titulares"] if i not in do_clube]
            if faltam:
                aviso_time = f"{len(faltam)} titulares não constam no elenco atual (saíram ou são da base)"
    except Exception:
        pass
    coords = elenco_tm.posicoes_no_campo(bloco.get("formacao"), len(bloco["titulares"]))
    titulares = [{"id": pid, "x": coords[i][0], "y": coords[i][1]}
                 for i, pid in enumerate(bloco["titulares"]) if i < len(coords)]
    return {
        "sumula": jogo["sumula"], "data": jogo["data"],
        "adversario": jogo["fora"] if mandante else jogo["casa"],
        "mandante": mandante, "placar": (jogo.get("placar") or "").replace(":", "x"),
        "formacao": bloco.get("formacao"),
        "sem_posicoes": not bloco.get("formacao"),
        "titulares": titulares, "suplentes": [{"id": p} for p in bloco.get("banco") or []],
        "avisos": [a for a in (av1, av2, aviso_time) if a],
    }


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
@app.get("/api/tm-img")
async def tm_img_proxy(u: str):
    """Serve uma imagem do Transfermarkt pela nossa origem.

    Existe por dois motivos: o TM recusa imagem carregada de fora do site dele
    (por isso o Referer aqui) e o endereço da foto mudou de formato — montar a
    URL por padrão fixo, como o /api/tm-photo fazia, virou 404. Aqui a URL vem
    lida da página. Restrito aos domínios do TM pra não virar proxy aberto."""
    from urllib.parse import urlparse
    host = (urlparse(u).hostname or "").lower()
    if not (host.endswith("transfermarkt.technology") or host.endswith("akamaized.net")
            or host.endswith("transfermarkt.com.br") or host.endswith("transfermarkt.com")):
        return Response(status_code=400)
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={
            "Referer": "https://www.transfermarkt.com.br/",
            "User-Agent": TM_HEADERS_UA,
        }) as client:
            r = await client.get(u, follow_redirects=True)
            if r.status_code == 200 and r.content:
                return Response(content=r.content,
                                media_type=r.headers.get("content-type", "image/jpeg"),
                                headers={"Cache-Control": "public, max-age=604800"})
    except Exception:
        pass
    return Response(status_code=404)


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


# ── Post de janela (entradas e saídas por clube) ─────────────────────────────
# Cores por clube, na grafia curta que sobra depois de limpar o nome do TM.
JANELA_CORES = {
    "HILAL": "🔵⚪️", "RIYADH": "⚫️🔴", "ITTIHAD": "⚫️🟡", "NASSR": "🟡🔵",
    "DAMAC": "🔴🟤", "FAYHA": "🟠🔵", "KHALEEJ": "🟢🟡", "KHOLOOD": "🔴🟢",
    "OKHDOOD": "🔵⚫️", "SHABAB": "⚪️⚫️", "ETTIFAQ": "🟢🔴", "FATEH": "🔵🟢",
    "AHLI": "🟢⚪️", "TAAWOUN": "🟡⚪️", "QADSIAH": "🔴🟡", "NEOM": "🔵🟣",
    "HAZEM": "🟡🟡", "NAJMA": "🟢⚫️", "NAJMAH": "🟢⚫️", "FAISALY": "🔴⚪️",
    "DIRIYAH": "🟤⚪️", "ABHA": "🔵🔴",
}

# Ordem em que as posições aparecem no post — do gol pra frente, técnico por último.
JANELA_POSICOES = [
    ("Goleiro", "G"), ("Zagueiro", "Z"), ("Lateral Dir.", "LD"), ("Lateral Esq.", "LE"),
    ("Volante", "V"), ("Meia Central", "M"), ("Meia Ofensivo", "M"),
    ("Ponta Direita", "A"), ("Ponta Esquerda", "A"), ("Centroavante", "A"),
    ("Treinador", "T"),
]
JANELA_SIGLA = {nome: sigla for nome, sigla in JANELA_POSICOES}
JANELA_ORDEM = {sigla: i for i, sigla in enumerate(["G", "Z", "LD", "LE", "V", "M", "A", "T"])}

# Nacionalidade (grafia do Transfermarkt em pt) -> ISO 3166-1 alfa-2.
# A bandeira é derivada do código, não escrita à mão, pra não haver emoji errado.
JANELA_PAIS_ISO = {
    "Arábia Saudita": "SA", "Brasil": "BR", "França": "FR", "Espanha": "ES",
    "Senegal": "SN", "Portugal": "PT", "Albânia": "AL", "RD do Congo": "CD",
    "Congo": "CG", "Holanda": "NL", "Países Baixos": "NL", "Argélia": "DZ",
    "Egito": "EG", "Uruguai": "UY", "Gâmbia": "GM", "Sudão": "SD", "Sérvia": "RS",
    "Costa do Marfim": "CI", "Gana": "GH", "Eslováquia": "SK", "Moldávia": "MD",
    "Argentina": "AR", "Grécia": "GR", "Jordânia": "JO", "Kosovo": "XK",
    "Togo": "TG", "Guiné": "GN", "Guiné-Bissau": "GW", "Mali": "ML",
    # Grafias que o TM usa sem hífen / territórios franceses — apareceram no
    # aviso da primeira geração real do post, não foram supostas aqui.
    "Guiné Bissau": "GW", "Guiné Equatorial": "GQ", "Guiana Francesa": "GF",
    "Suriname": "SR",
    "Neocaledónia": "NC", "Nova Caledónia": "NC", "Nova Caledônia": "NC",
    "Guadalupe": "GP", "Martinica": "MQ", "Reunião": "RE", "Curaçao": "CW",
    "Ruanda": "RW", "Roménia": "RO", "Romênia": "RO", "Marrocos": "MA",
    "Croácia": "HR", "Bósnia-Herzegovina": "BA", "Gabão": "GA", "Tunísia": "TN",
    "Alemanha": "DE", "Itália": "IT", "Bélgica": "BE", "Suíça": "CH",
    "Áustria": "AT", "Dinamarca": "DK", "Suécia": "SE", "Noruega": "NO",
    "Finlândia": "FI", "Islândia": "IS", "Polónia": "PL", "Polônia": "PL",
    "Ucrânia": "UA", "Rússia": "RU", "Bielorrússia": "BY", "Hungria": "HU",
    "Chéquia": "CZ", "República Checa": "CZ", "Eslovénia": "SI", "Eslovênia": "SI",
    "Bulgária": "BG", "Macedónia do Norte": "MK", "Macedônia do Norte": "MK",
    "Montenegro": "ME", "Geórgia": "GE", "Arménia": "AM", "Armênia": "AM",
    "Azerbaijão": "AZ", "Turquia": "TR", "Israel": "IL", "Chipre": "CY",
    "Nigéria": "NG", "Camarões": "CM", "Zâmbia": "ZM", "Quénia": "KE",
    "Quênia": "KE", "África do Sul": "ZA", "Angola": "AO", "Moçambique": "MZ",
    "Cabo Verde": "CV", "Burkina Faso": "BF", "Benim": "BJ", "Benin": "BJ",
    "Níger": "NE", "Chade": "TD", "Líbia": "LY", "Mauritânia": "MR",
    "Serra Leoa": "SL", "Libéria": "LR", "Uganda": "UG", "Tanzânia": "TZ",
    "Etiópia": "ET", "Somália": "SO", "Comores": "KM", "Madagáscar": "MG",
    "Emirados Árabes Unidos": "AE", "Catar": "QA", "Kuwait": "KW",
    "Bahrein": "BH", "Barém": "BH", "Omã": "OM", "Iémen": "YE", "Iêmen": "YE",
    "Palestina": "PS", "Síria": "SY", "Líbano": "LB", "Iraque": "IQ", "Irão": "IR",
    "Irã": "IR", "Uzbequistão": "UZ", "Tajiquistão": "TJ", "Coreia do Sul": "KR",
    "Japão": "JP", "China": "CN", "Austrália": "AU", "Nova Zelândia": "NZ",
    "Estados Unidos": "US", "Canadá": "CA", "México": "MX", "Colômbia": "CO",
    "Chile": "CL", "Peru": "PE", "Paraguai": "PY", "Equador": "EC",
    "Venezuela": "VE", "Bolívia": "BO", "Costa Rica": "CR", "Jamaica": "JM",
    "Trindade e Tobago": "TT", "República Dominicana": "DO", "Honduras": "HN",
    "Panamá": "PA", "Guatemala": "GT", "Irlanda": "IE", "Malta": "MT",
    "Luxemburgo": "LU", "Lituânia": "LT", "Letónia": "LV", "Estónia": "EE",
}
# Nações do Reino Unido não têm código ISO próprio; a bandeira é uma sequência
# especial, então ficam listadas à parte em vez de virarem código inventado.
JANELA_BANDEIRA_ESPECIAL = {
    "Inglaterra": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Escócia": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "País de Gales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "Irlanda do Norte": "🇬🇧", "Reino Unido": "🇬🇧",
}


def _janela_bandeira(pais: str | None) -> str | None:
    """Emoji da bandeira, ou None se o país não estiver mapeado.

    Devolver None de propósito: um país sem bandeira precisa APARECER no aviso,
    não sair com a bandeira de outro lugar."""
    p = (pais or "").strip()
    if not p:
        return None
    if p in JANELA_BANDEIRA_ESPECIAL:
        return JANELA_BANDEIRA_ESPECIAL[p]
    iso = JANELA_PAIS_ISO.get(p)
    if not iso:
        return None
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso.upper())


def _janela_clube_limpo(nome: str | None) -> str:
    """'Al-Hilal SFC' -> 'AL HILAL'; 'NEOM SC' -> 'NEOM'; 'Abha Club' -> 'ABHA'.

    Vale mais que uma tabela de nomes: o sufixo societário do TM é o que muda,
    o miolo não. E preserva o 'AL' de quem tem, sem colar em quem não tem."""
    n = (nome or "").strip()
    if not n:
        return ""
    n = re.sub(r"\s+(SFC|FC|SC|Club|CF)\s*$", "", n, flags=re.I).strip()
    return n.replace("-", " ").upper()


def _montar_post_janela() -> dict:
    """Texto do post de entradas e saídas, agrupado por clube da liga."""
    rows = get_window_transfers()
    if not rows:
        return {"erro": "sem dados de janela — rode a raspagem primeiro"}

    clubes: dict[str, dict] = {}
    sem_bandeira: set[str] = set()
    sem_cor: set[str] = set()
    sem_posicao: set[str] = set()

    for r in rows:
        entrada = r.get("direction") == "in"
        bruto = r.get("team_in_name") if entrada else r.get("team_out_name")
        clube = _janela_clube_limpo(bruto)
        if not clube:
            continue
        d = clubes.setdefault(clube, {"entradas": [], "saidas": []})
        nome = (r.get("player_name") or "").strip()
        if not nome:
            continue
        if entrada:
            pos = (r.get("position") or "").strip()
            sigla = JANELA_SIGLA.get(pos)
            if not sigla and pos:
                sem_posicao.add(pos)
            band = _janela_bandeira(r.get("nationality"))
            if band is None and (r.get("nationality") or "").strip():
                sem_bandeira.add(r["nationality"].strip())
            d["entradas"].append({
                "nome": nome, "sigla": sigla or pos or "?",
                "bandeira": band, "pais": (r.get("nationality") or "").strip(),
                "ordem": JANELA_ORDEM.get(sigla, 99),
            })
        else:
            d["saidas"].append(nome)

    destaque = ["AL HILAL", "AL NASSR", "AL AHLI", "AL ITTIHAD"]
    def _chave(c):
        return (destaque.index(c) if c in destaque else len(destaque), c)

    blocos = []
    for clube in sorted(clubes, key=_chave):
        d = clubes[clube]
        if not d["entradas"] and not d["saidas"]:
            continue
        token = clube.split()[-1]
        cor = JANELA_CORES.get(token)
        if cor is None:
            sem_cor.add(clube)
        linhas = [f"{clube} {cor}".strip() if cor else clube]
        for e in sorted(d["entradas"], key=lambda x: (x["ordem"], x["nome"])):
            # país sem bandeira mapeada vai com o nome entre colchetes: erro visível
            marca = e["bandeira"] or (f"[{e['pais']}]" if e["pais"] else "")
            linhas.append(f"{marca} {e['nome']} ({e['sigla']})".strip())
        if d["saidas"]:
            nomes = sorted(set(d["saidas"]))
            texto = nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]
            linhas.append("")
            linhas.append(f"❌ Saídas: {texto}.")
        blocos.append("\n".join(linhas))

    avisos = []
    if sem_cor:
        avisos.append("clubes sem cor definida: " + ", ".join(sorted(sem_cor)))
    if sem_bandeira:
        avisos.append("nacionalidades sem bandeira: " + ", ".join(sorted(sem_bandeira)))
    if sem_posicao:
        avisos.append("posições sem sigla: " + ", ".join(sorted(sem_posicao)))

    return {
        "texto": "\n\n".join(blocos),
        "clubes": len(blocos),
        "entradas": sum(len(c["entradas"]) for c in clubes.values()),
        "saidas": sum(len(c["saidas"]) for c in clubes.values()),
        "avisos": avisos,
    }


@app.get("/api/janela/post")
async def api_janela_post():
    """Texto pronto pra copiar do post de entradas e saídas da janela."""
    return _montar_post_janela()


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
{_HEAD_COMUM}
<style>
{_HEADER_CSS}
:root{{
  --bg:var(--c-bg);--surface:var(--c-bg-card);--surface2:var(--c-bg-soft);--border:var(--c-border);
  --text:var(--c-text);--text2:var(--c-muted-3);--accent:var(--c-acento);
  --green:#B6FF00;--blue:#B6FF00;--amber:#FFBE5D;--red:#FD5D5D;--purple:#FFBE5D;
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
.badge-in{{background:rgba(34,197,94,.15);color:#B6FF00;border:1px solid rgba(34,197,94,.3)}}
.badge-out{{background:rgba(239,68,68,.15);color:#FD5D5D;border:1px solid rgba(239,68,68,.3)}}
.badge-loan{{background:rgba(245,158,11,.15);color:#FFBE5D;border:1px solid rgba(245,158,11,.3)}}
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
    <button class="filter-btn" onclick="gerarPost()" id="btnPost">📋 Gerar post</button>
  </div>

  <div id="postBox" style="display:none;margin:0 0 18px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
      <strong style="font-size:14px">Entradas e saídas por clube</strong>
      <button class="filter-btn" onclick="copiarPost(this)">📋 Copiar</button>
      <span id="postMeta" style="font-size:12px;color:var(--text2)"></span>
    </div>
    <div id="postAvisos" style="display:none;font-size:12px;color:#FFBE5D;margin-bottom:8px"></div>
    <pre id="postTexto" style="white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.6;
      background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin:0;
      max-height:60vh;overflow:auto"></pre>
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

async function gerarPost() {{
  const box = document.getElementById('postBox');
  const btn = document.getElementById('btnPost');
  const orig = btn.textContent;
  btn.textContent = 'gerando…'; btn.disabled = true;
  try {{
    const r = await fetch('/api/janela/post?_=' + Date.now());
    const d = await r.json();
    if (d.erro) throw new Error(d.erro);
    document.getElementById('postTexto').textContent = d.texto;
    document.getElementById('postMeta').textContent =
      d.clubes + ' clubes · ' + d.entradas + ' entradas · ' + d.saidas + ' saídas';
    const av = document.getElementById('postAvisos');
    // Aviso visível: sem isso, um país sem bandeira sairia no post sem ninguém notar.
    if (d.avisos && d.avisos.length) {{
      av.textContent = '⚠️ ' + d.avisos.join(' · ');
      av.style.display = '';
    }} else {{
      av.style.display = 'none';
    }}
    box.style.display = '';
    box.scrollIntoView({{behavior: 'smooth', block: 'start'}});
  }} catch(e) {{
    showToast('Erro ao gerar: ' + e.message);
  }} finally {{
    btn.textContent = orig; btn.disabled = false;
  }}
}}

function copiarPost(btn) {{
  navigator.clipboard.writeText(document.getElementById('postTexto').textContent).then(() => {{
    const o = btn.textContent;
    btn.textContent = '✅ Copiado!';
    setTimeout(() => {{ btn.textContent = o; }}, 1800);
  }});
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


# ══════════════════════════════════════════════════════════════════════════
# ARBITRAGEM DO DIA
#
# O SAFF publica a escala no dia do jogo e depois tira do ar. Em datas
# antigas não há apito em jogo nenhum. Por isso esta guia guarda: o banco é a
# única cópia que sobra, e a busca diária das 8h é a única chance de pegar.
# ══════════════════════════════════════════════════════════════════════════

def _dia_de_brasilia(quantos_dias: int = 0) -> str:
    """A data de hoje em Brasília, no formato do SAFF.

    O Railway roda em UTC. Às 22h de Brasília já é o dia seguinte em UTC, e
    pedir "hoje" ao servidor traria o calendário de amanhã sem avisar.
    """
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    return (agora + timedelta(days=quantos_dias)).strftime("%Y-%m-%d")


def _traduzir_arbitro():
    """Uma função que converte nome do SAFF na grafia do canal.

    Lê o glossário inteiro de uma vez e devolve uma consulta em memória: são
    seis nomes por jogo, e uma ida ao banco por nome seria uma consulta por
    linha do post.
    """
    import arbitragem as arb
    try:
        tabela = traducoes_de_arbitros()
    except Exception:
        tabela = {}
    return lambda bruto: tabela.get(arb.chave_do_arbitro(bruto), "")


def _cabecalho_arbitragem() -> str:
    """A primeira linha do post, vinda de Configurações.

    Passa por `ajuste()` e não direto pelo get_state para valer o mesmo cache
    e o mesmo padrão dos outros — duas fontes para a mesma configuração é como
    se começa a ter dois valores diferentes para a mesma coisa.
    """
    import arbitragem as arb
    try:
        return (ajuste("arbitragem_cabecalho") or "").strip() or arb.CABECALHO_PADRAO
    except Exception:
        return arb.CABECALHO_PADRAO


def buscar_arbitragem(dia: str | None = None) -> dict:
    """Vai ao SAFF, guarda o que achar e conta o que aconteceu.

    Devolve sempre os três números — guardados, ignorados e erros. Um retorno
    que só diga "0 jogos" não distingue "o SAFF ainda não publicou" de "o site
    caiu", e essas duas situações pedem coisas diferentes de você.
    """
    import arbitragem as arb
    dia = dia or _dia_de_brasilia()
    achado = arb.buscar_do_dia(dia)
    gravados = salvar_arbitragem(achado["jogos"])
    resultado = {
        "dia": dia,
        "guardados": gravados,
        "encontrados": len(achado["jogos"]),
        "ignorados": achado["ignorados"],
        "erros": achado["erros"],
    }
    print(f"[ARBITRAGEM] {dia}: {gravados} guardados, "
          f"{len(achado['ignorados'])} fora das competições cobertas, "
          f"{len(achado['erros'])} erros", flush=True)
    for e in achado["erros"]:
        print(f"[ARBITRAGEM] erro: {e}", flush=True)
    return resultado


@app.get("/api/arbitragem")
async def api_arbitragem(dia: str = ""):
    """A escala guardada de um dia, já com o texto montado."""
    import arbitragem as arb
    dia = (dia or "").strip() or _dia_de_brasilia()
    jogos = arbitragem_do_dia(dia)
    traduzir = _traduzir_arbitro()
    return {
        "dia": dia,
        "hoje": _dia_de_brasilia(),
        "jogos": jogos,
        "texto": arb.montar_texto(jogos, traduzir, _cabecalho_arbitragem()) if jogos else "",
        "faltando": arb.nomes_sem_traducao(jogos, traduzir),
        "elenco": arb.elenco_do_dia(jogos, traduzir),
        "paises_sem_bandeira": arb.paises_desconhecidos(jogos),
        "dias": dias_com_arbitragem(30),
        "glossario_pendente": len(nomes_de_arbitros(so_faltando=True)),
    }


@app.post("/api/arbitragem/buscar")
async def api_arbitragem_buscar(request: Request):
    """Busca agora, sem esperar as 8h. Serve quando o SAFF atrasa."""
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    dia = (corpo.get("dia") or "").strip() or _dia_de_brasilia()
    return buscar_arbitragem(dia)


@app.get("/api/arbitragem/nomes")
async def api_arbitragem_nomes(faltando: str = ""):
    """O glossário de árbitros, os mais frequentes primeiro."""
    return {"nomes": nomes_de_arbitros(so_faltando=(faltando == "sim"))}


@app.post("/api/arbitragem/nome")
async def api_arbitragem_nome(request: Request):
    """Define a grafia do canal para um árbitro."""
    try:
        corpo = await request.json()
    except Exception:
        return JSONResponse({"erro": "corpo inválido"}, 400)
    chave = (corpo.get("chave") or "").strip()
    if not chave:
        return JSONResponse({"erro": "faltou dizer qual árbitro"}, 400)
    ok = definir_nome_de_arbitro(chave, corpo.get("nome") or "")
    if not ok:
        return JSONResponse({"erro": "não achei esse árbitro no glossário"}, 404)
    return {"ok": True}


_ARB_CSS = """
body{background:var(--c-bg);color:var(--c-text);
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;margin:0}
.wrap{max-width:820px;margin:0 auto;padding:6px 16px 90px}
h1{font-family:'Bebas Neue',sans-serif;font-size:2.1rem;letter-spacing:.02em;
  margin:10px 0 4px}
.sub{font-size:.76rem;color:var(--c-muted-3);line-height:1.55;margin:0 0 16px}
.barra{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.ctrl{background:var(--c-bg-card);color:var(--c-text);border:1px solid var(--c-border);
  border-radius:12px;padding:8px 13px;font-size:.78rem;font-family:inherit;cursor:pointer}
.ctrl:hover{border-color:var(--c-acento)}
.ctrl.forte{background:var(--c-acento);color:var(--c-acento-texto);border-color:var(--c-acento);
  font-weight:700}
.aviso{border-radius:14px;padding:12px 14px;font-size:.76rem;line-height:1.55;
  margin-bottom:12px;border:1px solid var(--c-border)}
.aviso.alerta{background:rgba(255,190,93,.10);border-color:var(--c-alerta)}
.aviso.ruim{background:rgba(253,93,93,.10);border-color:var(--c-negativo)}
.aviso b{display:block;margin-bottom:4px}
.bloco{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:18px;padding:14px 16px;margin-bottom:12px}
.bloco h2{font-family:'Bebas Neue',sans-serif;font-size:1.2rem;letter-spacing:.04em;
  margin:0 0 10px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.bloco h2 span{font-family:'Inter',sans-serif;font-size:.66rem;font-weight:500;
  letter-spacing:0;color:var(--c-muted-3)}
pre.texto{white-space:pre-wrap;word-break:break-word;font-family:inherit;
  font-size:.86rem;line-height:1.65;margin:0;background:var(--c-bg-soft);
  border-radius:14px;padding:14px 15px}
.vazio{text-align:center;color:var(--c-muted-3);font-size:.8rem;padding:34px 12px;
  line-height:1.6}
table.gloss{width:100%;border-collapse:collapse;font-size:.78rem}
table.gloss td{padding:6px 4px;border-bottom:1px solid var(--c-border)}
table.gloss td.saff{color:var(--c-muted-3);white-space:nowrap}
table.gloss input{width:100%;background:var(--c-bg-soft);color:var(--c-text);
  border:1px solid var(--c-border);border-radius:9px;padding:6px 8px;
  font-family:inherit;font-size:.78rem}
table.gloss input:focus{outline:none;border-color:var(--c-acento)}
.vezes{color:var(--c-muted-3);font-size:.68rem;text-align:right;white-space:nowrap}
.fonte{display:inline-block;margin-left:7px;font-size:.6rem;padding:1px 6px;
  border-radius:20px;vertical-align:middle;letter-spacing:.03em}
.fonte.f-seu{background:var(--c-acento);color:var(--c-acento-texto);font-weight:700}
.fonte.f-liga{background:var(--c-bg-soft);color:var(--c-muted-3);
  border:1px solid var(--c-border)}
.fonte.f-saff{background:rgba(255,190,93,.16);color:var(--c-alerta);
  border:1px solid var(--c-alerta)}
"""

_ARB_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arbitragem · IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
__ARB_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Arbitragem</h1>
  <p class="sub">O SAFF publica a escala no dia do jogo e tira do ar depois de
     alguns dias. O app busca sozinho às 8h e guarda — o que está aqui não
     depende mais do site continuar publicando.</p>
  <div class="barra">
    <input type="date" id="dia" class="ctrl">
    <button class="ctrl" onclick="carregar()">↻ Atualizar</button>
    <button class="ctrl forte" onclick="buscarAgora()">Buscar no SAFF agora</button>
  </div>
  <div id="avisos"></div>
  <div id="conteudo" class="vazio">carregando…</div>
  <div id="glossario"></div>
</div>
<script>
__ARB_JS__
</script>
</body>
</html>"""

_ARB_JS = r"""
function esc(s){return String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

let ULTIMO = null;

function hojeCampo(){
  const c = document.getElementById('dia');
  return (c && c.value) ? c.value : '';
}

async function carregar(){
  const d = hojeCampo();
  const r = await fetch('/api/arbitragem' + (d ? '?dia=' + encodeURIComponent(d) : ''));
  const dados = await r.json();
  ULTIMO = dados;
  const campo = document.getElementById('dia');
  if (campo && !campo.value) campo.value = dados.dia;
  desenhar(dados);
}

function desenhar(d){
  const avisos = [];
  // A lista de nomes sem grafia aparece ANTES do texto, de propósito. Se
  // aparecesse depois, você copiaria o bloco sem saber que tem nome do SAFF
  // dentro dele.
  if ((d.faltando || []).length) {
    avisos.push('<div class="aviso alerta"><b>' + d.faltando.length +
      ' nome(s) saindo com a grafia do SAFF</b>A liga oficial não tinha esses ' +
      'nomes e você não definiu. É a pior das três grafias — vale conferir na ' +
      'lista do fim da página.</div>');
  }
  if ((d.paises_sem_bandeira || []).length) {
    avisos.push('<div class="aviso alerta"><b>País sem bandeira no meu mapa</b>' +
      esc(d.paises_sem_bandeira.join(', ')) +
      ' — o nome sai sem bandeira. Me avise para eu incluir.</div>');
  }
  document.getElementById('avisos').innerHTML = avisos.join('');

  const alvo = document.getElementById('conteudo');
  if (!d.jogos || !d.jogos.length) {
    alvo.className = 'vazio';
    alvo.innerHTML = 'Nada guardado para ' + esc(d.dia) + '.<br><br>' +
      (d.dia === d.hoje
        ? 'Se já passou das 8h, use “Buscar no SAFF agora”. Pode ser que o SAFF ainda não tenha publicado a escala do dia.'
        : 'Este dia não foi capturado. O SAFF não guarda escala antiga, então não dá para buscar depois.');
    document.getElementById('glossario').innerHTML = '';
    return;
  }
  alvo.className = '';
  alvo.innerHTML =
    '<div class="bloco"><h2>Texto para copiar' +
      '<span>' + d.jogos.length + ' jogo(s)</span></h2>' +
      '<pre class="texto" id="texto">' + esc(d.texto) + '</pre>' +
      '<div class="barra" style="margin:12px 0 0">' +
      '<button class="ctrl forte" onclick="copiar()">Copiar</button></div></div>';
  desenharGlossario(d.elenco || []);
}

// Mostra TODO MUNDO, não só quem está faltando. A liga também erra — ela
// escreveu "Khald Alahmari" —, e nome errado fora de uma lista de pendências
// é nome errado que ninguém revisa.
const ROTULO_FONTE = {seu: 'seu', liga: 'liga', saff: 'SAFF'};

function desenharGlossario(elenco){
  const alvo = document.getElementById('glossario');
  if (!elenco.length) { alvo.innerHTML = ''; return; }
  const linhas = elenco.map(function(f){
    return '<tr>' +
      '<td class="saff">' + esc(f.publicado) +
        '<span class="fonte f-' + esc(f.fonte) + '">' +
        esc(ROTULO_FONTE[f.fonte] || f.fonte) + '</span></td>' +
      '<td><input placeholder="deixe em branco para manter" value="' + esc(f.seu) +
        '" data-chave="' + esc(f.chave) + '" onchange="salvarNome(this)"></td></tr>';
  }).join('');
  alvo.innerHTML = '<div class="bloco"><h2>Nomes do dia' +
    '<span>a etiqueta diz de onde veio</span></h2>' +
    '<table class="gloss">' + linhas + '</table>' +
    '<p class="sub" style="margin:12px 0 0">O que você escrever aqui passa a ' +
    'valer sempre, acima da liga e do SAFF. Campo em branco deixa como está.</p>' +
    '</div>';
}

async function salvarNome(el){
  const d = await (await fetch('/api/arbitragem/nome', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({chave: el.dataset.chave, nome: el.value})})).json();
  if (d.erro) { alert(d.erro); return; }
  carregar();
}

async function buscarAgora(){
  const alvo = document.getElementById('conteudo');
  alvo.className = 'vazio'; alvo.innerHTML = 'consultando o SAFF…';
  const d = await (await fetch('/api/arbitragem/buscar', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({dia: hojeCampo()})})).json();
  const partes = [];
  if (d.erros && d.erros.length) {
    partes.push('<div class="aviso ruim"><b>Deu problema na busca</b>' +
      d.erros.map(esc).join('<br>') + '</div>');
  }
  if (!d.guardados) {
    // Distinguir as duas ausências é o ponto. "Publicou, mas só sub-16" e
    // "não publicou nada" levam a decisões diferentes.
    const ign = (d.ignorados || []).length;
    partes.push('<div class="aviso alerta"><b>Nenhum jogo das nossas competições</b>' +
      (ign ? 'O SAFF publicou ' + ign + ' escala(s), mas de competições que ' +
             'não cobrimos (2ª divisão, sub-16, futsal).'
           : 'O SAFF ainda não publicou escala nenhuma para este dia.') +
      '</div>');
  }
  document.getElementById('avisos').innerHTML = partes.join('');
  await carregar();
  if (partes.length) {
    document.getElementById('avisos').innerHTML =
      partes.join('') + document.getElementById('avisos').innerHTML;
  }
}

function copiar(){
  const t = ULTIMO && ULTIMO.texto ? ULTIMO.texto : '';
  if (!t) return;
  navigator.clipboard.writeText(t).then(function(){
    const b = event.target; const antes = b.textContent;
    b.textContent = 'copiado'; setTimeout(function(){ b.textContent = antes; }, 1400);
  });
}

// O log da tela inicial linka para /arbitragem?dia=AAAA-MM-DD. Sem ler isto,
// o link abria sempre em hoje e o dia que você clicou não aparecia — o link
// funcionava, mas levava ao lugar errado, que é pior do que não funcionar.
(function(){
  const q = new URLSearchParams(location.search).get('dia') || '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(q)) document.getElementById('dia').value = q;
})();

document.getElementById('dia').addEventListener('change', carregar);
carregar();
"""


@app.get("/arbitragem", response_class=HTMLResponse)
async def pagina_arbitragem():
    return HTMLResponse(
        _ARB_HTML
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__ARB_CSS__", _ARB_CSS)
        .replace("__ARB_JS__", _ARB_JS)
        .replace("__HDR__", _header("/arbitragem"))
    )


@app.get("/api/diag/arbitros-sportmonks", response_class=PlainTextResponse)
async def diag_arbitros_sportmonks(data: str = "2026-08-26"):
    """Como a Sportmonks escreve o nome dos árbitros de um dia.

    Sondagem: serve para comparar a grafia dela com a do SAFF e com a do
    canal, antes de decidir de qual fonte o glossário deve nascer. Não guarda
    nada e não é chamada por nenhuma tela.
    """
    import fim_sportmonks as sm
    linhas = [f"data: {data}"]
    d, e = await sm._get(f"fixtures/date/{data}", ttl=60,
                         include="participants;referees.referee.country",
                         per_page="100")
    if e:
        return PlainTextResponse(f"erro: {e}")
    for f in ((d or {}).get("data") or []):
        nomes = [p.get("name") for p in (f.get("participants") or [])]
        linhas.append(f"\n[liga {f.get('league_id')}] {' x '.join(str(n) for n in nomes)}")
        arbs = f.get("referees") or []
        if not arbs:
            linhas.append("   (sem árbitro)")
        for a in arbs:
            r = a.get("referee") or {}
            pais = (r.get("country") or {}).get("name")
            linhas.append(f"   {a.get('type_id')}: {r.get('name')}"
                          f"  | common={r.get('common_name')}"
                          f"  | display={r.get('display_name')}  | {pais}")
    return PlainTextResponse("\n".join(linhas))


# ══════════════════════════════════════════════════════════════════════════
# PRÉVIA DE JOGO
#
# Para a sua preparação como comentarista, não para publicar. Só dos jogos
# marcados com transmissão na guia Agendamentos. Duas entregas: na véspera,
# com escalação provável deduzida, e de novo quando a liga publica a oficial.
# ══════════════════════════════════════════════════════════════════════════

def _chave_da_previa(fixture_id) -> str:
    return f"previa:{fixture_id}"


async def _jogos_para_previa(dia: str) -> list[dict]:
    """TODOS os jogos do dia nas competições que o app cobre.

    A primeira versão listava só os jogos com transmissão marcada. A tela
    mostrou por que isso era pior: marcar transmissão é uma decisão sobre o
    POST, e amarrar o relatório a ela obrigava você a mentir num lugar para
    conseguir uma coisa no outro. Aqui a lista é o dia inteiro e a escolha é o
    clique — que é também onde está a economia, porque relatório só custa
    quando alguém pede.

    A transmissão continua vindo junto, como informação do cartão.
    """
    import posts_gerador as pg
    marcados = transmissoes(jogos_com_transmissao())
    inicio = _af_temporada_corrente()
    saida = []
    for liga_id, nome_comp in pg.COMPETICOES.items():
        season = await _season_da_liga(liga_id, inicio)
        dados, err = await _af_get("fixtures", {"league": liga_id, "season": season,
                                                "date": dia}, ttl=1800)
        if err:
            print(f"[PRÉVIA] {nome_comp}: {err}", flush=True)
            continue
        for f in (dados or {}).get("response", []):
            fid = (f.get("fixture") or {}).get("id")
            times = f.get("teams") or {}
            saida.append({
                "fixture_id": fid,
                "casa": (times.get("home") or {}).get("name") or "",
                "fora": (times.get("away") or {}).get("name") or "",
                "quando": (f.get("fixture") or {}).get("date") or "",
                "estadio": ((f.get("fixture") or {}).get("venue") or {}).get("name") or "",
                "rodada": (f.get("league") or {}).get("round") or "",
                "competicao": nome_comp,
                "canais": marcados.get(fid) or [],
            })
    saida.sort(key=lambda j: (j.get("quando") or "", j.get("casa") or ""))
    return saida


def _noticias_dos_clubes(casa: str, fora: str, limite: int = 8) -> list[dict]:
    """O que saiu na semana sobre os dois, já traduzido.

    Uso o texto que JÁ foi traduzido e pago. Buscar notícia nova aqui seria
    pagar duas vezes pela mesma coisa.
    """
    import glossary
    alvos = [(glossary.padronizar_clube(n) or n).lower() for n in (casa, fora) if n]
    achadas = []
    try:
        for a in get_recent_articles(hours=8 * 24, limit=200):
            titulo = a.get("title_pt") or ""
            if not titulo:
                continue
            baixo = (titulo + " " + (a.get("body_pt") or "")[:400]).lower()
            if not any(x in baixo for x in alvos):
                continue
            # source_name, não source. Mesmo erro das lesões, no mesmo dia:
            # a chave errada não levanta exceção, devolve "" e o texto sai sem
            # a fonte — que é justamente o que dá lastro a uma citação no ar.
            achadas.append({"titulo": titulo,
                            "fonte": a.get("source_name") or "",
                            "quando": (a.get("collected_at") or "")[:10],
                            "categoria": a.get("category") or ""})
            if len(achadas) >= limite:
                break
    except Exception as e:
        print(f"[PRÉVIA] notícias: {e}", flush=True)
    return achadas


def _desfalques_dos_clubes(casa: str, fora: str) -> list[dict]:
    import glossary
    alvos = [(glossary.padronizar_clube(n) or n).lower() for n in (casa, fora) if n]
    fora_lista = []
    try:
        for l in get_injuries(include_recovered=False):
            clube = (l.get("club") or "")
            if (glossary.padronizar_clube(clube) or clube).lower() not in alvos:
                continue
            # A coluna é player_name. Eu li "player", que não existe, e mandei
            # oito lesões sem nome nenhum para o modelo — que escreveu, com
            # razão, "8 desfalques sem nomes divulgados". O modelo relatou a
            # ausência com honestidade; quem inventou o buraco fui eu.
            #
            # Por isso lesão sem nome agora nem é enviada: um registro vazio
            # não vira informação, vira uma frase estranha no meio do texto.
            nome = (l.get("player_name") or "").strip()
            if not nome:
                continue
            fora_lista.append({
                "jogador": nome, "clube": clube,
                "motivo": l.get("injury_type") or l.get("status") or "",
                "onde": l.get("body_part") or "",
                "retorno": l.get("expected_return") or "",
            })
    except Exception as e:
        print(f"[PRÉVIA] lesões: {e}", flush=True)
    return fora_lista


def _arbitragem_do_confronto(dia: str, casa: str, fora: str) -> list[dict]:
    """A escala já guardada para este jogo, se houver."""
    import liga_spl
    alvo = liga_spl.confronto(casa, fora)
    for a in arbitragem_do_dia(dia):
        if liga_spl.confronto(a.get("casa"), a.get("fora")) == alvo:
            traduzir = _traduzir_arbitro()
            import arbitragem as arb
            return [{"papel": p.get("papel"), "nome": arb.nome_publicado(p, traduzir),
                     "pais": p.get("pais")} for p in (a.get("papeis") or [])]
    return []


def _coletar_da_liga(jogo: dict, dia: str, cliente) -> dict:
    """Tudo que a liga sabe deste jogo: tabela, forma, confronto e escalação.

    Devolve {} quando não acha o jogo lá — o que acontece em Copa do Rei,
    Supercopa e AFC, que a API da liga não cobre. Quem chama precisa saber a
    diferença entre "não achei" e "achei e está vazio".
    """
    import liga_spl
    import previa as pv
    sid = liga_spl.temporada(dia, cliente)
    if not sid:
        return {}
    alvo = liga_spl.confronto(jogo["casa"], jogo["fora"])
    achado = None
    for j in liga_spl.jogos_do_dia(sid, dia, cliente):
        if liga_spl.confronto((j.get("home") or {}).get("shortName") or "",
                              (j.get("away") or {}).get("shortName") or "") == alvo:
            achado = j
            break
    if not achado:
        return {}

    mid = achado.get("matchId")
    tabela = liga_spl.tabela(sid, cliente)
    saida = {
        "sid": sid, "mid": mid,
        "tabela_casa": liga_spl.linha_da_tabela(tabela, jogo["casa"]),
        "tabela_fora": liga_spl.linha_da_tabela(tabela, jogo["fora"]),
        "previa": {},
        "escala_casa": {}, "escala_fora": {},
        "oficial": False,
    }
    try:
        saida["previa"] = liga_spl.previa_do_jogo(sid, mid, cliente)
    except Exception as e:
        print(f"[PRÉVIA] matchPreview {mid}: {e}", flush=True)

    # A oficial, se já saiu. Antes disso as listas vêm vazias — é assim que a
    # liga diz "ainda não", e é o sinal que dispara a segunda entrega.
    try:
        escala = liga_spl.escala_do_jogo(sid, mid, cliente)
    except Exception as e:
        escala = {}
        print(f"[PRÉVIA] lineups {mid}: {e}", flush=True)
    if liga_spl.tem_escalacao(escala):
        saida["oficial"] = True
        saida["escala_casa"] = pv.escalacao_oficial(escala, "home")
        saida["escala_fora"] = pv.escalacao_oficial(escala, "away")
        return saida

    # Ainda não saiu: deduzo dos últimos jogos de cada time.
    passados = liga_spl.jogos_ate(sid, dia, cliente)
    for lado, chave in (("home", "escala_casa"), ("away", "escala_fora")):
        time_id = (achado.get(lado) or {}).get("teamId") or ""
        if not time_id:
            continue
        dele = [j for j in passados
                if time_id in ((j.get("home") or {}).get("teamId"),
                               (j.get("away") or {}).get("teamId"))
                ][:pv.RODADAS_PARA_O_PROVAVEL]
        escalas = {}
        for j in dele:
            try:
                escalas[j.get("matchId")] = liga_spl.escala_do_jogo(
                    sid, j.get("matchId"), cliente)
            except Exception:
                continue
        saida[chave] = pv.escalacao_provavel(dele, escalas, time_id)
    return saida


async def gerar_previa(jogo: dict, dia: str, forcar: bool = False,
                       so_se_oficial: bool = False) -> dict:
    """Monta os fatos, pede o texto e confere os números antes de guardar.

    `so_se_oficial` é para a rotina automática: ela coleta, e só gasta chamada
    de modelo se a escalação oficial realmente saiu. Sem isso, varrer de meia
    em meia hora reescreveria o mesmo texto o dia todo, pagando por cada
    passada.
    """
    import httpx
    import previa as pv

    chave = _chave_da_previa(jogo["fixture_id"])
    if not forcar and previa_com_escalacao(chave) == "oficial":
        # Já foi reescrita com a escalação de verdade. Refazer só gastaria
        # chamada para chegar no mesmo lugar.
        return {"chave": chave, "pulado": "já está com a escalação oficial"}

    with httpx.Client() as cliente:
        try:
            liga = _coletar_da_liga(jogo, dia, cliente)
        except Exception as e:
            liga = {}
            print(f"[PRÉVIA] liga: {type(e).__name__}: {e}", flush=True)

    if so_se_oficial and not liga.get("oficial"):
        return {"chave": chave, "pulado": "a escalação oficial ainda não saiu"}

    fatos = pv.montar_fatos(
        jogo,
        liga.get("tabela_casa") or {}, liga.get("tabela_fora") or {},
        liga.get("previa") or {},
        liga.get("escala_casa") or {}, liga.get("escala_fora") or {},
        _arbitragem_do_confronto(dia, jogo["casa"], jogo["fora"]),
        _desfalques_dos_clubes(jogo["casa"], jogo["fora"]),
        _noticias_dos_clubes(jogo["casa"], jogo["fora"]),
        [],
    )

    faltou = pv.sem_dados_suficientes(fatos)
    if faltou:
        return {"chave": chave, "erro": faltou}

    from processor import call_claude
    try:
        async with httpx.AsyncClient() as ac:
            texto = await call_claude(pv.montar_pedido(fatos), pv.SISTEMA, ac,
                                      max_tokens=2000, cache_system=True)
    except Exception as e:
        return {"chave": chave, "erro": f"{type(e).__name__}: {e}"}

    suspeitos = pv.conferir_numeros(texto, fatos)
    origem = "oficial" if liga.get("oficial") else "provavel"
    ok = salvar_previa({
        "chave": chave, "dia": dia, "casa": jogo["casa"], "fora": jogo["fora"],
        "quando": jogo.get("quando") or None, "competicao": jogo.get("competicao"),
        "texto": texto, "fatos": fatos, "suspeitos": suspeitos, "escalacao": origem,
    })
    return {"chave": chave, "ok": ok, "escalacao": origem,
            "suspeitos": suspeitos, "tamanho": len(texto)}


async def reescrever_previas_com_oficial(dia: str | None = None) -> dict:
    """Reescreve as prévias JÁ GERADAS deste dia, se a escalação oficial saiu.

    Só mexe no que já existe. Um jogo que você não pediu continua sem custar
    nada — a rotina automática nunca cria prévia, só atualiza a que você
    mandou criar.
    """
    dia = dia or _dia_de_brasilia()
    existentes = {p.get("chave"): p for p in previas_do_dia(dia)}
    pendentes = [c for c, p in existentes.items() if p.get("escalacao") != "oficial"]
    if not pendentes:
        return {"dia": dia, "candidatas": 0, "reescritas": 0}
    jogos = {(_chave_da_previa(j["fixture_id"])): j
             for j in await _jogos_para_previa(dia)}
    feitas = 0
    for chave in pendentes:
        jogo = jogos.get(chave)
        if not jogo:
            continue
        r = await gerar_previa(jogo, dia, forcar=True, so_se_oficial=True)
        if r.get("ok"):
            feitas += 1
    return {"dia": dia, "candidatas": len(pendentes), "reescritas": feitas}


@app.get("/api/previa")
async def api_previa(dia: str = ""):
    """Os jogos do dia, cada um com a prévia se ela já existir.

    A prévia gerada vem junto na resposta, e não atrás de uma segunda chamada.
    O motivo é o que você pediu: uma vez escrita, ela é a mesma para quem
    abrir — ninguém dispara geração nova só por olhar a tela.
    """
    dia = (dia or "").strip() or _dia_de_brasilia()
    prontas = {p.get("chave"): p for p in previas_do_dia(dia)}
    jogos = await _jogos_para_previa(dia)
    saida = []
    for j in jogos:
        p = prontas.get(_chave_da_previa(j["fixture_id"])) or {}
        saida.append({**j, "gerada": bool(p),
                      "texto": p.get("texto") or "",
                      "escalacao": p.get("escalacao") or "",
                      "suspeitos": p.get("suspeitos") or [],
                      "gerado_em": p.get("gerado_em") or ""})
    return {"dia": dia, "hoje": _dia_de_brasilia(),
            "jogos": saida, "dias": dias_com_previa(30)}


@app.post("/api/previa/gerar")
async def api_previa_gerar(request: Request):
    """Gera a prévia de UM jogo, quando você clica.

    Um jogo por chamada de propósito. Gerar o dia inteiro de uma vez era o
    desenho anterior e gastava relatório de jogo que ninguém ia ler.
    """
    try:
        corpo = await request.json()
    except Exception:
        return JSONResponse({"erro": "corpo inválido"}, 400)
    dia = (corpo.get("dia") or "").strip() or _dia_de_brasilia()
    try:
        fid = int(corpo.get("fixture_id"))
    except (TypeError, ValueError):
        return JSONResponse({"erro": "faltou dizer qual jogo"}, 400)

    # Se já existe, devolvo a que está lá. Dois cliques seguidos, ou dois
    # usuários na mesma tela, não podem virar duas chamadas de modelo.
    if not corpo.get("forcar"):
        for p in previas_do_dia(dia):
            if p.get("chave") == _chave_da_previa(fid):
                return {"ok": True, "ja_existia": True, "chave": p.get("chave")}

    jogo = next((j for j in await _jogos_para_previa(dia)
                 if j["fixture_id"] == fid), None)
    if not jogo:
        return JSONResponse({"erro": "não achei esse jogo nesta data"}, 404)
    return await gerar_previa(jogo, dia, forcar=bool(corpo.get("forcar")))


_PREVIA_CSS = """
body{background:var(--c-bg);color:var(--c-text);
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;margin:0}
.wrap{max-width:820px;margin:0 auto;padding:6px 16px 90px}
h1{font-family:'Bebas Neue',sans-serif;font-size:2.1rem;letter-spacing:.02em;
  margin:10px 0 4px}
.sub{font-size:.76rem;color:var(--c-muted-3);line-height:1.55;margin:0 0 16px}
.barra{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.ctrl{background:var(--c-bg-card);color:var(--c-text);border:1px solid var(--c-border);
  border-radius:12px;padding:8px 13px;font-size:.78rem;font-family:inherit;cursor:pointer}
.ctrl:hover{border-color:var(--c-acento)}
.ctrl.forte{background:var(--c-acento);color:var(--c-acento-texto);
  border-color:var(--c-acento);font-weight:700}
.jogo{background:var(--c-bg-card);border:1px solid var(--c-border);
  border-radius:18px;padding:0;margin-bottom:14px;overflow:hidden}
/* Verde quer dizer "já existe, é só abrir". A cor é o estado, e por isso ela
   está na borda e no topo do cartão, e não num texto que some na rolagem. */
.jogo.pronta{border-color:var(--c-acento)}
.jogo.pronta .topo{background:rgba(182,255,0,.07)}
.jogo .topo{padding:14px 16px;display:flex;justify-content:space-between;
  align-items:flex-start;gap:12px;cursor:pointer}
.jogo .acao{display:flex;gap:8px;align-items:center;flex:0 0 auto}
.canais{font-size:.62rem;color:var(--c-muted-3);margin-top:5px}
.jogo .conf{font-family:'Bebas Neue',sans-serif;font-size:1.35rem;
  letter-spacing:.03em;line-height:1.1}
.jogo .meta{font-size:.68rem;color:var(--c-muted-3);margin-top:4px}
.selo{font-size:.6rem;padding:2px 8px;border-radius:20px;white-space:nowrap;
  letter-spacing:.03em}
.selo.oficial{background:var(--c-acento);color:var(--c-acento-texto);font-weight:700}
.selo.provavel{background:rgba(255,190,93,.16);color:var(--c-alerta);
  border:1px solid var(--c-alerta)}
.corpo{padding:0 16px 16px;display:none}
.corpo.aberto{display:block}
.corpo h2{font-family:'Bebas Neue',sans-serif;font-size:1.05rem;letter-spacing:.04em;
  margin:18px 0 6px;color:var(--c-acento)}
.corpo p,.corpo li{font-size:.86rem;line-height:1.65;margin:6px 0}
.corpo ul{padding-left:18px;margin:6px 0}
.corpo strong{font-weight:700}
.aviso{border-radius:14px;padding:11px 13px;font-size:.74rem;line-height:1.55;
  margin:12px 0;border:1px solid var(--c-alerta);background:rgba(255,190,93,.10)}
.aviso b{display:block;margin-bottom:3px}
.vazio{text-align:center;color:var(--c-muted-3);font-size:.8rem;padding:34px 12px;
  line-height:1.6}
"""

_PREVIA_HTML = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prévia · IARABÃO</title>
__THEME__
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
__HEADER_CSS__
__PREVIA_CSS__
</style>
</head>
<body>
__HDR__
<div class="wrap">
  <h1>Prévia</h1>
  <p class="sub">Os jogos do dia. Clique em Gerar no que você vai comentar — o
     relatório só custa quando alguém pede. Depois de gerado, o cartão fica verde
     e abre no toque, igual para todo mundo. Se a escalação oficial sair, ele se
     reescreve sozinho.</p>
  <div class="barra">
    <input type="date" id="dia" class="ctrl">
    <button class="ctrl" onclick="carregar()">↻ Atualizar</button>
  </div>
  <div id="conteudo" class="vazio">carregando…</div>
</div>
<script>
__PREVIA_JS__
</script>
</body>
</html>"""

_PREVIA_JS = r"""
function esc(s){return String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// Markdown mínimo: título, lista, negrito e parágrafo. Não uso biblioteca de
// fora porque o texto vem de um modelo, e menos superfície é melhor.
function md(t){
  const linhas = esc(t).split('\n');
  let saida = '', lista = false;
  for (let l of linhas) {
    l = l.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const li = l.match(/^\s*[-*]\s+(.*)$/);
    const h2 = l.match(/^\s*#{1,3}\s+(.*)$/);
    if (li) { if (!lista) { saida += '<ul>'; lista = true; }
              saida += '<li>' + li[1] + '</li>'; continue; }
    if (lista) { saida += '</ul>'; lista = false; }
    if (h2) { saida += '<h2>' + h2[1] + '</h2>'; continue; }
    if (l.trim()) saida += '<p>' + l + '</p>';
  }
  if (lista) saida += '</ul>';
  return saida;
}

function hora(iso){
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleString('pt-BR',
    {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
}

async function carregar(){
  const d = document.getElementById('dia').value;
  const r = await (await fetch('/api/previa' + (d ? '?dia=' + encodeURIComponent(d) : ''))).json();
  const campo = document.getElementById('dia');
  if (campo && !campo.value) campo.value = r.dia;
  desenhar(r);
}

function desenhar(r){
  const alvo = document.getElementById('conteudo');
  const jogos = r.jogos || [];
  if (!jogos.length) {
    alvo.className = 'vazio';
    alvo.innerHTML = 'Nenhum jogo das nossas competições em ' + esc(r.dia) + '.';
    return;
  }
  alvo.className = '';
  alvo.innerHTML = jogos.map(function(p, i){
    const oficial = p.escalacao === 'oficial';
    const aviso = (p.suspeitos && p.suspeitos.length)
      ? '<div class="aviso"><b>' + p.suspeitos.length +
        ' número(s) que não achei nos dados</b>' + esc(p.suspeitos.join(', ')) +
        ' — confira antes de falar no ar.</div>'
      : '';
    const canais = (p.canais && p.canais.length)
      ? '<div class="canais">🖥️ ' + esc(p.canais.join(', ')) + '</div>' : '';
    const acao = p.gerada
      ? '<span class="selo ' + (oficial ? 'oficial' : 'provavel') + '">' +
        (oficial ? 'escalação oficial' : 'escalação provável') + '</span>'
      : '<button class="ctrl forte" onclick="gerar(event,' + p.fixture_id + ')">' +
        'Gerar</button>';
    return '<div class="jogo' + (p.gerada ? ' pronta' : '') + '" id="j' + p.fixture_id + '">' +
      '<div class="topo" onclick="' + (p.gerada ? 'abrir(' + i + ')' : '') + '">' +
        '<div><div class="conf">' + esc(p.casa) + ' x ' + esc(p.fora) + '</div>' +
        '<div class="meta">' + esc(p.competicao || '') + ' · ' + hora(p.quando) +
        (p.gerada ? ' · relatório de ' + hora(p.gerado_em) : '') + '</div>' +
        canais + '</div>' +
        '<div class="acao">' + acao + '</div>' +
      '</div>' +
      (p.gerada
        ? '<div class="corpo" id="c' + i + '">' + aviso + md(p.texto) + '</div>'
        : '') +
      '</div>';
  }).join('');
}

function abrir(i){
  const el = document.getElementById('c' + i);
  if (el) el.classList.toggle('aberto');
}

async function gerar(ev, fid){
  ev.stopPropagation();
  const b = ev.target;
  b.disabled = true;
  b.textContent = 'montando…';
  try {
    const d = await (await fetch('/api/previa/gerar', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({dia: document.getElementById('dia').value,
                            fixture_id: fid})})).json();
    if (d.erro) { alert(d.erro); b.disabled = false; b.textContent = 'Gerar'; return; }
    await carregar();
  } catch (e) {
    alert('não deu: ' + (e.message || e));
    b.disabled = false; b.textContent = 'Gerar';
  }
}

(function(){
  const q = new URLSearchParams(location.search).get('dia') || '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(q)) document.getElementById('dia').value = q;
})();
document.getElementById('dia').addEventListener('change', carregar);
carregar();
"""


@app.get("/previa", response_class=HTMLResponse)
async def pagina_previa():
    return HTMLResponse(
        _PREVIA_HTML
        .replace("__THEME__", _HEAD_COMUM)
        .replace("__HEADER_CSS__", _HEADER_CSS)
        .replace("__PREVIA_CSS__", _PREVIA_CSS)
        .replace("__PREVIA_JS__", _PREVIA_JS)
        .replace("__HDR__", _header("/previa"))
    )


@app.get("/api/convites")
async def api_convites_listar():
    """Os convites já criados. O código NÃO está aqui — nunca esteve no banco."""
    return {"convites": listar_convites(50),
            "papeis": [{"chave": p, "rotulo": contas.ROTULO_DO_PAPEL[p]}
                       for p in contas.PAPEIS if p != "adm"],
            "usuarios": listar_usuarios()}


@app.post("/api/convites")
async def api_convites_criar(request: Request):
    """Cria um convite e devolve o código UMA vez.

    Depois desta resposta o código não existe mais em lugar nenhum além de
    onde você colar. Perdeu, gera outro — é de uso único e vence em uma
    semana, então nada se perde de verdade.
    """
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    papel = contas.papel_valido(corpo.get("papel"))
    if papel == "adm":
        # Promover a adm é decisão para a tela de usuários, com a conta já
        # existindo. Um convite de adm circulando por e-mail é uma chave mestra
        # dentro de um aplicativo de mensagem.
        return JSONResponse({"erro": "convite de administrador não, por segurança"}, 400)
    codigo, resumo = contas.novo_convite()
    quem = _quem_esta_logado(request)
    if not registrar_convite(resumo, papel, quem, contas.validade_do_convite()):
        return JSONResponse({"erro": "não consegui guardar o convite"}, 500)
    return {"ok": True, "codigo": codigo, "papel": papel,
            "rotulo": contas.ROTULO_DO_PAPEL[papel],
            "dias": contas.DIAS_DE_CONVITE,
            "link": f"/cadastrar?convite={codigo}"}


@app.post("/api/usuarios/papel")
async def api_usuarios_papel(request: Request):
    """Troca o papel de alguém.

    Não deixo tirar o último adm. Um app sem administrador nenhum só se
    conserta mexendo no banco à mão, e quem faria isso é justamente quem
    perdeu o acesso.
    """
    try:
        corpo = await request.json()
    except Exception:
        return JSONResponse({"erro": "corpo inválido"}, 400)
    email = contas.normalizar_email(corpo.get("email"))
    papel = contas.papel_valido(corpo.get("papel"))
    if not email:
        return JSONResponse({"erro": "faltou o e-mail"}, 400)
    if papel != "adm":
        adms = [u for u in listar_usuarios() if (u.get("papel") or "") == "adm"]
        if len(adms) <= 1 and any(u.get("email") == email for u in adms):
            return JSONResponse(
                {"erro": "este é o último administrador — promova outro antes"}, 409)
    if not mudar_papel(email, papel):
        return JSONResponse({"erro": "não achei essa conta"}, 404)
    return {"ok": True, "papel": papel}


@app.get("/api/meu-perfil")
async def api_meu_perfil(request: Request):
    """Quem sou eu e o que posso ver — a tela usa para esconder o que não pode.

    Esconder é conforto, não proteção: quem chamar a rota direto continua
    barrado pelo middleware. As duas coisas juntas, nunca só a de cima.
    """
    email = _quem_esta_logado(request)
    papel = papel_do_usuario(email) if email else ""
    return {"email": email, "papel": papel,
            "rotulo": contas.ROTULO_DO_PAPEL.get(papel, ""),
            "pode_configurar": bool(papel) and contas.pode_ver(papel, "/configuracoes"),
            "pode_home": bool(papel) and contas.pode_ver(papel, "/"),
            "casa": contas.CASA_DO_PAPEL.get(papel, "/noticias")}


@app.get("/api/diag/nomes", response_class=PlainTextResponse)
async def diag_nomes():
    """Quantas grafias diferentes o app usa para a mesma coisa.

    Sondagem para decidir o tamanho da padronização. Não muda nada: só conta.
    """
    import glossary
    from difflib import SequenceMatcher
    linhas = []

    def bloco(t):
        linhas.append("")
        linhas.append(t)
        linhas.append("─" * len(t))

    def pega(sql, params=None):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(sql, params or [])
                return c.fetchall()
        except Exception as e:
            linhas.append(f"  (erro: {type(e).__name__}: {e})")
            return []

    # ── CLUBES: a mesma equipe, escrita em quantos lugares diferentes ──────
    bloco("CLUBES — uma grafia por guia")
    fontes = {
        "arbitragem": "SELECT casa FROM arbitragem UNION SELECT fora FROM arbitragem",
        "previa":     "SELECT casa FROM previa UNION SELECT fora FROM previa",
        "lesoes":     "SELECT DISTINCT club FROM injuries",
        "janela":     "SELECT DISTINCT team_out_name FROM window_transfers "
                      "UNION SELECT DISTINCT team_in_name FROM window_transfers",
        "clubes_extra": "SELECT DISTINCT nome FROM clubes_extra",
    }
    por_canonico = {}
    for guia, sql in fontes.items():
        brutos = [r[0] for r in pega(sql) if r[0]]
        reconhecidos = 0
        for b in brutos:
            canon = glossary.padronizar_clube(b)
            if canon:
                reconhecidos += 1
                por_canonico.setdefault(canon, {}).setdefault(b, set()).add(guia)
            else:
                por_canonico.setdefault(f"?? {b}", {}).setdefault(b, set()).add(guia)
        linhas.append(f"  {guia:14} {len(brutos):4} grafias, "
                      f"{reconhecidos} reconhecidas pelo glossário, "
                      f"{len(brutos) - reconhecidos} não")

    divergentes = {k: v for k, v in por_canonico.items()
                   if not k.startswith("??") and len(v) > 1}
    linhas.append(f"\n  clubes escritos de mais de um jeito: {len(divergentes)}")
    for canon, grafias in sorted(divergentes.items())[:25]:
        linhas.append(f"    {canon}")
        for g, guias in sorted(grafias.items()):
            linhas.append(f"        {g!r:38} ({', '.join(sorted(guias))})")

    desconhecidos = sorted(k[3:] for k in por_canonico if k.startswith("??"))
    linhas.append(f"\n  clubes que o glossário NÃO reconhece: {len(desconhecidos)}")
    for d in desconhecidos[:30]:
        linhas.append(f"    {d!r}")

    # ── JOGADORES: só existem em lesões e janela, e sem id nenhum ──────────
    bloco("JOGADORES")
    lesoes = [(r[0] or "", r[1] or "", r[2] or "")
              for r in pega("SELECT player_name, player_name_orig, club FROM injuries")]
    nomes = sorted({l[0] for l in lesoes if l[0]})
    com_orig = [l for l in lesoes if l[1]]
    arabes = [l for l in com_orig if any("؀" <= c <= "ۿ" for c in l[1])]
    linhas.append(f"  lesões registradas ......... {len(lesoes)}")
    linhas.append(f"  nomes distintos ............ {len(nomes)}")
    linhas.append(f"  com grafia original ........ {len(com_orig)}")
    linhas.append(f"  com original em árabe ...... {len(arabes)}")

    # Pares parecidos: é aqui que o SequenceMatcher de 0,75 pode ter fundido
    # gente diferente, ou deixado de fundir a mesma pessoa.
    def _norm(s):
        import unicodedata
        s = (s or "").lower().strip()
        return "".join(c for c in unicodedata.normalize("NFD", s)
                       if unicodedata.category(c) != "Mn")
    perigosos, quase = [], []
    for i, a in enumerate(nomes):
        for b in nomes[i + 1:]:
            r = SequenceMatcher(None, _norm(a), _norm(b)).ratio()
            if r >= 0.75:
                perigosos.append((round(r, 2), a, b))
            elif r >= 0.62:
                quase.append((round(r, 2), a, b))
    linhas.append(f"\n  pares com semelhança >= 0,75 (o app trata como a MESMA"
                  f" pessoa): {len(perigosos)}")
    for r, a, b in sorted(perigosos, reverse=True)[:20]:
        linhas.append(f"    {r}  {a!r}  ~  {b!r}")
    linhas.append(f"\n  pares entre 0,62 e 0,75 (o app trata como pessoas"
                  f" DIFERENTES): {len(quase)}")
    for r, a, b in sorted(quase, reverse=True)[:20]:
        linhas.append(f"    {r}  {a!r}  ~  {b!r}")

    jan = [(r[0] or "", r[1] or "") for r in
           pega("SELECT player_name, player_id FROM window_transfers")]
    linhas.append(f"\n  jogadores na janela ........ {len(jan)}")
    linhas.append(f"  com id do Transfermarkt .... {sum(1 for j in jan if j[1])}")
    fotos = pega("SELECT COUNT(*) FROM window_transfers WHERE photo <> ''")
    if fotos:
        linhas.append(f"  com foto ................... {fotos[0][0]}")
    # Os nomes da janela e os das lesões são as mesmas pessoas? Se batessem,
    # os ids do Transfermarkt já resolveriam metade do problema de graça.
    nomes_jan = {_norm(j[0]) for j in jan if j[0]}
    nomes_les = {_norm(n) for n in nomes}
    linhas.append(f"  nomes de lesão que existem na janela: "
                  f"{len(nomes_jan & nomes_les)} de {len(nomes_les)}")

    # ── A TABELA DE JOGADORES ──────────────────────────────────────────────
    bloco("JOGADORES DA LIGA (tabela nova)")
    n = contar_jogadores()
    linhas.append(f"  total ...................... {n.get('total')}")
    linhas.append(f"  com nome em árabe .......... {n.get('com_arabe')}")
    linhas.append(f"  com foto ................... {n.get('com_foto')}")
    linhas.append(f"  com id do Transfermarkt .... {n.get('com_transfermarkt')}")
    linhas.append(f"  com id da API-Football ..... {n.get('com_api_football')}")
    linhas.append(f"  clubes ..................... {n.get('clubes')}")
    faltando = pega("SELECT nome, clube FROM jogador "
                    "WHERE nome_ar IS NULL OR nome_ar = '' ORDER BY nome")
    if faltando:
        linhas.append(f"\n  sem nome em árabe ({len(faltando)}):")
        for nome, clube in faltando[:20]:
            linhas.append(f"    {nome}  ({clube})")
    amostra = pega("SELECT nome, nome_ar, clube FROM jogador "
                   "WHERE nome_ar <> '' ORDER BY random() LIMIT 8")
    if amostra:
        linhas.append("\n  amostra das duas escritas:")
        for nome, ar, clube in amostra:
            linhas.append(f"    {nome:28} = {ar:24} ({clube})")

    # ── O MAPA: onde mora identidade de jogador, e com que id ─────────────
    bloco("MAPA DAS TABELAS DE JOGADOR")
    linhas.append("  tabela              fonte             linhas   id próprio   "
                  "casa com a liga")
    linhas.append("  " + "─" * 76)

    def _n(sql):
        r = pega(sql)
        return (r[0][0] if r else 0) or 0

    n_liga = _n("SELECT COUNT(*) FROM jogador")
    n_liga_tm = _n("SELECT COUNT(*) FROM jogador WHERE tm_id IS NOT NULL AND tm_id <> ''")
    n_jan = _n("SELECT COUNT(DISTINCT player_id) FROM window_transfers "
               "WHERE player_id IS NOT NULL AND player_id <> ''")
    n_af = _n("SELECT COUNT(DISTINCT player_id) FROM stats_apuradas")
    n_les = _n("SELECT COUNT(*) FROM injuries")
    n_art = _n("SELECT COUNT(*) FROM articles")

    # Quantos da API-Football casam com a liga, pelo nome normalizado?
    liga_chaves = {glossary.chave_latina(n) for (n,) in
                   pega("SELECT nome FROM jogador") if n}
    af_nomes = [n for (n,) in pega("SELECT DISTINCT player_name FROM stats_apuradas") if n]
    af_casam = sum(1 for n in af_nomes if glossary.chave_latina(n) in liga_chaves)
    les_nomes = [n for (n,) in pega("SELECT DISTINCT player_name FROM injuries") if n]
    les_casam = sum(1 for n in les_nomes if glossary.chave_latina(n) in liga_chaves)

    for rot, fonte, total, tem_id, casa in [
        ("jogador", "API da liga", n_liga, "spl_id", f"— é a base ({n_liga_tm} com id TM)"),
        ("window_transfers", "Transfermarkt", n_jan, "id TM", f"{n_liga_tm} ligados"),
        ("stats_apuradas", "API-Football", n_af, "id AF", f"{af_casam} de {len(af_nomes)} pelo nome"),
        ("injuries", "notícia + modelo", n_les, "NENHUM", f"{les_casam} de {len(les_nomes)} pelo nome"),
        ("articles", "raspagem", n_art, "NENHUM", "0 — não há jogador extraído"),
    ]:
        linhas.append(f"  {rot:19} {fonte:17} {total:6}   {tem_id:11}  {casa}")

    # ── O que falta casar com a API-Football ──────────────────────────────
    bloco("O QUE FALTA CASAR COM A API-FOOTBALL")
    from difflib import SequenceMatcher as _SM2
    liga2 = {}
    for nome, clube in pega("SELECT nome, clube FROM jogador"):
        liga2.setdefault(glossary.chave_latina(nome), (nome, clube))
    ult = pega("SELECT MAX(season) FROM stats_apuradas")
    temporada = ult[0][0] if ult and ult[0][0] else None
    af_linhas = pega("SELECT DISTINCT player_name, team_name FROM stats_apuradas "
                     "WHERE season = %s", [temporada]) if temporada else []
    quase2, sem2, batem2 = [], [], 0
    for nome, time in af_linhas:
        ch = glossary.chave_latina(nome or "")
        if ch in liga2:
            batem2 += 1
            continue
        melhor, escore = None, 0.0
        for ch2, (n2, c2) in liga2.items():
            r2 = _SM2(None, ch, ch2).ratio()
            if r2 > escore:
                escore, melhor = r2, (n2, c2)
        if melhor and escore >= 0.80:
            quase2.append((round(escore, 2), nome or "", time or "", melhor[0], melhor[1]))
        else:
            sem2.append(nome or "")
    linhas.append(f"  temporada olhada .................. {temporada}")
    linhas.append(f"  nomes distintos na API-Football ... {len(af_linhas)}")
    linhas.append(f"  casam exato ...................... {batem2}")
    linhas.append(f"  QUASE (>= 0,80, recusados) ....... {len(quase2)}")
    linhas.append(f"  sem nada parecido ................ {len(sem2)}")
    if quase2:
        linhas.append("\n  os quase-acertos:")
        for r2, a2, t2, b2, c2 in sorted(quase2, reverse=True)[:20]:
            linhas.append(f"    {r2}  AF   {a2!r} ({t2})")
            linhas.append(f"          liga {b2!r} ({c2})")
    if sem2:
        linhas.append(f"\n  sem par (amostra): {', '.join(sem2[:12])}")

    # ── Por que o cruzamento com o Transfermarkt para onde para ───────────
    # A pergunta não é "quantos casaram", é "os que não casaram são gente que
    # não transferiu, ou quase-acerto de grafia que eu recusei?". A segunda
    # categoria é matéria-prima do índice de apelidos; a primeira não é nada.
    bloco("O QUE FALTA CASAR COM O TRANSFERMARKT")
    from difflib import SequenceMatcher as _SM
    liga = pega("SELECT nome, clube FROM jogador")
    jan = pega("SELECT DISTINCT player_name FROM window_transfers "
               "WHERE player_id IS NOT NULL AND player_id <> ''")
    por_chave_liga = {}
    for nome, clube in liga:
        por_chave_liga.setdefault(glossary.chave_latina(nome), (nome, clube))
    sem_par, quase = [], []
    for (nome,) in jan:
        ch = glossary.chave_latina(nome)
        if ch in por_chave_liga:
            continue
        melhor, escore = None, 0.0
        for ch2, (n2, c2) in por_chave_liga.items():
            r = _SM(None, ch, ch2).ratio()
            if r > escore:
                escore, melhor = r, (n2, c2)
        if melhor and escore >= 0.80:
            quase.append((round(escore, 2), nome, melhor[0], melhor[1]))
        else:
            sem_par.append(nome)
    linhas.append(f"  nomes distintos na janela .......... {len(jan)}")
    linhas.append(f"  já casados (chave exata) .......... {len(jan) - len(quase) - len(sem_par)}")
    linhas.append(f"  QUASE (>= 0,80, recusados) ........ {len(quase)}")
    linhas.append(f"  sem nada parecido na liga ......... {len(sem_par)}")
    if quase:
        linhas.append("\n  os quase-acertos — é aqui que o apelido resolve:")
        for r, a1, b1, c1 in sorted(quase, reverse=True)[:25]:
            linhas.append(f"    {r}  janela {a1!r}")
            linhas.append(f"          liga   {b1!r}  ({c1})")

    # ── NOTÍCIAS: quanto do material bruto é árabe ─────────────────────────
    bloco("NOTÍCIAS")
    art = pega("SELECT language, COUNT(*) FROM articles GROUP BY language "
               "ORDER BY 2 DESC")
    for lang, n in art:
        linhas.append(f"  {str(lang or '?'):6} {n}")
    guardados = pega("SELECT COUNT(*) FROM articles WHERE body_orig <> ''")
    if guardados:
        linhas.append(f"  com corpo original guardado: {guardados[0][0]}")

    return PlainTextResponse("\n".join(linhas))


# ══════════════════════════════════════════════════════════════════════════
# QUEM JOGA NA LIGA
#
# A varredura que preenche a tabela `jogador`. Lê a escalação de cada partida
# disputada nos DOIS idiomas — o mesmo playerId responde em inglês e em árabe,
# e é essa coincidência de id que vira a ponte entre a grafia da imprensa
# saudita e a nossa. Sem transliteração, sem palpite.
# ══════════════════════════════════════════════════════════════════════════

def varrer_jogadores(limite_de_jogos: int = 0) -> dict:
    """Percorre as partidas já disputadas e guarda quem foi relacionado.

    Do mais recente para o mais antigo, de propósito: se a varredura for
    interrompida no meio, o que ficou pronto é o elenco atual, não o de
    agosto. `limite_de_jogos` existe para a primeira execução poder ser curta
    e conferível antes de soltar a temporada inteira.

    A leitura em si mora no liga_spl (jogadores_dos_jogos), que já junta as
    duas escritas pelo playerId. Aqui fica só a decisão de QUAIS jogos ler e
    o que contar depois.
    """
    import httpx
    import liga_spl

    dia = _dia_de_brasilia()
    with httpx.Client() as cliente:
        sid = liga_spl.temporada(dia, cliente)
        if not sid:
            return {"erro": "não achei a temporada corrente na API da liga"}
        jogos = liga_spl.jogos_ate(sid, dia, cliente)
        if limite_de_jogos:
            jogos = jogos[:limite_de_jogos]
        try:
            pessoas = liga_spl.jogadores_dos_jogos(sid, jogos, cliente)
        except Exception as e:
            return {"erro": f"{type(e).__name__}: {e}"}

    r = salvar_jogadores(pessoas)
    # Cruzar com o Transfermarkt logo em seguida: do seu ponto de vista é a
    # mesma tarefa, e separar em dois botões só criaria a chance de alguém
    # rodar um e esquecer o outro.
    tm = cruzar_transfermarkt()
    af = cruzar_api_football()
    resumo = {"jogos_lidos": len(jogos), "pessoas": len(pessoas),
              **r, "transfermarkt": tm, "api_football": af, **contar_jogadores()}
    print(f"[JOGADORES] {resumo}", flush=True)
    return resumo


@app.post("/api/jogadores/api-football")
async def api_jogadores_af():
    """Liga a tabela de jogadores aos ids da API-Football da estatística."""
    import asyncio as _a
    return await _a.to_thread(cruzar_api_football)


@app.post("/api/jogadores/transfermarkt")
async def api_jogadores_tm():
    """Liga a tabela de jogadores aos ids do Transfermarkt que a janela traz."""
    import asyncio as _a
    return await _a.to_thread(cruzar_transfermarkt)


@app.post("/api/jogadores/varrer")
async def api_jogadores_varrer(request: Request):
    """Roda a varredura. `jogos` limita, para conferir antes de soltar tudo."""
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    try:
        limite = int(corpo.get("jogos") or 0)
    except (TypeError, ValueError):
        limite = 0
    import asyncio as _a
    return await _a.to_thread(varrer_jogadores, limite)


@app.get("/api/jogadores")
async def api_jogadores(clube: str = "", limite: int = 600):
    """O resumo sempre; a lista só se você pedir.

    A tela de Configurações quer os números, não as 450 linhas — puxar tudo
    para mostrar uma contagem é o tipo de peso que ninguém percebe até a
    página começar a demorar.
    """
    try:
        limite = max(0, min(int(limite), 2000))
    except (TypeError, ValueError):
        limite = 600
    return {"resumo": contar_jogadores(),
            "jogadores": listar_jogadores(clube, limite) if limite else []}


async def congelar_elencos_do_tm() -> dict:
    """Guarda no banco os elencos que hoje vêm do Transfermarkt ao vivo.

    Isto é o ponto de retorno. A guia /elencos nunca teve cópia no banco —
    ela raspava o TM a cada abertura, com cache só na memória. Desligar a
    fonte sem isto não deixaria o campinho mais pobre, deixaria a guia vazia,
    e não haveria de onde voltar.

    Roda sozinha na primeira subida depois deste deploy, ENQUANTO o TM ainda
    está no projeto. Uma vez só: o objetivo é um retrato, não um espelho.
    """
    if get_state("elencos_congelados") == "sim":
        return {"pulado": True}
    import elenco_tm
    times, aviso = await elenco_tm.clubes()
    if not times:
        # Sem clube nenhum não marco como feito: a próxima subida tenta de
        # novo. Marcar aqui congelaria o vazio para sempre.
        print(f"[CONGELAR] não achei clube nenhum no TM ({aviso})", flush=True)
        return {"erro": aviso or "sem clubes"}
    total = 0
    falhas = []
    for t in times:
        try:
            plantel, av = await elenco_tm.elenco(t["id"])
        except Exception as e:
            falhas.append(f"{t['nome']}: {type(e).__name__}: {e}")
            continue
        if not plantel:
            falhas.append(f"{t['nome']}: elenco vazio ({av})")
            continue
        total += congelar_elenco(t["id"], t["nome"], plantel)
    # Só considero feito se a maioria dos clubes veio. Um congelamento pela
    # metade marcado como pronto seria pior que nenhum: some o aviso e fica o
    # buraco.
    if len(falhas) <= len(times) // 3:
        set_state("elencos_congelados", "sim")
    print(f"[CONGELAR] {total} jogadores de {len(times) - len(falhas)} clubes; "
          f"{len(falhas)} falhas", flush=True)
    for f in falhas[:5]:
        print(f"[CONGELAR] {f}", flush=True)
    return {"jogadores": total, "clubes": len(times) - len(falhas),
            "falhas": falhas, **resumo_do_congelamento()}


@app.post("/api/elencos/congelar")
async def api_elencos_congelar():
    """Refaz o retrato à mão, se precisar antes de o TM sair."""
    set_state("elencos_congelados", "")
    return await congelar_elencos_do_tm()


@app.get("/api/diag/congelado", response_class=PlainTextResponse)
async def diag_congelado():
    """O que está guardado do Transfermarkt — a rede antes do salto."""
    r = resumo_do_congelamento()
    linhas = [f"jogadores guardados .... {r.get('jogadores')}",
              f"clubes ................. {r.get('clubes')}",
              f"com pé preferido ....... {r.get('com_pe')}",
              f"congelado em ........... {r.get('quando')}"]
    porc = {}
    for j in elenco_congelado():
        porc.setdefault(j.get("clube") or "?", 0)
        porc[j["clube"]] += 1
    linhas.append("")
    for clube, n in sorted(porc.items()):
        linhas.append(f"  {clube:22} {n}")
    return PlainTextResponse("\n".join(linhas))
