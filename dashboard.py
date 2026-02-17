"""Diary YouTube Sync — Web Dashboard."""

import os
import json
import subprocess
import sys
import threading
import logging
from datetime import date, timedelta
from collections import defaultdict

from flask import Flask, render_template, jsonify, request
import yaml

from diary_finder import find_all_diary_notes, find_all_diary_notes_everywhere, get_expected_path, parse_date_from_filename
from note_updater import analyze_note
from transcript_fetcher import is_in_cooldown as _check_cooldown

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "sync.log")

app = Flask(__name__)

# Track running sync process
_sync_lock = threading.Lock()
_sync_process = None
_sync_output = []


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"processed_videos": {}}


def get_log_lines(n=100):
    """Read the last n lines from the sync log."""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip() for line in lines[-n:]]


def get_dashboard_data():
    """Gather all data needed for the dashboard."""
    config = load_config()
    state = load_state()
    processed = state.get("processed_videos", {})

    # All diary notes — search entire vault to catch misplaced notes
    vault_path = config.get("vault_path", "")
    diary_subdir = config.get("diary_subdir", "Diary")
    all_notes = []
    unparsed_notes = []
    if os.path.isdir(vault_path):
        all_notes, unparsed_notes = find_all_diary_notes_everywhere(vault_path)

    # Notes in wrong location (not in Diary/YYYY/)
    wrong_location = []
    for filepath, note_date in all_notes:
        expected_dir = get_expected_path(vault_path, diary_subdir, note_date)
        actual_dir = os.path.dirname(filepath)
        if os.path.normpath(actual_dir) != os.path.normpath(expected_dir):
            wrong_location.append({
                "date": str(note_date),
                "filename": os.path.basename(filepath),
                "current": os.path.relpath(filepath, vault_path),
                "expected": os.path.relpath(expected_dir, vault_path),
            })
    wrong_location.sort(key=lambda x: x["date"], reverse=True)

    # Dates that have YouTube uploads (from state)
    upload_dates = set()
    for vid_info in processed.values():
        if "date" in vid_info:
            upload_dates.add(vid_info["date"])

    # Missing uploads: diary notes from July 2025+ with no matching video
    video_start = date(2025, 7, 1)
    missing_uploads = []
    for filepath, note_date in all_notes:
        if note_date < video_start or note_date >= date.today():
            continue
        if str(note_date) not in upload_dates:
            # Check if note itself has a video link
            try:
                analysis = analyze_note(filepath)
                if analysis["has_video_link"] and not analysis["has_placeholder"]:
                    continue  # Has a video link already, probably processed before state tracking
            except Exception:
                pass
            missing_uploads.append(str(note_date))
    missing_uploads.sort(reverse=True)

    # Processed videos summary
    status_counts = defaultdict(int)
    recent_synced = []
    for vid_id, vid_info in processed.items():
        status_counts[vid_info.get("status", "unknown")] += 1
        if vid_info.get("status") == "complete":
            recent_synced.append({
                "video_id": vid_id,
                "note": vid_info.get("note", ""),
                "date": vid_info.get("date", ""),
            })
    recent_synced.sort(key=lambda x: x["date"], reverse=True)

    # Pending transcripts (videos that were found but captions weren't ready)
    pending_transcripts = []
    for vid_id, vid_info in processed.items():
        if vid_info.get("status") == "no_transcript":
            pending_transcripts.append({
                "video_id": vid_id,
                "note": vid_info.get("note", ""),
                "date": vid_info.get("date", ""),
            })
    pending_transcripts.sort(key=lambda x: x["date"], reverse=True)

    # Notes without video link (recent only, last 30 days)
    cutoff = date.today() - timedelta(days=30)
    notes_no_video = []
    for filepath, note_date in all_notes:
        if note_date < cutoff:
            continue
        try:
            analysis = analyze_note(filepath)
            if not analysis["has_video_link"]:
                notes_no_video.append({
                    "date": str(note_date),
                    "filename": os.path.basename(filepath),
                })
        except Exception:
            pass
    notes_no_video.sort(key=lambda x: x["date"], reverse=True)

    # Missing diary entries: days with no note at all (since July 2016)
    diary_start = date(2016, 7, 6)
    note_dates = {d for _, d in all_notes}
    missing_entries = []
    day = diary_start
    today = date.today()
    while day <= today:
        if day not in note_dates:
            missing_entries.append({"date": str(day)})
        day += timedelta(days=1)
    missing_entries.sort(key=lambda x: x["date"], reverse=True)

    # Days with video on YouTube but no diary note
    video_no_note = []
    for vid_id, vid_info in processed.items():
        if "date" in vid_info:
            vid_date_str = vid_info["date"]
            try:
                vid_date = date.fromisoformat(vid_date_str)
            except (ValueError, TypeError):
                continue
            if vid_date not in note_dates:
                video_no_note.append({
                    "date": vid_date_str,
                    "video_id": vid_id,
                    "title": vid_info.get("note", vid_id),
                })
    video_no_note.sort(key=lambda x: x["date"], reverse=True)

    # IP block cooldown status
    cooldown_until = None
    try:
        if os.path.exists(STATE_PATH):
            blocked_until = state.get("blocked_until")
            if blocked_until:
                from datetime import datetime
                until = datetime.fromisoformat(blocked_until)
                if datetime.now() < until:
                    remaining = until - datetime.now()
                    hours = remaining.total_seconds() / 3600
                    cooldown_until = {
                        "until": blocked_until,
                        "hours_remaining": round(hours, 1),
                    }
    except (ValueError, TypeError):
        pass

    # Last sync time from log
    log_lines = get_log_lines(200)
    last_sync_time = None
    last_sync_summary = None
    for line in reversed(log_lines):
        if "=== Diary YouTube Sync complete ===" in line:
            last_sync_time = line[:23]  # timestamp portion
        if "Video sync:" in line:
            last_sync_summary = line.split("Video sync:")[1].strip()
            break

    # "Dear Diary" files we couldn't parse a date from
    unparsed = [
        {
            "filename": os.path.basename(fp),
            "path": os.path.relpath(fp, vault_path),
        }
        for fp in unparsed_notes
    ]

    # Count issues
    total_issues = (
        len(missing_uploads)
        + len(pending_transcripts)
        + len(missing_entries)
        + len(video_no_note)
        + len(wrong_location)
        + len(unparsed)
    )

    return {
        "total_notes": len(all_notes),
        "total_processed": status_counts.get("complete", 0),
        "total_issues": total_issues,
        "pending_transcripts": pending_transcripts,
        "missing_uploads": missing_uploads,
        "missing_upload_count": len(missing_uploads),
        "missing_entries": missing_entries,
        "missing_entry_count": len(missing_entries),
        "video_no_note": video_no_note,
        "wrong_location": wrong_location,
        "wrong_location_count": len(wrong_location),
        "unparsed_notes": unparsed,
        "notes_no_video": notes_no_video,
        "recent_synced": recent_synced[:20],
        "last_sync_time": last_sync_time,
        "last_sync_summary": last_sync_summary,
        "cooldown": cooldown_until,
        "config": {
            "vault_path": config.get("vault_path", ""),
            "lookback_days": config.get("lookback_days", 30),
        },
    }


@app.route("/")
def index():
    data = get_dashboard_data()
    return render_template("dashboard.html", **data)


@app.route("/api/sync", methods=["POST"])
def trigger_sync():
    """Trigger a sync run in the background."""
    global _sync_process, _sync_output

    with _sync_lock:
        if _sync_process and _sync_process.poll() is None:
            return jsonify({"status": "already_running"})

        _sync_output.clear()
        body = request.get_json(silent=True) or {}
        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "sync.py")]
        if body.get("force"):
            cmd.append("--force")

        _sync_process = subprocess.Popen(
            cmd,
            cwd=SCRIPT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Read output in background thread
        def _reader():
            for line in _sync_process.stdout:
                _sync_output.append(line.rstrip())
            _sync_process.wait()

        threading.Thread(target=_reader, daemon=True).start()

    return jsonify({"status": "started"})


@app.route("/api/sync/status")
def sync_status():
    """Check the status of a running sync."""
    global _sync_process
    if _sync_process is None:
        return jsonify({"status": "idle", "output": []})

    is_running = _sync_process.poll() is None
    return jsonify({
        "status": "running" if is_running else "finished",
        "exit_code": _sync_process.returncode,
        "output": list(_sync_output),
    })


@app.route("/log")
def view_log():
    """Return recent log lines as JSON."""
    n = request.args.get("n", 100, type=int)
    return jsonify({"lines": get_log_lines(n)})


if __name__ == "__main__":
    print("Dashboard: http://localhost:5050")
    app.run(host="127.0.0.1", port=5050, debug=False)
