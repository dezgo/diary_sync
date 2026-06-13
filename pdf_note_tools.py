#!/usr/bin/env python
"""Helpers for the 'pdf-note enrich' chore — the broad-vault counterpart to
scan_tools.py (which handles the Scans/ folder's PDF+companion pairs).

The vault is full of Evernote/Yarle-export notes whose entire body is a single
`![[_resources/<stem>.resources/<stem>.pdf]]` embed and whose title is the
import datestamp (e.g. `2012_12_30_12_18_54`). Obsidian only full-text-searches
markdown, never inside the PDF, so these documents are effectively unfindable.

This module gives a Claude Code session the deterministic pieces to fix that:
  - find candidate notes (datestamp/junk title, embeds a PDF),
  - pull the PDF's text layer (born-digital or OCR'd) for the operator to read,
  - inject that text into the note body as a collapsed callout (now searchable),
  - rename the note to an operator-chosen meaningful title and fix wikilinks.

The PDF and its _resources folder are never touched — the embed is path-based,
so renaming only the .md leaves the embed working. The "what is this / what
should it be called" judgement is the operator's (Claude reading the text);
this module only does the mechanical, reviewable, idempotent work.
"""

import re
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# A title that doesn't describe its contents: pure datestamp, or scanner/camera
# default junk. Word-titled notes are assumed already-meaningful and skipped.
_DATESTAMP = re.compile(r"^[\d][\d\-_.\s]{5,}\d$")
_JUNK = re.compile(
    r"^(img[_-]?\d|scan\d|doc\d{2,}|untitled|evernote|snapshot|image\d|"
    r"photo\d|fullsizerender|scanned|new doc)", re.I)
_PDF_EMBED = re.compile(r"!\[\[([^\]]*?\.pdf)(?:[|#][^\]]*)?\]\]", re.I)
_PDF_LINK = re.compile(r"!?\[\[([^\]]*?\.pdf)(?:[|#][^\]]*)?\]\]", re.I)

CALLOUT_HEADER = "> [!quote]- Document text (for search)"
# Matches a previously-injected callout block so re-runs replace, not duplicate.
_CALLOUT_BLOCK = re.compile(
    r"(?ms)^> \[!quote\]- Document text \(for search\)\n(?:^>.*\n?)*")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def title_is_junk(stem: str) -> bool:
    """True if a note title is a datestamp or scanner/camera default."""
    return bool(_DATESTAMP.match(stem) or _JUNK.match(stem))


def build_pdf_index(config: dict) -> dict:
    """Map lowercased PDF basename -> list of full paths, once per vault scan."""
    vault = Path(config["vault_path"])
    index: dict[str, list[Path]] = {}
    for p in vault.rglob("*.pdf"):
        index.setdefault(p.name.lower(), []).append(p)
    return index


def resolve_embed(text: str, index: dict, note: Path) -> Path | None:
    """Resolve the note's first PDF embed to a real path via the basename index,
    preferring a candidate nearest the note's folder when several share a name."""
    refs = _PDF_LINK.findall(text)
    if not refs:
        return None
    name = Path(refs[0].replace("%20", " ")).name.lower()
    cands = index.get(name)
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    nd = set(note.parent.parts)
    return min(cands, key=lambda c: len(set(c.parts) ^ nd))


def extract_text(pdf_path: str, max_pages: int = 12) -> tuple[str, int]:
    """Return (extracted_text, page_count) for a PDF's text layer. Empty text
    means an image-only scan that needs OCR before it can be made searchable."""
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as doc:
        n = len(doc.pages)
        parts = [(p.extract_text() or "") for p in doc.pages[:max_pages]]
    return "\n".join(parts).strip(), n


def find_tesseract(config: dict | None = None) -> str | None:
    """Locate the Tesseract binary. Prefers config['tesseract_cmd'], then PATH,
    then the standard Windows install dirs. Returns the path or None if absent."""
    import shutil

    if config and config.get("tesseract_cmd"):
        cand = Path(config["tesseract_cmd"])
        if cand.is_file():
            return str(cand)
    found = shutil.which("tesseract")
    if found:
        return found
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if Path(p).is_file():
            return p
    return None


def ocr_pdf(pdf_path: str, max_pages: int = 12, dpi: int = 300,
            tesseract_cmd: str | None = None) -> tuple[str, int]:
    """OCR an image-only PDF and return (text, page_count).

    For scans where extract_text() returns empty (no text layer). Pages are
    rasterised with pypdfium2 — a pure-Python renderer, so no poppler needed —
    then read by Tesseract. Pass tesseract_cmd (from find_tesseract) when the
    binary isn't on PATH. Raises RuntimeError if Tesseract isn't available."""
    import pypdfium2 as pdfium
    import pytesseract

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    scale = dpi / 72.0
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        n = len(pdf)
        parts = []
        for i in range(min(n, max_pages)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            try:
                parts.append(pytesseract.image_to_string(bitmap.to_pil()) or "")
            finally:
                bitmap.close()
                page.close()
    finally:
        pdf.close()
    return "\n".join(parts).strip(), n


def _sanitise(title: str) -> str:
    name = _ILLEGAL.sub("", title)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:120].rstrip()


def _as_callout(body_text: str) -> str:
    """Render extracted text as a collapsed Obsidian callout (each line quoted).
    Collapsed so the note stays visually clean; still fully search-indexed."""
    lines = [ln.rstrip() for ln in body_text.splitlines()]
    # Drop runs of blank lines; a blank quoted line keeps the callout intact.
    quoted = "\n".join(f"> {ln}" if ln else ">" for ln in lines)
    return f"{CALLOUT_HEADER}\n{quoted}\n"


def inject_body(text: str, body_text: str) -> str:
    """Add (or replace) the searchable-text callout after the PDF embed.
    Idempotent: a second call with the same text yields the same result."""
    callout = _as_callout(body_text)
    if _CALLOUT_BLOCK.search(text):
        return _CALLOUT_BLOCK.sub(callout, text, count=1)
    m = _PDF_EMBED.search(text)
    if m:
        before = text[:m.end()].rstrip("\n")
        after = text[m.end():].lstrip("\n")
        block = before + "\n\n" + callout
        return block + ("\n" + after if after else "")
    return text.rstrip() + "\n\n" + callout


def _update_refs(config: dict, old_stem: str, new_stem: str) -> int:
    """Rewrite `[[old_stem]]`/`[[old_stem|alias]]`/`[[old_stem#h]]` wikilinks to
    the renamed note across the vault. Returns count of files changed."""
    vault = Path(config["vault_path"])
    link = re.compile(r"\[\[" + re.escape(old_stem) + r"(?=[\]|#])")
    changed = 0
    for f in vault.rglob("*.md"):
        try:
            t = f.read_text(encoding="utf-8")
        except OSError:
            continue
        new = link.sub("[[" + new_stem, t)
        if new != t:
            f.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def apply_note(config: dict, note_path: str, new_title: str, body_text: str,
               dry_run: bool = False) -> dict:
    """Inject searchable text and rename one note to a meaningful title.

    - Injects `body_text` as a collapsed callout after the embed (idempotent).
    - Renames `<note>.md` -> `<new_title>.md` (Windows-sanitised, collision-safe)
      and rewrites wikilinks pointing at the old stem.
    - Leaves the PDF and its _resources folder untouched.

    With dry_run=True nothing is written; the returned dict shows what would
    change. Pass new_title == current stem to inject text without renaming.
    """
    note = Path(note_path)
    if not note.is_file():
        raise FileNotFoundError(note)
    text = note.read_text(encoding="utf-8")

    new_stem = _sanitise(new_title)
    if not new_stem:
        raise ValueError("Title empty after sanitising")
    new_note = note.with_name(new_stem + ".md")

    result = {
        "old": note.name, "new": new_note.name,
        "rename": new_note != note,
        "collision": new_note != note and new_note.exists(),
        "injected": bool(body_text.strip()),
        "refs_updated": 0, "applied": False,
    }
    if dry_run or result["collision"]:
        return result

    if body_text.strip():
        text = inject_body(text, body_text)
    note.write_text(text, encoding="utf-8")
    if result["rename"]:
        note.rename(new_note)
        result["refs_updated"] = _update_refs(config, note.stem, new_note.stem)
    result["applied"] = True
    return result
