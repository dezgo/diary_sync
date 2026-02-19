"""Analyze and modify Obsidian diary notes."""

import os
import re
import shutil
import logging
from datetime import date

log = logging.getLogger(__name__)

VIDEO_LINK_RE = re.compile(r"\[Video\]\((https?://[^\)]+)\)")
PLACEHOLDER_RE = re.compile(r"\[Video\]\(https?://a\)")
MEDIA_EMBED_RE = re.compile(r"!\[\[.*?\]\]")
DIARY_TAG_RE = re.compile(r"Diary-(\d{4})")
SUMMARY_HEADING_RE = re.compile(r"^#{1,3}\s+Summary\s*$", re.IGNORECASE)


def analyze_note(filepath: str) -> dict:
    """Analyze a diary note to determine what processing it needs.

    Returns a dict describing the current state of the note.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    result = {
        "has_video_link": False,
        "has_placeholder": False,
        "has_blockquote_transcript": False,
        "has_summary": False,
        "video_url": None,
        "video_line_index": None,
        "video_in_blockquote": False,
        "content": content,
        "lines": lines,
    }

    for i, line in enumerate(lines):
        if SUMMARY_HEADING_RE.match(line.strip()):
            result["has_summary"] = True
        stripped = line.strip()

        # Check for [Video](...) link
        video_match = VIDEO_LINK_RE.search(stripped)
        if not video_match:
            continue

        result["has_video_link"] = True
        result["video_line_index"] = i
        result["video_url"] = video_match.group(1)
        result["video_in_blockquote"] = stripped.startswith(">")

        if PLACEHOLDER_RE.search(stripped):
            result["has_placeholder"] = True

        # Check if there's transcript text in blockquote lines after the video link.
        # Look for non-empty blockquote lines (not just ">") within the next lines.
        for j in range(i + 1, min(i + 10, len(lines))):
            s = lines[j].strip()
            if s.startswith(">"):
                text_after = s[1:].strip()
                if text_after and text_after != ">":
                    result["has_blockquote_transcript"] = True
                    break
            elif s == "":
                continue
            else:
                # Hit non-blockquote, non-blank content — no transcript in blockquote
                break

        break  # Only process the first [Video] link

    return result


def update_note(
    filepath: str,
    video_url: str,
    transcript_text: str,
    analysis: dict,
    backup_dir: str,
    summary_text: str | None = None,
) -> bool:
    """Update a diary note with video link and/or transcript.

    Scenarios:
    1. Placeholder [Video](https://a) with existing blockquote text
       → Replace placeholder URL with real URL, leave existing text alone
    2. Placeholder [Video](https://a) with NO existing blockquote text
       → Replace with blockquote video link + transcript
    3. Real [Video](url) already in blockquote with transcript → skip (return False)
    4. No [Video] line at all → insert blockquote video+transcript after media embeds

    If summary_text is provided and no summary section exists yet, a ## Summary
    section is inserted above the transcript blockquote.

    Returns True if the note was modified, False if skipped.
    """
    lines = analysis["lines"]
    idx = analysis["video_line_index"]

    # Scenario 3: already has real video link + transcript — nothing to do
    if (
        analysis["has_video_link"]
        and not analysis["has_placeholder"]
        and analysis["has_blockquote_transcript"]
    ):
        log.debug(f"Note already has video link + transcript, skipping")
        return False

    # Back up before modifying
    _backup_note(filepath, backup_dir)

    if analysis["has_placeholder"]:
        if analysis["has_blockquote_transcript"] or _has_nearby_blockquote(lines, idx):
            # Scenario 1: placeholder with existing content — just fix the URL
            old_line = lines[idx]
            new_line = PLACEHOLDER_RE.sub(f"[Video]({video_url})", old_line)
            # If the video wasn't in a blockquote, put it in one
            if not old_line.strip().startswith(">"):
                new_line = f"> {new_line.strip()}"
            lines[idx] = new_line
            log.info(f"Replaced placeholder URL with {video_url}")
        else:
            # Scenario 2: placeholder with no content — replace with full block
            _replace_line_with_blockquote(lines, idx, video_url, transcript_text)
            log.info(f"Replaced placeholder with video link + transcript")
    elif not analysis["has_video_link"]:
        # Scenario 4: no video link — insert after media embeds
        insert_idx = _find_insertion_point(lines)
        blockquote = _build_blockquote(video_url, transcript_text)
        # Insert blank line + blockquote
        lines.insert(insert_idx + 1, "")
        lines.insert(insert_idx + 2, blockquote)
        log.info(f"Inserted video link + transcript after media embeds")
    else:
        # Has real video link but no transcript — add transcript after video line
        if analysis["video_in_blockquote"]:
            # Insert transcript lines into existing blockquote
            transcript_lines = _format_as_blockquote_lines(transcript_text)
            # Insert after the video link line (and any blank > line)
            insert_after = idx
            for j in range(idx + 1, min(idx + 3, len(lines))):
                if lines[j].strip() in ("", ">"):
                    insert_after = j
                else:
                    break
            for k, tline in enumerate(transcript_lines):
                lines.insert(insert_after + 1 + k, tline)
            log.info(f"Added transcript to existing blockquote")
        else:
            # Standalone video link — wrap in blockquote with transcript
            _replace_line_with_blockquote(
                lines, idx, analysis["video_url"], transcript_text
            )
            log.info(f"Wrapped standalone video link in blockquote with transcript")

    # Insert summary section above the transcript blockquote if provided
    if summary_text and not analysis["has_summary"]:
        _insert_summary(lines, summary_text)

    new_content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def fix_tag_if_needed(filepath: str, expected_year: int, backup_dir: str) -> bool:
    """Check and fix the Diary-YYYY tag in a note's frontmatter.

    Returns True if the tag was fixed, False if it was already correct.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    expected_tag = f"Diary-{expected_year}"

    # Find existing Diary-YYYY tag
    tag_match = DIARY_TAG_RE.search(content)
    if tag_match:
        existing_tag = tag_match.group(0)
        if existing_tag == expected_tag:
            return False  # Already correct

        # Fix the tag
        _backup_note(filepath, backup_dir)
        new_content = content.replace(existing_tag, expected_tag, 1)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        log.info(
            f"Fixed tag {existing_tag} → {expected_tag} in {os.path.basename(filepath)}"
        )
        return True

    # No Diary- tag found at all — add one to frontmatter
    # The frontmatter format is: ---\n\ntags: \n\n  - Diary-YYYY\n\n---
    if "tags:" in content:
        # tags: section exists but no Diary- tag — add it
        _backup_note(filepath, backup_dir)
        new_content = content.replace("tags: \n", f"tags: \n\n  - {expected_tag}\n", 1)
        if new_content == content:
            # Try without the blank line variant
            new_content = content.replace("tags:\n", f"tags:\n  - {expected_tag}\n", 1)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        log.info(f"Added missing tag {expected_tag} to {os.path.basename(filepath)}")
        return True

    log.warning(f"No tags section found in {os.path.basename(filepath)}, skipping tag fix")
    return False


def _insert_summary(lines: list[str], summary_text: str):
    """Insert a ## Summary section above the first blockquote line."""
    # Find the first blockquote line (the video link / transcript)
    bq_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith(">"):
            bq_idx = i
            break

    if bq_idx is None:
        # No blockquote found — insert at the end
        bq_idx = len(lines)

    summary_block = ["## Summary", "", summary_text, ""]
    for k, sline in enumerate(summary_block):
        lines.insert(bq_idx + k, sline)


def _has_nearby_blockquote(lines: list[str], from_idx: int) -> bool:
    """Check if there's blockquote content near a given line index."""
    for j in range(from_idx + 1, min(from_idx + 6, len(lines))):
        stripped = lines[j].strip()
        if stripped.startswith(">") and len(stripped) > 1:
            text = stripped[1:].strip()
            if text and text != ">":
                return True
    return False


def _build_blockquote(video_url: str, transcript_text: str) -> str:
    """Build a complete blockquote block with video link and transcript."""
    bq_lines = [f"> [Video]({video_url})", "> "]
    for para in transcript_text.split("\n\n"):
        para = para.strip()
        if para:
            bq_lines.append(f"> {para}")
            bq_lines.append(">")
    # Remove trailing empty blockquote line
    if bq_lines and bq_lines[-1] == ">":
        bq_lines.pop()
    return "\n".join(bq_lines)


def _format_as_blockquote_lines(transcript_text: str) -> list[str]:
    """Format transcript text as blockquote lines for insertion."""
    result = []
    for para in transcript_text.split("\n\n"):
        para = para.strip()
        if para:
            result.append(f"> {para}")
            result.append(">")
    if result and result[-1] == ">":
        result.pop()
    return result


def _replace_line_with_blockquote(
    lines: list[str], idx: int, video_url: str, transcript_text: str
):
    """Replace a line (typically a placeholder) with a full blockquote block."""
    blockquote = _build_blockquote(video_url, transcript_text)
    # Ensure blank line before blockquote
    if idx > 0 and lines[idx - 1].strip() != "":
        lines[idx] = "\n" + blockquote
    else:
        lines[idx] = blockquote


def _find_insertion_point(lines: list[str]) -> int:
    """Find the line index after which to insert the video blockquote.

    Returns the index of the last media embed line, or the end of frontmatter.
    """
    in_frontmatter = False
    frontmatter_end = -1
    last_media_line = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---":
            if not in_frontmatter:
                in_frontmatter = True
            else:
                in_frontmatter = False
                frontmatter_end = i
            continue
        if in_frontmatter:
            continue
        if MEDIA_EMBED_RE.search(stripped):
            last_media_line = i

    if last_media_line > frontmatter_end:
        return last_media_line
    return frontmatter_end


def _backup_note(filepath: str, backup_dir: str):
    """Create a backup copy of a note before modifying it."""
    os.makedirs(backup_dir, exist_ok=True)
    filename = os.path.basename(filepath)
    backup_path = os.path.join(backup_dir, filename)
    # Don't overwrite an existing backup (preserve the original)
    if not os.path.exists(backup_path):
        shutil.copy2(filepath, backup_path)
        log.debug(f"Backed up {filename}")
