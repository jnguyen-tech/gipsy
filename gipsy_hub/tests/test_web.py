"""The hub serves the web version of the app (for iPhone/iPad Home Screen).

Run from gipsy_hub/:   python -m unittest tests.test_web
Each check starts a fresh Python so the hub looks for the web folder again.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]

PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
import gipsy_hub
c = TestClient(gipsy_hub.app)
out = {}
for path in ["/", "/index.html", "/manifest.json", "/api/kaiju"]:
    r = c.get(path)
    out[path] = [r.status_code, r.text[:200], r.headers.get("cache-control")]
print(json.dumps(out))
"""


def probe(web_dir: str) -> dict:
    data = tempfile.mkdtemp()
    env = dict(os.environ, GIPSY_DATA_DIR=data, GIPSY_WEB_DIR=web_dir)
    r = subprocess.run(
        [sys.executable, "-c", PROBE, str(HERE)], env=env, capture_output=True, text=True, timeout=120, cwd=data
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class WebAppTests(unittest.TestCase):
    def test_serves_built_app_and_keeps_api(self):
        web = tempfile.mkdtemp()
        Path(web, "index.html").write_text("<html>GIPSY WEB</html>", encoding="utf-8")
        Path(web, "manifest.json").write_text('{"name": "Gipsy"}', encoding="utf-8")
        out = probe(web)
        self.assertEqual(out["/"][0], 200)
        self.assertIn("GIPSY WEB", out["/"][1])
        self.assertEqual(out["/"][2], "no-cache")
        self.assertEqual(json.loads(out["/manifest.json"][1])["name"], "Gipsy")
        # The API still answers under the web app.
        self.assertEqual(out["/api/kaiju"][0], 200)
        self.assertIn("line", json.loads(out["/api/kaiju"][1]))

    def test_explains_when_not_installed(self):
        if (HERE / "web" / "index.html").is_file() or (HERE.parent / "gipsy_app" / "build" / "web" / "index.html").is_file():
            self.skipTest("a web build is installed on this machine")
        out = probe(tempfile.mkdtemp())  # empty folder: no index.html
        self.assertEqual(out["/"][0], 200)
        self.assertIn("install_web_app.bat", out["/"][1])


if __name__ == "__main__":
    unittest.main()
