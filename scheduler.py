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
from database import log_collection

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
INACTIVE_START = 1   # 01:00 BRT
INACTIVE_END   = 6   # 06:00 BRT
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 360))


def is_inactive_period() -> bool:
    hour = datetime.now(BRASILIA_TZ).hour
    return INACTIVE_START <= hour < INACTIVE_END


def lookback_hours() -> int:
    """Após o período inativo, varre as horas que ficaram pra trás."""
    now = datetime.now(BRASILIA_TZ)
    if now.hour == INACTIVE_END:
        inactive_hours = INACTIVE_END - INACTIVE_START
        return inactive_hours + (COLLECT_INTERVAL // 60)
    return COLLECT_INTERVAL // 60 or 2


async def run_pipeline(force: bool = False):
    if not force and is_inactive_period():
        print(f"😴 Período inativo (01h–06h BRT) — coleta suspensa")
        return {"skipped": True}

    hours = lookback_hours()
    log = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "sources_ok": 0,
        "sources_fail": 0,
        "articles_new": 0,
        "articles_dup": 0,
        "error_msg": None,
    }
    try:
        collect_result = await collect_all(hours=hours)
        log["sources_ok"] = collect_result.get("sources_ok", 0)
        log["sources_fail"] = collect_result.get("sources_fail", 0)
        process_result = await process_and_save(collect_result["articles"])
        log["articles_new"] = process_result.get("articles_new", 0)
        log["articles_dup"] = process_result.get("articles_dup", 0)
        print(f"✅ Pipeline concluída — {log['articles_new']} artigos novos (janela: {hours}h)")
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
