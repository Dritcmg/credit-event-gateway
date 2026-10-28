import argparse
import json
import signal
from threading import Event as StopEvent

from sqlalchemy.exc import SQLAlchemyError

from gateway.config import Settings
from gateway.db import session_factory
from gateway.service import process_one, utc_now


def run_worker(factory, settings, *, once=False, max_failures=5, stop=None, wait=None, now=utc_now):
    """Bound consecutive DB failures; keep exception strings and configuration out of logs."""
    if not 1 <= max_failures <= 10:
        raise ValueError("max_failures must be between 1 and 10")
    stop = stop or StopEvent()
    wait = wait or stop.wait
    failures = 0
    while not stop.is_set():
        try:
            outcome = process_one(factory, settings, now())
        except SQLAlchemyError:
            failures += 1
            if failures >= max_failures:
                print(
                    json.dumps({"event": "worker_failure_budget_exhausted", "attempts": failures}),
                    flush=True,
                )
                return 1
            delay = min(2 ** (failures - 1), 30)
            print(
                json.dumps(
                    {
                        "event": "worker_database_retry",
                        "attempt": failures,
                        "retry_in_seconds": delay,
                    }
                ),
                flush=True,
            )
            if wait(delay):
                return 0
            continue
        failures = 0
        print(json.dumps({"event": "worker_tick", "outcome": outcome}), flush=True)
        if once:
            return 0
        if outcome is None and wait(1):
            return 0
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-failures", type=int, choices=range(1, 11), default=5)
    args = parser.parse_args()
    settings = Settings.from_env()
    engine, factory = session_factory(settings.database_url)
    stop = StopEvent()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    try:
        return run_worker(
            factory, settings, once=args.once, max_failures=args.max_failures, stop=stop
        )
    except KeyboardInterrupt:
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
