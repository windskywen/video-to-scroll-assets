"""Run Scroll Asset Studio on loopback; all project assets stay in the selected workspace."""
from __future__ import annotations

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from media import (ROOT, MediaError, Runner, default_settings, export_pack, find_tools,
                   make_source_poster, normalize, probe, render, settings_hash, write_json)

MAX_UPLOAD = 10 * 1024**3


class SessionLock:
    """OS lock released automatically if the server exits or crashes."""
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = (directory / ".studio.lock").open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise MediaError("A service is already running for this session. Open the URL in its server.json or use a new work directory.")

    def close(self):
        self.stream.close()


class Studio:
    def __init__(self, workdir, output_dir, tools):
        self.workdir, self.output_dir, self.tools = workdir.resolve(), output_dir.resolve(), tools
        if self.output_dir.is_relative_to(self.workdir / "drafts"):
            raise MediaError("The export directory must not be inside the drafts directory.")
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "drafts").mkdir(exist_ok=True)
        (self.workdir / "incoming").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.source_path = None
        self.source = None
        self.settings = None
        self.manifest = None
        self.revision = None
        self.export = None
        self.busy = False
        self.message = "Choose a video, then set the interval to use."
        self.error = None
        self.percent = 0
        self.runner = Runner()

    def status(self):
        with self.lock:
            return {"source": self.source, "settings": self.settings, "manifest": self.manifest,
                    "revisionId": self.revision, "busy": self.busy, "message": self.message,
                    "error": self.error, "percent": self.percent, "export": self.export}

    def save(self):
        write_json(self.workdir / "session.json", {
            "sourcePath": str(self.source_path) if self.source_path else None,
            "sourceName": self.source["name"] if self.source else None,
            "settings": self.settings, "revisionId": self.revision,
            "outputDir": str(self.output_dir)
        })

    def update(self, message, percent):
        with self.lock:
            self.message, self.percent = message, percent

    def begin(self, message):
        with self.lock:
            if self.busy:
                raise MediaError("Processing is in progress. Wait for it to finish.")
            self.busy, self.error, self.percent, self.message = True, None, 0, message
            self.runner = Runner()

    def task(self, job):
        def worker():
            try:
                job()
            except Exception as error:
                with self.lock:
                    self.error, self.message = str(error), "Processing did not finish. Review the error and try again."
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=worker, daemon=True).start()

    def load_source(self, path, start=0, end=None, saved=None, display_name=None):
        meta = probe(path, self.tools, self.runner)
        if display_name:
            meta["name"] = str(display_name).replace("\\", "/").split("/")[-1][:255]
        setting = normalize(saved, meta) if saved else default_settings(meta, start, end)
        poster = self.workdir / ("poster-" + uuid.uuid4().hex + ".jpg")
        make_source_poster(path, poster, self.tools, self.runner)
        with self.lock:
            self.source_path, self.source, self.settings = Path(path).resolve(), meta, setting
            self.poster_path = poster
            self.manifest = self.revision = self.export = None
            self.message, self.percent, self.error = "Video loaded. Adjust your settings, then generate assets.", 0, None
            self.save()

    def build(self, data):
        with self.lock:
            if not self.source:
                raise MediaError("Load a video first.")
            setting = normalize(data, self.source)
            self.begin("Preparing to generate assets")
            source, meta = self.source_path, dict(self.source)
            revision = "r-" + uuid.uuid4().hex
        def job():
            result = render(source, meta, setting, self.workdir / "drafts" / revision,
                            self.tools, self.runner, self.update)
            with self.lock:
                self.settings, self.manifest, self.revision = setting, result, revision
                self.export = None
                self.save()
        self.task(job)

    def confirm(self, data):
        with self.lock:
            if not self.manifest or data.get("revisionId") != self.revision:
                raise MediaError("The preview revision has changed. Review it again.")
            setting = normalize(data.get("settings"), self.source)
            if settings_hash(setting, self.source["sha256"]) != self.manifest["settingsHash"]:
                raise MediaError("Settings have unapplied changes. Regenerate the assets before confirming.")
            self.begin("Packaging the confirmed assets")
            revision, manifest = self.revision, self.manifest
        def job():
            result = export_pack(self.workdir / "drafts" / revision, self.output_dir, setting, manifest)
            result["url"] = "/exports/" + result["name"] + ".zip"
            result["previewUrl"] = "/exports/" + result["name"] + "/preview.html"
            with self.lock:
                self.export = result
                self.message, self.percent = "Assets confirmed. The export folder and ZIP have been verified.", 100
        self.task(job)


def contained(root, relative):
    root = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise MediaError("File not found.")
    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "ScrollAssetStudio/1.0"

    @property
    def app(self):
        return self.server.app

    def log_message(self, format, *args):
        if args and str(args[0]).startswith("POST"):
            print(format % args, flush=True)

    def send_headers(self, code, content_type, length=None, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def check(self, token=False):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != host:
            raise MediaError("Only this studio's loopback address is accepted.")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise MediaError("Cross-origin request rejected.")
        if token and not secrets.compare_digest(self.headers.get("X-Session-Token", ""), self.app.token):
            raise MediaError("This session is no longer valid. Refresh the page.")

    def file(self, path, head=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        request_range = self.headers.get("Range")
        extra = {"Accept-Ranges": "bytes"}
        if request_range:
            found = re.fullmatch(r"bytes=(\d*)-(\d*)", request_range)
            if not found or (not found[1] and not found[2]):
                self.send_headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            if found[1]:
                start = int(found[1])
                end = min(end, int(found[2])) if found[2] else end
            else:
                start = max(0, size - int(found[2]))
            if start > end or start >= size:
                self.send_headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        if path.suffix == ".zip":
            extra["Content-Disposition"] = f'attachment; filename="{path.name}"'
        content_type = {".js": "text/javascript", ".webp": "image/webp"}.get(
            path.suffix, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_headers(status, content_type, max(0, end - start + 1), extra)
        if not head:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        try:
            self.check()
            route = unquote(urlsplit(self.path).path)
            if route == "/":
                html = (ROOT / "assets" / "index.html").read_text(encoding="utf-8")
                data = html.replace("__SESSION_TOKEN__", self.app.token).encode("utf-8")
                self.send_headers(200, "text/html; charset=utf-8", len(data))
                if not head:
                    self.wfile.write(data)
            elif route == "/api/state":
                self.check(token=True)
                self.json(self.app.status())
            elif route.startswith("/assets/"):
                self.file(contained(ROOT / "assets", route[len("/assets/"):]), head)
            elif route.startswith("/drafts/"):
                self.file(contained(self.app.workdir / "drafts", route[len("/drafts/"):]), head)
            elif route.startswith("/exports/"):
                self.file(contained(self.app.output_dir, route[len("/exports/"):]), head)
            elif route == "/media/source" and self.app.source_path:
                self.file(self.app.source_path, head)
            elif route == "/media/poster" and self.app.source:
                self.file(self.app.poster_path, head)
            elif route == "/favicon.ico":
                self.send_headers(204, "image/x-icon", 0)
            else:
                self.json({"error": "Page not found."}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except MediaError as error:
            self.json({"error": str(error)}, 403)
        except Exception:
            self.json({"error": "Cannot read this file."}, 500)

    def do_POST(self):
        try:
            self.check(token=True)
            parsed = urlsplit(self.path)
            if parsed.path == "/api/upload":
                return self.upload(parsed)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise MediaError("Use JSON format.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 128 * 1024:
                raise MediaError("Invalid request size.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise MediaError("Request must be a JSON object.")
            if parsed.path == "/api/render":
                self.app.build(data)
            elif parsed.path == "/api/confirm":
                self.app.confirm(data)
            elif parsed.path == "/api/stop":
                self.app.runner.cancel()
                self.json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.json({"error": "Unsupported operation."}, 404)
                return
            self.json(self.app.status(), 202)
        except (MediaError, ValueError, TypeError, KeyError) as error:
            self.json({"error": str(error)}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as error:
            self.json({"error": str(error)}, 500)

    def upload(self, parsed):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_UPLOAD:
            raise MediaError("Choose a video smaller than 10 GB.")
        self.app.begin("Loading video")
        original_name = parse_qs(parsed.query).get("name", ["video.mp4"])[0]
        extension = Path(original_name).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
            extension = ".video"
        path = self.app.workdir / "incoming" / (uuid.uuid4().hex + extension)
        try:
            remaining = length
            with path.open("xb") as stream:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise MediaError("Video upload interrupted.")
                    stream.write(chunk)
                    remaining -= len(chunk)
            self.app.task(lambda: self.app.load_source(path, display_name=original_name))
            self.json(self.app.status(), 202)
        except Exception:
            with self.app.lock:
                self.app.busy = False
            if path.is_file():
                path.unlink()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Local source video; optional with browser upload.")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--settings", type=Path, help="settings.json from an earlier asset pack")
    parser.add_argument("--workdir", type=Path, default=Path.cwd() / "work" / "scroll-assets")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "outputs" / "scroll-assets")
    parser.add_argument("--port", type=int, default=0, help="0 selects an available loopback port")
    parser.add_argument("--check", action="store_true", help="Check runtime without starting a server")
    args = parser.parse_args()
    session_lock = None
    try:
        tools = find_tools()
        if args.check:
            runner = Runner()
            for name, path in tools.items():
                print(runner.run([path, "-version"]).splitlines()[0])
            return
        session_lock = SessionLock(args.workdir.resolve())
        app = Studio(args.workdir, args.output_dir, tools)
        saved = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else None
        if args.source:
            app.load_source(args.source, args.start, args.end, saved)
        elif (app.workdir / "session.json").is_file():
            session = json.loads((app.workdir / "session.json").read_text(encoding="utf-8"))
            if session.get("sourcePath") and Path(session["sourcePath"]).is_file():
                app.load_source(Path(session["sourcePath"]), saved=saved or session.get("settings"),
                                display_name=session.get("sourceName"))
                previous = session.get("revisionId")
                if previous and re.fullmatch(r"r-[0-9a-f]{32}", previous):
                    manifest_path = app.workdir / "drafts" / previous / "manifest.json"
                    if manifest_path.is_file():
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if manifest["settingsHash"] == settings_hash(app.settings, app.source["sha256"]):
                            app.manifest, app.revision = manifest, previous
                            app.message = "Previous assets restored. Continue reviewing or change the settings."
                            app.save()
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        server.daemon_threads = True
        server.app = app
        url = f"http://127.0.0.1:{server.server_port}/"
        write_json(app.workdir / "server.json", {
            "url": url, "pid": os.getpid(), "startedAt": datetime.now().isoformat()
        })
        print(json.dumps({"url": url, "pid": os.getpid(), "workdir": str(app.workdir),
                          "outputDir": str(app.output_dir)}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            app.runner.cancel()
            server.server_close()
    except (MediaError, ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
    except KeyboardInterrupt:
        pass
    finally:
        if session_lock:
            session_lock.close()


if __name__ == "__main__":
    main()
