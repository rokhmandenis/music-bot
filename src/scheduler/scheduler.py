from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from config import TIMEZONE

def start_scheduler(job_func):
    tz = timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)

    scheduler.add_job(job_func, "cron", hour=8, minute=0)
    scheduler.start()
    print("Scheduler started (08:00 Europe/Berlin)")
