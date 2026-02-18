"""Move misplaced diary notes into their correct Diary/YYYY/ folders.

Usage:
    python reorganise.py          # dry-run: show what would move
    python reorganise.py --move   # actually move the files
"""

import os
import sys
import yaml

from diary_finder import find_all_diary_notes_everywhere, get_expected_path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")


def main():
    dry_run = "--move" not in sys.argv

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    vault_path = config["vault_path"]
    diary_subdir = config.get("diary_subdir", "Diary")

    all_notes, unparsed = find_all_diary_notes_everywhere(vault_path)

    moves = []
    for filepath, note_date in all_notes:
        expected_dir = get_expected_path(vault_path, diary_subdir, note_date)
        actual_dir = os.path.dirname(filepath)
        if os.path.normpath(actual_dir) != os.path.normpath(expected_dir):
            dest = os.path.join(expected_dir, os.path.basename(filepath))
            moves.append((filepath, dest, expected_dir))

    if not moves:
        print("All diary notes are already in the right place.")
        return

    print(f"{'DRY RUN — ' if dry_run else ''}Found {len(moves)} note(s) to move:\n")
    for src, dest, _ in moves:
        src_rel = os.path.relpath(src, vault_path)
        dest_rel = os.path.relpath(dest, vault_path)
        print(f"  {src_rel}")
        print(f"    -> {dest_rel}")
        print()

    if dry_run:
        print(f"Run with --move to actually move these {len(moves)} files.")
        return

    moved = 0
    errors = 0
    for src, dest, expected_dir in moves:
        try:
            os.makedirs(expected_dir, exist_ok=True)
            if os.path.exists(dest):
                print(f"  SKIP (already exists): {os.path.relpath(dest, vault_path)}")
                errors += 1
                continue
            os.rename(src, dest)
            moved += 1
            print(f"  Moved: {os.path.relpath(src, vault_path)} -> {os.path.relpath(dest, vault_path)}")
        except OSError as e:
            print(f"  ERROR: {os.path.relpath(src, vault_path)}: {e}")
            errors += 1

    print(f"\nDone: {moved} moved, {errors} errors/skipped.")


if __name__ == "__main__":
    main()
