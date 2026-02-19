# Diary YouTube Sync

## Overview

Automates adding YouTube video links and auto-generated transcripts to Obsidian diary notes. Also creates daily diary notes, audits tags, and detects issues (missing entries, misplaced files, missing uploads).

**Runs:** Daily at 6am via Windows Task Scheduler (`DiaryYouTubeSync`)
**Backfill:** Every 6 hours via Task Scheduler (`DiaryBackfillTranscripts`) — 5 videos per batch
**Dashboard:** http://localhost:5050 / https://diary.derekgillett.com (Cloudflare Tunnel + Zero Trust)
**Repo:** github.com/dezgo/diary_sync
**Log:** `sync.log` (rotating, 1MB max, 5 backups)

## Architecture

```
sync.py (main entry point)
  ├── youtube_client.py    → YouTube Data API v3 (OAuth2, Brand Account @dezgo74)
  ├── transcript_fetcher.py → youtube-transcript-api (auto-generated captions)
  ├── diary_finder.py      → Find diary notes by date (vault-wide search)
  ├── note_updater.py      → Analyze + modify note files (add video link + transcript + summary)
  └── summariser.py        → Claude Haiku AI summary generation (Anthropic SDK)

backfill.py (gradual transcript backfill, 5 per batch)

dashboard.py (Flask web UI, port 5050)
  └── templates/dashboard.html

start_services.bat (starts dashboard + Cloudflare Tunnel on login)
```

## Sync Flow

1. Create today's diary note if it doesn't exist (correct filename, tag, location)
2. Authenticate with YouTube API (cached refresh token)
3. Fetch channel uploads within lookback window
4. For each video, find matching diary note — **prefers title date** over publish date (handles late-night uploads that cross midnight)
5. Fetch auto-generated captions via youtube-transcript-api
6. Generate AI summary of transcript via Claude Haiku (best-effort, non-blocking)
7. Update note: add `## Summary` section + blockquote with video link + formatted transcript
8. Run tag audit on all diary notes (fix `Diary-YYYY` mismatches)
9. Check for missing YouTube uploads (diary note exists but no video)

### Single-Date Sync

Sync a single diary entry instead of the full lookback window:

```
python sync.py --date 2026-02-16
```

Also available from the dashboard: date picker next to "Sync Now", or per-row "Sync" buttons on pending transcripts.

## IP Block Handling

YouTube blocks IPs that fetch transcripts too aggressively. The system handles this automatically:

- **Detection:** First blocked request immediately triggers a 24h cooldown — no retries
- **Per-IP:** Cooldown records which IP was blocked (`ip_block` in `state.json`)
- **VPN-aware:** On each run, checks current external IP against blocked IP. Different IP = safe to sync
- **Dashboard:** Shows three states — red "Blocked" (same IP), green "OK (VPN)" (different IP), green "OK" (no block)
- **Rate limiting:** Backfill uses 10s delay with random jitter between fetches; batch size of 5

## Configuration (`config.yaml`)

| Key | Value | Notes |
|-----|-------|-------|
| `vault_path` | `C:\Users\Derek\iCloudDrive\Documents\ObsidianVault` | Obsidian vault root |
| `diary_subdir` | `Diary` | Expected location: `Diary/YYYY/` |
| `channel_id` | `UCZ-ss-BTWofA-sy5i6q5XAg` | @dezgo74 Brand Account |
| `lookback_days` | `30` | How far back to sync videos |
| `transcript_lang` | `en` | Caption language |
| `timezone` | `Australia/Sydney` | For converting YouTube UTC timestamps |
| `anthropic_api_key` | `sk-ant-...` | API key for Claude summary generation (or use `ANTHROPIC_API_KEY` env var) |
| `summary_model` | `claude-haiku-4-5-20251001` | Claude model for summaries (optional, defaults to Haiku) |

## Key Files

| File | Purpose |
|------|---------|
| `sync.py` | Main entry point — orchestrates everything. Supports `--date YYYY-MM-DD` for single-note sync |
| `youtube_client.py` | OAuth2 auth + upload listing via YouTube Data API v3 |
| `transcript_fetcher.py` | Fetch + format auto-generated captions. IP block detection, per-IP cooldown, external IP checking |
| `diary_finder.py` | Find diary notes by date, vault-wide search, wrong-location detection |
| `note_updater.py` | Analyze note state, update with video link + transcript + summary, fix tags |
| `summariser.py` | Generate concise daily summary from transcript via Claude Haiku (Anthropic SDK) |
| `dashboard.py` | Flask web dashboard |
| `backfill.py` | Gradual transcript backfill (5 videos/batch, 10s+jitter delays) |
| `config.yaml` | User configuration |
| `credentials.json` | Google OAuth2 client credentials (from Cloud Console) |
| `token.json` | Cached OAuth2 refresh token (Brand Account) |
| `state.json` | Tracks processed videos + IP block cooldown |
| `sync.log` | Audit log of all sync activity |
| `start_services.bat` | Starts dashboard + Cloudflare Tunnel on login |
| `backups/` | `.bak` copies of notes before modification |

## Filename Parser

The diary finder accepts any file starting with "Dear Diary" and extracts dates flexibly:
- Strips all commas before matching
- Strips ordinal suffixes (1st, 2nd, 3rd, 4th → 1, 2, 3, 4)
- Searches for `DD MonthName YYYY` anywhere in the filename
- Case-insensitive month matching with abbreviations (Jan, Feb, Aug, Sept, etc.)
- Known typos handled (e.g., "Octoboer")
- Files starting with "Dear Diary" that can't be parsed are flagged as "Unrecognized"

## Note Matching (Late-Night Uploads)

Video titles contain the diary date (e.g. "16 February 2026"). YouTube's publish date is in UTC and can be +1 day for late-night Sydney uploads. The sync **prefers the title date** — it tries that first, and only falls back to publish date if no note exists for the title date.

## Known Issues

### iCloud Sync In Progress

**Status:** Waiting

Diary notes are being migrated from Evernote into the Obsidian vault via iCloud. Until sync completes, many notes are scattered across non-standard locations (e.g., `Main.5/` instead of `Diary/YYYY/`). The dashboard detects and reports these but does NOT move files while sync is in progress.

**Action:** Once iCloud sync is complete, move misplaced notes to `Diary/YYYY/` and rename any with non-standard filenames.

### Older Notes Not Yet Backfilled

**Status:** In progress (automated)

Backfill task (`DiaryBackfillTranscripts`) runs every 6 hours, processing 5 videos per batch with randomised 10s delays to avoid YouTube rate limiting. Progress tracked in `state.json`. If IP gets blocked, enters 24h cooldown automatically; resumes on next run if IP has changed or cooldown has expired.

### Unrecognized Diary Notes

Some older files have mangled filenames that can't be parsed (e.g., `Dear Diary, it's Thursday 15 December 2015Untitled note.md`). These show in the dashboard under "Unrecognized Diary Notes" and need manual fixing.

## Dashboard Sections

| Section | Description |
|---------|-------------|
| **Status Bar** | Last sync time, sync summary, date picker, "Sync Now" button |
| **Cooldown Banner** | Shows when IP blocked (orange) or on different IP/VPN (green) |
| **Stat Cards** | Total notes, videos synced, issues count, pending transcripts, wrong location, YouTube IP status |
| **Notes in Wrong Location** | Diary notes not in expected `Diary/YYYY/` folder |
| **Unrecognized Diary Notes** | "Dear Diary" files where date couldn't be parsed |
| **Missing Diary Entries** | Days since 6 July 2016 with no diary note at all |
| **No YouTube Video** | Diary notes (July 2025+) with no matching YouTube upload |
| **YouTube Video But No Note** | Videos uploaded but no diary note found for that date |
| **Pending Transcripts** | Videos found but captions not ready yet — per-row "Sync" buttons |
| **Recent Notes Without Video Link** | Last 30 days, notes missing `[Video]` link — per-row "Sync" buttons |
| **Recently Synced** | Last 20 successfully processed videos |

## Current Status

**Phase:** Operational. Daily sync running. Backfill in progress. Dashboard live locally and via Cloudflare Tunnel. Evernote migration in progress.

### What Works

- [x] YouTube OAuth2 with Brand Account (@dezgo74)
- [x] Fetch uploads and match to diary notes by date
- [x] Title-date-first matching for late-night uploads
- [x] Single-date sync (`--date YYYY-MM-DD` / dashboard per-row buttons)
- [x] Fetch auto-generated captions and format as prose paragraphs
- [x] AI-generated daily summary via Claude Haiku (above transcript, best-effort)
- [x] Update notes with `## Summary` + blockquote video link + transcript
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
- [x] Cloudflare Tunnel for remote access (diary.derekgillett.com)
- [x] Cloudflare Zero Trust with email OTP authentication
- [x] Gradual backfill (5 videos/batch, every 6 hours)
- [x] GitHub repo (dezgo/diary_sync)
- [x] Per-IP cooldown with auto VPN detection
- [x] Dashboard IP status card (OK / Blocked / OK via VPN)

### What Doesn't Work Yet
- [ ] **Move misplaced notes** — Waiting for iCloud sync to complete
- [ ] **Fix unrecognized filenames** — Manual rename needed for mangled filenames

## TODOs

### Priority 1: Backfill
- [x] Backfill task running automatically (5 videos every 6 hours)
- [ ] Monitor progress — delete `DiaryBackfillTranscripts` scheduled task once all videos are done

### Priority 2: Post-iCloud Sync Cleanup
- [ ] Move all misplaced notes to `Diary/YYYY/` folders
- [ ] Rename unrecognized diary notes with correct formatting
- [ ] Re-run dashboard to confirm zero wrong-location / unrecognized issues

### Priority 3: Enhancements
- [ ] Add "Move to correct location" button to dashboard (once iCloud sync done)
- [ ] Add "Rename" suggestions for unrecognized notes
- [ ] Consider adding search/filter to dashboard tables (entries will grow over time)
