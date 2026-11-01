"""24/7 worker: APScheduler drives the three tasks. Run with `python -m agent run`."""
from __future__ import annotations

import asyncio
import logging
import time

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .app import task_discover, task_inbox, task_poll
from .notify import send_text
from .settings import Settings
from .store import Store

log = logging.getLogger("agent.scheduler")
_last_alert: dict[str, float] = {}


async def _guard(name: str, fn, s: Settings):
    try:
        res = await asyncio.wait_for(fn(s), timeout=60 * 60)  # no task may hang forever
        log.info("%s ok: %s", name, res)
        if s.healthcheck_url and name == "poll":
            await asyncio.to_thread(lambda: requests.get(s.healthcheck_url, timeout=10))
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", name)
        if time.time() - _last_alert.get(name, 0) > 6 * 3600:  # don't spam
            _last_alert[name] = time.time()
            send_text(f"⚠️ Agent task '{name}' failed: {type(e).__name__}: {e}")


async def heartbeat(s: Settings):
    st = Store(s.state_db)
    lines = []
    for kind in ("discover", "poll", "inbox"):
        r = st.last_run(kind)
        lines.append(f"{kind}: " + ("never" if not r else f"{'ok' if r['ok'] else 'FAILED'} @ {time.strftime('%d %b %H:%M', time.localtime(r['finished']))}"))
    send_text("✅ Job agent alive\n" + "\n".join(lines))


async def run_forever(s: Settings | None = None):
    s = s or Settings()
    s.ensure_dirs()
    sch = AsyncIOScheduler(timezone=s.timezone)
    common = dict(max_instances=1, coalesce=True, misfire_grace_time=3600)
    sch.add_job(_guard, CronTrigger.from_crontab(s.discovery_cron, timezone=s.timezone), args=["discover", task_discover, s], id="discover", **common)
    sch.add_job(_guard, CronTrigger.from_crontab(s.inbox_cron, timezone=s.timezone), args=["inbox", task_inbox, s], id="inbox", **common)
    sch.add_job(_guard, "interval", minutes=s.poll_minutes, args=["poll", task_poll, s], id="poll", **common)
    sch.add_job(heartbeat, CronTrigger.from_crontab("0 21 * * *", timezone=s.timezone), args=[s], id="heartbeat", **common)
    sch.start()
    log.info("scheduler started (tz=%s)", s.timezone)
    await asyncio.Event().wait()
