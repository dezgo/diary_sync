#!/usr/bin/env python
"""Helpers for the scan-enrich skill — the human-in-the-loop counterpart to the
unattended scan_companion pass in sync.py.

sync.py creates a blank companion note (empty tags, datestamp name) for every
scanned PDF. This module gives a Claude Code session the deterministic pieces
it needs to *enrich* those scans: find which ones still need work, render their
pages so they can be looked at, surface the vault's existing tag vocabulary to
ground suggestions, and apply a reviewed rename+tagging atomically — renaming
the PDF and its companion together and rewriting every link that pointed at the
old name.

Nothing here calls an LLM or mutates anything until apply_enrichment() runs with
dry_run=False. The "what should the tag/name be" judgement is the operator's
(Claude reading the rendered page); this module only does the mechanical work.
"""

import os
import re
import logging
from pathlib import Path

import yaml

log = logging.getLogger("diary_sync")

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
RENDER_DIR = SCRIPT_DIR / ".scan_render"  # transient PNGs for Claude to Read

# Windows-illegal filename characters (and control chars), stripped from names.
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FRONTMATTER = re.compile(r"(?s)\A---\n(.*?)\n---")
_EMPTY_TAGS = re.compile(r"(?m)^tags:\s*\[\s*\]\s*$")
_DATE_FIELD = re.compile(r"(?m)^date:\s*(\d{4}-\d{2}-\d{2})\s*$")
_DATE_LINE = re.compile(r"(?m)^date:\s*.*$")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _scans_dir(config: dict) -> Path:
    return Path(config["vault_path"]) / config.get("scans_subdir", "Scans")


def _date_from_companion(text: str) -> str | None:
    m = _DATE_FIELD.search(text)
    return m.group(1) if m else None


def list_pending(config: dict) -> list[dict]:
    """Scans that have a companion note but still need enriching.

    "Needs enriching" = the companion still has empty `tags: []` (the blank
    state sync.py writes). Returns one dict per scan with its paths, the date
    from frontmatter, and page count — sorted by filename (date-ascending,
    since names start with the scan date).
    """
    import pdfplumber

    pending = []
    for pdf in sorted(_scans_dir(config).glob("*.pdf")):
        comp = pdf.with_suffix(".md")
        if not comp.exists():
            continue  # sync.py creates the companion first; nothing to enrich yet
        text = comp.read_text(encoding="utf-8")
        if not _EMPTY_TAGS.search(text):
            continue  # already tagged — leave it
        try:
            with pdfplumber.open(str(pdf)) as doc:
                pages = len(doc.pages)
        except Exception as e:
            log.warning(f"Couldn't open {pdf.name} for page count: {e}")
            pages = None
        pending.append({
            "pdf": str(pdf),
            "companion": str(comp),
            "date": _date_from_companion(text),
            "pages": pages,
        })
    return pending


def render_page(pdf_path: str, page: int = 0, resolution: int = 150) -> tuple[str, int]:
    """Render one page of a PDF to a PNG and return (png_path, total_pages).

    `page` is 0-based and clamped to the last page. PNGs land in .scan_render/
    so a Claude session can Read them; they're transient and safe to delete.
    """
    import pdfplumber

    pdf = Path(pdf_path)
    RENDER_DIR.mkdir(exist_ok=True)
    out = RENDER_DIR / f"{pdf.stem}__p{page + 1}.png"
    with pdfplumber.open(str(pdf)) as doc:
        total = len(doc.pages)
        pg = doc.pages[min(page, total - 1)]
        pg.to_image(resolution=resolution).save(str(out))
    return str(out), total


def vault_tags(config: dict, exclude_diary: bool = True) -> list[str]:
    """Every distinct frontmatter tag across the vault, sorted.

    Reads both block-style (`tags:\\n  - x`) and inline (`tags: [x, y]`) lists.
    Excludes the auto-generated Diary-YYYY tags by default. This is the
    vocabulary to ground tag suggestions in — prefer matching one of these
    before minting a new tag.
    """
    tags: set[str] = set()
    vault = Path(config["vault_path"])
    for f in vault.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _FRONTMATTER.match(text)
        if not m:
            continue
        fm = m.group(1)
        block = re.search(r"(?ms)^tags:\s*\n((?:[ \t]*-[ \t]*\S.*\n?)+)", fm)
        if block:
            for line in block.group(1).splitlines():
                t = line.strip().lstrip("-").strip().strip("\"'")
                if t:
                    tags.add(t)
        inline = re.search(r"(?m)^tags:\s*\[(.+)\]\s*$", fm)
        if inline:
            for t in inline.group(1).split(","):
                t = t.strip().strip("\"'")
                if t:
                    tags.add(t)
    if exclude_diary:
        tags = {t for t in tags if not t.lower().startswith("diary-")}
    return sorted(tags)


def _sanitise(description: str) -> str:
    """Make a description safe for a Windows filename: strip illegal chars,
    collapse whitespace, drop a trailing dot/space."""
    name = _ILLEGAL.sub("", description)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name


def _set_tags_block(text: str, tags: list[str]) -> str:
    """Replace the companion's `tags:` line (empty or otherwise) with a
    block-style list of the given tags, preserving the rest of frontmatter."""
    block = "tags:\n" + "\n".join(f"  - {t}" for t in tags)
    # Replace an inline-empty `tags: []` or an existing block list.
    if _EMPTY_TAGS.search(text):
        return _EMPTY_TAGS.sub(block, text, count=1)
    return re.sub(
        r"(?ms)^tags:\s*(?:\[[^\]]*\]\s*$|\n(?:[ \t]*-[ \t]*\S.*\n?)*)",
        block + "\n",
        text,
        count=1,
    )


def _set_date_field(text: str, date_str: str) -> str:
    """Set the companion's frontmatter `date:` to date_str. Replaces an existing
    date line, or inserts one right after the opening `---` if absent."""
    if _DATE_LINE.search(text):
        return _DATE_LINE.sub(f"date: {date_str}", text, count=1)
    return re.sub(r"\A---\n", f"---\ndate: {date_str}\n", text, count=1)


def _update_vault_refs(config: dict, old_pdf: str, new_pdf: str,
                       old_stem: str, new_stem: str) -> int:
    """Rewrite links to a renamed scan across every note in the vault.

    Handles the full filename (covers `![[x.pdf]]` and `[[x.pdf]]`) and bare
    wikilinks to the companion stem (`[[stem]]`, `[[stem|alias]]`, `[[stem#h]]`).
    Returns the number of files changed.
    """
    vault = Path(config["vault_path"])
    changed = 0
    stem_link = re.compile(r"\[\[" + re.escape(old_stem) + r"(?=[\]|#])")
    for f in vault.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        new = text.replace(old_pdf, new_pdf)
        new = stem_link.sub("[[" + new_stem, new)
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def apply_enrichment(config: dict, pdf_path: str, description: str,
                     tags: list[str], date=None, dry_run: bool = False) -> dict:
    """Apply a reviewed rename + tagging to one scan.

    Builds the new stem as "<ISO date> <description>" and renames both the PDF
    and companion to it, writes the tags into the companion, rewrites the
    companion's embed, and fixes any other vault links to the old name.

    The `date` controls the ISO prefix (and the note's frontmatter date):
      - None (default): use the companion's existing frontmatter date; no prefix
        if it has none.
      - "YYYY-MM-DD": use this date for the prefix and rewrite the frontmatter
        `date:` to match — for when the document's own date (a receipt's
        purchase date, say) differs from the scan date the companion was born
        with.
      - False: no date prefix at all (for undated docs like manuals); the
        frontmatter date is left as-is.

    With dry_run=True nothing is written — the returned dict shows exactly what
    would change, for showing the operator before committing.
    """
    pdf = Path(pdf_path)
    comp = pdf.with_suffix(".md")
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    if not comp.is_file():
        raise FileNotFoundError(f"Companion not found: {comp}")

    text = comp.read_text(encoding="utf-8")
    if date is None:
        use_date = _date_from_companion(text)
    elif date is False:
        use_date = None
    else:
        use_date = date
    desc = _sanitise(description)
    if not desc:
        raise ValueError("Description is empty after sanitising")
    stem = f"{use_date} {desc}" if use_date else desc
    # Leave headroom under Windows' ~255-char path-segment limit.
    if len(stem) > 120:
        stem = stem[:120].rstrip()

    new_pdf = pdf.with_name(stem + pdf.suffix)
    new_comp = comp.with_name(stem + ".md")

    result = {
        "old_pdf": pdf.name, "new_pdf": new_pdf.name,
        "old_companion": comp.name, "new_companion": new_comp.name,
        "tags": tags, "date": use_date,
        "collision": (new_pdf != pdf and new_pdf.exists())
                     or (new_comp != comp and new_comp.exists()),
        "refs_updated": 0, "applied": False,
    }
    if dry_run or result["collision"]:
        return result

    new_text = _set_tags_block(text, tags)
    # Rewrite the frontmatter date only when an explicit date was supplied.
    if isinstance(date, str):
        new_text = _set_date_field(new_text, date)
    new_text = new_text.replace(f"![[{pdf.name}]]", f"![[{new_pdf.name}]]")
    comp.write_text(new_text, encoding="utf-8")

    pdf.rename(new_pdf)
    comp.rename(new_comp)
    result["refs_updated"] = _update_vault_refs(
        config, pdf.name, new_pdf.name, pdf.stem, new_pdf.stem
    )
    result["applied"] = True
    log.info(f"Enriched scan: {pdf.name} -> {new_pdf.name} ({len(tags)} tags, "
             f"{result['refs_updated']} ref file(s) updated)")
    return result
