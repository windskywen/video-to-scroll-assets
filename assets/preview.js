(() => {
  const pack = window.SCROLL_PACK, $ = id => document.getElementById(id);
  let player = null, queued = false;
  $("motion").checked = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  $("info").textContent = pack.source.name + " · " + pack.range.start + "–" + pack.range.end + " s · " + pack.frameCount + " real source frames";
  for (const key of Object.keys(pack.variants)) {
    const option = document.createElement("option"); option.value = key;
    option.textContent = key === "desktop" ? "Desktop" : "Mobile"; $("variant").append(option);
  }
  function progress() {
    return $("scrollbox").scrollTop / Math.max(1, $("scrollbox").scrollHeight - $("scrollbox").clientHeight);
  }
  function draw() {
    const p = progress(); $("scrub").value = Math.round(p * 1000);
    if (player) player.setProgress($("motion").checked ? p : 0);
  }
  function resize() { $("track").style.height = ($("scrollbox").clientHeight + Number($("distance").value)) + "px"; }
  function select() {
    if (player) player.dispose();
    const key = $("variant").value, spec = pack.variants[key];
    $("canvas").classList.toggle("mobile", key === "mobile");
    player = new ScrollSequence($("canvas"), pack, key, "./", frame => {
      $("position").textContent = (frame.target + 1) + " / " + pack.frameCount + " · " + frame.sourceTime.toFixed(3) + "s" + (frame.error ? " · Image failed" : frame.loading ? " · Loading" : "");
    });
    $("stats").textContent = spec.width + " × " + spec.height + " px · " + (spec.bytes / 1024 / 1024).toFixed(2) + " MB · WebP";
    draw();
  }
  $("variant").addEventListener("change", select);
  $("distance").addEventListener("change", () => { resize(); draw(); });
  $("motion").addEventListener("change", draw);
  $("scrollbox").addEventListener("scroll", () => {
    if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; draw(); }); }
  }, {passive:true});
  $("scrub").addEventListener("input", () => {
    $("scrollbox").scrollTop = Number($("scrub").value) / 1000 * ($("scrollbox").scrollHeight - $("scrollbox").clientHeight); draw();
  });
  new ResizeObserver(resize).observe($("scrollbox"));
  resize(); select();
})();
