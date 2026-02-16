# Diary YouTube Sync

## Overview

Automates adding YouTube video links and auto-generated transcripts to Obsidian diary notes. Also creates daily diary notes, audits tags, and detects issues (missing entries, misplaced files, missing uploads).

**Runs:** Daily at 6am via Windows Task Scheduler (`DiaryYouTubeSync`)
**Dashboard:** http://localhost:5050
**Log:** `sync.log` (rotating, 1MB max, 5 backups)

## Architecture

```
sync.py (main entry point)
  ├── youtube_client.py    → YouTube Data API v3 (OAuth2, Brand Account @dezgo74)
  ├── transcript_fetcher.py → youtube-transcript-api (auto-generated captions)
  ├── diary_finder.py      → Find diary notes by date (vault-wide search)
  └── note_updater.py      → Analyze + modify note files (add video link + transcript)

dashboard.py (Flask web UI, port 5050)
  └── templates/dashboard.html
```

## Sync Flow

1. Create today's diary note if it doesn't exist (correct filename, tag, location)
2. Authenticate with YouTube API (cached refresh token)
3. Fetch channel uploads within lookback window
4. For each video, find matching diary note by date
5. Fetch auto-generated captions via youtube-transcript-api
6. Update note: add blockquote with video link + formatted transcript
7. Run tag audit on all diary notes (fix `Diary-YYYY` mismatches)
8. Check for missing YouTube uploads (diary note exists but no video)

## Configuration (`config.yaml`)

| Key | Value | Notes |
|-----|-------|-------|
| `vault_path` | `C:\Users\Derek\iCloudDrive\Documents\ObsidianVault` | Obsidian vault root |
| `diary_subdir` | `Diary` | Expected location: `Diary/YYYY/` |
| `channel_id` | `UCZ-ss-BTWofA-sy5i6q5XAg` | @dezgo74 Brand Account |
| `lookback_days` | `30` | How far back to sync videos |
| `transcript_lang` | `en` | Caption language |
| `timezone` | `Australia/Sydney` | For converting YouTube UTC timestamps |

## Key Files

| File | Purpose |
|------|---------|
| `sync.py` | Main entry point — orchestrates everything |
| `youtube_client.py` | OAuth2 auth + upload listing via YouTube Data API v3 |
| `transcript_fetcher.py` | Fetch + format auto-generated captions |
| `diary_finder.py` | Find diary notes by date, vault-wide search, wrong-location detection |
| `note_updater.py` | Analyze note state, update with video link + transcript, fix tags |
| `dashboard.py` | Flask web dashboard |
| `config.yaml` | User configuration |
| `credentials.json` | Google OAuth2 client credentials (from Cloud Console) |
| `token.json` | Cached OAuth2 refresh token (Brand Account) |
| `state.json` | Tracks which videos have been processed |
| `sync.log` | Audit log of all sync activity |
| `backups/` | `.bak` copies of notes before modification |

## Filename Parser

The diary finder accepts any file starting with "Dear Diary" and extracts dates flexibly:
- Strips all commas before matching
- Strips ordinal suffixes (1st, 2nd, 3rd, 4th → 1, 2, 3, 4)
- Searches for `DD MonthName YYYY` anywhere in the filename
- Case-insensitive month matching with abbreviations (Jan, Feb, Aug, Sept, etc.)
- Known typos handled (e.g., "Octoboer")
- Files starting with "Dear Diary" that can't be parsed are flagged as "Unrecognized"

## Known Issues

### iCloud Sync In Progress

**Status:** Waiting

Diary notes are being migrated from Evernote into the Obsidian vault via iCloud. Until sync completes, many notes are scattered across non-standard locations (e.g., `Main.5/` instead of `Diary/YYYY/`). The dashboard detects and reports these but does NOT move files while sync is in progress.

**Action:** Once iCloud sync is complete, move misplaced notes to `Diary/YYYY/` and rename any with non-standard filenames.

### Older Notes Not Yet Backfilled

**Status:** Ready to do

The sync only processed the last 30 days on first run (18 notes updated). Videos from July 2025 through mid-January 2026 have not had transcripts added yet. Need to bump `lookback_days` temporarily and run a sync to backfill.

### Some Videos Map to Wrong Date

YouTube's `publishedAt` is in UTC. Videos recorded late at night in Sydney may appear as the next day in UTC. The sync converts to `Australia/Sydney` timezone, but edge cases around midnight could still mismatch.

### Unrecognized Diary Notes

Some older files have mangled filenames that can't be parsed (e.g., `Dear Diary, it's Thursday 15 December 2015Untitled note.md`). These show in the dashboard under "Unrecognized Diary Notes" and need manual fixing.

## Dashboard Sections

| Section | Description |
|---------|-------------|
| **Status Bar** | Last sync time, sync summary, "Sync Now" button |
| **Stat Cards** | Total notes, videos synced, issues count, pending transcripts, wrong location |
| **Notes in Wrong Location** | Diary notes not in expected `Diary/YYYY/` folder |
| **Unrecognized Diary Notes** | "Dear Diary" files where date couldn't be parsed |
| **Missing Diary Entries** | Days since 6 July 2016 with no diary note at all |
| **No YouTube Video** | Diary notes (July 2025+) with no matching YouTube upload |
| **YouTube Video But No Note** | Videos uploaded but no diary note found for that date |
| **Pending Transcripts** | Videos found but captions not ready yet (retried next sync) |
| **Recent Notes Without Video Link** | Last 30 days, notes missing `[Video]` link |
| **Recently Synced** | Last 20 successfully processed videos |

## Current Status

**Phase:** Operational. Daily sync running. Dashboard live. Evernote migration in progress.

### What Works

- [x] YouTube OAuth2 with Brand Account (@dezgo74)
- [x] Fetch uploads and match to diary notes by date
- [x] Fetch auto-generated captions and format as prose paragraphs
- [x] Update notes with blockquote video link + transcript
- [x] Preserve existing YouTube URLs (including `?si=` share params)
- [x] Replace placeholder `[Video](https://a)` links with real URLs
- [x] Tag audit and auto-correction (`Diary-YYYY`)
- [x] Daily note creation (correct filename, tag, location)
- [x] State tracking for idempotent re-runs
- [x] Backups before any note modification
- [x] Web dashboard with all issue categories
- [x] Vault-wide search (catches misplaced notes)
- [x] Flexible filename parser (commas, apostrophes, abbreviations, typos)
- [x] Windows Task Scheduler (daily 6am, catch-up on missed runs)
- [x] Rotating audit log

### What Doesn't Work Yet

- [ ] **Backfill older videos** — Need to increase lookback to cover July 2025 onward
- [ ] **Move misplaced notes** — Waiting for iCloud sync to complete
- [ ] **Fix unrecognized filenames** — Manual rename needed for mangled filenames

## TODOs

### Priority 1: Backfill
- [ ] Temporarily set `lookback_days: 300` and run sync to backfill all videos since July 2025
- [ ] Reset `lookback_days: 30` after backfill

### Priority 2: Post-iCloud Sync Cleanup
- [ ] Move all misplaced notes to `Diary/YYYY/` folders
- [ ] Rename unrecognized diary notes with correct formatting
- [ ] Re-run dashboard to confirm zero wrong-location / unrecognized issues

### Priority 3: Enhancements
- [ ] Add "Move to correct location" button to dashboard (once iCloud sync done)
- [ ] Add "Rename" suggestions for unrecognized notes
- [ ] Consider adding search/filter to dashboard tables (entries will grow over time)
