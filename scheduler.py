"""
Agendador — usa APScheduler para rodar a pipeline de coleta periodicamente.
Período inativo: 01h–06h horário de Brasília (UTC-3).
"""
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from collector import collect_all
from processor import process_and_save
from database import log_collection, get_state, set_state

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
INACTIVE_START = 1   # 01:00 BRT
INACTIVE_END   = 6   # 06:00 BRT
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 360))
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


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=COLLECT_INTERVAL),
        id="collect_pipeline",
        replace_existing=True,
    )
    print(f"⏰ Scheduler: coleta a cada {COLLECT_INTERVAL} minutos | inativo 01h–06h BRT")
    return scheduler
