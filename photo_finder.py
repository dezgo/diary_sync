"""Locate photos in iCloud-synced folders for diary embedding.

Two photos per diary date, both sourced from "drop folders" that the phone shares
into via Share-Sheet Shortcuts:
  - Selfie: picked up from the selfie drop folder
  - Photo of the day: picked up from the POTD drop folder (with the iCloud
    shared album as a fallback for older entries)

A file in a drop folder is matched to its diary day by a leading yyyy-MM-dd in
the filename (set by the Shortcut), falling back to EXIF capture date mapped
via the day-cutoff rule.

HEIC originals are converted to JPG for embedding (Obsidian-friendly).
Originals are not modified.
"""

import errno
import logging
import re
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ExifTags

log = logging.getLogger(__name__)

# The sync stamps the photo-of-day at 12:00:00 of the diary date and the selfie
# at its real capture time, so a "Pasted image …120000" is the script POTD and
# any other pasted image is treated as the selfie (or a manual paste we leave
# alone). This is the single source of truth for selfie/POTD coverage.
POTD_FILENAME_RE = re.compile(r"^Pasted image \d{8}120000\..+$", re.IGNORECASE)


def classify_embedded_photos(embedded_filenames) -> dict:
    """Classify a note's already-embedded photos into selfie/POTD coverage.

    Mirrors the photo-coverage model in status_report.classify_note (minus the
    shared-album cross-check): the noon-stamp marks the script POTD; one
    non-stamped photo counts as the selfie; two or more count as both covered.
    Returns {"has_selfie": bool, "has_potd": bool, "photo_count": int}.
    """
    pasted = [f for f in embedded_filenames if f.startswith("Pasted image ")]
    count = len(pasted)
    has_script_potd = any(POTD_FILENAME_RE.match(f) for f in pasted)
    if has_script_potd:
        return {"has_selfie": count >= 2, "has_potd": True, "photo_count": count}
    if count == 0:
        return {"has_selfie": False, "has_potd": False, "photo_count": 0}
    if count == 1:
        return {"has_selfie": True, "has_potd": False, "photo_count": 1}
    return {"has_selfie": True, "has_potd": True, "photo_count": count}

# Register HEIC opener with Pillow if available
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIC_OK = True
except ImportError:
    _HEIC_OK = False
    log.warning("pillow-heif not installed; HEIC photos will be skipped")


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
_EXIF_DATETIME_TAG = next(
    (tag for tag, name in ExifTags.TAGS.items() if name == "DateTimeOriginal"),
    36867,  # standard tag id
)


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def _read_exif(path: Path) -> dict | None:
    """Return the merged EXIF dict (including IFD) or None on failure."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            # The LensModel often lives in the EXIF IFD (sub-dict)
            merged = dict(exif)
            try:
                ifd = exif.get_ifd(0x8769)  # ExifIFDPointer
                merged.update(ifd)
            except Exception:
                pass
            return merged
    except Exception as e:
        log.debug(f"Could not read EXIF from {path.name}: {e}")
        return None


def _read_capture_time(path: Path) -> datetime | None:
    """Read EXIF DateTimeOriginal. Falls back to file mtime if unavailable."""
    exif = _read_exif(path)
    if exif:
        raw = exif.get(_EXIF_DATETIME_TAG)
        if raw:
            try:
                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def selfie_diary_date(capture: datetime, day_cutoff_hour: int = 5) -> date:
    """Map a selfie's capture time to the diary day it belongs to.

    The diary is recorded at night, sometimes spilling past midnight, and never
    in the early morning. So a photo captured before day_cutoff_hour is treated
    as belonging to the *previous* day (e.g. a selfie at 00:30 on the 17th is
    for the 16th's entry).
    """
    if capture.hour < day_cutoff_hour:
        return capture.date() - timedelta(days=1)
    return capture.date()


_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _date_from_filename(stem: str) -> date | None:
    """Parse a leading yyyy-MM-dd from a filename stem, else None."""
    m = _DATE_PREFIX_RE.match(stem)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def find_potd_in_drop_dir(
    diary_date: date,
    drop_dir: Path,
    day_cutoff_hour: int = 5,
) -> Path | None:
    """Find a photo-of-day for diary_date in a 'drop folder' — a reliably-synced
    folder (e.g. Google Drive) you share the day's photo into from your phone.

    This sidesteps iCloud Shared Albums entirely: the shared file is a brand-new
    file in a folder that actually syncs, rather than a metadata edit on an
    existing photo (which iCloud for Windows won't propagate).

    A file is matched to the diary day by, in order:
      1. a leading yyyy-MM-dd in the filename (set by the share Shortcut), or
      2. the photo's EXIF capture time mapped via the day-cutoff rule (so a plain
         "Save to Files" with the original name still works).
    If several match, the most recently modified wins.
    """
    if not drop_dir.is_dir():
        return None
    matches: list[tuple[float, Path]] = []
    for entry in drop_dir.iterdir():
        if not entry.is_file() or not _is_image(entry):
            continue
        d = _date_from_filename(entry.stem)
        if d is None:
            cap = _read_capture_time(entry)
            d = selfie_diary_date(cap, day_cutoff_hour) if cap else None
        if d == diary_date:
            try:
                matches.append((entry.stat().st_mtime, entry))
            except OSError:
                continue
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    chosen = matches[-1][1]
    log.info(f"Photo-of-day from drop folder: {chosen.name} for {diary_date}")
    return chosen


def resolve_drop_selfie_date(
    entry: Path,
    day_cutoff_hour: int,
    is_day_covered,
) -> date | None:
    """Resolve which diary day a drop-folder selfie file belongs to.

    Base date is the filename's leading yyyy-MM-dd, falling back to the EXIF
    capture date. On top of that, the catch-up rule: if EXIF capture time is
    before day_cutoff_hour AND the previous day's note doesn't already have a
    selfie, the file shifts to that previous day. (A morning selfie is treated
    as a catch-up for yesterday's missed diary — unless yesterday is already
    covered, in which case it's today's selfie taken unusually early.)

    is_day_covered is a callable taking a date and returning True if that day's
    diary note already has a selfie embedded. Returns None if no date can be
    determined at all.
    """
    cap = _read_capture_time(entry)
    base = _date_from_filename(entry.stem) or (cap.date() if cap else None)
    if base is None:
        return None
    if cap and cap.hour < day_cutoff_hour:
        prev = base - timedelta(days=1)
        if not is_day_covered(prev):
            return prev
    return base


def find_selfie_in_drop_dir(
    diary_date: date,
    drop_dir: Path,
    day_cutoff_hour: int,
    is_day_covered,
) -> Path | None:
    """Find a selfie for diary_date in the selfie drop folder.

    Mirrors find_potd_in_drop_dir: a Share-Sheet Shortcut on the phone drops
    the selfie into a synced iCloud Drive folder as a brand-new file, which
    sidesteps iCloud-for-Windows' refusal to propagate metadata-only edits on
    existing library photos. This replaces the old EXIF lens-model + upload-time
    matcher, which had to guess which photo was the selfie.

    Each file's date is resolved via resolve_drop_selfie_date (filename +
    catch-up rule). If several files resolve to diary_date, the most recently
    modified wins.
    """
    if not drop_dir.is_dir():
        return None
    matches: list[tuple[float, Path]] = []
    for entry in drop_dir.iterdir():
        if not entry.is_file() or not _is_image(entry):
            continue
        d = resolve_drop_selfie_date(entry, day_cutoff_hour, is_day_covered)
        if d == diary_date:
            try:
                matches.append((entry.stat().st_mtime, entry))
            except OSError:
                continue
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    chosen = matches[-1][1]
    log.info(f"Selfie from drop folder: {chosen.name} for {diary_date}")
    return chosen


def find_photo_of_day(
    diary_date: date,
    shared_album_root: Path,
    album_name_template: str,
    icloud_photos_dir: Path,
) -> Path | None:
    """Find the photo of the day for diary_date.

    Strategy:
      1. Locate shared album: shared_album_root / album_name_template.format(year=diary_date.year)
      2. Find files in that shared album dated to diary_date (by capture time, falling back to mtime)
      3. Resolve to the full-res original in icloud_photos_dir, matching by filename first, then by capture time
    """
    album_dir = shared_album_root / album_name_template.format(year=diary_date.year)
    if not album_dir.is_dir():
        log.info(f"Shared album not found: {album_dir}")
        return None

    target_day_start = datetime.combine(diary_date, datetime.min.time())
    target_day_end = target_day_start + timedelta(days=1)

    shared_match: Path | None = None
    shared_capture: datetime | None = None
    for entry in album_dir.iterdir():
        if not entry.is_file() or not _is_image(entry):
            continue
        capture = _read_capture_time(entry)
        if not capture:
            continue
        if target_day_start <= capture < target_day_end:
            shared_match = entry
            shared_capture = capture
            break

    if not shared_match:
        log.info(f"No photo-of-day found in shared album for {diary_date}")
        return None

    # Look up the full-res original. Try filename match first.
    if icloud_photos_dir.is_dir():
        same_name = icloud_photos_dir / shared_match.name
        if same_name.is_file():
            log.info(f"Photo-of-day: {shared_match.name} (full-res by filename)")
            return same_name

        # Fall back: match by EXIF capture time within ±1 second
        for entry in icloud_photos_dir.iterdir():
            if not entry.is_file() or not _is_image(entry):
                continue
            capture = _read_capture_time(entry)
            if capture and shared_capture and abs(capture - shared_capture) < timedelta(seconds=2):
                log.info(f"Photo-of-day: {entry.name} (full-res by capture time)")
                return entry

    # Nothing matched in flat folder — use the shared (downscaled) copy.
    # This is the normal case when iCloud Photos full-library sync is off.
    log.info(
        f"Photo-of-day: using downscaled shared copy ({shared_match.name}); "
        "full-res original not found in iCloud Photos folder"
    )
    return shared_match


# iCloud for Windows keeps a freshly-synced drop file as an "online-only"
# placeholder (a ReparsePoint): it reports its real size but holds no local
# bytes, so the first read returns OSError(EINVAL / [Errno 22]) until iCloud
# hydrates it. Accessing the data is what triggers that download, so we poke the
# file and retry with backoff to give the bytes time to land before we copy.
_HYDRATE_RETRIES = 6
_HYDRATE_BACKOFF = 2.0  # seconds, grows linearly per attempt (2,4,…,12 ≈ 42s)


def _ensure_hydrated(src: Path) -> bool:
    """Force a cloud placeholder to download before we read/convert/copy it.

    Returns True once the file's bytes are readable, False if it never
    hydrated. A no-op for normal local files — the first read succeeds at once.
    """
    last_err: OSError | None = None
    for attempt in range(_HYDRATE_RETRIES):
        try:
            with open(src, "rb") as f:
                f.read(1)  # touching the data triggers iCloud's on-demand pull
            return True
        except OSError as e:
            last_err = e
            if e.errno != errno.EINVAL:
                break  # not the placeholder symptom — a real error, fail fast
            time.sleep(_HYDRATE_BACKOFF * (attempt + 1))
    log.warning(f"Could not hydrate cloud file {src.name}: {last_err}")
    return False


def _is_complete(dest: Path) -> bool:
    """True only if dest exists with real bytes. A 0-byte file is the remnant
    of a failed copy (copyfile creates the dest before reading the source, so a
    read error leaves an empty file behind) — it must be overwritten, never
    reused, or the note ends up with a broken embed link.
    """
    try:
        return dest.is_file() and dest.stat().st_size > 0
    except OSError:
        return False


def prepare_for_embed(
    src: Path,
    vault_root: Path,
    attachments_subdir: str,
    when: datetime,
) -> str | None:
    """Copy/convert src into vault attachments folder.

    Returns just the filename (for Obsidian wikilink) or None on failure.
    HEIC sources are converted to JPG. Other formats are copied as-is.
    """
    dest_dir = vault_root / attachments_subdir / str(when.year)
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = when.strftime("%Y%m%d%H%M%S")
    src_ext = src.suffix.lower()

    if src_ext in {".heic", ".heif"}:
        if not _HEIC_OK:
            log.error(f"Cannot embed HEIC without pillow-heif: {src.name}")
            return None
        dest_name = f"Pasted image {stamp}.jpg"
        dest = dest_dir / dest_name
        if _is_complete(dest):
            log.debug(f"Embed target already exists, reusing: {dest_name}")
            return dest_name
        if not _ensure_hydrated(src):
            return None
        try:
            with Image.open(src) as img:
                rgb = img.convert("RGB")
                rgb.save(dest, format="JPEG", quality=92, optimize=True)
            log.info(f"Converted HEIC -> JPG: {dest_name}")
            return dest_name
        except Exception as e:
            dest.unlink(missing_ok=True)  # don't leave a partial file to poison reruns
            log.error(f"Failed to convert {src.name}: {e}")
            return None

    # JPG/PNG/etc — copy as-is, normalising extension to lowercase
    ext = src_ext if src_ext != ".jpeg" else ".jpg"
    dest_name = f"Pasted image {stamp}{ext}"
    dest = dest_dir / dest_name
    if _is_complete(dest):
        log.debug(f"Embed target already exists, reusing: {dest_name}")
        return dest_name
    if not _ensure_hydrated(src):
        return None
    try:
        shutil.copy2(src, dest)
        if dest.stat().st_size != src.stat().st_size:
            raise OSError(
                f"size mismatch after copy ({dest.stat().st_size} != {src.stat().st_size})"
            )
        log.info(f"Copied photo: {dest_name}")
        return dest_name
    except Exception as e:
        dest.unlink(missing_ok=True)  # don't leave a partial file to poison reruns
        log.error(f"Failed to copy {src.name}: {e}")
        return None
