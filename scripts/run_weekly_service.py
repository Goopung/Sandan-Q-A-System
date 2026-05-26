import os
import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
scheduler = BlockingScheduler(timezone="Asia/Seoul")


@scheduler.scheduled_job("cron", day_of_week="mon", hour=3, minute=0)
def weekly_update() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "update_weekly.py")]
    print("[WEEKLY UPDATE]", " ".join(command))
    subprocess.run(command, check=False, cwd=str(PROJECT_ROOT), env=env)


if __name__ == "__main__":
    print("Weekly update service started. Schedule: every Monday 03:00 Asia/Seoul")
    scheduler.start()
