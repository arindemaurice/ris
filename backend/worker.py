"""RIS maintenance worker: expiry, ISP SaaS billing and account deprovisioning.

Run as a separate process (python worker.py). Keep one worker active per DB.
"""
from __future__ import annotations
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app import init_db, logger, process_maintenance_once

if __name__ == "__main__":
    interval = max(15, int(os.getenv("RIS_WORKER_INTERVAL_SECONDS", "60")))
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    init_db()
    logger.info("RIS maintenance worker started; interval=%ss", interval)
    while True:
        try:
            result = process_maintenance_once()
            logger.info("Maintenance cycle: %s", result)
        except KeyboardInterrupt:
            logger.info("RIS maintenance worker stopping")
            break
        except Exception:
            logger.exception("Maintenance cycle failed")
        time.sleep(interval)
