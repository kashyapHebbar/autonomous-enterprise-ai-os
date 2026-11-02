"""Run the bounded, restart-safe CSV screening queue without model calls."""

from __future__ import annotations

import argparse
import signal
import time

from aeai_os.scaling.risk import process_next


def main():
    parser = argparse.ArgumentParser(description="Disk-backed pattern screening worker")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll", type=float, default=2.0)
    options = parser.parse_args()
    stopping = False

    def close(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, close)
    signal.signal(signal.SIGINT, close)
    while not stopping:
        job = process_next(stop=lambda: stopping)
        if job:
            print(f"Completed screening worker cycle: {job}", flush=True)
        if not options.loop:
            break
        if not job:
            time.sleep(max(0.2, options.poll))


if __name__ == "__main__":
    main()
