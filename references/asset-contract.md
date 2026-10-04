# Scroll asset pack contract — schema version 1

This package is independent of React, GSAP, Motion or any website framework.
It contains image sequences and an inspection preview, not a production website
component. Open preview.html directly from disk, or serve this folder locally.

## Files

- manifest.json: public, machine-readable sequence contract.
- settings.json: the exact recipe used to render this version; reusable with the
  original source video in Scroll Asset Studio.
- desktop/ and/or mobile/: sequential frame-000001.webp files.
- poster-{variant}.webp and last-{variant}.webp: exact first/last output frames.
- contact-{variant}.jpg: up to 12 evenly spaced reference thumbnails, read left
  to right and top to bottom; unused cells are blank.
- verification.json: decode/count/time checks, distinguished from visual review.
- confirmation.json: the revision and settings hash accepted on export.
- checksums.json: SHA-256 for every delivered file except checksums.json itself.
- preview.html, preview.css, preview.js, player.js, manifest.js: local review
  viewer, with no external CDN dependency. manifest.js mirrors manifest.json so
  the preview also works through file:// without fetching JSON.

No original source video, absolute source path, session token or server runtime
is included. Source metadata contains only a filename, source hash and media
properties for provenance.

## manifest.json

- schemaVersion: 1.
- source: original media SHA-256, name, dimensions, rotation, codec, fps, duration.
- range.start and range.end: seconds from the first decoded source video frame.
- range.endExclusive: true; the source interval is [start, end).
- duration: requested end minus start; not a website playback or scroll duration.
- sampling.maxFps: maximum sampling buckets per source second.
- frameCount: actual count in each enabled variant.
- indexBase: 0. Array indices are zero-based; filenames start at 000001.
- sourceTimes[i]: timestamp of actual selected source frame i.
- relativeTimes[i]: sourceTimes[i] minus range.start.
- variants.desktop / variants.mobile:
  - width, height: actual exported image pixels, with no upscaling.
  - crop: source display-pixel x, y, width, height after rotation/SAR normalization.
  - frames[i]: relative URL of frame i; forward-slash paths.
  - poster, last, contactSheet: relative URLs.
  - bytes: compressed size of the frame sequence, excluding auxiliary files.
  - decodedBytesPerFrame: width * height * 4, a baseline RGBA memory estimate;
    browser/GPU overhead and in-flight decoding require additional memory.

Both variants use the same source frame/time array. Sampling chooses the first
actual frame in each occupied sampling bucket. Empty buckets are skipped, not
filled with duplicate or interpolated images. Variable frame rate or sparse
sources can therefore have fewer frames and uneven time spacing.

## Progress mapping

Clamp section progress p to [0, 1]. Set target relative time to p * duration.
Choose the last index with relativeTimes[i] <= target time, clamped to the first
frame. At p = 1 choose the final frame explicitly. Use a binary search for a
large sequence. This mapping preserves source timing even for VFR inputs.

Use the explicit frames array; do not guess count, extension or numbering.
Resolve asset paths relative to this pack's base URL. Websites can independently
choose their scroll distance, section layout and breakpoints. Display-mode
cropping (cover) can crop further than the baked asset crop; check critical
subjects in the actual website layout.

## Loading and fallback

Start with the relevant variant's poster. Prioritize the requested frame and
nearby frames; limit decoded cache memory. Do not preload/decode every full-size
image at once or load both variants unnecessarily. Keep a valid nearby frame
or poster while the target is loading. Handle fast reverse scrolling without
letting old requests overwrite the current target.

Respect reduced-motion preferences and supply a static poster when animation
is disabled, assets fail, or JavaScript is unavailable. The review viewer allows
an explicit reduced-motion override for inspection.

## Reproducing an edit

Keep the original video separately. Load it with settings.json through the
global video-to-scroll-assets skill, adjust settings, regenerate, review and
confirm a new export. Changed settings must not be represented as applied until
the actual images have been regenerated.
