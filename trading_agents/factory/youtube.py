"""YouTube ingestion helpers for the Strategy Factory.

Wraps yt-dlp for metadata, auto-subtitle transcript, and (optional) video
download. Every function degrades gracefully when yt-dlp / network is missing so
the pipeline can continue (NotebookLM + Vision still work from what's available).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("factory.youtube")

_YT_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|live/|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_url(text: str) -> Optional[str]:
    """Return the first YouTube URL in a text blob, or None."""
    m = re.search(r"https?://[^\s]*(?:youtube\.com|youtu\.be)[^\s]*", text or "")
    return m.group(0) if m else None


def video_id(url: str) -> str:
    m = _YT_RE.search(url or "")
    return m.group(1) if m else ""


def _ytdlp() -> Optional[str]:
    return shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")


def fetch_metadata(url: str) -> dict:
    """Title/channel/description/duration via `yt-dlp --dump-json`. Returns a
    dict with best-effort fields; never raises."""
    vid = video_id(url)
    out = {"video_id": vid, "title": "", "channel": "", "description": "",
           "duration_s": 0}
    exe = _ytdlp()
    if not exe:
        log.warning("yt-dlp not installed — metadata unavailable")
        return out
    try:
        r = subprocess.run(
            [exe, "--dump-json", "--no-playlist", "--skip-download", url],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode != 0:
            log.warning("yt-dlp metadata rc=%s: %s", r.returncode, r.stderr[:200])
            return out
        j = json.loads(r.stdout)
        out.update({
            "video_id": j.get("id", vid),
            "title": j.get("title", ""),
            "channel": j.get("channel") or j.get("uploader", ""),
            "description": (j.get("description") or "")[:6000],
            "duration_s": int(j.get("duration") or 0),
        })
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp metadata failed: %s", e)
    return out


def fetch_transcript(url: str, out_dir: Path) -> Optional[str]:
    """Auto-subtitle transcript via yt-dlp (no Whisper needed). Returns plain
    text or None. Cheap first-pass before falling back to Whisper on the video.
    """
    exe = _ytdlp()
    if not exe:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / "subs"
    try:
        subprocess.run(
            [exe, "--skip-download", "--write-auto-sub", "--write-sub",
             "--sub-lang", "en", "--sub-format", "vtt",
             "--no-playlist", "-o", str(stem) + ".%(ext)s", url],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp subtitle fetch failed: %s", e)
        return None
    vtts = list(out_dir.glob("subs*.vtt"))
    if not vtts:
        return None
    return _vtt_to_text(vtts[0])


def _vtt_to_text(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if (not s or s == "WEBVTT" or "-->" in s or s.isdigit()
                or s.startswith(("Kind:", "Language:", "NOTE"))):
            continue
        s = re.sub(r"<[^>]+>", "", s)  # strip inline timing tags
        if s and (not lines or lines[-1] != s):
            lines.append(s)
    return "\n".join(lines)


def download_video(url: str, out_dir: Path, max_height: int = 480) -> Optional[Path]:
    """Download a capped-resolution mp4 for Whisper+Vision. Returns the path or
    None. Capped to keep size/time bounded."""
    exe = _ytdlp()
    if not exe:
        log.warning("yt-dlp not installed — cannot download video")
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "video.mp4"
    try:
        r = subprocess.run(
            [exe, "-f", f"best[height<={max_height}][ext=mp4]/best[height<={max_height}]/best",
             "--no-playlist", "--merge-output-format", "mp4",
             "-o", str(target), url],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            log.warning("yt-dlp download rc=%s: %s", r.returncode, r.stderr[:200])
            return None
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp download failed: %s", e)
        return None
    return target if target.exists() else None
