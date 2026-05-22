"""Locate photos in iCloud-synced folders for diary embedding.

Two photos per diary date:
  - Selfie: closest EXIF capture to YouTube upload time, within ±window_minutes
  - Photo of the day: chosen by shared-album membership for the diary date,
    full-res original looked up in the flat Photos folder

HEIC originals are converted to JPG for embedding (Obsidian-friendly).
Originals in the Photos library are not modified.
"""

import logging
import re
import shutil
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
_EXIF_LENS_MODEL_TAG = next(
    (tag for tag, name in ExifTags.TAGS.items() if name == "LensModel"),
    42036,  # standard tag id
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


def _is_front_camera(path: Path) -> bool:
    """True if EXIF identifies the photo as taken with an iPhone front camera.

    Matches both the older literal "front camera" lens model and the
    TrueDepth-era format (e.g. "iPhone 15 Pro Max front TrueDepth camera
    2.69mm f/1.9"), where "front" and "camera" are not adjacent.
    """
    exif = _read_exif(path)
    if not exif:
        return False
    lens = exif.get(_EXIF_LENS_MODEL_TAG, "")
    if not isinstance(lens, str):
        return False
    lens = lens.lower()
    return "front" in lens and "camera" in lens


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


def find_selfie(
    upload_time: datetime,
    icloud_photos_dir: Path,
    window_minutes: int = 60,
    require_front_camera: bool = True,
    diary_date: date | None = None,
    day_cutoff_hour: int = 5,
) -> Path | None:
    """Return the front-camera photo in icloud_photos_dir captured closest to
    upload_time within ±window_minutes. Returns None if no candidate qualifies.

    With require_front_camera=True (default), only photos whose EXIF LensModel
    contains "Front Camera" are considered — this avoids matching a back-camera
    or someone else's photo taken at the same moment.

    If diary_date is given, a candidate only qualifies when its capture time maps
    to that diary day (see selfie_diary_date). This prevents a late-night photo
    being pulled onto the wrong entry when, e.g., two days' videos are uploaded
    back-to-back near midnight.

    Matching is two-stage when diary_date is given: first the photo closest to
    upload_time within ±window_minutes (the common case, video uploaded near
    recording); if none qualifies, fall back to the latest front-camera photo
    belonging to that diary day. The fallback catches entries uploaded long
    after recording — e.g. a 02:37 selfie for an entry not uploaded until the
    following night — which the upload-time window can't reach.

    Optimised by reading EXIF only on files whose mtime is within ±1 day of
    either upload_time or the target diary_date.
    """
    if not icloud_photos_dir.is_dir():
        log.info(f"iCloud photos dir not found: {icloud_photos_dir}")
        return None

    # Make upload_time naive for comparison (EXIF lacks timezone)
    if upload_time.tzinfo is not None:
        upload_time = upload_time.replace(tzinfo=None)

    window = timedelta(minutes=window_minutes)
    rough_window = timedelta(days=1)

    window_candidates: list[tuple[timedelta, Path]] = []
    day_candidates: list[tuple[datetime, Path]] = []
    for entry in icloud_photos_dir.iterdir():
        if not entry.is_file() or not _is_image(entry):
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
        except OSError:
            continue
        near_upload = abs(mtime - upload_time) <= rough_window
        near_diary = diary_date is not None and abs((mtime.date() - diary_date).days) <= 1
        if not (near_upload or near_diary):
            continue

        capture = _read_capture_time(entry)
        if not capture:
            continue
        if require_front_camera and not _is_front_camera(entry):
            continue

        on_diary_day = diary_date is None or selfie_diary_date(capture, day_cutoff_hour) == diary_date

        delta = abs(capture - upload_time)
        if delta <= window and on_diary_day:
            window_candidates.append((delta, entry))
        if diary_date is not None and on_diary_day:
            day_candidates.append((capture, entry))

    if window_candidates:
        window_candidates.sort(key=lambda x: x[0])
        closest = window_candidates[0][1]
        log.info(f"Selfie match: {closest.name} (delta {window_candidates[0][0]})")
        return closest

    if day_candidates:
        day_candidates.sort(key=lambda x: x[0])  # latest capture last
        chosen = day_candidates[-1][1]
        log.info(f"Selfie match (day fallback for {diary_date}): {chosen.name} "
                 f"captured {day_candidates[-1][0]}")
        return chosen

    log.info(
        f"No selfie found within ±{window_minutes}min of {upload_time}"
        f"{f' or on {diary_date}' if diary_date else ''}"
        f"{' (front-camera only)' if require_front_camera else ''}"
    )
    return None


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
        if dest.exists():
            log.debug(f"Embed target already exists, reusing: {dest_name}")
            return dest_name
        try:
            with Image.open(src) as img:
                rgb = img.convert("RGB")
                rgb.save(dest, format="JPEG", quality=92, optimize=True)
            log.info(f"Converted HEIC -> JPG: {dest_name}")
            return dest_name
        except Exception as e:
            log.error(f"Failed to convert {src.name}: {e}")
            return None

    # JPG/PNG/etc — copy as-is, normalising extension to lowercase
    ext = src_ext if src_ext != ".jpeg" else ".jpg"
    dest_name = f"Pasted image {stamp}{ext}"
    dest = dest_dir / dest_name
    if dest.exists():
        log.debug(f"Embed target already exists, reusing: {dest_name}")
        return dest_name
    try:
        shutil.copy2(src, dest)
        log.info(f"Copied photo: {dest_name}")
        return dest_name
    except Exception as e:
        log.error(f"Failed to copy {src.name}: {e}")
        return None
