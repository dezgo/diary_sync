#!/usr/bin/env python
"""One-off script: add 'date: YYYY-MM-DD' to YAML frontmatter of all diary notes."""

import os
import sys
import logging

import yaml

from diary_finder import find_all_diary_notes, parse_date_from_filename

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def add_date_to_note(filepath: str, note_date) -> str | None:
    """Add 'date: YYYY-MM-DD' to a diary note's YAML frontmatter.

    Returns a status string: 'added', 'already_has_date', 'added_frontmatter', or 'skipped'.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    date_str = note_date.isoformat()
    lines = content.split("\n")

    # Case 1: note already has YAML frontmatter (starts with ---)
    if lines and lines[0].strip() == "---":
        # Find the closing ---
        closing_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                closing_idx = i
                break

        if closing_idx is None:
            log.warning(f"  Unclosed frontmatter in {os.path.basename(filepath)}, skipping")
            return "skipped"

        # Check if date: already exists in frontmatter
        for i in range(1, closing_idx):
            if lines[i].strip().startswith("date:"):
                return "already_has_date"

        # Insert date: right after opening ---
        # If there's a blank line right after ---, replace it with the date line
        if lines[1].strip() == "":
            lines[1] = f"date: {date_str}"
        else:
            lines.insert(1, f"date: {date_str}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return "added"

    # Case 2: no frontmatter at all — add one
    frontmatter = f"---\ndate: {date_str}\n---\n"
    new_content = frontmatter + content

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    return "added_frontmatter"


def main():
    config = load_config()
    vault_path = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")

    notes = find_all_diary_notes(vault_path, diary_subdir)
    log.info(f"Found {len(notes)} diary notes")

    counts = {"added": 0, "already_has_date": 0, "added_frontmatter": 0, "skipped": 0}

    for filepath, note_date in notes:
        filename = os.path.basename(filepath)
        # Skip syncthing conflict files
        if ".sync-conflict-" in filename:
            log.debug(f"  Skipping conflict file: {filename}")
            counts["skipped"] += 1
            continue

        result = add_date_to_note(filepath, note_date)
        counts[result] += 1

        if result in ("added", "added_frontmatter"):
            log.info(f"  {result}: {filename} -> date: {note_date.isoformat()}")

    log.info(
        f"Done! {counts['added']} updated, {counts['added_frontmatter']} got new frontmatter, "
        f"{counts['already_has_date']} already had date, {counts['skipped']} skipped"
    )


if __name__ == "__main__":
    main()
