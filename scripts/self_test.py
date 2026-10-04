"""Meaningful processing and HTTP regression checks using generated, disposable media."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

from media import (MediaError, Runner, default_settings, export_pack, find_tools,
                   normalize, probe, render)
from studio import Handler, Studio, ThreadingHTTPServer


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="scroll-assets-test-")
        cls.root = Path(cls.tmp.name)
        cls.tools = find_tools()
        cls.source = cls.root / "source with spaces caf\u00e9.mp4"
        Runner().run([cls.tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y",
                      "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=3",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", cls.source])
        cls.meta = probe(cls.source, cls.tools)
        cls.settings = default_settings(cls.meta, 1, 2)
        cls.settings["variants"]["mobile"].update({"ratio": "9:16", "x": 1, "width": 80})
        cls.draft = cls.root / "r-primary"
        cls.manifest = render(cls.source, cls.meta, cls.settings, cls.draft, cls.tools,
                              Runner(), lambda *_: None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_01_end_exclusive_real_times_and_consistent_variants(self):
        result = self.manifest
        self.assertEqual(result["frameCount"], 30)
        self.assertAlmostEqual(result["sourceTimes"][0], 1)
        self.assertLess(result["sourceTimes"][-1], 2)
        self.assertEqual(result["sourceTimes"], sorted(set(result["sourceTimes"])))
        for variant in result["variants"].values():
            self.assertEqual(len(variant["frames"]), 30)
            self.assertTrue((self.draft / variant["contactSheet"]).is_file())
            self.assertTrue(all((self.draft / frame).is_file() for frame in variant["frames"]))
        self.assertEqual(result["variants"]["desktop"]["width"], 160)  # no upscale
        mobile = result["variants"]["mobile"]
        self.assertGreater(mobile["crop"]["x"], 0)
        self.assertLessEqual(mobile["width"], mobile["crop"]["width"])
        self.assertAlmostEqual(mobile["width"] / mobile["height"], 9 / 16, delta=0.015)

    def test_02_reject_invalid_intervals_and_nan(self):
        for overrides in ({"start": -1}, {"end": 9}, {"end": 1}, {"fps": float("nan")}, {"quality": 101}):
            value = copy.deepcopy(self.settings)
            value.update(overrides)
            with self.assertRaises(MediaError):
                normalize(value, self.meta)

    def test_03_reject_unapplied_export_settings(self):
        changed = copy.deepcopy(self.settings)
        changed["quality"] = 70
        with self.assertRaises(MediaError):
            export_pack(self.draft, self.root / "outputs", changed, self.manifest)
        self.assertFalse((self.root / "outputs").exists())

    def test_04_verified_portable_export(self):
        exported = export_pack(self.draft, self.root / "outputs", self.settings, self.manifest)
        folder = Path(exported["folder"])
        hashes = json.loads((folder / "checksums.json").read_text())
        with zipfile.ZipFile(exported["zip"]) as zipped:
            self.assertIsNone(zipped.testzip())
            for name, digest in hashes.items():
                self.assertEqual(hashlib.sha256(zipped.read(name)).hexdigest(), digest)
        self.assertFalse(any(p.suffix == ".mp4" for p in folder.rglob("*")))
        self.assertNotIn(str(self.source), (folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("confirmation.json", hashes)

    def test_05_variable_rate_does_not_fabricate_frames(self):
        vfr = self.root / "variable.mkv"
        Runner().run([self.tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y",
                      "-i", self.source, "-vf", "select='if(lt(t,1.5),1,not(mod(n,3)))'",
                      "-fps_mode", "vfr", "-c:v", "ffv1", vfr])
        meta = probe(vfr, self.tools)
        settings = default_settings(meta, 1, 2.5)
        settings["fps"] = 60  # cannot create more actual frames than exist
        settings["variants"]["mobile"]["enabled"] = False
        manifest = render(vfr, meta, settings, self.root / "r-vfr", self.tools, Runner(), lambda *_: None)
        self.assertEqual(manifest["frameCount"], 25)
        times = manifest["sourceTimes"]
        self.assertEqual(len(times), len(set(times)))
        self.assertTrue(any(times[i + 1] - times[i] > 0.09 for i in range(len(times) - 1)))

    def test_06_rotation_and_fractional_interval(self):
        rotated = self.root / "rotated.mp4"
        Runner().run([self.tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y",
                      "-display_rotation", "90", "-i", self.source, "-c", "copy", rotated])
        meta = probe(rotated, self.tools)
        self.assertEqual((meta["width"], meta["height"]), (90, 160))
        settings = default_settings(meta, 0.51, 0.99)
        settings["variants"]["mobile"]["enabled"] = False
        manifest = render(rotated, meta, settings, self.root / "r-rotate", self.tools, Runner(), lambda *_: None)
        self.assertGreaterEqual(manifest["sourceTimes"][0], 0.51)
        self.assertLess(manifest["sourceTimes"][-1], 0.99)
        self.assertEqual((manifest["variants"]["desktop"]["width"],
                          manifest["variants"]["desktop"]["height"]), (90, 160))

    def test_07_http_auth_range_and_stale_confirmation(self):
        app = Studio(self.root / "http", self.root / "http-outputs", self.tools)
        app.load_source(self.source, 1, 2)
        app.manifest, app.revision, app.settings = self.manifest, self.manifest["revisionId"], self.settings
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.app = app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            def request(path, payload=None, headers=None):
                return urllib.request.urlopen(urllib.request.Request(
                    base + path, data=json.dumps(payload).encode() if payload is not None else None,
                    headers=headers or {}), timeout=10)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                request("/api/state")
            self.assertEqual(denied.exception.code, 403)
            with request("/media/source", headers={"Range": "bytes=0-15"}) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 16)
            with self.assertRaises(urllib.error.HTTPError):
                request("/assets/../../scripts/studio.py")
            with self.assertRaises(urllib.error.HTTPError):
                request("/", headers={"Host": "attacker.example"})
            changed = copy.deepcopy(self.settings); changed["quality"] = 70
            for revision, setting in (("old-revision", self.settings), (app.revision, changed)):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    request("/api/confirm", {"revisionId": revision, "settings": setting},
                            {"Content-Type": "application/json", "X-Session-Token": app.token})
                self.assertEqual(denied.exception.code, 400)
            self.assertFalse(app.busy)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
