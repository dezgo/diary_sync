"""Fix broken resource links across the Obsidian vault.

Finds notes with ./_resources/ links pointing to resources in old
Evernote export folders, moves the resources next to the note, and
updates the link paths.

Usage:
    python fix_resource_links.py              # dry-run: report what would change
    python fix_resource_links.py --apply      # actually move files and fix links
"""

import os
import re
import sys
import shutil

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

# Matches resource links in all variants:
#   ![[./_resources/folder.resources/file.jpg]]
#   ![[/_resources/folder.resources/file.jpg]]
#   ![[_resources/folder.resources/file.jpg]]
#   [![[./_resources/folder.resources/file.jpg]]](url)
RESOURCE_LINK_RE = re.compile(
    r"""
    \[\[                        # opening [[
    (\.?/?_resources/           # path prefix: ./_resources/ or /_resources/ or _resources/
    [^\]/]+/                    # resource dir name (e.g. Note_Name.resources/)
    [^\]]+)                     # filename
    \]\]                        # closing ]]
    """,
    re.VERBOSE,
)

# For splitting the resource path into (dir_name, filename)
RESOURCE_PATH_RE = re.compile(r"\.?/?_resources/([^/]+)/(.*)")

# For fixing links in content: strip ./ or / before _resources
LINK_FIX_RE = re.compile(r"(\[\[)\.?/(_resources/)")

SKIP_DIRS = {".obsidian", ".trash"}


def build_resource_index(vault_path):
    """Build index of all resource files: (dir_name, filename) -> [paths].

    Auto-discovers all <folder>/_resources/ directories in the vault.
    """
    index = {}
    resource_roots = []

    for entry in os.listdir(vault_path):
        candidate = os.path.join(vault_path, entry, "_resources")
        if os.path.isdir(candidate):
            resource_roots.append(candidate)

    print(f"Found {len(resource_roots)} _resources source folders")

    total_files = 0
    for res_root in resource_roots:
        for res_dir_name in os.listdir(res_root):
            res_dir_path = os.path.join(res_root, res_dir_name)
            if not os.path.isdir(res_dir_path):
                continue
            for filename in os.listdir(res_dir_path):
                filepath = os.path.join(res_dir_path, filename)
                if not os.path.isfile(filepath):
                    continue
                key = (res_dir_name, filename)
                index.setdefault(key, []).append(filepath)
                total_files += 1

    print(f"Indexed {total_files} resource files")
    return index


def find_broken_links(vault_path):
    """Scan all notes for resource links. Returns list of actions needed.

    Each action: {
        'note_path': str,
        'links': [{'raw': str, 'dir_name': str, 'filename': str}, ...]
    }
    """
    results = []

    for dirpath, dirnames, filenames in os.walk(vault_path):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]

        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(dirpath, fname)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            matches = RESOURCE_LINK_RE.findall(content)
            if not matches:
                continue

            links = []
            for raw_path in matches:
                m = RESOURCE_PATH_RE.match(raw_path)
                if m:
                    links.append({
                        "raw": raw_path,
                        "dir_name": m.group(1),
                        "filename": m.group(2),
                    })

            if links:
                results.append({"note_path": filepath, "links": links})

    return results


def plan_actions(vault_path, notes_with_links, index):
    """Plan move and rewrite actions for each broken link.

    Returns (actions, stats) where actions is a list of:
    {
        'note_path': str,
        'moves': [(source, target), ...],
        'rewrite': bool,
    }
    """
    actions = []
    stats = {
        "total_links": 0,
        "already_ok": 0,
        "found": 0,
        "not_found": 0,
        "same_location": 0,
    }

    for note_info in notes_with_links:
        note_path = note_info["note_path"]
        note_dir = os.path.dirname(note_path)
        moves = []
        needs_rewrite = False

        for link in note_info["links"]:
            stats["total_links"] += 1
            dir_name = link["dir_name"]
            filename = link["filename"]

            target_dir = os.path.join(note_dir, "_resources", dir_name)
            target_path = os.path.join(target_dir, filename)

            # Check if resource is already at target
            if os.path.exists(target_path):
                # Still need to fix the link text if it has ./ prefix
                needs_rewrite = True
                stats["already_ok"] += 1
                continue

            # Look up in index
            key = (dir_name, filename)
            candidates = index.get(key, [])

            if not candidates:
                stats["not_found"] += 1
                rel = os.path.relpath(note_path, vault_path)
                print(f"  NOT FOUND: {rel} -> {dir_name}/{filename}")
                needs_rewrite = True
                continue

            source = candidates[0]
            if len(candidates) > 1:
                # Multiple sources — pick by file size match (they're usually identical)
                # Just use the first one
                pass

            # Check if source and target are the same path
            if os.path.normpath(source) == os.path.normpath(target_path):
                stats["same_location"] += 1
                needs_rewrite = True
                continue

            moves.append((source, target_path))
            needs_rewrite = True
            stats["found"] += 1

        if needs_rewrite or moves:
            actions.append({
                "note_path": note_path,
                "moves": moves,
                "rewrite": needs_rewrite,
            })

    return actions, stats


def execute_actions(vault_path, actions, dry_run=True):
    """Execute planned actions: move files and rewrite note links."""
    files_moved = 0
    notes_rewritten = 0
    errors = 0

    for action in actions:
        note_path = action["note_path"]
        rel = os.path.relpath(note_path, vault_path)

        # Move resource files
        for source, target in action["moves"]:
            if dry_run:
                src_rel = os.path.relpath(source, vault_path)
                tgt_rel = os.path.relpath(target, vault_path)
                # Only show first 10 moves in dry run to avoid spam
                if files_moved < 10:
                    print(f"  {src_rel}")
                    print(f"    -> {tgt_rel}")
                files_moved += 1
                continue

            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
                files_moved += 1
            except OSError as e:
                print(f"  ERROR moving: {e}")
                errors += 1

        # Rewrite note links
        if action["rewrite"]:
            if dry_run:
                notes_rewritten += 1
                continue

            try:
                with open(note_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                fixed = LINK_FIX_RE.sub(r"\1\2", content)

                if fixed != content:
                    with open(note_path, "w", encoding="utf-8") as f:
                        f.write(fixed)
                    notes_rewritten += 1
            except OSError as e:
                print(f"  ERROR rewriting {rel}: {e}")
                errors += 1

    return files_moved, notes_rewritten, errors


def main():
    dry_run = "--apply" not in sys.argv

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    vault_path = config["vault_path"]

    if not os.path.isdir(vault_path):
        print(f"Vault not found: {vault_path}")
        sys.exit(1)

    print("Building resource index...")
    index = build_resource_index(vault_path)

    print("Scanning notes for resource links...")
    notes_with_links = find_broken_links(vault_path)

    print(f"Found {len(notes_with_links)} notes with resource links\n")

    print("Planning actions...")
    actions, stats = plan_actions(vault_path, notes_with_links, index)

    print(f"\n{'DRY RUN — ' if dry_run else ''}Summary:")
    print(f"  Total resource links: {stats['total_links']}")
    print(f"  Resources to move:    {stats['found']}")
    print(f"  Already in place:     {stats['already_ok']}")
    print(f"  Same location:        {stats['same_location']}")
    print(f"  Not found:            {stats['not_found']}")
    print(f"  Notes to rewrite:     {len(actions)}")

    if not actions:
        print("\nNothing to do.")
        return

    if dry_run:
        print(f"\nSample moves (first 10):")

    files_moved, notes_rewritten, errors = execute_actions(
        vault_path, actions, dry_run
    )

    print(f"\n{'Would move' if dry_run else 'Moved'}: {files_moved} files")
    print(f"{'Would rewrite' if dry_run else 'Rewrote'}: {notes_rewritten} notes")
    if errors:
        print(f"Errors: {errors}")

    # Cleanup pass: fix any remaining ./_resources/ prefixes in notes
    # that weren't caught by the main scan (e.g. mangled paths)
    cleanup_re = re.compile(r"([\[\"=])\./_resources/")
    cleanup_count = 0
    for dirpath, dirnames, filenames in os.walk(vault_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(dirpath, fname)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if "./_resources/" not in content:
                    continue
                fixed = cleanup_re.sub(r"\1_resources/", content)
                if fixed != content:
                    if not dry_run:
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(fixed)
                    cleanup_count += 1
            except OSError:
                pass

    if cleanup_count:
        print(f"{'Would fix' if dry_run else 'Fixed'}: {cleanup_count} additional notes (cleanup pass)")

    if dry_run:
        print(f"\nRun with --apply to execute.")


if __name__ == "__main__":
    main()
