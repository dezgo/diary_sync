"""Find Obsidian diary notes by date."""

import os
import re
import logging
from datetime import date

log = logging.getLogger(__name__)

# Full and abbreviated month names, plus known typos from the vault
MONTHS = {
    "january": 1, "jan": 1, "januay": 1,
    "february": 2, "feb": 2, "feburary": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8, "augut": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "octoboer": 10,
    "november": 11, "nov": 11, "novembe": 11,
    "december": 12, "dec": 12,
}

# Flexible pattern: find "DD Month YYYY" anywhere in the filename.
# Strips commas, ordinal suffixes (st/nd/rd/th), and is case-insensitive.
_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")


def is_diary_filename(filename: str) -> bool:
    """Check if a filename looks like a diary note."""
    name = filename.lower()
    return (name.startswith("dear diary")
            or name.startswith("dear dairy")
            or name.startswith("dear diari")
            or name.startswith("deer diary")
            or name.startswith("do you diary"))


def parse_date_from_filename(filename: str) -> date | None:
    """Extract the date from a diary note filename.

    Accepts any file starting with 'Dear Diary' and hunts for a
    DD MonthName YYYY pattern within it. Handles commas, ordinal
    suffixes, abbreviations, and known typos.
    """
    if not is_diary_filename(filename):
        return None

    # Strip commas and ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    cleaned = filename.replace(",", "")
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", cleaned)

    match = _DATE_RE.search(cleaned)
    if not match:
        return None

    day = int(match.group(1))
    month_name = match.group(2).lower()
    year = int(match.group(3))

    month = MONTHS.get(month_name)
    if not month:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_diary_note(vault_path: str, diary_subdir: str, target_date: date) -> str | None:
    """Find the diary note file path matching a given date.

    Searches the diary root directory and the Diary/YYYY/ subdirectory.
    Returns the full file path, or None if not found.
    """
    diary_root = os.path.join(vault_path, diary_subdir)

    if not os.path.isdir(diary_root):
        log.error(f"Diary directory not found: {diary_root}")
        return None

    # Search root and year subdirectory
    search_dirs = [diary_root]
    year_dir = os.path.join(diary_root, str(target_date.year))
    if os.path.isdir(year_dir):
        search_dirs.append(year_dir)

    for search_dir in search_dirs:
        try:
            for filename in os.listdir(search_dir):
                if not filename.endswith(".md"):
                    continue
                file_date = parse_date_from_filename(filename)
                if file_date == target_date:
                    return os.path.join(search_dir, filename)
        except OSError as e:
            log.warning(f"Error reading directory {search_dir}: {e}")

    return None


def find_all_diary_notes(vault_path: str, diary_subdir: str) -> list[tuple[str, date]]:
    """Find all diary notes in the Diary subdirectory.

    Returns a list of (filepath, date) tuples for every parseable diary note.
    """
    diary_root = os.path.join(vault_path, diary_subdir)
    results = []

    if not os.path.isdir(diary_root):
        log.error(f"Diary directory not found: {diary_root}")
        return results

    for dirpath, _dirnames, filenames in os.walk(diary_root):
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            file_date = parse_date_from_filename(filename)
            if file_date:
                results.append((os.path.join(dirpath, filename), file_date))

    return results


def find_all_diary_notes_everywhere(vault_path: str) -> tuple[list[tuple[str, date]], list[str]]:
    """Find ALL diary notes anywhere in the vault (not just the Diary folder).

    Walks the entire vault to catch notes that are in the wrong location.
    Skips .obsidian and other hidden/system directories.
    Returns (parsed, unparsed) where:
      - parsed: list of (filepath, date) tuples for notes with a valid date
      - unparsed: list of filepaths for "Dear Diary" files we couldn't parse
    """
    parsed = []
    unparsed = []

    if not os.path.isdir(vault_path):
        log.error(f"Vault path not found: {vault_path}")
        return parsed, unparsed

    skip_dirs = {".obsidian", ".trash", "_resources", "Resources"}

    for dirpath, dirnames, filenames in os.walk(vault_path):
        # Skip hidden/system directories
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]

        for filename in filenames:
            if not is_diary_filename(filename):
                continue
            if not filename.endswith(".md"):
                continue
            filepath = os.path.join(dirpath, filename)
            file_date = parse_date_from_filename(filename)
            if file_date:
                parsed.append((filepath, file_date))
            else:
                unparsed.append(filepath)

    return parsed, unparsed


def get_expected_path(vault_path: str, diary_subdir: str, note_date: date) -> str:
    """Return the expected directory for a diary note based on its date.

    Expected location: vault_path/diary_subdir/YYYY/
    """
    return os.path.join(vault_path, diary_subdir, str(note_date.year))
