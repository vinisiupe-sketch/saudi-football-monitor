"""
Agendador — usa APScheduler para rodar a pipeline de coleta periodicamente.
Período inativo: 01h–06h horário de Brasília (UTC-3).
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from collector import collect_all
from processor import process_and_save
from database import log_collection, get_state, set_state
from janela_scraper import run_janela_scrape

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
INACTIVE_START = 1   # 01:00 BRT
INACTIVE_END   = 6   # 06:00 BRT
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 30))
LAST_COLLECT_KEY = "last_collect_at"
# Teto da janela de "olhar pra trás" — mesmo limite que collector.py usa pra
# descartar artigos antigos (ARTICLE_MAX_AGE_HOURS). Pedir mais que isso não
# adianta: o parse_entries vai jogar fora qualquer coisa além desse prazo.
MAX_LOOKBACK_HOURS = 48


def is_inactive_period() -> bool:
    hour = datetime.now(BRASILIA_TZ).hour
    return INACTIVE_START <= hour < INACTIVE_END


def lookback_hours() -> int:
    """
    Janela de coleta — precisa cobrir tudo que aconteceu desde a ÚLTIMA coleta
    bem-sucedida, não um valor fixo.

    Bug real (2026-06-24): a versão antiga calculava um valor fixo a partir do
    intervalo configurado (`COLLECT_INTERVAL // 60 or 2`). Durante a queda de
    autenticação do X, várias coletas em sequência falharam totalmente
    (sources_ok=0); quando a autenticação foi corrigida horas depois, a janela
    fixa não alcançava mais os tweets do início da queda — ficaram pra sempre
    fora do alcance mesmo com a falha já corrigida, porque a cada execução o
    "agora" andava e a janela fixa nunca esticava pra compensar o buraco.

    Agora a janela é dinâmica: cobre o tempo real desde a última coleta com ao
    menos 1 fonte OK (+1h de margem de segurança), com piso no intervalo
    configurado e teto em MAX_LOOKBACK_HOURS.
    """
    configured_floor = max(COLLECT_INTERVAL // 60, 1)
    now = datetime.now(timezone.utc)
    hours = configured_floor
    try:
        last_raw = get_state(LAST_COLLECT_KEY)
        if last_raw:
            last_dt = datetime.fromisoformat(last_raw)
            gap_hours = (now - last_dt).total_seconds() / 3600
            hours = max(configured_floor, gap_hours + 1)
    except Exception as e:
        print(f"  ⚠️  Não foi possível ler last_collect_at, usando piso padrão: {e}")
    return min(int(hours) + 1, MAX_LOOKBACK_HOURS)


async def run_pipeline(force: bool = False, hours: int | None = None):
    if not force and is_inactive_period():
        print(f"😴 Período inativo (01h–06h BRT) — coleta suspensa")
        return {"skipped": True}

    effective_hours = hours if hours is not None else lookback_hours()
    log = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "sources_ok": 0,
        "sources_fail": 0,
        "articles_new": 0,
        "articles_dup": 0,
        "error_msg": None,
    }
    try:
        collect_result = await collect_all(hours=effective_hours)
        log["sources_ok"] = collect_result.get("sources_ok", 0)
        log["sources_fail"] = collect_result.get("sources_fail", 0)
        process_result = await process_and_save(collect_result["articles"])
        log["articles_new"] = process_result.get("articles_new", 0)
        log["articles_dup"] = process_result.get("articles_dup", 0)
        print(f"✅ Pipeline concluída — {log['articles_new']} artigos novos (janela: {effective_hours}h)")
        # Só avança o marcador se ao menos 1 fonte respondeu. Numa falha total
        # (ex: auth caída), o marcador antigo fica como está, e a PRÓXIMA
        # execução automaticamente vai pedir uma janela maior pra cobrir o
        # buraco inteiro — é exatamente esse comportamento que faltava.
        if log["sources_ok"] > 0:
            try:
                set_state(LAST_COLLECT_KEY, log["ran_at"])
            except Exception as e:
                print(f"  ⚠️  Não foi possível salvar last_collect_at: {e}")
    except Exception as e:
        log["error_msg"] = str(e)
        print(f"❌ Erro na pipeline: {e}")
    finally:
        log_collection(log)
    return log


def _next_scheduled_fire() -> datetime:
    """
    Ancora o próximo disparo do job recorrente em last_collect_at + intervalo,
    em vez de sempre "agora + intervalo" (comportamento padrão do APScheduler
    a cada scheduler.start()).

    Bug real (2026-07-25): durante uma sessão de deploys frequentes (várias
    correções em sequência), cada restart do processo reiniciava a contagem
    do IntervalTrigger a partir do boot — então o job recorrente nunca
    completava os 30min antes do próximo restart interromper de novo. Só o
    "roda uma vez na inicialização" disparava, repetidas vezes, dando a
    impressão de coleta funcionando enquanto o agendamento de fundo real
    nunca se sustentava. Agora o próximo disparo é calculado a partir do
    estado persistido (Postgres), sobrevivendo a qualquer restart.
    """
    now = datetime.now(timezone.utc)
    try:
        last_raw = get_state(LAST_COLLECT_KEY)
        if last_raw:
            last_dt = datetime.fromisoformat(last_raw)
            next_due = last_dt + timedelta(minutes=COLLECT_INTERVAL)
            return next_due if next_due > now else now + timedelta(seconds=30)
    except Exception as e:
        print(f"  ⚠️  Não foi possível calcular próximo disparo, usando padrão: {e}")
    return now + timedelta(minutes=COLLECT_INTERVAL)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=COLLECT_INTERVAL, start_date=_next_scheduled_fire()),
        id="collect_pipeline",
        replace_existing=True,
    )
    scheduler.add_job(
        run_janela_scrape,
        trigger="cron",
        hour=7,
        minute=0,
        id="janela_scrape_daily",
        replace_existing=True,
    )
    scheduler.add_job(
        run_varredura_competicoes,
        trigger="cron",
        hour=5,
        minute=30,
        id="varredura_competicoes_daily",
        replace_existing=True,
    )
    # Véspera à noite: os jogos do dia seguinte entram na fila para você
    # preencher a transmissão com calma. Nada é publicado aqui — só enfileirado.
    # O Railway roda em UTC, então 23h aqui é 20h de Brasília. E "amanhã" também
    # é contado em UTC, o que casa com os jogos sauditas (15h–19h UTC).
    scheduler.add_job(
        run_fila_bola_rolando,
        trigger="cron",
        hour=23,
        minute=0,
        id="fila_bola_rolando_diaria",
        replace_existing=True,
    )
    # Não existe rotina que CRIA prévia: quem cria é o seu clique. Esta aqui
    # só reescreve o que já foi criado, quando a escalação oficial sai. Os
    # jogos sauditas vão das 15h às 19h UTC e a escalação sai perto de uma
    # hora antes, então varro das 13h às 19h. Fora dessa janela seria à toa.
    scheduler.add_job(
        run_previa_oficial,
        trigger="cron",
        hour="13-19",
        minute="0,30",
        id="previa_oficial",
        replace_existing=True,
    )
    # 8h de Brasília = 11h UTC. A escala de arbitragem do SAFF sai no dia, em
    # horário que eles não anunciam. Uma passada só, como combinado; se o SAFF
    # atrasar, o botão "Buscar no SAFF agora" na guia resolve na hora.
    scheduler.add_job(
        run_arbitragem,
        trigger="cron",
        hour=11,
        minute=0,
        id="arbitragem_diaria",
        replace_existing=True,
    )
    # A cada 30s: publica o que VOCÊ aprovou e cujo horário de início chegou.
    # O X não tem endpoint de agendamento fora da Ads API (que exige conta de
    # anunciante), então o disparo é nosso mesmo. Com 60s o atraso podia chegar
    # a um minuto; com 30s o pior caso cai pela metade, e o custo é só uma
    # consulta a mais por minuto no banco — nenhuma chamada à API do X.
    # Enquanto durar a comparação com a Sportmonks: carimba, de minuto em
    # minuto, o instante em que cada fonte publica cada gol. É barato (só olha
    # jogo ao vivo) e é o único jeito de saber qual chega antes.
    scheduler.add_job(
        run_coletar_gols,
        trigger=IntervalTrigger(seconds=45),
        id="coletar_gols_ao_vivo",
        replace_existing=True,
    )
    # Escalações: a mesma medição, para outro dado. De 40 em 40 segundos —
    # a diferença entre as fontes só é confiável até a resolução deste
    # intervalo, e apertar demais gastaria chamada sem ganho.
    scheduler.add_job(
        run_coletar_escalacoes,
        trigger=IntervalTrigger(seconds=40),
        id="coletar_escalacoes",
        replace_existing=True,
    )
    scheduler.add_job(
        run_descartar_clipes,
        trigger=IntervalTrigger(minutes=10),
        id="descartar_clipes",
        replace_existing=True,
    )
    scheduler.add_job(
        run_publicar_aprovados,
        trigger=IntervalTrigger(seconds=30),
        id="publicar_aprovados",
        replace_existing=True,
    )
    print(
        f"⏰ Scheduler iniciado: coleta a cada {COLLECT_INTERVAL}min "
        "+ varredura de competições às 05h30 + scrape janela às 07h"
    )
    return scheduler


async def run_varredura_competicoes():
    """Reapura as competições que a API-Football não cobre por jogador.

    Roda de madrugada, longe do horário de jogo, porque reprocessa a competição
    inteira (~2 chamadas por partida). Se a API restaurar a cobertura de alguma
    delas, ela simplesmente deixa de ser detectada e o app volta a usar o número
    da fonte — sem precisar mexer aqui."""
    try:
        from main import _af_varrer_tudo
        r = await _af_varrer_tudo()
        print(f"🧮 Varredura de competições: {r.get('competicoes_detectadas')} detectadas")
        return r
    except Exception as e:
        print(f"❌ Erro na varredura de competições: {e}")
        return {"erro": str(e)}


async def run_previa_oficial():
    """Reescreve as prévias JÁ GERADAS de hoje quando a escalação oficial sai.

    Nunca cria prévia. Quem decide que um jogo merece relatório é o clique na
    tela — esta rotina só atualiza o que você já mandou escrever, e só quando
    há motivo: se a oficial ainda não saiu, ela nem chega a pedir texto ao
    modelo. Sem essa guarda, varrer de meia em meia hora pagaria pelo mesmo
    relatório doze vezes por dia.
    """
    try:
        from main import reescrever_previas_com_oficial
        r = await reescrever_previas_com_oficial()
        if r.get("reescritas"):
            print(f"📋 Prévia: {r.get('reescritas')} de {r.get('candidatas')} "
                  f"reescritas com a escalação oficial")
        return r
    except Exception as e:
        print(f"❌ Erro ao reescrever a prévia de hoje: {type(e).__name__}: {e}")
        return {"erro": str(e)}


async def run_arbitragem():
    """Busca a escala de arbitragem do dia no SAFF e guarda.

    Esta é a única chance. O SAFF publica no dia e depois tira do ar — em
    datas antigas não há apito em jogo nenhum. Se esta rotina falhar calada,
    o dia se perde e ninguém descobre, então o erro é impresso e o resultado
    também: "0 guardados" precisa aparecer no log tanto quanto "5 guardados".
    """
    try:
        from main import buscar_arbitragem
        r = await asyncio.to_thread(buscar_arbitragem)
        print(f"🧑‍⚖️ Arbitragem {r.get('dia')}: {r.get('guardados')} guardados, "
              f"{len(r.get('ignorados') or [])} fora das nossas competições, "
              f"{len(r.get('erros') or [])} erros")
        return r
    except Exception as e:
        print(f"❌ Erro ao buscar a arbitragem do dia: {type(e).__name__}: {e}")
        return {"erro": str(e)}


async def run_fila_bola_rolando():
    """Coloca na fila os BOLA ROLANDO dos jogos de amanhã."""
    try:
        from main import gerar_bola_rolando
        r = await gerar_bola_rolando()
        print(f"📝 Fila BOLA ROLANDO ({r.get('data')}): {r.get('novos')} novos, "
              f"{r.get('ja_estavam')} já estavam")
        return r
    except Exception as e:
        print(f"❌ Erro ao montar a fila de posts: {e}")
        return {"erro": str(e)}


async def run_descartar_clipes():
    """Apaga os clipes que ninguém mandou guardar. Silencioso quando não há."""
    try:
        from database import descartar_clipes, listar_lives
        from main import ajuste
        r = descartar_clipes([l.get("id") for l in listar_lives()],
                             int(ajuste("clipe_horas_descarte")))
        if r.get("apagados"):
            print(f"🗑️ {r['apagados']} clipe(s) descartado(s)")
        elif r.get("erro"):
            # Falha de faxina precisa aparecer. A versão anterior só falava
            # quando dava certo, e por isso o defeito ficou invisível.
            print(f"❌ Descarte de clipes falhou: {r['erro']}")
        return r
    except Exception as e:
        print(f"❌ Erro ao descartar clipes: {e}")
        return {"erro": str(e)}


async def run_coletar_escalacoes():
    """Carimba as escalações das duas fontes. Silencioso fora da janela."""
    try:
        from main import coletar_escalacoes
        r = await coletar_escalacoes()
        if r.get("novos"):
            print(f"📋 {r['novos']} escalação(ões) carimbada(s)")
        return r
    except Exception as e:
        print(f"❌ Erro ao carimbar escalações: {e}")
        return {"erro": str(e)}


async def run_coletar_gols():
    """Carimba os gols das duas fontes. Silencioso quando não há jogo."""
    try:
        from main import coletar_gols_ao_vivo
        r = await coletar_gols_ao_vivo()
        if r.get("novos"):
            print(f"⚽ {r['novos']} gol(s) carimbado(s): {r.get('detalhe')}")
        return r
    except Exception as e:
        print(f"❌ Erro ao carimbar gols: {e}")
        return {"erro": str(e)}


async def run_publicar_aprovados():
    """Dispara os posts aprovados no horário do apito. Só toca em 'aprovado'."""
    try:
        from main import publicar_aprovados
        r = await publicar_aprovados()
        if r.get("publicados") or r.get("falhas"):
            print(f"📤 Posts: {r['publicados']} publicados, {r['falhas']} falharam")
        return r
    except Exception as e:
        print(f"❌ Erro ao publicar aprovados: {e}")
        return {"erro": str(e)}
