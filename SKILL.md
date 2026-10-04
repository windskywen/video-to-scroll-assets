---
name: video-to-scroll-assets
description: Convert a user-supplied video segment into desktop and mobile WebP image sequences for scroll scrubbing, with a local browser workspace for changing timestamps, resolution, sampling, quality and independent crops, reviewing scroll playback, and confirming an exportable asset pack. Use for video-to-scroll asset conversion, scroll-scrubbing assets, or video-to-image-sequence preparation. Produces assets and a review preview; website component implementation is a separate task.
---

# Video to Scroll Assets

Create real, reviewable assets with the bundled local studio. Do not replace the
workflow with screenshots, instructions only, a generated animation, or a website
component. The browser is the user's editor and confirmation surface.

Keep all shipped instructions, studio labels, preview text, and application
messages in English. Preserve user-supplied filenames and respond in the user's
preferred language when discussing the task.

## Intake and defaults

Ask only for missing source video and start/end seconds. Accept decimal seconds
or convert a user-supplied timecode to seconds. Use a supplied local path or
downloadable attachment. A social page URL is not itself a video input: obtain
the actual supplied media before running. If the user wants to pick the source
in the studio, launch without --source and let them choose it there.

Start/end are measured from the first decoded video frame, using [start, end).
Never change an explicitly supplied interval to make it pass validation.
The browser can change all material settings before export.

Defaults: both desktop and mobile; original aspect ratio; width ceilings of
1920 and 960 pixels; WebP quality 82; sampling ceiling at the lower of source
average fps and 30. Sampling uses actual timestamps, first source frame per
bucket, without interpolation, duplicate padding, or upscaling. For variable
frame rate media, actual frame count and time spacing can differ from duration
times sampling rate. Both variants share the same frame/time ordering.

Desktop and mobile each have their own aspect ratio and crop position.
Keep original composition unless the user changes the crop. The x/y controls
move the crop within available horizontal/vertical space; they are not automatic
subject tracking. The source overlay helps select the crop, and the rendered
preview is the final visual evidence.

## Launch

Resolve paths relative to this SKILL.md, never relative to the current project.
Python 3.11+ and ffmpeg/ffprobe are required; the code uses only Python's standard
library. First run:

    python "<skill>/scripts/studio.py" --check

The studio searches this skill's runtime/ffmpeg/bin, then PATH. Explicit
SCROLL_FFMPEG and SCROLL_FFPROBE environment variables take priority. If tools
are missing on Windows, the explicit setup command downloads a portable build
from the Windows provider linked by ffmpeg.org and verifies its SHA-256:

    python "<skill>/scripts/setup_ffmpeg.py"

Use the available Python executable if the command is named differently.
On non-Windows hosts, use existing ffmpeg/ffprobe or the host's normal dependency
installation workflow; this setup script is Windows-only. Do not repeatedly
download a runtime that is already present.

Launch a persistent process in the current project's permitted workspace:

    python "<skill>/scripts/studio.py" --source "<video>" --start 2 --end 5 --workdir "<project>/work/scroll-assets/<session>" --output-dir "<project>/outputs/scroll-assets"

The service binds to 127.0.0.1 on an available port and prints JSON with its URL
and PID. It also writes workdir/server.json. Keep the process alive while the
user edits. On Windows, background launches must use a hidden window, for example
Start-Process -WindowStyle Hidden with task-local stdout/stderr log files.
Do not start another service in the same session directory.

Open the returned URL with open_in_codex or the available browser tool. If no
source is ready, omit --source; the UI lets the user upload a local video.
Only show the loopback URL, not internal session tokens.

Project media, drafts and exports belong in the current project's chosen
directories, never inside the installed global skill. Use work/ for scratch
and the task's designated output directory for final artifacts. Preserve all
unrelated project files and the original source.

## Browser workflow

1. Load video and set the requested interval.
2. Let the user adjust timestamps, sampling ceiling, quality, enabled variants,
   width ceilings, independent aspect ratios and x/y crop positions.
3. Use Generate assets and preview / Regenerate assets and preview. Processing runs asynchronously.
4. Review desktop and mobile: first and last frames, reverse/forward scrolling,
   source-time labels, crop, contact sheets, actual dimensions and bytes.
5. Only use Confirm and export after the user confirms the preview, unless they have
   explicitly authorized accepting specified settings without further review.
   Starting a conversion alone is not confirmation of its appearance.
6. Return the verified export folder/ZIP and summarize actual frame count,
   interval, dimensions and bytes. Link user deliverables, not temporary drafts.

The dirty badge must remain visible when material settings differ from the
rendered revision. Confirmation is disabled in the UI and independently rejected
by the server for mismatched settings or revision IDs. Do not bypass these
checks to declare completion. Scroll distance, fit mode and reduced-motion
override only affect preview playback and do not require regenerating assets.

Each successful render gets a new draft directory. Failed renders preserve the
previous valid revision. Confirming creates a uniquely named export folder and
ZIP without overwriting earlier exports. The ZIP is checked against the exported
files. State the draft/confirmed distinction clearly in the response.

## Reuse and handoff

To reuse an exported recipe, supply the original video and:

    python "<skill>/scripts/studio.py" --source "<video>" --settings "<pack>/settings.json" --workdir "<new-session>" --output-dir "<outputs>"

To resume a session, start with the same --workdir and --output-dir and omit
--source; source metadata is rechecked before restoring a matching revision.
Never kill a process merely because it occupies a preferred port. Use the PID
from the session you launched and stop only that process when no longer needed.

Read [the asset contract](references/asset-contract.md) when explaining handoff
or changing the exporter. Exported packs include that contract, settings.json,
manifest.json, real frame sequences, poster/last/contact images, validation,
checksums and an independent preview.html. The exported preview opens directly
from disk without a build step; regeneration still uses the studio and source.
The source video is not copied into the final pack.

## Verification and limits

The backend checks source hashes before/after rendering, decodes every output
image, verifies numbering/counts and dimensions, and records actual source times.
Inspect first/middle/last frames and both crop variants visually as well.
Do not claim a visual review, browser coverage, or a confirmed export that did
not occur. Export data is framework-neutral; do not add project dependencies,
edit website components, publish a site, or deploy as part of this skill.

The renderer limits decoded-image caching and loads the requested frame first.
Respect reduced motion by showing a static frame until the user explicitly
enables preview motion. Network bytes and decoded memory are distinct metrics.

First version handles ordinary SDR local video. HDR sources are explicitly
rejected instead of silently changing colors; a user-approved SDR conversion
can be a separate preprocessing task. It does not remove backgrounds or create
transparency. Browser source playback may be unavailable for some codecs;
the source poster and generated WebP preview still work.

Invalid/empty intervals, missing tools, corrupt input, >10,000 planned frames,
or >10 GB browser uploads produce clear errors. Do not fabricate replacements.
Use the error to correct the actual input or settings.
