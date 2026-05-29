---
name: scan-enrich
description: Tag and human-readably rename scanned PDFs in Derek's Obsidian vault Scans folder. Use when Derek asks to organise/tag/name/process his scans, or to clean up scans that still have a datestamp filename and blank tags. Runs in the current Claude Code session (no API cost) with Derek reviewing before anything is renamed.
---

# Scan Enrich

Give each scanned PDF in the vault's `Scans/` folder a meaningful tag and a
human-readable name. This is the human-in-the-loop counterpart to the unattended
`scan_companion` pass in `sync.py`: that pass creates a *blank* companion note
(empty `tags: []`, datestamp filename) for every scan; this skill fills the tag
in and renames the scan + companion to `YYYY-MM-DD Description`.

It runs in the session — **you** read the rendered page and decide the tag and
name, so there is no Anthropic API cost (unlike routing it through Haiku in the
script). Derek wants to **review before any rename happens** — never skip that.

## Why this is a skill and not part of sync.py

The scans are image-only PDFs (no text layer), so tagging needs vision. Derek
scans in infrequent bursts, doesn't search by tags much, and wants to eyeball
the suggestions — and renames ripple into every link that points at the scan.
All of that fits on-demand, reviewed work far better than a 3am cron job. See
the repo's `scan_companion.py` (blank companion creation) and `scan_tools.py`
(the deterministic helpers this skill drives).

## Conventions (decided with Derek)

- **One companion note per PDF**, sitting next to it in `Scans/`.
- **Name format: `YYYY-MM-DD Description.pdf`** — ISO date prefix (for
  chronological folder sorting) + a concise human-readable description. The date
  comes from the companion's frontmatter `date:` field, which is authoritative.
- **Prefer an existing tag.** The vault has ~2,200 hierarchical tags
  (`CW/Ref/Cust/<name>`, `CW/Project/Done/<job>`, `CW/Ref/<area>`, etc.). Match
  one of those before minting anything new. Only propose a **new** tag when
  nothing fits, and follow the existing hierarchy style (same casing, same
  `Area/Sub/Leaf` shape). Flag new tags clearly as NEW in the review.
- **Ground every tag and name in what the page actually says.** Do not infer
  beyond the document. If a scan is illegible or ambiguous, say so and leave it
  for Derek rather than guessing. (Same discipline as Life Events curation.)

## Workflow

All helpers are in `scan_tools.py` at the repo root. Run them with
`python -c "import scan_tools as st; ..."` (config is loaded from `config.yaml`).

### 1. Find what needs enriching

```python
import scan_tools as st
cfg = st.load_config()
pending = st.list_pending(cfg)   # scans whose companion still has tags: []
```

Each entry has `pdf`, `companion`, `date`, `pages`. If empty, tell Derek there's
nothing to do (run `sync.py` first if scans exist but have no companion yet).

### 2. Load the tag vocabulary once

```python
tags = st.vault_tags(cfg)   # sorted list of existing non-diary tags
```

Keep this list in mind as the menu to match against. Skim it for the areas
relevant to each scan (work/CW, super/finance, family, etc.).

### 3. Look at each scan

```python
png, total = st.render_page(pdf_path, page=0, resolution=150)
# Read the PNG with the Read tool to view it. Render page=1 too if page 1
# doesn't identify the document. Don't render whole long PDFs — 1–2 pages is
# enough to identify and name a scan.
```

Read the rendered PNG, then decide:
- **Description** — what it is, concise (a few words, e.g. `Daikin refrigerant
  spec - HSNRP series`, `Cassidy court fine notice`, `Aware Super statement`).
- **Tag(s)** — the best existing match(es), or a new tag if nothing fits.

### 4. Present proposals and get Derek's OK

Show a compact table: current filename → proposed name, and proposed tag(s) with
NEW ones marked. Use `dry_run=True` to get the exact resulting filename without
changing anything:

```python
preview = st.apply_enrichment(cfg, pdf_path, description, tag_list, dry_run=True)
# preview['new_pdf'], preview['collision']  ← show these; collision means the
# target name already exists, so adjust the description.
```

**Wait for Derek to approve or amend** before step 5. Batch the review — show
all proposals at once so he can scan them quickly.

### 5. Apply the approved enrichments

```python
res = st.apply_enrichment(cfg, pdf_path, description, tag_list)
# Renames the PDF + companion to "<date> <description>", writes the tags as a
# block list into the companion, rewrites its ![[embed]], and fixes any other
# vault note that linked to the old name. res['refs_updated'] = files changed.
```

Report what changed. After renaming, `sync.py` won't re-create a companion
(the stem still matches), and the date is preserved in frontmatter.

## Guardrails

- **Never rename without Derek's explicit OK** on the proposed name + tags.
- Apply is deterministic but irreversible-ish (it's a rename + edits). The vault
  is not git-tracked, so if Derek wants a safety net, suggest he commit/back up
  the vault first, or do a `dry_run=True` pass and review every `new_pdf`.
- Don't touch scans whose companion already has tags — `list_pending` skips
  them; respect that unless Derek explicitly asks to re-tag one.
- `.scan_render/` holds transient PNGs; it's gitignored and safe to delete after.
