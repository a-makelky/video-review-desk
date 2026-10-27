"""Tests for desk.py: the file store, its git commits, the HTTP API and its write guard, init, and the example."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("desk", HERE.parent / "desk.py")
desk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desk)


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout


class DeskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.proj = self.repo / "projects/launch/review"
        self.proj.mkdir(parents=True)
        (self.proj / "media").mkdir()
        (self.proj / "media/C01-v1.mp4").write_bytes(bytes(range(256)) * 4)
        (self.proj / "desk.json").write_text(json.dumps({"title": "Test", "media": "media", "clips": [
            {"id": "C01", "title": "One", "versions": [{"v": "v1", "file": "C01-v1.mp4"}]}, {"id": "C02", "title": "Two", "versions": []}]}))
        git(self.repo.parent, "init", "-q", str(self.repo))
        git(self.repo, "config", "user.name", "Test Person")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        (self.repo / "unrelated.txt").write_text("someone else's work in progress")  # must never be committed by the desk
        self.store = desk.Store(self.proj)

    def tearDown(self):
        self.tmp.cleanup()

    def test_note_lifecycle_is_files_and_commits(self):
        n = self.store.add("C02", "v2", 25.4, "The last word gets cut off", "Aaron")
        f = self.proj / "notes" / f"{n['id']}.json"
        self.assertEqual(json.loads(f.read_text())["text"], "The last word gets cut off")
        self.store.update(n["id"], by="codex", status="resolved", resolvedIn="v4", reply="Cut moved after the word")
        r = json.loads(f.read_text())
        self.assertEqual((r["status"], r["resolvedIn"], r["resolvedBy"]), ("resolved", "v4", "codex"))
        self.store.update(n["id"], status="open")
        self.assertNotIn("resolvedIn", json.loads(f.read_text()))
        log = git(self.repo, "log", "--format=%s").splitlines()
        self.assertEqual(log[:3], ["Reopen review note on C02 v2 at 0:25.4", "Resolve review note on C02 v2 at 0:25.4", "Review note on C02 v2 at 0:25.4"])
        self.assertIn("?? unrelated.txt", git(self.repo, "status", "--porcelain"))
        for body in git(self.repo, "log", "--format=%B").split("\n"):
            self.assertNotRegex(body.lower(), r"co-authored|generated with|claude")

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.add("C09", "v1", 1, "x", "a")
        with self.assertRaises(ValueError):
            self.store.add("C01", "v1/../x", 1, "x", "a")
        with self.assertRaises(ValueError):
            self.store.add("C01", "v1", 1, "   ", "a")
        n = self.store.add("C01", "v1", 1, "x", "a")
        with self.assertRaises(ValueError):
            self.store.update(n["id"], by="a", by_hand="no")
        with self.assertRaises(KeyError):
            self.store.note("../../etc")

    def test_approvals_and_import(self):
        exp = Path(self.tmp.name) / "export"
        (exp / "notes").mkdir(parents=True)
        (exp / "clips").mkdir()
        (exp / "notes/abc123.json").write_text(json.dumps({"by": "u_x", "clip": "C02", "createdAt": "2026-10-27T19:25:35.913Z",
                                                           "status": "open", "t": 1.8, "text": "dark plate", "version": "v2"}))
        (exp / "clips/C01.json").write_text(json.dumps({"id": "C01", "data": {"approval": "approved", "at": "2026-10-27T21:40:05Z", "by": "u_x", "version": "v3"}}))
        desk.import_export(self.store, exp, {"u_x": "Aaron"})
        desk.import_export(self.store, exp, {"u_x": "Aaron"})  # idempotent for notes
        self.assertEqual([(n["id"], n["by"]) for n in self.store.notes()], [("abc123", "Aaron")])
        self.assertEqual(self.store.approvals()["C01"]["at"], "2026-10-27T21:40:05Z")
        self.store.approve("C01", None, "v3", "Aaron")
        self.assertEqual(self.store.approvals(), {})

    def test_http_api_and_guard(self):
        srv = desk.Server(("127.0.0.1", 0), desk.make_handler(self.store, "Test Person"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(method, path, body=None, headers=None):
            req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json", **(headers or {})})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read(), dict(e.headers)
        try:
            st, b, _ = call("GET", "/")
            self.assertEqual(st, 200)
            self.assertTrue(b.startswith(b"<!doctype html>") and b'name="viewport"' in b and b"<title>Test</title>" in b)
            self.assertEqual(json.loads(call("GET", "/api/health")[1])["by"], "Test Person")
            st, b, _ = call("POST", "/api/notes", {"clip": "C01", "version": "v1", "t": 3.2, "text": "hi"})
            self.assertEqual(st, 403)  # no X-Desk header: a plain form post from another site can't write
            st, b, _ = call("POST", "/api/notes", {"clip": "C01", "version": "v1", "t": 3.2, "text": "hi"}, {"X-Desk": "1", "Origin": "https://evil.example"})
            self.assertEqual(st, 403)
            st, b, _ = call("POST", "/api/notes", {"clip": "C01", "version": "v1", "t": 3.2, "text": "hi"}, {"X-Desk": "1"})
            self.assertEqual(st, 201)
            nid = json.loads(b)["id"]
            self.assertEqual(json.loads(b)["by"], "Test Person")
            st, b, _ = call("POST", f"/api/notes/{nid}", {"status": "resolved", "resolvedIn": "v2", "by": "Grok"}, {"X-Desk": "1"})
            self.assertEqual(json.loads(b)["resolvedBy"], "Grok")
            self.assertEqual(call("POST", "/api/notes/zzz", {"status": "open"}, {"X-Desk": "1"})[0], 404)
            self.assertEqual(call("POST", "/api/approvals/C01", {"approval": "approved", "version": "v2"}, {"X-Desk": "1"})[0], 200)
            state = json.loads(call("GET", "/api/state")[1])
            self.assertEqual((len(state["notes"]), state["approvals"]["C01"]["approval"]), (1, "approved"))
            st, b, h = call("GET", "/media/C01-v1.mp4", headers={"Range": "bytes=10-19"})
            self.assertEqual((st, b, h["Content-Range"]), (206, bytes(range(10, 20)), "bytes 10-19/1024"))
            self.assertEqual(call("GET", "/media/../../etc/passwd")[0], 404)
            self.assertEqual(call("DELETE", f"/api/notes/{nid}", headers={"X-Desk": "1"})[0], 200)
        finally:
            srv.shutdown()
            srv.server_close()


class StandaloneTest(unittest.TestCase):
    def test_init_and_no_git(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "p"
            (d / "media").mkdir(parents=True)
            for n in ("hook-v1.mp4", "hook-v2.mp4", "outro-v1.webm", "notes.txt"):
                (d / "media" / n).write_bytes(b"x")
            desk.init_project(d, "media", "My cut")
            m = json.loads((d / "desk.json").read_text())
            self.assertEqual([(c["id"], [v["v"] for v in c["versions"]]) for c in m["clips"]], [("hook", ["v1", "v2"]), ("outro", ["v1"])])
            st = desk.Store(d)  # not a git repo: notes are saved, nothing is committed
            self.assertFalse(st.commit_on)
            n = st.add("hook", "v2", 0.5, "tighter", "me")
            self.assertTrue((d / "notes" / f"{n['id']}.json").exists())

    def test_no_commit_anywhere(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "desk.json").write_text(json.dumps({"clips": [{"id": "a", "versions": []}]}))
            desk.main(["--project", str(d), "add", "a", "v1", "1", "x", "--no-commit"])
            self.assertEqual(len(list((d / "notes").glob("*.json"))), 1)

    def test_example_renders(self):
        st = desk.Store(HERE.parent / "example", commit=False)
        html = desk.page.render(st.manifest())
        self.assertIn("Example project: review", html)
        self.assertEqual(len(st.notes()), 1)
        self.assertTrue(all((st.media_dir() / v["file"]).exists() for c in st.manifest()["clips"] for v in c["versions"]))


if __name__ == "__main__":
    unittest.main()
