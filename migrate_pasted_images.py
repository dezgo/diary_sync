#!/usr/bin/env python
"""One-shot migration: move 'Pasted image YYYYMMDD*.{jpg,png,heic,gif}' files
from the vault root into attachments/Diary/{year}/.

Obsidian wikilinks resolve by filename globally, so existing ![[...]] embeds
keep working after the move — no note rewriting needed.
"""

import argparse
import os
import re
import shutil
import sys
import yaml
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

PASTED_RE = re.compile(r"^Pasted image (\d{4})(\d{2})(\d{2})\d+\.(jpg|jpeg|png|heic|gif)$", re.IGNORECASE)


def load_vault_path() -> Path:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return Path(cfg["vault_path"])


def find_pasted_images(vault_root: Path) -> list[tuple[Path, int]]:
    """Return [(src_path, year), ...] for matching files at vault root."""
    results = []
    for entry in vault_root.iterdir():
        if not entry.is_file():
            continue
        m = PASTED_RE.match(entry.name)
        if m:
            year = int(m.group(1))
            results.append((entry, year))
    return results


def migrate(vault_root: Path, attachments_subdir: str, dry_run: bool) -> tuple[int, int, list[str]]:
    matches = find_pasted_images(vault_root)
    moved = 0
    skipped = 0
    errors = []

    for src, year in matches:
        dest_dir = vault_root / attachments_subdir / str(year)
        dest = dest_dir / src.name

        if dest.exists():
            skipped += 1
            print(f"  SKIP (exists): {src.name} -> {dest.relative_to(vault_root)}")
            continue

        if dry_run:
            print(f"  WOULD MOVE: {src.name} -> {dest.relative_to(vault_root)}")
            moved += 1
            continue

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved += 1
            print(f"  MOVED: {src.name} -> {dest.relative_to(vault_root)}")
        except Exception as e:
            errors.append(f"{src.name}: {e}")
            print(f"  ERROR: {src.name}: {e}")

    return moved, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Migrate vault-root pasted images to attachments/Diary/{year}/")
    parser.add_argument("--commit", action="store_true",
                        help="Actually move files (default is dry-run)")
    parser.add_argument("--attachments-subdir", default="attachments/Diary",
                        help="Target subdirectory under vault root (default: attachments/Diary)")
    args = parser.parse_args()

    vault_root = load_vault_path()
    if not vault_root.is_dir():
        print(f"Vault path not found: {vault_root}", file=sys.stderr)
        sys.exit(2)

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"=== Pasted-image migration ({mode}) ===")
    print(f"Vault: {vault_root}")
    print(f"Target: {vault_root / args.attachments_subdir}/{{year}}/")
    print()

    moved, skipped, errors = migrate(vault_root, args.attachments_subdir, dry_run=not args.commit)

    print()
    print(f"=== Summary: {moved} {'would-move' if not args.commit else 'moved'}, {skipped} skipped, {len(errors)} errors ===")
    if not args.commit and moved > 0:
        print("\nRe-run with --commit to actually move the files.")


if __name__ == "__main__":
    main()
