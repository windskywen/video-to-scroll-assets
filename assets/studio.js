(() => {
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="session-token"]').content;
  let state = {}, sourceKey = "", currentRevision = "", variant = "desktop", player = null;
  let applied = null, posting = false, lastDelivery = "", scrollFrame = 0, clientError = "";
  $("motion").checked = !matchMedia("(prefers-reduced-motion: reduce)").matches;

  async function api(path, data) {
    const response = await fetch(path, {
      method: data === undefined ? "GET" : "POST",
      headers: {"X-Session-Token": token, ...(data === undefined ? {} : {"Content-Type": "application/json"})},
      ...(data === undefined ? {} : {body: JSON.stringify(data)})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The operation failed.");
    return result;
  }
  function settings() {
    return {
      name: $("name").value.trim(), start: Number($("start").value), end: Number($("end").value),
      fps: Number($("fps").value), quality: Number($("quality").value),
      variants: Object.fromEntries(["desktop", "mobile"].map(key => [key, {
        enabled: $(key + "-enabled").checked, width: Number($(key + "-width").value),
        ratio: $(key + "-ratio").value, x: Number($(key + "-x").value) / 100,
        y: Number($(key + "-y").value) / 100
      }]))
    };
  }
  function fill(value) {
    for (const key of ["name", "start", "end", "fps", "quality"]) $(key).value = value[key];
    for (const key of ["desktop", "mobile"]) {
      const item = value.variants[key];
      $(key + "-enabled").checked = item.enabled;
      for (const field of ["width", "ratio"]) $(key + "-" + field).value = item[field];
      for (const field of ["x", "y"]) $(key + "-" + field).value = item[field] * 100;
    }
  }
  const same = (a, b) => !!a && !!b && JSON.stringify(a) === JSON.stringify(b);
  const mb = bytes => (bytes / 1024 / 1024).toFixed(2) + " MB";

  function edited() {
    const value = settings(), dirty = !same(value, applied);
    $("revision").textContent = !state.manifest ? "No preview yet" : dirty ? "Unapplied changes" : "Preview up to date";
    $("revision").className = "badge " + (state.manifest ? (dirty ? "dirty" : "ready") : "");
    const busy = state.busy || posting;
    $("confirm").disabled = busy || dirty || !state.manifest;
    $("render").disabled = busy || !state.source;
    $("file").disabled = busy;
    $("media-fields").disabled = busy || !state.source;
    $("render").textContent = state.manifest ? "Regenerate assets and preview" : "Generate assets and preview";
    $("ready-label").textContent = dirty && state.manifest ? "Regenerate to apply your changes" : "Ready to keep this version?";
    if (state.source) {
      const count = Math.ceil(Math.max(0, value.end - value.start) * Math.min(value.fps, state.source.sourceFps || value.fps));
      $("estimate").textContent = "Estimated upper bound: about " + count.toLocaleString() + " frames per variant. Final counts and sizes are available after rendering. No upscaling.";
      updateCrop();
    }
  }

  function resetTrack() {
    $("track").style.height = ($("scrollbox").clientHeight + Number($("distance").value)) + "px";
  }
  function scrollProgress() {
    return $("scrollbox").scrollTop / Math.max(1, $("scrollbox").scrollHeight - $("scrollbox").clientHeight);
  }
  function drawProgress(progress) {
    $("scrub").value = Math.round(progress * 1000);
    if (player) player.setProgress($("motion").checked ? progress : 0);
  }
  function createPlayer() {
    if (player) player.dispose();
    player = null;
    $("viewport").classList.toggle("mobile", variant === "mobile");
    $("view-desktop").classList.toggle("active", variant === "desktop");
    $("view-mobile").classList.toggle("active", variant === "mobile");
    updateCrop();
    const manifest = state.manifest;
    if (!manifest || !manifest.variants[variant]) {
      $("empty").hidden = false;
      $("empty").querySelector("p").textContent = manifest ? "This variant has not been rendered. Enable it and regenerate." : "Generate assets, then scroll here to review them.";
      $("stats").textContent = "Set a separate aspect ratio and crop for each variant.";
      $("review-links").replaceChildren();
      return;
    }
    $("empty").hidden = true;
    player = new ScrollSequence($("canvas"), manifest, variant, "/drafts/" + state.revisionId + "/", frame => {
      const suffix = frame.error ? " · Load failed" : frame.loading ? " · Loading" : "";
      $("frame-label").textContent = (frame.target + 1) + " / " + manifest.frameCount + " · " + frame.sourceTime.toFixed(3) + "s" + suffix;
    });
    player.fit = $("fit").value;
    player.setProgress($("motion").checked ? scrollProgress() : 0);
    const spec = manifest.variants[variant];
    $("stats").textContent = spec.width + " × " + spec.height + " px · " + manifest.frameCount + " WebP frames · " + mb(spec.bytes) +
      " · Estimated decoded size per frame: " + mb(spec.decodedBytesPerFrame);
    $("review-links").replaceChildren();
    for (const [label, path] of [["First frame", spec.poster], ["Last frame", spec.last], ["Contact sheet", spec.contactSheet]]) {
      const link = document.createElement("a");
      link.textContent = label; link.href = "/drafts/" + state.revisionId + "/" + path;
      link.target = "_blank"; link.rel = "noopener";
      $("review-links").append(link);
    }
  }
  function updateCrop() {
    if (!state.source) return;
    const item = settings().variants[variant], width = state.source.width, height = state.source.height;
    const ratio = item.ratio === "original" ? width / height : item.ratio.split(":").map(Number).reduce((a, b) => a / b);
    let cw = width, ch = height;
    if (width / height > ratio) cw = height * ratio;
    else ch = width / ratio;
    Object.assign($("crop-box").style, {
      left: ((width - cw) * item.x / width * 100) + "%", top: ((height - ch) * item.y / height * 100) + "%",
      width: (cw / width * 100) + "%", height: (ch / height * 100) + "%"
    });
    for (const key of ["desktop", "mobile"]) {
      const original = $(key + "-ratio").value === "original";
      $(key + "-x").disabled = original; $(key + "-y").disabled = original;
    }
  }

  function update(next) {
    state = next;
    if (state.source && state.source.sha256 !== sourceKey) {
      sourceKey = state.source.sha256;
      fill(state.settings);
      applied = null; currentRevision = "";
      $("filename").textContent = state.source.name;
      $("source-meta").textContent = state.source.width + " × " + state.source.height + " · " + state.source.duration.toFixed(3) +
        " s · Source average: " + state.source.sourceFps.toFixed(3) + " fps";
      $("start").max = $("end").max = state.source.duration;
      $("source-video").hidden = false; $("source-poster").hidden = true;
      $("source-video").src = "/media/source?v=" + sourceKey;
      $("source-video").poster = "/media/poster?v=" + sourceKey;
      $("source-poster").src = "/media/poster?v=" + sourceKey;
      $("video-note").textContent = "";
      createPlayer();
    }
    if (state.revisionId !== currentRevision) {
      currentRevision = state.revisionId;
      applied = state.settings ? JSON.parse(JSON.stringify(state.settings)) : null;
      if (state.manifest && !state.manifest.variants[variant]) variant = Object.keys(state.manifest.variants)[0];
      createPlayer();
    }
    $("status").textContent = state.message || "";
    $("error").textContent = clientError || state.error || "";
    $("progress").value = state.percent || 0;
    if (state.export && state.export.name !== lastDelivery) {
      lastDelivery = state.export.name;
      const box = $("delivery"); box.hidden = false; box.replaceChildren();
      for (const [label, href] of [["Download asset ZIP", state.export.url], ["Open exported scroll preview", state.export.previewUrl]]) {
        const link = document.createElement("a"); link.textContent = label; link.href = href;
        if (href.endsWith(".zip")) link.download = ""; else { link.target = "_blank"; link.rel = "noopener"; }
        box.append(link);
      }
      const note = document.createElement("p"); note.textContent = "Folder: " + state.export.folder;
      box.append(note);
      const verified = document.createElement("p"); verified.textContent = "Confirmed version · ZIP " + mb(state.export.bytes) + " · Checksums verified";
      box.append(verified);
    }
    if (!state.export) { $("delivery").hidden = true; lastDelivery = ""; }
    edited();
  }
  async function perform(path, payload) {
    posting = true; clientError = ""; $("error").textContent = ""; edited();
    try { update(await api(path, payload)); }
    catch (error) { clientError = error.message; $("error").textContent = clientError; }
    finally { posting = false; edited(); }
  }
  $("settings").addEventListener("input", () => { clientError = ""; $("error").textContent = ""; edited(); });
  $("settings").addEventListener("change", event => {
    edited();
    if (event.target.id === "start" && $("source-video").readyState >= 1) {
      $("source-video").currentTime = Number($("start").value);
    }
  });
  $("settings").addEventListener("submit", event => {
    event.preventDefault();
    if ($("settings").reportValidity()) perform("/api/render", settings());
  });
  $("confirm").addEventListener("click", () => perform("/api/confirm", {revisionId: state.revisionId, settings: settings()}));
  $("file").addEventListener("change", async () => {
    const file = $("file").files[0]; if (!file) return;
    posting = true; clientError = ""; edited(); $("error").textContent = ""; $("status").textContent = "Loading video…";
    try {
      const response = await fetch("/api/upload?name=" + encodeURIComponent(file.name), {
        method: "POST", headers: {"X-Session-Token": token, "Content-Type": "application/octet-stream"}, body: file
      });
      const next = await response.json();
      if (!response.ok) throw new Error(next.error);
      sourceKey = ""; update(next);
    } catch (error) { clientError = error.message; $("error").textContent = clientError; }
    finally { posting = false; $("file").value = ""; edited(); }
  });
  for (const key of ["desktop", "mobile"]) $("view-" + key).addEventListener("click", () => { variant = key; createPlayer(); });
  $("scrollbox").addEventListener("scroll", () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(() => { scrollFrame = 0; drawProgress(scrollProgress()); });
  }, {passive: true});
  $("scrub").addEventListener("input", () => {
    const progress = Number($("scrub").value) / 1000;
    $("scrollbox").scrollTop = progress * ($("scrollbox").scrollHeight - $("scrollbox").clientHeight);
    drawProgress(progress);
  });
  $("distance").addEventListener("change", () => { resetTrack(); drawProgress(scrollProgress()); });
  $("fit").addEventListener("change", () => { if (player) { player.fit = $("fit").value; player.draw(); } });
  $("motion").addEventListener("change", () => drawProgress(scrollProgress()));
  $("source-video").addEventListener("loadedmetadata", () => { $("source-video").currentTime = Number($("start").value); });
  $("source-video").addEventListener("error", () => {
    $("source-video").hidden = true; $("source-poster").hidden = false;
    $("video-note").textContent = "Your browser cannot play this source codec. Showing the first frame instead. You can still generate and review WebP assets.";
  });
  new ResizeObserver(resetTrack).observe($("scrollbox"));
  async function poll() {
    try { if (!posting) update(await api("/api/state")); }
    catch (_) { $("status").textContent = "Studio disconnected. Check that the local service is still running."; }
    setTimeout(poll, state.busy ? 700 : 1600);
  }
  resetTrack(); poll();
})();
