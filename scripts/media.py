"""Deterministic video-to-image-sequence processing. Python standard library only."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"


class MediaError(Exception):
    pass


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def find_tools():
    result = {}
    for name in ("ffmpeg", "ffprobe"):
        override = os.environ.get("SCROLL_" + name.upper())
        bundled = ROOT / "runtime" / "ffmpeg" / "bin" / (name + (".exe" if os.name == "nt" else ""))
        executable = override or (str(bundled) if bundled.is_file() else shutil.which(name))
        if not executable or not Path(executable).is_file():
            raise MediaError(
                "ffmpeg / ffprobe not found. On Windows, run this skill's scripts/setup_ffmpeg.py; "
                "on other systems, install FFmpeg or set SCROLL_FFMPEG and SCROLL_FFPROBE."
            )
        result[name] = str(Path(executable).resolve())
    return result


class Runner:
    def __init__(self):
        self.process = None
        self.cancelled = threading.Event()
        self.lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def run(self, args, on_line=None):
        if self.cancelled.is_set():
            raise MediaError("Processing cancelled.")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with self.lock:
            self.process = subprocess.Popen(
                [str(arg) for arg in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", creationflags=flags, stdin=subprocess.DEVNULL
            )
            process = self.process
        lines = [] if on_line is None else deque(maxlen=40)
        with process.stdout:
            for line in process.stdout:
                lines.append(line)
                if on_line:
                    on_line(line)
        code = process.wait()
        with self.lock:
            self.process = None
        if self.cancelled.is_set():
            raise MediaError("Processing cancelled.")
        if code:
            raise MediaError("Media processing failed:\n" + "".join(lines)[-2400:])
        return "".join(lines)


def rate(value):
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(source, tools, runner=None):
    runner = runner or Runner()
    source = Path(source).resolve()
    if not source.is_file():
        raise MediaError("Source video not found.")
    info = json.loads(runner.run([
        tools["ffprobe"], "-v", "error", "-select_streams", "v:0",
        "-show_streams", "-show_format", "-of", "json", source
    ]))
    streams = info.get("streams", [])
    if not streams:
        raise MediaError("This file has no readable video track.")
    stream = streams[0]
    duration = rate(stream.get("duration")) or rate(info.get("format", {}).get("duration"))
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("Cannot determine video duration. Provide a playable local video.")
    width, height = int(stream["width"]), int(stream["height"])
    sar = rate(stream.get("sample_aspect_ratio", "1:1").replace(":", "/")) or 1
    display_width, display_height = round(width * sar), height
    rotation = next((float(data.get("rotation", 0)) for data in stream.get("side_data_list", [])
                     if "rotation" in data), float(stream.get("tags", {}).get("rotate", 0)))
    if round(abs(rotation)) % 180 == 90:
        display_width, display_height = display_height, display_width
    transfer = stream.get("color_transfer", "unknown")
    if transfer in ("smpte2084", "arib-std-b67"):
        raise MediaError("This video is HDR. This version requires SDR input. Explicitly choose an HDR-to-SDR conversion before continuing to avoid unexpected color changes.")
    return {
        "name": source.name, "sha256": fingerprint(source), "bytes": source.stat().st_size,
        "duration": duration, "width": display_width, "height": display_height,
        "encodedWidth": width, "encodedHeight": height, "rotation": rotation,
        "sourceFps": rate(stream.get("avg_frame_rate")) or rate(stream.get("r_frame_rate")),
        "codec": stream.get("codec_name"), "colorTransfer": transfer,
        "pixelFormat": stream.get("pix_fmt"), "timeOrigin": "first decoded video frame"
    }


def default_settings(meta, start=0, end=None):
    start = float(start)
    end = min(meta["duration"], start + 3) if end is None else float(end)
    settings = {
        "name": "scroll-assets", "start": start, "end": end,
        "fps": round(max(1, min(30, meta["sourceFps"] or 30)), 6), "quality": 82,
        "variants": {
            "desktop": {"enabled": True, "width": 1920, "ratio": "original", "x": 0.5, "y": 0.5},
            "mobile": {"enabled": True, "width": 960, "ratio": "original", "x": 0.5, "y": 0.5}
        }
    }
    return normalize(settings, meta)


def number(value, label, lower, upper):
    if isinstance(value, bool):
        raise MediaError(label + " must be a number.")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise MediaError(label + " must be a number.")
    if not math.isfinite(value) or value < lower or value > upper:
        raise MediaError(f"{label} must be between {lower:g} and {upper:g}.")
    return value


def normalize(value, meta):
    if not isinstance(value, dict):
        raise MediaError("Settings must be a JSON object.")
    name = str(value.get("name", "scroll-assets")).strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise MediaError("Use 1–64 letters, digits, hyphens, or underscores for the asset name; start with a letter or digit.")
    start = number(value.get("start"), "Start time (s)", 0, meta["duration"])
    end = number(value.get("end"), "End time (s)", 0, meta["duration"])
    if end <= start:
        raise MediaError("End time must be greater than start time.")
    fps = number(value.get("fps"), "Max sampling fps", 1, 120)
    if (end - start) * fps > 10000:
        raise MediaError("A render is limited to 10,000 planned frames. Shorten the clip or reduce the sampling rate.")
    quality = number(value.get("quality"), "WebP quality", 1, 100)
    variants = {}
    incoming = value.get("variants")
    if not isinstance(incoming, dict):
        raise MediaError("Desktop/mobile settings are missing.")
    for key in ("desktop", "mobile"):
        item = incoming.get(key, {})
        if not isinstance(item, dict) or not isinstance(item.get("enabled", True), bool):
            raise MediaError("Variant enabled setting must be a boolean.")
        ratio = str(item.get("ratio", "original"))
        if ratio != "original" and ratio not in ("16:9", "9:16", "4:3", "3:4", "1:1", "21:9"):
            raise MediaError("Unsupported crop aspect ratio.")
        variants[key] = {
            "enabled": item.get("enabled", True),
            "width": int(number(item.get("width"), "Max width (px)", 64, 3840)),
            "ratio": ratio, "x": number(item.get("x", 0.5), "Horizontal crop", 0, 1),
            "y": number(item.get("y", 0.5), "Vertical crop", 0, 1)
        }
    if not any(item["enabled"] for item in variants.values()):
        raise MediaError("Enable at least one variant: desktop or mobile.")
    return {"name": name, "start": start, "end": end, "fps": fps,
            "quality": int(quality), "variants": variants}


def settings_hash(settings, source_hash):
    return hashlib.sha256((source_hash + json.dumps(
        settings, sort_keys=True, separators=(",", ":"), allow_nan=False
    )).encode()).hexdigest()


def geometry(meta, setting):
    width, height = meta["width"], meta["height"]
    ratio = width / height if setting["ratio"] == "original" else rate(setting["ratio"].replace(":", "/"))
    cw, ch = width, height
    if width / height > ratio:
        cw = max(2, round(height * ratio))
    else:
        ch = max(2, round(width / ratio))
    cw, ch = min(width, cw), min(height, ch)
    x, y = round((width - cw) * setting["x"]), round((height - ch) * setting["y"])
    factor = min(1, setting["width"] / cw)
    # WebP permits odd dimensions, so do not distort the requested crop to force even sizes.
    ow, oh = max(1, round(cw * factor)), max(1, round(ch * factor))
    return {"crop": {"x": x, "y": y, "width": cw, "height": ch}, "width": ow, "height": oh}


def make_source_poster(source, destination, tools, runner):
    runner.run([tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y",
                "-i", source, "-map", "0:v:0", "-vf",
                "scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=960:960:force_original_aspect_ratio=decrease",
                "-frames:v", "1", "-update", "1", destination])


def render(source, meta, settings, directory, tools, runner, progress):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if fingerprint(source) != meta["sha256"]:
        raise MediaError("The source video has changed. Reload the source.")
    start, end, fps = settings["start"], settings["end"], settings["fps"]
    variants = {key: geometry(meta, setting) for key, setting in settings["variants"].items() if setting["enabled"]}
    # Pick the first actual source frame in each sampling bucket. Never synthesize or duplicate.
    expression = (
        f"if(isnan(prev_selected_t),1,gt(floor((t-{start:.9f})*{fps:.9f}+0.000001),"
        f"floor((prev_selected_t-{start:.9f})*{fps:.9f}+0.000001)))"
    )
    filters = (
        f"[0:v:0]setpts=PTS-STARTPTS,trim=start={start:.9f}:end={end:.9f},"
        f"select='{expression}',showinfo,scale={meta['width']}:{meta['height']}:flags=lanczos,setsar=1,"
        f"format=rgb24,split={len(variants)}"
        + "".join(f"[s{index}]" for index in range(len(variants))) + ";"
    )
    for index, (key, geo) in enumerate(variants.items()):
        crop = geo["crop"]
        filters += (
            f"[s{index}]crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}:exact=1,"
            f"scale={geo['width']}:{geo['height']}:flags=lanczos[{key}];"
        )
        (directory / key).mkdir()
    command = [tools["ffmpeg"], "-hide_banner", "-nostdin", "-y", "-i", str(source),
               "-filter_complex_threads", "1", "-filter_complex", filters.rstrip(";")]
    for key in variants:
        command += ["-map", f"[{key}]", "-an", "-fps_mode", "vfr", "-c:v", "libwebp",
                    "-quality", str(settings["quality"]), "-compression_level", "4",
                    "-start_number", "1", str(directory / key / "frame-%06d.webp")]
    timestamps = []

    def on_line(line):
        found = re.search(r"Parsed_showinfo.*\bn:\s*\d+.*\bpts_time:([-\d.e+]+)", line)
        if found:
            time = float(found.group(1))
            timestamps.append(time)
            if len(timestamps) % 10 == 0:
                progress(f"Extracted {len(timestamps)} frames", min(80, int(80 * (time - start) / (end - start))))

    progress("Extracting the selected interval and rendering image sequences", 5)
    runner.run(command, on_line)
    if not timestamps:
        raise MediaError("No source frames exist in the selected interval. Adjust the start/end times.")
    if any(t < start - 0.00005 or t >= end + 0.00005 for t in timestamps):
        raise MediaError("Frame timestamps fall outside the selected interval. Output was stopped.")
    if len(timestamps) != len(set(timestamps)) or timestamps != sorted(timestamps):
        raise MediaError("Source timestamps are non-monotonic or duplicated. Normalize the source first.")
    checks = {}
    for key, geo in variants.items():
        progress(f"Verifying {key} frames and building the contact sheet", 85)
        files = sorted((directory / key).glob("frame-*.webp"))
        expected = [f"frame-{index:06d}.webp" for index in range(1, len(timestamps) + 1)]
        if [p.name for p in files] != expected:
            raise MediaError("Frame counts or numbering do not match the recorded source timestamps.")
        # Decode every exported image, not just the first and last.
        runner.run([tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-xerror",
                    "-start_number", "1", "-i", directory / key / "frame-%06d.webp",
                    "-f", "null", "-"])
        dimensions = json.loads(runner.run([
            tools["ffprobe"], "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "json", files[0]
        ]))["streams"][0]
        if dimensions["width"] != geo["width"] or dimensions["height"] != geo["height"]:
            raise MediaError("Output image dimensions do not match the settings.")
        shutil.copy2(files[0], directory / f"poster-{key}.webp")
        shutil.copy2(files[-1], directory / f"last-{key}.webp")
        step = max(1, math.ceil(len(files) / 12))
        runner.run([
            tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-start_number", "1",
            "-i", directory / key / "frame-%06d.webp", "-vf",
            f"select='not(mod(n,{step}))',scale=240:160:force_original_aspect_ratio=decrease,"
            "pad=240:160:(ow-iw)/2:(oh-ih)/2:color=0x101719,tile=4x3:padding=4:margin=4:color=0x101719",
            "-frames:v", "1", "-update", "1", directory / f"contact-{key}.jpg"
        ])
        geo.update({
            "frames": [f"{key}/{p.name}" for p in files],
            "poster": f"poster-{key}.webp", "last": f"last-{key}.webp",
            "contactSheet": f"contact-{key}.jpg", "bytes": sum(p.stat().st_size for p in files),
            "decodedBytesPerFrame": geo["width"] * geo["height"] * 4
        })
        checks[key] = {"decodedAllFrames": True, "contiguousNumbering": True,
                       "frameCount": len(files), "dimensions": dimensions}
    if fingerprint(source) != meta["sha256"]:
        raise MediaError("The source video changed during processing. Reload the source.")
    manifest = {
        "schemaVersion": 1, "generator": f"video-to-scroll-assets/{VERSION}",
        "revisionId": directory.name, "createdAt": datetime.now(timezone.utc).isoformat(),
        "settingsHash": settings_hash(settings, meta["sha256"]),
        "source": meta, "range": {"start": start, "end": end, "endExclusive": True},
        "duration": end - start, "sampling": {
            "maxFps": fps, "method": "first source frame per time bucket; no interpolation or duplicates"
        },
        "frameCount": len(timestamps), "indexBase": 0,
        "sourceTimes": timestamps, "relativeTimes": [round(time - start, 9) for time in timestamps],
        "format": "webp", "variants": variants
    }
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "settings.json", settings)
    write_json(directory / "verification.json", {
        "status": "passed", "sourceUnchanged": True, "endExclusive": True,
        "firstSourceTime": timestamps[0], "lastSourceTime": timestamps[-1],
        "variants": checks, "visualReview": "User reviews the local preview before confirmation."
    })
    for filename in ("player.js", "preview.css", "preview.js"):
        shutil.copy2(ROOT / "assets" / filename, directory / filename)
    preview = (ROOT / "assets" / "preview.html").read_text(encoding="utf-8")
    links = " / ".join(f'<a href="poster-{key}.webp">{key}</a>' for key in variants)
    (directory / "preview.html").write_text(preview.replace("__POSTER_LINKS__", links), encoding="utf-8")
    (directory / "manifest.js").write_text(
        "window.SCROLL_PACK = " + json.dumps(manifest, ensure_ascii=True) + ";\n", encoding="utf-8"
    )
    shutil.copy2(ROOT / "references" / "asset-contract.md", directory / "INTEGRATION.md")
    progress("Assets are ready to review and confirm", 100)
    return manifest


def export_pack(draft, output_root, settings, manifest):
    draft, output_root = Path(draft), Path(output_root)
    if manifest["settingsHash"] != settings_hash(settings, manifest["source"]["sha256"]):
        raise MediaError("Settings have unapplied changes. Regenerate the assets before confirming.")
    output_root.mkdir(parents=True, exist_ok=True)
    stem = f"{settings['name']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    target = output_root / stem
    shutil.copytree(draft, target)
    write_json(target / "confirmation.json", {
        "confirmedAt": datetime.now(timezone.utc).isoformat(),
        "revisionId": manifest["revisionId"], "settingsHash": manifest["settingsHash"]
    })
    hashes = {p.relative_to(target).as_posix(): fingerprint(p) for p in target.rglob("*") if p.is_file()}
    write_json(target / "checksums.json", hashes)
    archive = output_root / (stem + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(target).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip():
            raise MediaError("ZIP verification failed.")
        for relative, digest in hashes.items():
            if hashlib.sha256(zipped.read(relative)).hexdigest() != digest:
                raise MediaError("ZIP contents do not match the confirmed assets.")
    return {"folder": str(target.resolve()), "zip": str(archive.resolve()),
            "name": stem, "bytes": archive.stat().st_size, "verified": True}
