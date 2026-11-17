"""Entry point: python -m customs_ingest.main [--once] [--live]"""
import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

from .graph_client import GraphClient
from .pipeline import process_message
from .qargo_client import QargoClient
from .state import State

log = logging.getLogger("customs_ingest")


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None or val == "":
        sys.exit(f"Missing setting {name} (see .env.example)")
    return val


def run_once(graph: GraphClient, qargo: QargoClient, state: State, dry_run: bool, report: Path) -> None:
    cfg_type = env("QARGO_DOCUMENT_TYPE", "Customs Document")
    cache: dict = {}
    rows = []
    for msg in graph.messages_with_attachments(env("SOURCE_FOLDER", "Inbox")):
        res = process_message(msg, qargo, state, cfg_type, dry_run, cache)
        for f in res.files or [None]:
            rows.append({
                "received": msg.received, "from": msg.sender, "subject": msg.subject,
                "file": f.filename if f else "", "reference": (f.reference if f else "") or "",
                "order_id": (f.order_id if f else "") or "", "status": f.status if f else "review",
                "reason": (f.reason if f else res.reason),
            })
        if dry_run:
            continue
        if res.needs_review:
            graph.add_category(msg.id, "Qargo: needs review")
            graph.move(msg.id, env("REVIEW_FOLDER", "Qargo - Needs Review"))
            log.warning("Needs review: %s | %s", msg.subject, res.reason or [f.reason for f in res.files if f.reason])
        else:
            graph.move(msg.id, env("DONE_FOLDER", "Qargo - Uploaded"))

    if rows:
        new = not report.exists()
        with report.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            if new:
                w.writeheader()
            w.writerows(rows)
    log.info("Processed %d file(s)%s", len(rows), " [DRY RUN - nothing uploaded or moved]" if dry_run else "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Customs PDFs from Outlook -> Qargo order documents")
    ap.add_argument("--once", action="store_true", help="process the mailbox once and exit")
    ap.add_argument("--live", action="store_true", help="really upload and move mail (overrides DRY_RUN)")
    ap.add_argument("--report", default="report.csv", help="CSV log of every file processed")
    args = ap.parse_args()

    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = not args.live and env("DRY_RUN", "true").lower() != "false"

    graph = GraphClient(env("GRAPH_TENANT_ID"), env("GRAPH_CLIENT_ID"), env("GRAPH_CLIENT_SECRET"), env("MAILBOX"))
    qargo = QargoClient(env("QARGO_BASE_URL", "https://api.qargo.com"), env("QARGO_CLIENT_ID"), env("QARGO_CLIENT_SECRET"))
    state = State(env("STATE_DB", "state.sqlite3"))

    while True:
        try:
            run_once(graph, qargo, state, dry_run, Path(args.report))
        except Exception:
            log.exception("Run failed; will retry")
        if args.once or dry_run:
            break
        time.sleep(int(env("POLL_SECONDS", "60")))


if __name__ == "__main__":
    main()
