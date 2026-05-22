#!/usr/bin/env python
"""Generate 'Diary Sync Status.md' in the vault root summarising what each
recent diary note is missing (video, transcript, summary, photo-of-day, selfie).

POTD is detected by the script's filename signature: Pasted image YYYYMMDD120000.*
Any other Pasted image is treated as a selfie / manual photo.
"""

import argparse
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from diary_finder import find_all_diary_notes
from note_updater import analyze_note
from photo_finder import _read_capture_time, _is_image

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

log = logging.getLogger("status_report")

POTD_RE = re.compile(r"^Pasted image \d{8}120000\..+$", re.IGNORECASE)


def classify_note(note_path: str, album_dates: set[date], note_date: date) -> dict:
    """Classify a note.

    Photo coverage model (per user workflow: 2 photos/day, selfie + POTD):
      - script POTD pattern present     -> POTD covered, selfie covered iff >=2 photos
      - 0 photos                        -> both missing
      - 1 photo (no pattern)            -> selfie covered, POTD missing (a lone photo
                                            is treated as the selfie since the selfie
                                            is the recording-ritual photo)
      - 2+ photos (no pattern)          -> selfie covered, POTD covered iff shared
                                            album has a photo for that date
    """
    analysis = analyze_note(note_path)
    pasted = [
        f for f in analysis.get("embedded_filenames", set())
        if f.startswith("Pasted image ")
    ]
    has_script_potd = any(POTD_RE.match(f) for f in pasted)
    photo_count = len(pasted)
    album_has_for_date = note_date in album_dates

    if has_script_potd:
        potd_covered = True
        selfie_covered = photo_count >= 2
    elif photo_count == 0:
        potd_covered = False
        selfie_covered = False
    elif photo_count == 1:
        potd_covered = False
        selfie_covered = True
    else:  # photo_count >= 2 -- treat note as fully photographed
        potd_covered = True
        selfie_covered = True

    return {
        "has_video": analysis["has_video_link"] and not analysis["has_placeholder"],
        "has_transcript": analysis["has_blockquote_transcript"],
        "has_summary": analysis["has_summary"],
        "has_potd": potd_covered,
        "has_selfie": selfie_covered,
        "album_has_for_date": album_has_for_date,
        "photo_count": photo_count,
    }


def _index_shared_album_dates(album_dir: Path) -> set[date]:
    """Return the set of dates that have at least one photo in the album."""
    dates: set[date] = set()
    if not album_dir.is_dir():
        return dates
    for entry in album_dir.iterdir():
        if not entry.is_file() or not _is_image(entry):
            continue
        capture = _read_capture_time(entry)
        if capture:
            dates.add(capture.date())
    return dates


def _find_sync_conflicts(vault: Path) -> list[Path]:
    return sorted(vault.rglob("*.sync-conflict-*.md"))


def generate_report(config: dict, days: int = 30) -> str:
    vault = Path(config["vault_path"])
    diary_subdir = config.get("diary_subdir", "Diary")

    today = date.today()
    cutoff = today - timedelta(days=days)

    all_notes = find_all_diary_notes(str(vault), diary_subdir)
    # Drop Syncthing/Mobius conflict files — they're surfaced separately below
    notes = [
        (p, d) for p, d in all_notes
        if cutoff <= d <= today and "sync-conflict" not in p
    ]
    notes.sort(key=lambda x: x[1], reverse=True)
    conflicts = _find_sync_conflicts(vault)

    # Index which dates have photos in the relevant shared albums (typically
    # one album per year; index every year that appears in the visible notes).
    shared_root = Path(config.get("photo_of_day_shared_dir", ""))
    album_fmt = config.get("photo_of_day_album_format", "Photo of the day {year}")
    album_dates: set[date] = set()
    if shared_root.is_dir():
        years_in_window = {d.year for _, d in notes}
        for y in years_in_window:
            album_dates |= _index_shared_album_dates(shared_root / album_fmt.format(year=y))

    # Shared-album freshness: iCloud for Windows syncs Shared Albums on a
    # separate path that stalls silently. If the newest photo is well behind
    # today, the sync is likely stuck (rather than photos being genuinely
    # missing). max(album_dates) is the latest diary day with a photo.
    stale_days = int(config.get("shared_album_stale_days", 2))
    newest_album_date = max(album_dates) if album_dates else None
    album_stale = newest_album_date is not None and newest_album_date < today - timedelta(days=stale_days)

    classified: list[dict] = []
    for note_path, note_date in notes:
        cls = classify_note(note_path, album_dates, note_date)
        cls["date"] = note_date
        classified.append(cls)

    # Photo-of-day issues split by where action is needed.
    # The "missing from album" list is shown regardless of note photo state —
    # even if the note has 2 manual photos, you may still want to add the day's
    # POTD to the shared album.
    needs_iphone = [c for c in classified if not c["album_has_for_date"]]
    needs_backfill = [
        c for c in classified
        if c["album_has_for_date"] and not c["has_potd"]
    ]

    lines: list[str] = []
    lines.append("---")
    lines.append(f"date: {today.isoformat()}")
    lines.append("tags:")
    lines.append("  - DiarySyncStatus")
    lines.append("---")
    lines.append("")
    lines.append("# Diary Sync Status")
    lines.append("")
    lines.append(f"_Auto-generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
                 "Maintenance items that need action outside Obsidian (conflicts and "
                 "photo-of-day album coverage). For the per-day video/selfie/photo "
                 "view, see [[Diary Dashboard]]._")
    lines.append("")

    # Sync conflicts (vault-wide, not date-windowed)
    if conflicts:
        lines.append(f"## Sync conflicts to clean up ({len(conflicts)})")
        lines.append("")
        lines.append("_Leftover files from Syncthing/Mobius conflicts. Compare each to its non-conflict sibling, "
                     "keep the better version, delete the other._")
        lines.append("")
        for p in conflicts:
            rel = Path(p).relative_to(vault)
            lines.append(f"- `{rel.as_posix()}`")
        lines.append("")

    if album_stale:
        days_behind = (today - newest_album_date).days
        lines.append("## ⚠️ Shared album may be out of sync")
        lines.append("")
        lines.append(f"_Newest photo in the shared album is from **{newest_album_date}** "
                     f"({days_behind} days ago). If you've added photos since then on your "
                     "phone, iCloud Shared Album sync is likely stuck — the main library can "
                     "report \"up to date\" while Shared Albums lag separately. Try toggling "
                     "or restarting Shared Albums in iCloud for Windows. Until it catches up, "
                     "the missing-photo list below may be false alarms._")
        lines.append("")

    if needs_iphone:
        lines.append("## Photo-of-day missing from shared album")
        lines.append("")
        lines.append("_Add a photo to the year's Shared Album on the iPhone._")
        lines.append("")
        for c in needs_iphone:
            d = c["date"]
            lines.append(f"- {d} -- {d.strftime('%A')}")
        lines.append("")
    if needs_backfill:
        lines.append("## Photo-of-day in album but not in note")
        lines.append("")
        lines.append("_Will be picked up by the next `sync.py` run, or run "
                     "`python audit_photo_of_day.py --commit` to backfill immediately._")
        lines.append("")
        for c in needs_backfill:
            d = c["date"]
            lines.append(f"- {d} -- {d.strftime('%A')}")
        lines.append("")

    if not conflicts and not needs_iphone and not needs_backfill and not album_stale:
        lines.append(f"✅ No sync conflicts, and photo-of-day album coverage is "
                     f"complete for the last {days} days. Nothing to action.")
        lines.append("")

    return "\n".join(lines)


def write_report(config: dict, days: int = 30) -> Path:
    vault = Path(config["vault_path"])
    report = generate_report(config, days=days)
    out = vault / "Diary Sync Status.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    return out


def main():
    parser = argparse.ArgumentParser(description="Generate diary sync status note")
    parser.add_argument("--days", type=int, default=30, help="Lookback window (default 30)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    out = write_report(config, days=args.days)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
