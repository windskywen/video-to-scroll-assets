# Video to Scroll Assets

A reusable Codex skill that turns a selected video interval into WebP image
sequences for scroll scrubbing. It includes a local browser studio for editing
settings, reviewing the result, and confirming an export.

The output is a framework-neutral asset pack with a standalone scroll preview.
Implementing a website component is a separate task.

## What it does

- Select a source video and an exact start/end time in seconds.
- Configure independent desktop and mobile crops, aspect ratios, and width limits.
- Adjust the maximum sampling rate and WebP quality.
- Generate real source frames without interpolation, duplicate padding, or upscaling.
- Review forward/reverse scrolling, first/last frames, and contact sheets.
- Regenerate after changing settings, then confirm a version to export a folder and ZIP.
- Keep the recipe, actual frame timestamps, and checksums with the assets.

All studio labels, generated preview text, and application error messages are
in English. User-supplied filenames remain unchanged. Processing runs locally;
the source video is not uploaded to an external service or included in the asset pack.

## Requirements

- Python 3.11 or newer. The scripts use only the Python standard library.
- FFmpeg and ffprobe, including the `libwebp` encoder. The self-tests also use `libx264`.
- A current browser with Canvas and WebP support.

Verified locally on Windows with Python 3.13, FFmpeg 9.0.2, and Codex's Chromium
browser. macOS, Linux, Safari, and physical mobile devices have not been verified.
The portable FFmpeg installer is Windows-only. Runtime binaries are not stored
in this repository.

## Install as a global Codex skill

Clone this repository into your Codex skills directory. The examples respect
`CODEX_HOME` when set and otherwise use `~/.codex`.

Windows PowerShell:

```powershell
$codexSkillBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$scrollSkill = Join-Path $codexSkillBase 'skills/video-to-scroll-assets'
git clone https://github.com/windskywen/video-to-scroll-assets.git "$scrollSkill"
python "$scrollSkill/scripts/studio.py" --check
```

If FFmpeg is missing on Windows, run:

```powershell
python "$scrollSkill/scripts/setup_ffmpeg.py"
python "$scrollSkill/scripts/studio.py" --check
```

The installer downloads a portable build from the Windows provider linked by
[FFmpeg](https://ffmpeg.org/download.html), verifies the publisher's SHA-256,
and retains its license and provenance under `runtime/ffmpeg/`.

macOS/Linux shell, with FFmpeg and ffprobe already installed:

```sh
scroll_skill="${CODEX_HOME:-$HOME/.codex}/skills/video-to-scroll-assets"
git clone https://github.com/windskywen/video-to-scroll-assets.git "$scroll_skill"
python3 "$scroll_skill/scripts/studio.py" --check
```

Use the available Python executable if it has a different name. A clone must
target a directory that does not already contain an installation. If you have
an earlier manually installed copy, preserve it before replacing it. For an
existing Git clone, update with `git pull --ff-only` after reviewing local changes.
Restart Codex if the new skill is not listed, then open a chat in any project.

## Use in Codex

Attach a video or provide a local path, then ask:

```text
Use $video-to-scroll-assets with the attached video, from 2 to 5 seconds.
Create desktop and mobile assets and open the editable scroll preview.
Let me review the result before confirming the export.
```

You can also choose the source in the studio:

```text
Use $video-to-scroll-assets and open the studio so I can choose a video.
```

Only the source video and the desired interval are needed to start. Optional
settings include the asset name, enabled variants, width limits, aspect ratios,
crop positions, sampling rate, and WebP quality.

Defaults are desktop and mobile enabled, original aspect ratio, width limits of
1920 and 960 pixels, quality 82, and a sampling ceiling of the lower of 30 fps
and the source average frame rate. The browser lets you change these settings.

### Review and export

1. Choose a video and enter the start and end times.
2. Adjust the desktop and mobile settings independently.
3. Select **Generate assets and preview**.
4. Scroll or use the slider to inspect the real rendered frames. Check both
   variants, the first/last frames, and the contact sheets.
5. After changing material settings, select **Regenerate assets and preview**.
   The preview is marked as out of date until regeneration completes.
6. Select **Confirm and export** when satisfied. Download the verified ZIP or
   use the exported folder.

Scroll distance, Contain/Cover display, and the motion toggle affect only the
preview. They do not require regenerating the assets. Reduced-motion preferences
are respected; motion can be enabled explicitly for review.

## Run the studio directly

From the repository root:

```sh
python scripts/studio.py --source "path/to/video.mp4" --start 2 --end 5 --workdir "work/scroll-session" --output-dir "outputs/scroll-assets"
```

Open the loopback URL printed by the command. It is also saved in
`work/scroll-session/server.json`. Keep the process running while editing.
Omit `--source`, `--start`, and `--end` to choose the video and interval in the UI.
Keep session media and exports in the current project, outside the installed
skill. Do not start two services against the same session directory.

To resume, use the same work and output directories and omit `--source`.
To render an existing recipe with its original source:

```sh
python scripts/studio.py --source "path/to/video.mp4" --settings "path/to/pack/settings.json" --workdir "work/new-session" --output-dir "outputs/scroll-assets"
```

Tool discovery checks `SCROLL_FFMPEG` / `SCROLL_FFPROBE` environment overrides,
then `runtime/ffmpeg/bin`, then `PATH`.

## Export contents

```text
asset-pack/
  desktop/frame-000001.webp ...
  mobile/frame-000001.webp ...
  poster-desktop.webp, poster-mobile.webp
  last-desktop.webp, last-mobile.webp
  contact-desktop.jpg, contact-mobile.jpg
  manifest.json, manifest.js
  settings.json
  preview.html, preview.css, preview.js, player.js
  verification.json, confirmation.json, checksums.json
  INTEGRATION.md
```

Only enabled variants are included. The source video, absolute source path,
session tokens, and server runtime are excluded. Source metadata includes the
original filename, media properties, and a SHA-256 fingerprint.

The preview has no external CDN or build dependency. It uses `manifest.js` for
direct disk opening and can also be served locally. The exported preview has
been verified over HTTP. For example, run `python -m http.server 8000 --bind
127.0.0.1` in the pack directory and open `http://127.0.0.1:8000/preview.html`.

See [the asset contract](references/asset-contract.md) for the manifest schema,
timestamp-based progress mapping, and loading guidance. Your frontend can use
the assets with its own layout, scroll library, and breakpoints.

## Limits and validation

The requested interval is `[start, end)`: start is included and end is excluded,
measured from the first decoded source frame. Sampling selects the first real
source frame in each occupied time bucket. Variable-frame-rate input can produce
uneven time spacing and fewer frames than duration multiplied by sampling rate.

This version accepts SDR video, with a maximum of 10,000 planned frames per
render and a 10 GB browser upload limit. HDR input requires a separately chosen
SDR conversion. Background removal and transparency generation are not included.
Some source codecs cannot play in the browser; a source poster and rendered WebP
frames remain available.

The renderer checks source hashes before and after processing, decodes all output
frames, and verifies counts, numbering, dimensions, and timestamps. Export checks
the current settings and revision, then verifies ZIP contents against the files.
These checks complement the user's visual review.

Run the existing regression checks with:

```sh
python -B scripts/self_test.py
```

They create disposable synthetic media to check interval boundaries, crop
geometry, variable frame rates, rotation, portable export integrity, local HTTP
access checks, and rejection of stale confirmations.

## Repository layout

- `SKILL.md`: Codex workflow and invocation instructions.
- `agents/openai.yaml`: skill display metadata and default prompt.
- `scripts/`: local server, media processing, runtime setup, and self-tests.
- `assets/`: studio interface and standalone review viewer.
- `references/asset-contract.md`: framework-neutral asset handoff contract.

FFmpeg is a separate dependency governed by its own upstream licensing. See
[FFmpeg licensing](https://ffmpeg.org/legal.html) and the
[Windows build provider](https://www.gyan.dev/ffmpeg/builds/) for details.
