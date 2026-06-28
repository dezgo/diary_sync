---
name: diary-transcript-cleanup
description: Fix and backfill diary-note transcripts in Derek's Obsidian vault. Use when a diary day is missing its transcript (esp. "no transcript" because background music triggered a YouTube Content ID block), when a transcript reads garbled, or when Derek wants speech-to-text errors cleaned up. Covers re-running a single day's sync, recovering a blocked transcript locally with Whisper, cleaning up garbles using the known-misspellings table, and verifying exact wording.
---

# Diary Transcript Cleanup

Repair or backfill the transcript (and summary) in a diary note. This is the
human-in-the-loop counterpart to the unattended `sync.py` run: when the normal
sync can't get a transcript, or gets one that's garbled, this skill is how it
gets fixed in-session with Derek reviewing.

Background context lives in two memories — read them first:
`project_music_blocked_transcripts.md` (the fallback procedure) and
`reference_diary_proper_nouns.md` (the canonical spellings). This skill is the
operational version of both; **keep all three in sync** when something new is
learned.

## When to use

- `python sync.py --date YYYY-MM-DD` reported `no transcript` / "Subtitles are
  disabled for this video" — almost always background music tripping Content ID.
  Re-running won't help; the captions won't ever appear.
- A transcript is present but reads garbled / has wrong names.
- Derek asks to tidy up a specific day or recover what he actually said.

## Step 1 — Re-run the single day first

```
python sync.py --date YYYY-MM-DD
```

`--date` mode bypasses the lookback, the already-complete skip, and the
`sync_delay_days` wait, so it force-reprocesses that day. It does **only** the
video link + transcript + summary (no photos, no audits). If it writes the
transcript, you're done. If it says `no transcript`, go to Step 2.

## Step 2 — Music-blocked fallback (local Whisper)

Nothing leaves the machine; transcription is CPU-only. Models are already cached
in `C:\Users\Derek\.cache\huggingface\hub\` (`small.en` ~464 MB fast pass;
`large-v3` ~3 GB accurate pass) — no re-download.

1. **Download the audio.** Must use format `18` (combined 360p mp4 w/ audio);
   `bestaudio` fails — YouTube's SABR-only streaming + no JS runtime strips the
   audio-only formats.
   ```
   yt-dlp --no-update -f 18 -x --audio-format mp3 -o "<scratch>/<id>.%(ext)s" <url>
   ```
2. **Transcribe + inject** by reusing the project's own formatting so the result
   is byte-identical to a normal sync. Run from the repo dir:
   ```python
   import sys; sys.path.insert(0, ".")
   from dataclasses import dataclass
   from faster_whisper import WhisperModel
   from transcript_fetcher import format_transcript
   from note_updater import analyze_note, update_note
   from summariser import generate_summary
   import yaml

   @dataclass
   class Seg:            # format_transcript expects .text/.start/.duration
       text: str; start: float; duration: float

   cfg = yaml.safe_load(open("config.yaml"))
   model = WhisperModel("small.en", device="cpu", compute_type="int8")
   segs, _ = model.transcribe(AUDIO, language="en", vad_filter=True)
   segs = [Seg(s.text, s.start, s.end - s.start) for s in segs]
   text = format_transcript(segs)

   a = analyze_note(NOTE)
   summary = None
   if not a["has_summary"]:
       summary = generate_summary(text, api_key=cfg.get("anthropic_api_key"),
                                  model=cfg.get("summary_model"))
   update_note(NOTE, a["video_url"], text, a, "backups", summary_text=summary)
   ```
3. **Summary.** `generate_summary` needs `ANTHROPIC_API_KEY` in the env (it is
   NOT in config.yaml). If it's absent it returns `None` and skips silently — in
   that case write the summary by hand in `summariser.py`'s house style: 3–8
   sentences, past tense, refer to Derek as "Derek", warm and natural, grounded
   only in what the transcript says. Insert it as a `## Summary` section above the
   transcript blockquote (that's where `note_updater._insert_summary` puts it).

## Step 3 — Clean up the garbles

`small.en` is fast but mangles proper nouns and runs sentences together.
Rewrite obvious speech-to-text errors into best-guess readable prose, **keeping
Derek's voice and meaning** - don't formalise it, don't add content. Then apply
the canonical spellings below.

**No em dashes.** Derek dislikes long em dashes (`—`) - they read as
AI-generated. Use a plain hyphen (`-`) instead, in both the transcript and the
summary. Do a final pass and replace every `—` with `-` before saving.

### Known misspellings / recurring fixes

| Whisper hears | Correct | What it is |
|---|---|---|
| Vicki / Vicky | **Vicky** | Derek's girlfriend (met early 2026 at 88) |
| ADA / 88 | **88** | an 80s bar in town (Canberra) |
| Yovani / Giovanni | **Giovani** | housemate (Derek's spelling) |
| App Boundary / appboundary.cc | **App Foundry / flowfield.appfoundry.cc** | Derek's site/brand |
| Chord / Chord code | **Claude / Claude Code** | |
| Jollymont | **Jolimont Centre** | |
| ChachiBT | **ChatGPT** | |

Names that usually come through fine: Joshua, Ashley, Sabrina, Damian, Rowena.

*(Add new entries here as they come up — that's the point of this table.)*

### Vault-wide spelling sweeps

If a misspelling is everywhere, scope the sweep — **the same token can be a
different real person elsewhere** (e.g. "Vicki Beard" in the CW/Computer Whiz
business notes is NOT Derek's Vicky). Restrict to `Diary/<year>`, match
whole-word (`\bVicki\b`), and back up each file before writing.

## Step 4 — Recovering exact wording (optional)

When Derek wants to verify what he *actually* said in a fuzzy spot, re-transcribe
with `large-v3` (`compute_type=int8`, device cpu) and read the segment with
timestamps. **Caveat: bigger isn't always right** — large-v3 has "corrected"
right words to wrong ones (it turned the correct "88" into "ADA"). Treat it as a
second opinion, cross-check against small.en and Derek's memory, not gospel.

## Review discipline

- Never invent proper nouns. If you can't make out a name/place, leave a clear
  best-guess and flag it for Derek rather than committing a confident wrong one.
- Ground everything in the audio/transcript. Same discipline as Life Events
  curation — no embellishment, especially around relationships.
- Show Derek what changed; he'll spot-correct names (that's how the table grows).
