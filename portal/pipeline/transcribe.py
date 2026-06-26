"""Stage 2 — TRANSCRIBER AGENT.

Walks every recording under mcc/, transcribes new ones with whisper.cpp,
and stores one JSON transcript per call (with filename metadata) in
data/transcripts/. Incremental: skips calls already transcribed, so the
daily run only processes new audio.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

WHISPER_BIN = shutil.which("whisper-cli") or "whisper-cli"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return 0.0


def transcribe_one(mp3_path, workdir):
    """Return (text, segments) for a single mp3."""
    wav = os.path.join(workdir, "a.wav")
    subprocess.run(
        [FFMPEG, "-y", "-i", mp3_path, "-ar", "16000", "-ac", "1", wav],
        capture_output=True, timeout=120,
    )
    out_stem = os.path.join(workdir, "out")
    subprocess.run(
        [WHISPER_BIN, "-m", C.WHISPER_MODEL, "-f", wav,
         "-oj", "-of", out_stem],
        capture_output=True, timeout=300,
    )
    data = C.load_json(out_stem + ".json", {}) or {}
    segments = []
    text_parts = []
    for seg in data.get("transcription", []):
        t = (seg.get("text") or "").strip()
        if not t:
            continue
        offs = seg.get("offsets", {})
        segments.append({
            "start": round(offs.get("from", 0) / 1000.0, 2),
            "end": round(offs.get("to", 0) / 1000.0, 2),
            "text": t,
        })
        text_parts.append(t)
    return " ".join(text_parts).strip(), segments


def run(limit=None, force=False, progress_every=25):
    recs = list(C.iter_recordings())
    total = len(recs)
    print(f"[transcribe] {total} recordings found")
    done = 0
    new = 0
    t0 = time.time()
    for mp3_path, campaign, dispo, meta in recs:
        done += 1
        cid = C.call_id(campaign, dispo, meta["filename"])
        out_path = os.path.join(C.TRANSCRIPTS_DIR, cid + ".json")
        if os.path.exists(out_path) and not force:
            continue
        if limit and new >= limit:
            break
        with tempfile.TemporaryDirectory() as wd:
            try:
                text, segments = transcribe_one(mp3_path, wd)
            except Exception as e:  # noqa: BLE001
                text, segments = "", []
                print(f"  ! error on {cid}: {e}")
        record = {
            "id": cid,
            "campaign": campaign,
            "dispo": dispo,
            "dispo_label": meta["dispo_label"],
            "date": meta["date"],
            "time": meta["time"],
            "phone": meta["phone"],
            "filename": meta["filename"],
            "rel_path": meta["rel_path"],
            "duration": _duration(mp3_path),
            "text": text,
            "segments": segments,
            "word_count": len(text.split()),
        }
        C.save_json(out_path, record)
        new += 1
        if new % progress_every == 0:
            rate = new / max(time.time() - t0, 0.001)
            print(f"  transcribed {new} new ({done}/{total}) ~{rate:.1f}/s")
    print(f"[transcribe] done. {new} new transcripts in {time.time()-t0:.0f}s")
    return new


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = None
    force = "--force" in args
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    run(limit=limit, force=force)
