#!/usr/bin/env python
"""Helpers for the 'evernote link repair' chore — broad-vault sibling of
pdf_note_tools.py.

The Yarle-exported vault is littered with internal Evernote note-links that no
longer resolve: `https://www.evernote.com/shard/sNNN/nl/<user>/<noteGuid>/`,
`share.evernote.com/note/<guid>`, `evernote.com/l/<short>`, etc. Each one
pointed at another note that *is* now in the vault — but the GUID is opaque and
there is no offline GUID->title map (the ENEX export carries no note GUIDs), so
resolution is a per-link judgement: read the source context, narrow by tag /
date / content, and pick the target. The Evernote shares are login-walled, so
nothing can be auto-scraped.

This module does only the deterministic, reviewable, idempotent mechanics:
  - find every internal-note-link across the vault (all URL forms),
  - emit a review report (one record per link: file, line, anchor, guid, ctx),
  - apply a reviewed mapping: resolved links -> `[[Target|anchor]]` wikilinks;
    unresolvable links -> "de-deaded" (anchor kept, dead URL removed, GUID
    preserved in an invisible comment) so no broken link is left behind.

The "which note does this point to" reasoning is the operator's (a Claude
session reading each note); this module never guesses a target itself.

External marketing/blog links (evernote.com/blog, /forum, mailto:, webclipper…)
are deliberately NOT matched — only internal note references.
"""

import json
import re
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
REPORT_PATH = SCRIPT_DIR / "evernote_links_report.json"
BACKUP_DIR = SCRIPT_DIR / "backups" / "evernote_link_repair"

# Internal-note-link URL forms only (NOT blog/forum/premium/webclipper/mailto).
_URL = (
    r"(?:https?://)?(?:www\.|share\.)?evernote\.com/"
    r"(?:shard/s\d+/(?:sh|nl)/[^)\s\"'<>]+"
    r"|l/[^)\s\"'<>]+"
    r"|note/[0-9a-fA-F-]+"
    r"|link/[^)\s\"'<>]+)"
    r"|evernote:///?view/[^)\s\"'<>]+"
)
_MD_LINK = re.compile(r"\[([^\]]*)\]\((" + _URL + r")\)")
_HTML_LINK = re.compile(r"<a[^>]*href=\"(" + _URL + r")\"[^>]*>(.*?)</a>",
                        re.S)
# Angle-bracket autolinks: <https://www.evernote.com/...> — no anchor text.
_ANGLE_LINK = re.compile(r"<(" + _URL + r")>")
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                   r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _guid_of(url: str) -> str | None:
    m = _GUID.search(url)
    return m.group(0).lower() if m else None


def _link_id(rel_path: str, anchor: str, url: str) -> str:
    """Stable id for a link occurrence, so a reviewed mapping survives re-scans
    and the apply step can target an exact link without line-number drift."""
    guid = _guid_of(url) or url
    return f"{rel_path}::{guid}::{anchor.strip()[:40]}"


def iter_links(text: str):
    """Yield (anchor, url, span) for every internal Evernote note-link in text,
    covering markdown `[a](u)`, HTML `<a href=u>a</a>`, and bare `<url>` forms.
    Angle-bracket autolinks yield an empty anchor; to_wikilink collapses these
    to `[[Target]]` without an alias."""
    for m in _MD_LINK.finditer(text):
        yield m.group(1), m.group(2), m.span()
    for m in _HTML_LINK.finditer(text):
        yield re.sub(r"<[^>]+>", "", m.group(2)).strip(), m.group(1), m.span()
    for m in _ANGLE_LINK.finditer(text):
        yield "", m.group(1), m.span()


def scan_vault(config: dict) -> list[dict]:
    """Walk the vault and return one record per internal-note-link occurrence."""
    vault = Path(config["vault_path"])
    records: list[dict] = []
    for f in vault.rglob("*.md"):
        if ".obsidian" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = f.relative_to(vault).as_posix()
        line_starts = None
        for anchor, url, (start, _end) in iter_links(text):
            if line_starts is None:
                line_starts = _build_line_index(text)
            line = _line_of(line_starts, start)
            ctx = _context(text, start)
            records.append({
                "id": _link_id(rel, anchor, url),
                "file": rel,
                "line": line,
                "anchor": anchor.strip(),
                "url": url,
                "guid": _guid_of(url),
                "context": ctx,
                # filled in during review:
                "action": None,      # "wikilink" | "dedead" | None (unresolved)
                "target": None,      # vault note stem when action == "wikilink"
                "confidence": None,  # "high" | "medium" | "low"
                "rationale": None,
            })
    return records


def _build_line_index(text: str) -> list[int]:
    idx, pos = [0], text.find("\n")
    while pos != -1:
        idx.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return idx


def _line_of(line_starts: list[int], offset: int) -> int:
    import bisect
    return bisect.bisect_right(line_starts, offset)


def _context(text: str, start: int, width: int = 90) -> str:
    a = max(0, start - width)
    b = min(len(text), start + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def write_report(records: list[dict], path: Path = REPORT_PATH) -> None:
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def load_report(path: Path = REPORT_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarise(records: list[dict]) -> dict:
    files = {r["file"] for r in records}
    by_action: dict[str, int] = {}
    for r in records:
        by_action[r["action"] or "unresolved"] = \
            by_action.get(r["action"] or "unresolved", 0) + 1
    return {"links": len(records), "files": len(files),
            "unique_guids": len({r["guid"] for r in records if r["guid"]}),
            "by_action": by_action}


# --- rewriting ---------------------------------------------------------------

def _norm(s: str) -> str:
    """Normalise a title/anchor for comparison (case, punctuation, Yarle .N)."""
    s = re.sub(r"\.\d+$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def to_wikilink(anchor: str, target: str) -> str:
    """`[[Target|anchor]]`, collapsing to `[[Target]]` when the anchor already
    equals the target title (avoids the noisy `[[Foo|Foo]]`)."""
    anchor = anchor.strip()
    if not anchor or _norm(anchor) == _norm(target):
        return f"[[{target}]]"
    return f"[[{target}|{anchor}]]"


def de_dead(anchor: str, guid: str | None, treatment: str = "hidden_guid") -> str:
    """Replacement text for an unresolvable link: keep the readable anchor, drop
    the broken URL. Treatments:
      - "hidden_guid": anchor + an invisible `%%evernote:GUID%%` comment so a
        future mapping source can still recover it (default).
      - "tag":        anchor + ` #dead-evernote-link` (searchable breadcrumb).
      - "plain":      anchor only.
    """
    anchor = anchor.strip()
    if treatment == "plain" or not guid:
        return anchor if treatment != "tag" else f"{anchor} #dead-evernote-link"
    if treatment == "tag":
        return f"{anchor} #dead-evernote-link"
    return f"{anchor} %%evernote:{guid}%%"


def _replacement(rec: dict, treatment: str) -> str | None:
    """The exact text that should replace this link's markdown, or None if the
    record carries no decision yet."""
    if rec.get("action") == "wikilink" and rec.get("target"):
        return to_wikilink(rec["anchor"], rec["target"])
    if rec.get("action") == "dedead":
        return de_dead(rec["anchor"], rec.get("guid"), treatment)
    return None


def apply_file(config: dict, rel_path: str, recs: list[dict],
               treatment: str = "hidden_guid", dry_run: bool = False) -> dict:
    """Apply all decided link records for ONE file. Idempotent: matches the
    live `[anchor](url)` / `<a>` markup, so re-running after a partial apply is
    safe; links whose markup is already gone are reported as 'missing'.

    Backs the file up to backups/evernote_link_repair/ before writing.
    """
    vault = Path(config["vault_path"])
    f = vault / rel_path
    text = f.read_text(encoding="utf-8")
    original = text
    applied, missing, skipped = [], [], []

    # Rebuild the live link spans each pass so offsets stay valid as we splice.
    decided = {r["id"]: r for r in recs}
    for rec in recs:
        repl = _replacement(rec, treatment)
        if repl is None:
            skipped.append(rec["id"])
            continue
        hit = None
        for anchor, url, span in iter_links(text):
            if _link_id(rel_path, anchor, url) == rec["id"]:
                hit = span
                break
        if hit is None:
            missing.append(rec["id"])
            continue
        text = text[:hit[0]] + repl + text[hit[1]:]
        applied.append(rec["id"])

    result = {"file": rel_path, "applied": len(applied),
              "missing": len(missing), "skipped": len(skipped),
              "changed": text != original, "wrote": False}
    if dry_run or text == original:
        return result

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / (f.stem + "__" + _guid_safe(rel_path) + ".md.bak")
    backup.write_text(original, encoding="utf-8")
    f.write_text(text, encoding="utf-8")
    result["wrote"] = True
    return result


def _guid_safe(rel_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", rel_path)[-60:]


def apply_all(config: dict, records: list[dict], treatment: str = "hidden_guid",
              dry_run: bool = False) -> dict:
    """Apply every decided record, grouped by file. Returns aggregate counts."""
    by_file: dict[str, list[dict]] = {}
    for r in records:
        by_file.setdefault(r["file"], []).append(r)
    agg = {"files": 0, "applied": 0, "missing": 0, "skipped": 0}
    for rel, recs in by_file.items():
        res = apply_file(config, rel, recs, treatment, dry_run)
        if res["changed"]:
            agg["files"] += 1
        for k in ("applied", "missing", "skipped"):
            agg[k] += res[k]
    return agg


def build_title_index(config: dict) -> dict:
    """Map normalised note title -> [stems], to help a reviewer resolve an
    anchor or guessed title to an actual vault note."""
    vault = Path(config["vault_path"])
    idx: dict[str, list[str]] = {}
    for f in vault.rglob("*.md"):
        if ".obsidian" in f.parts:
            continue
        idx.setdefault(_norm(f.stem), []).append(f.stem)
    return idx
