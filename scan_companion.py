#!/usr/bin/env python
"""Scan companion notes — give every scanned PDF in the vault's Scans folder a
sidecar Markdown note so it can be tagged and linked.

This is a vault-maintenance pass in the same spirit as the photo drop-folder
drains in sync.py: walk a folder, act only on what's missing, and stay
idempotent so it's safe to run every cycle. For each PDF in Scans/ that has no
"<stem>.md" sitting next to it, create one with an empty tags list (for Derek
to fill in), a date parsed from the filename when possible, and an embed of the
PDF so the companion shows the scan inline in Obsidian.
"""

import os
import re
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger("diary_sync")

# Scans are named with a leading DDMMYYYY date stamp, e.g. "25052026_001.pdf"
# or "06032026_aware super V.pdf". Capture it to date the companion note.
_DATE_PREFIX_RE = re.compile(r"^(\d{2})(\d{2})(\d{4})")


def _date_from_scan_name(stem: str) -> date | None:
    """Parse a leading DDMMYYYY stamp from a scan filename stem.

    Returns None if there's no such prefix or it isn't a real date (so notes
    for oddly-named scans just omit the date field rather than guess).
    """
    m = _DATE_PREFIX_RE.match(stem)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _companion_body(pdf_name: str, scan_date: date | None) -> str:
    """Build the Markdown for a scan's companion note: frontmatter with empty
    tags (and a date when known) plus an embed of the PDF."""
    lines = ["---"]
    if scan_date is not None:
        lines.append(f"date: {scan_date.isoformat()}")
    lines += [
        "tags: []",
        "---",
        "",
        f"![[{pdf_name}]]",
        "",
    ]
    return "\n".join(lines)


def ensure_scan_companions(config: dict) -> int:
    """Create a companion .md next to any scanned PDF that lacks one.

    Walks <vault>/<scans_subdir> (non-recursive — scans live flat), and for
    each PDF whose "<stem>.md" doesn't already exist, writes that sidecar note.
    Returns the number of companions created.
    """
    vault_path = config.get("vault_path", "")
    scans_subdir = config.get("scans_subdir", "Scans")
    scans_dir = Path(vault_path) / scans_subdir

    if not scans_dir.is_dir():
        log.debug(f"Scans folder not found, skipping companion pass: {scans_dir}")
        return 0

    created = 0
    for entry in sorted(scans_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() != ".pdf":
            continue

        companion = entry.with_suffix(".md")
        if companion.exists():
            continue

        scan_date = _date_from_scan_name(entry.stem)
        try:
            companion.write_text(
                _companion_body(entry.name, scan_date), encoding="utf-8"
            )
            created += 1
            log.info(f"  Scan companion created: {companion.name}")
        except OSError as e:
            log.error(f"  Scan companion for {entry.name} failed: {e}", exc_info=True)

    return created
