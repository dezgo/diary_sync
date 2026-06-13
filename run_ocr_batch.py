#!/usr/bin/env python
"""Phase A OCR batch — resumable, logs progress to ocr_batch.log.

Skip any note that already has the '> [!quote]- Document text (for search)'
callout, so a restart picks up where it left off.
"""
import json
import sys
import time
from pathlib import Path

from pdf_note_tools import (
    CALLOUT_HEADER, build_pdf_index, find_tesseract, inject_body, load_config,
    ocr_pdf,
)

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "ocr_batch.log"


def log(msg: str, also_stdout: bool = True) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if also_stdout:
        print(line, flush=True)


def main() -> None:
    cfg = load_config()
    vault = Path(cfg["vault_path"])
    tess = find_tesseract(cfg)
    if not tess:
        log("ERROR: Tesseract not found"); sys.exit(1)

    log("Building PDF index...")
    idx = build_pdf_index(cfg)
    log(f"PDF index: {sum(len(v) for v in idx.values())} PDFs")

    with open(SCRIPT_DIR / "pdf_notes_needs_ocr.json") as f:
        ocr_list = json.load(f)
    with open(SCRIPT_DIR / "pdf_notes_low_quality.json") as f:
        low_list = json.load(f)

    all_entries = [(r, "needs_ocr") for r in ocr_list] + \
                  [(r, "low_quality") for r in low_list]
    log(f"Entries: {len(all_entries)} ({len(ocr_list)} needs_ocr + {len(low_list)} low_quality)")

    written = already_done = no_pdf = empty_ocr = errors = 0
    t0 = time.time()

    for i, (rec, src) in enumerate(all_entries):
        note_path = vault / rec["note"]

        # Resumability: skip if callout already present
        try:
            existing = note_path.read_text(encoding="utf-8")
        except OSError as e:
            log(f"  SKIP (can't read) {rec['note']}: {e}")
            errors += 1
            continue

        if src == "needs_ocr" and CALLOUT_HEADER in existing:
            already_done += 1
            continue
        # For low_quality we always re-inject (replaces garbled text), unless
        # the note clearly has a good callout already (heuristic: >200 chars).
        if src == "low_quality" and CALLOUT_HEADER in existing:
            # Check the callout body is non-trivial
            import re
            m = re.search(r"> \[!quote\]- Document text.*?\n((?:>.*\n?)*)", existing, re.S)
            if m and len(m.group(1)) > 200:
                already_done += 1
                continue

        # Resolve PDF path
        pdf_name = rec["pdf"].lower()
        cands = idx.get(pdf_name, [])
        if not cands:
            no_pdf += 1
            continue
        if len(cands) == 1:
            pdf_path = cands[0]
        else:
            note_parts = set(note_path.parent.parts)
            pdf_path = min(cands, key=lambda c: len(set(c.parts) ^ note_parts))

        # OCR
        try:
            body, _ = ocr_pdf(str(pdf_path), max_pages=12, tesseract_cmd=tess)
        except Exception as e:
            log(f"  ERR ocr {rec['note']}: {e}")
            errors += 1
            continue

        if not body.strip():
            empty_ocr += 1
            continue

        # Inject
        try:
            new_text = inject_body(existing, body)
            if new_text != existing:
                note_path.write_text(new_text, encoding="utf-8")
                written += 1
            else:
                already_done += 1
        except Exception as e:
            log(f"  ERR write {rec['note']}: {e}")
            errors += 1
            continue

        if (i + 1) % 25 == 0:
            elapsed = time.time() - t0
            rate = max((i + 1 - already_done), 1) / max(elapsed, 1)
            todo = len(all_entries) - i - 1
            eta = int(todo / rate) if rate else 0
            log(f"[{i+1}/{len(all_entries)}] written={written} done={already_done} "
                f"no_pdf={no_pdf} empty={empty_ocr} err={errors} eta~{eta}s")

    elapsed = time.time() - t0
    log(f"=== COMPLETE in {elapsed:.0f}s ===")
    log(f"  Written (injected/replaced): {written}")
    log(f"  Already had callout:         {already_done}")
    log(f"  No PDF found:                {no_pdf}")
    log(f"  OCR returned empty:          {empty_ocr}")
    log(f"  Errors:                      {errors}")


if __name__ == "__main__":
    main()
