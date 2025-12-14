import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from dotenv import load_dotenv


def start_scheduler(job_func):
    # Находим корень проекта и грузим config/.env НАДЁЖНО (абсолютным путём)
    base_dir = Path(__file__).resolve().parents[2]  # .../music-bot
    env_path = base_dir / "config" / ".env"
    load_dotenv(dotenv_path=env_path)

    tz_name = os.getenv("TIMEZONE", "Europe/Berlin")
    tz = timezone(tz_name)

    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(job_func, "cron", hour=8, minute=0)
    scheduler.start()
    print(f"Scheduler started (08:00 {tz_name})")
