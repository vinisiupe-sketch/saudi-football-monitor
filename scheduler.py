"""
Agendador — usa APScheduler para rodar a pipeline de coleta periodicamente.
"""
import os
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from collector import collect_all
from processor import process_and_save
from database import log_collection


async def run_pipeline():
    log = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "sources_ok": 0,
        "sources_fail": 0,
        "articles_new": 0,
        "articles_dup": 0,
        "error_msg": None,
    }
    try:
        collect_result = await collect_all()
        log["sources_ok"] = collect_result.get("sources_ok", 0)
        log["sources_fail"] = collect_result.get("sources_fail", 0)
        process_result = await process_and_save(collect_result["articles"])
        log["articles_new"] = process_result.get("articles_new", 0)
        log["articles_dup"] = process_result.get("articles_dup", 0)
        print(f"✅ Pipeline concluída — {log['articles_new']} artigos novos")
    except Exception as e:
        log["error_msg"] = str(e)
        print(f"❌ Erro na pipeline: {e}")
    finally:
        log_collection(log)
    return log


def create_scheduler() -> AsyncIOScheduler:
    interval = int(os.environ.get("COLLECT_INTERVAL_MINUTES", 120))
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=interval),
        id="collect_pipeline",
        replace_existing=True,
    )
    print(f"⏰ Scheduler: coleta a cada {interval} minutos ({interval//60}h)")
    return scheduler
