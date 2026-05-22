#!/usr/bin/env python
"""Backfill ## Summary sections for diary notes that have text but no summary.

Reads existing content (transcript or body text) from each note and sends it
to Claude Haiku for summarisation. Designed to be run standalone or triggered
from the dashboard.

Usage:
    python backfill_summaries.py                    # process all
    python backfill_summaries.py --batch-size 50    # process 50 then stop
    python backfill_summaries.py --delay 0.5        # 0.5s between API calls
"""

import argparse
import os
import sys
import time
import logging

import yaml

from diary_finder import find_all_diary_notes
from note_updater import analyze_note, extract_note_text, _insert_summary, _backup_note
from summariser import generate_summary

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def add_summary_to_note(filepath: str, summary_text: str) -> bool:
    """Insert a ## Summary section into a diary note.

    Returns True if the note was modified.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    _backup_note(filepath, BACKUP_DIR)
    _insert_summary(lines, summary_text)

    new_content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def main():
    parser = argparse.ArgumentParser(description="Backfill diary note summaries")
    parser.add_argument(
        "--batch-size", type=int, default=0,
        help="Max notes to process (0 = all)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds between API calls (default 1.0)",
    )
    args = parser.parse_args()

    config = load_config()
    vault_path = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")
    api_key = config.get("anthropic_api_key")
    model = config.get("summary_model")

    notes = find_all_diary_notes(vault_path, diary_subdir)
    notes.sort(key=lambda x: x[1], reverse=True)  # newest first
    log.info(f"Found {len(notes)} diary notes")

    need_summary = []
    for filepath, note_date in notes:
        if ".sync-conflict-" in os.path.basename(filepath):
            continue
        analysis = analyze_note(filepath)
        if analysis["has_summary"]:
            continue
        text = extract_note_text(analysis)
        if text is None:
            continue
        need_summary.append((filepath, note_date, text))

    log.info(f"{len(need_summary)} notes need summaries")

    if not need_summary:
        log.info("Nothing to backfill!")
        return

    batch_limit = args.batch_size if args.batch_size > 0 else len(need_summary)
    processed = 0
    succeeded = 0
    failed = 0

    for filepath, note_date, text in need_summary:
        if processed >= batch_limit:
            break

        filename = os.path.basename(filepath)
        log.info(f"[{processed + 1}/{min(batch_limit, len(need_summary))}] {filename}")

        summary = generate_summary(text, api_key=api_key, model=model)
        if summary is None:
            log.warning(f"  Failed to generate summary")
            failed += 1
            processed += 1
            continue

        try:
            add_summary_to_note(filepath, summary)
            log.info(f"  Added summary ({len(summary)} chars)")
            succeeded += 1
        except Exception as e:
            log.error(f"  Failed to write summary: {e}")
            failed += 1

        processed += 1

        if processed < batch_limit and processed < len(need_summary):
            time.sleep(args.delay)

    remaining = len(need_summary) - processed
    log.info(
        f"Summary backfill: {succeeded} added, {failed} failed, "
        f"{remaining} remaining"
    )


if __name__ == "__main__":
    main()
