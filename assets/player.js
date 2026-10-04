/* Bounded, target-first sequence renderer. No framework or network dependency. */
(() => {
  class ScrollSequence {
    constructor(canvas, manifest, variant, base, onFrame = () => {}) {
      this.canvas = canvas;
      this.context = canvas.getContext("2d");
      this.manifest = manifest;
      this.variant = manifest.variants[variant];
      this.base = base;
      this.onFrame = onFrame;
      this.cache = new Map();
      this.pending = new Map();
      this.failed = new Set();
      this.capacity = Math.max(1, Math.min(16, Math.floor(48 * 1024 * 1024 / this.variant.decodedBytesPerFrame)));
      this.target = 0;
      this.progress = 0;
      this.fit = "contain";
      this.poster = new Image();
      this.poster.onload = () => this.draw();
      this.poster.src = base + this.variant.poster;
      this.observer = new ResizeObserver(() => this.draw());
      this.observer.observe(canvas);
      this.setProgress(0);
    }
    setProgress(progress) {
      if (this.disposed) return;
      this.progress = Math.max(0, Math.min(1, progress));
      const time = this.progress * this.manifest.duration;
      const times = this.manifest.relativeTimes;
      let low = 0, high = times.length;
      while (low < high) {
        const mid = (low + high) >> 1;
        if (times[mid] <= time + 1e-8) low = mid + 1;
        else high = mid;
      }
      this.target = this.progress === 1 ? times.length - 1 : Math.max(0, low - 1);
      this.draw();
      this.pump();
    }
    wanted() {
      const indices = [this.target];
      for (let step = 1; step <= 3; step++) {
        if (this.target + step < this.manifest.frameCount) indices.push(this.target + step);
        if (this.target - step >= 0) indices.push(this.target - step);
      }
      return indices.slice(0, this.capacity);
    }
    pump() {
      if (this.disposed) return;
      const wanted = this.wanted();
      for (const index of wanted) {
        if (this.pending.size >= 2) break;
        if (this.cache.has(index) || this.pending.has(index) || this.failed.has(index)) continue;
        const image = new Image();
        this.pending.set(index, image);
        image.onload = async () => {
          try { if (image.decode) await image.decode(); } catch (_) { /* onload already decoded */ }
          if (this.disposed) return;
          this.pending.delete(index);
          this.cache.set(index, image);
          this.trim();
          this.draw();
          this.pump();
        };
        image.onerror = () => {
          if (this.disposed) return;
          this.pending.delete(index);
          this.failed.add(index);
          this.draw();
          this.pump();
        };
        image.src = this.base + this.variant.frames[index];
      }
    }
    trim() {
      while (this.cache.size > this.capacity) {
        const candidates = [...this.cache.keys()].sort((a, b) => Math.abs(b - this.target) - Math.abs(a - this.target));
        this.cache.delete(candidates[0]);
      }
    }
    draw() {
      if (this.disposed) return;
      const rect = this.canvas.getBoundingClientRect();
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.round(rect.width * pixelRatio));
      const height = Math.max(1, Math.round(rect.height * pixelRatio));
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      const keys = [...this.cache.keys()];
      const shown = keys.includes(this.target) ? this.target :
        keys.sort((a, b) => Math.abs(a - this.target) - Math.abs(b - this.target))[0];
      const image = shown !== undefined ? this.cache.get(shown) : this.poster;
      this.context.fillStyle = "#101718";
      this.context.fillRect(0, 0, width, height);
      if (image && image.complete && image.naturalWidth) {
        const scale = this.fit === "cover"
          ? Math.max(width / image.naturalWidth, height / image.naturalHeight)
          : Math.min(width / image.naturalWidth, height / image.naturalHeight);
        const w = image.naturalWidth * scale, h = image.naturalHeight * scale;
        this.context.drawImage(image, (width - w) / 2, (height - h) / 2, w, h);
      }
      this.canvas.dataset.targetFrame = String(this.target);
      this.canvas.dataset.shownFrame = shown === undefined ? "poster" : String(shown);
      this.onFrame({
        target: this.target, shown, loading: shown !== this.target,
        error: this.failed.has(this.target), progress: this.progress,
        sourceTime: this.manifest.sourceTimes[this.target]
      });
    }
    dispose() {
      this.disposed = true;
      this.observer.disconnect();
      for (const image of this.pending.values()) { image.onload = image.onerror = null; image.src = ""; }
      this.pending.clear();
      this.cache.clear();
      this.poster.onload = null;
    }
  }
  window.ScrollSequence = ScrollSequence;
})();
