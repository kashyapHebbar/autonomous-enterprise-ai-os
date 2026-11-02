"""Run trusted operator-owned ingestion definitions once or on a schedule."""

import argparse
import json
import logging
import time

from aeai_os.connectors.ingestion import IngestionStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--database", default="artifacts/ingestion.db")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    with open(args.config) as handle:
        jobs = json.load(handle)
    store = IngestionStore(args.database)
    while True:
        failed = False
        for job in jobs:
            try:
                changed = store.sync(job)
                # Export even after an unchanged fetch, recovering a crash after DB commit.
                if job.get("output_csv"):
                    store.export_csv(job, job["output_csv"])
                logging.warning("Ingestion %s: %d changed records", job["id"], changed)
            except Exception as exc:
                failed = True
                # Provider errors can contain credentials; log only the exception type.
                logging.error("Ingestion failed (%s)", type(exc).__name__)
        if not args.loop:
            return 1 if failed else 0
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
