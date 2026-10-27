"""Video review desk: timecoded notes and approvals for video versions, kept as plain JSON files you can commit.

A project is a folder with a desk.json manifest (the clips and their versions, see page.py) next to:
  notes/<id>.json       {id, clip, version, t (s), text, status: "open"|"resolved", by, createdAt, updatedAt,
                         resolvedIn?, reply?, resolvedBy?}
  approvals/<clip>.json {clip, approval: "approved"|"changes", version, by, at}
One file per record, so two people (or agents) writing at once never conflict in git.

Commands (--project DIR, default: the nearest folder up from here with a desk.json):
  init DIR --media MEDIA_DIR [--title T]   Scaffold desk.json from video files named <clip>-<version>.mp4.
  serve [--port 8765] [--lan] [--push] [--no-commit]
        The review page with the videos, at http://localhost:8765/. Inside a git repo every change is committed
        (only the desk's files); --push pushes after each commit. --lan listens on the local network.
  notes [--clip ID] [--open] [--json]
  add CLIP VERSION SECONDS TEXT [--by NAME]
  resolve ID --in VERSION [--reply TEXT] [--by NAME]     reopen ID     reply ID TEXT [--by NAME]
  approve CLIP --version VERSION [--changes] [--clear] [--by NAME]
  import PATH [--by-map OLD=New ...]   Records exported one per JSON file ({"id", "data": {...}} or bare objects).
  sync [--push]   Commit desk files edited by hand, pull --rebase, push with --push.

Python 3.9+ standard library only. MIT License.
"""
import argparse
import datetime
import http.server
import json
import os
import re
import secrets
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page  # noqa: E402

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VER_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
MEDIA_RE = re.compile(r"^[A-Za-z0-9._-]+\.(mp4|m4v|mov|webm)$", re.I)
NAMED_RE = re.compile(r"^(?P<clip>[A-Za-z0-9_-]+?)-(?P<v>v\d+)\.(mp4|m4v|mov|webm)$", re.I)
LOCK = threading.Lock()
SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            'initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);'
            'padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}'
            '[hidden]{display:none!important}</style></head><body>')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fmt(t):
    m = int(t // 60)
    return f"{m}:{t - 60 * m:04.1f}"


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def git_root(p):
    r = git(p, "rev-parse", "--show-toplevel", check=False)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def find_project(arg):
    if arg:
        return Path(arg).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "desk.json").exists():
            return p
    raise SystemExit("no desk.json here or above; pass --project DIR or run `desk.py init`")


class Store:
    def __init__(self, project, commit=True, push=False):
        self.dir = Path(project).resolve()
        self.manifest_path = self.dir / "desk.json"
        if not self.manifest_path.exists():
            raise SystemExit(f"{self.manifest_path} not found")
        self.repo = git_root(self.dir)
        self.commit_on, self.push_on = commit and self.repo is not None, push
        for sub in ("notes", "approvals"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)

    def manifest(self):
        return json.loads(self.manifest_path.read_text())

    def media_dir(self):
        m = Path(os.path.expanduser(self.manifest().get("media", "media")))
        return m if m.is_absolute() else self.dir / m

    @property
    def clips(self):
        return {c["id"] for c in self.manifest()["clips"]}

    # ---- reads
    def notes(self):
        out = []
        for f in sorted((self.dir / "notes").glob("*.json")):
            try:
                out.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                print(f"!! unreadable note file {f}", file=sys.stderr)
        return sorted(out, key=lambda n: (n.get("clip", ""), n.get("version", ""), n.get("t", 0)))

    def approvals(self):
        return {f.stem: json.loads(f.read_text()) for f in sorted((self.dir / "approvals").glob("*.json"))}

    def note(self, nid):
        f = self.dir / "notes" / f"{nid}.json"
        if not ID_RE.match(nid) or not f.exists():
            raise KeyError(nid)
        return json.loads(f.read_text())

    def stamp(self):
        """Changes whenever any desk file changes; the page polls it."""
        fs = [*(self.dir / "notes").glob("*.json"), *(self.dir / "approvals").glob("*.json"), self.manifest_path]
        return f"{len(fs)}-{max((f.stat().st_mtime_ns for f in fs), default=0)}"

    # ---- writes
    def _write(self, path, data, message):
        with LOCK:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
            tmp.replace(path)
            self._commit([path], message)

    def _remove(self, path, message):
        with LOCK:
            if path.exists():
                path.unlink()
                self._commit([path], message)

    def _commit(self, paths, message):
        if not self.commit_on:
            return
        rel = [str(p.relative_to(self.repo)) for p in paths]
        git(self.repo, "add", "-A", "--", *rel)
        if git(self.repo, "diff", "--cached", "--quiet", "--", *rel, check=False).returncode == 0:
            return
        r = git(self.repo, "commit", "-q", "-m", message, "--", *rel, check=False)
        if r.returncode:
            print("!! commit failed: " + (r.stderr or r.stdout).strip(), file=sys.stderr)
            return
        if self.push_on:
            threading.Thread(target=self._push, daemon=True).start()

    def _push(self):
        with LOCK:
            r = git(self.repo, "push", "-q", check=False)
            if r.returncode:
                r = git(self.repo, "pull", "-q", "--rebase", "--autostash", check=False)
                r = r if r.returncode else git(self.repo, "push", "-q", check=False)
            if r.returncode:
                print("!! push failed (the notes are committed locally): " + r.stderr.strip(), file=sys.stderr)

    def check(self, clip, version=None, t=None):
        if clip not in self.clips:
            raise ValueError(f"unknown clip {clip!r}")
        if version is not None and not VER_RE.match(str(version)):
            raise ValueError(f"bad version {version!r}")
        if t is not None and not (0 <= float(t) < 36000):
            raise ValueError("t must be seconds into the clip")

    def add(self, clip, version, t, text, by, nid=None, created=None):
        self.check(clip, version, t)
        text = str(text).strip()
        if not text:
            raise ValueError("empty note")
        nid = nid or secrets.token_hex(6)
        if not ID_RE.match(nid):
            raise ValueError("bad id")
        n = dict(id=nid, clip=clip, version=version, t=round(float(t), 2), text=text[:4000], status="open",
                 by=by or "unknown", createdAt=created or now(), updatedAt=now())
        self._write(self.dir / "notes" / f"{nid}.json", n, f"Review note on {clip} {version} at {fmt(n['t'])}")
        return n

    def update(self, nid, by=None, **patch):
        n = self.note(nid)
        for k, v in patch.items():
            if k not in {"status", "text", "resolvedIn", "reply", "t"}:
                raise ValueError(f"field {k!r} can't be changed")
            if v is None:
                n.pop(k, None)
            else:
                n[k] = v
        if n.get("status") not in ("open", "resolved"):
            raise ValueError("status is open or resolved")
        if n["status"] == "resolved":
            if "resolvedIn" in n and not VER_RE.match(str(n["resolvedIn"])):
                raise ValueError("bad resolvedIn version")
            n.setdefault("resolvedBy", by or "unknown")
        else:
            for k in ("resolvedIn", "resolvedBy"):
                n.pop(k, None)
        n["updatedAt"] = now()
        what = "Resolve" if patch.get("status") == "resolved" else "Reopen" if patch.get("status") == "open" else "Edit"
        self._write(self.dir / "notes" / f"{nid}.json", n, f"{what} review note on {n['clip']} {n['version']} at {fmt(n['t'])}")
        return n

    def delete(self, nid):
        n = self.note(nid)
        self._remove(self.dir / "notes" / f"{nid}.json", f"Delete review note on {n['clip']} {n['version']} at {fmt(n['t'])}")

    def approve(self, clip, approval, version, by, at=None):
        self.check(clip, version)
        path = self.dir / "approvals" / f"{clip}.json"
        if approval is None:
            self._remove(path, f"Clear the approval on {clip}")
            return None
        if approval not in ("approved", "changes"):
            raise ValueError("approval is approved or changes")
        a = dict(clip=clip, approval=approval, version=version, by=by or "unknown", at=at or now())
        self._write(path, a, f"{'Approve' if approval == 'approved' else 'Request changes on'} {clip} {version}")
        return a

    def sync(self, push):
        if self.repo is None:
            raise SystemExit("not in a git repo")
        with LOCK:
            rel = str(self.dir.relative_to(self.repo))
            git(self.repo, "add", "-A", "--", rel)
            if git(self.repo, "diff", "--cached", "--quiet", "--", rel, check=False).returncode:
                git(self.repo, "commit", "-q", "-m", "Review desk edits", "--", rel)
            r = git(self.repo, "pull", "-q", "--rebase", "--autostash", check=False)
            if r.returncode:
                raise SystemExit("pull failed: " + r.stderr)
            if push:
                git(self.repo, "push", "-q")


# ---------------------------------------------------------------- server
def make_handler(store, default_by):
    class H(http.server.BaseHTTPRequestHandler):
        server_version = "VideoReviewDesk/1"

        def log_message(self, fmt_, *a):
            if not self.path.startswith("/api/state"):
                sys.stderr.write("%s %s\n" % (self.command, self.path))

        def send_bytes(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, obj, code=200):
            self.send_bytes(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 100_000:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def guard(self):
            # Writes only from the desk page itself: other sites can't post to this localhost port.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
                self.send_json(dict(error="cross-origin write refused"), 403)
                return False
            if self.headers.get("X-Desk") != "1":
                self.send_json(dict(error="missing X-Desk header"), 403)
                return False
            return True

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                return self.send_bytes((SKELETON + page.render(store.manifest()) + "</body></html>").encode(), "text/html; charset=utf-8")
            if path == "/api/health":
                remote = git(store.repo, "remote", "get-url", "origin", check=False).stdout.strip() if store.repo else ""
                where = str(store.dir.relative_to(store.repo)) if store.repo else store.dir.name
                return self.send_json(dict(ok=True, store=where, by=default_by, repo=remote))
            if path == "/api/state":
                return self.send_json(dict(stamp=store.stamp(), notes=store.notes(), approvals=store.approvals()))
            if path.startswith("/media/") and MEDIA_RE.match(path[7:]):
                return self.file(store.media_dir() / path[7:])
            self.send_json(dict(error="not found"), 404)

        def do_POST(self):
            if not self.guard():
                return
            path = urlparse(self.path).path
            try:
                b = self.body()
                if path == "/api/notes":
                    return self.send_json(store.add(b.get("clip"), b.get("version"), b.get("t"), b.get("text", ""), b.get("by") or default_by), 201)
                m = re.match(r"^/api/notes/([A-Za-z0-9_-]+)$", path)
                if m:
                    by = b.pop("by", None) or default_by
                    return self.send_json(store.update(m.group(1), by=by, **b))
                m = re.match(r"^/api/approvals/([A-Za-z0-9_-]{1,64})$", path)
                if m:
                    return self.send_json(store.approve(m.group(1), b.get("approval"), b.get("version"), b.get("by") or default_by) or {})
            except KeyError:
                return self.send_json(dict(error="no such note"), 404)
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                return self.send_json(dict(error=str(e)), 400)
            self.send_json(dict(error="not found"), 404)

        def do_DELETE(self):
            if not self.guard():
                return
            m = re.match(r"^/api/notes/([A-Za-z0-9_-]+)$", urlparse(self.path).path)
            if not m:
                return self.send_json(dict(error="not found"), 404)
            try:
                store.delete(m.group(1))
            except KeyError:
                return self.send_json(dict(error="no such note"), 404)
            self.send_json(dict(ok=True))

        def file(self, f):
            if not f.exists():
                return self.send_json(dict(error=f"missing {f.name}"), 404)
            size = f.stat().st_size
            start, end = 0, size - 1
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            ext = f.suffix.lower()
            self.send_header("Content-Type", {".webm": "video/webm", ".mov": "video/quicktime"}.get(ext, "video/mp4"))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return H


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def reviewer_name(store):
    if store.repo:
        n = git(store.repo, "config", "user.name", check=False).stdout.strip()
        if n:
            return n
    return os.environ.get("USER", "reviewer")


# ---------------------------------------------------------------- CLI
def init_project(d, media, title):
    d = Path(d).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    mdir = Path(os.path.expanduser(media))
    mabs = mdir if mdir.is_absolute() else (d / mdir)
    clips = {}
    for f in sorted(mabs.iterdir()) if mabs.exists() else []:
        m = NAMED_RE.match(f.name)
        if m:
            clips.setdefault(m["clip"], []).append(dict(v=m["v"].lower(), file=f.name))
    if not clips:
        raise SystemExit(f"no videos named <clip>-v<N>.mp4 in {mabs}")
    man = dict(title=title or d.name, heading=title or d.name, media=str(media),
               clips=[dict(id=k, title=k, versions=sorted(v, key=lambda x: int(x["v"][1:]))) for k, v in clips.items()])
    (d / "desk.json").write_text(json.dumps(man, indent=1) + "\n")
    print(f"wrote {d / 'desk.json'}: {len(clips)} clips, {sum(len(v) for v in clips.values())} versions")


def import_export(store, path, by_map):
    files = [path] if path.is_file() else sorted(path.rglob("*.json"))
    n_notes = n_appr = 0
    for f in files:
        raw = json.loads(f.read_text())
        for rec in raw if isinstance(raw, list) else [raw]:
            d = rec.get("data", rec)
            rid = rec.get("id") or f.stem
            by = by_map.get(d.get("by"), d.get("by") or "unknown")
            if "approval" in d:
                store.approve(d.get("clip") or rid, d["approval"], d["version"], by, at=d.get("at"))
                n_appr += 1
                continue
            if (store.dir / "notes" / f"{rid}.json").exists():
                continue
            n = store.add(d["clip"], d["version"], d["t"], d["text"], by, nid=rid, created=d.get("createdAt"))
            if d.get("status") == "resolved" or d.get("reply"):
                store.update(n["id"], by=by_map.get(d.get("resolvedBy"), d.get("resolvedBy") or by), status=d.get("status", "open"),
                             **{k: d[k] for k in ("resolvedIn", "reply") if d.get(k)})
            n_notes += 1
    print(f"imported {n_notes} notes and {n_appr} approvals")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project")
    ap.add_argument("--no-commit", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("dir")
    s.add_argument("--media", default="media")
    s.add_argument("--title")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--lan", action="store_true")
    s.add_argument("--push", action="store_true")
    s = sub.add_parser("notes")
    s.add_argument("--clip")
    s.add_argument("--open", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("add")
    s.add_argument("clip")
    s.add_argument("version")
    s.add_argument("t", type=float)
    s.add_argument("text")
    s.add_argument("--by")
    s = sub.add_parser("resolve")
    s.add_argument("id")
    s.add_argument("--in", dest="resolved_in", required=True)
    s.add_argument("--reply")
    s.add_argument("--by")
    s = sub.add_parser("reopen")
    s.add_argument("id")
    s = sub.add_parser("reply")
    s.add_argument("id")
    s.add_argument("text")
    s.add_argument("--by")
    s = sub.add_parser("approve")
    s.add_argument("clip")
    s.add_argument("--version", required=True)
    s.add_argument("--changes", action="store_true")
    s.add_argument("--clear", action="store_true")
    s.add_argument("--by")
    s = sub.add_parser("import")
    s.add_argument("path")
    s.add_argument("--by-map", nargs="*", default=[])
    s = sub.add_parser("sync")
    s.add_argument("--push", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--no-commit" in argv:  # a global option, accepted anywhere on the line
        argv = ["--no-commit"] + [x for x in argv if x != "--no-commit"]
    a = ap.parse_args(argv)

    if a.cmd == "init":
        return init_project(a.dir, a.media, a.title)
    store = Store(find_project(a.project), commit=not a.no_commit, push=getattr(a, "push", False))
    me = reviewer_name(store)

    if a.cmd == "serve":
        srv = Server(("0.0.0.0" if a.lan else "127.0.0.1", a.port), make_handler(store, me))
        mode = "committed and pushed" if store.commit_on and store.push_on else "committed" if store.commit_on else "saved (not committed)"
        print(f"Review desk: http://localhost:{a.port}/  (notes {mode} in {store.dir})", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    if a.cmd == "notes":
        ns = [n for n in store.notes() if (not a.clip or n["clip"] == a.clip) and (not a.open or n["status"] == "open")]
        if a.json:
            print(json.dumps(dict(notes=ns, approvals=store.approvals()), indent=1, ensure_ascii=False))
            return
        for n in ns:
            tail = f"  -> resolved in {n.get('resolvedIn', '?')}: {n.get('reply', '')}" if n["status"] == "resolved" else ""
            print(f"{n['id']}  {n['clip']} {n['version']} {fmt(n['t']):>6}  [{n['status']}] {n['text']}  ({n['by']}){tail}")
        for c, ap_ in store.approvals().items():
            if not a.clip or c == a.clip:
                print(f"approval  {c} {ap_['approval']} at {ap_['version']} ({ap_['by']})")
        return
    try:
        if a.cmd == "add":
            out = store.add(a.clip, a.version, a.t, a.text, a.by or me)
        elif a.cmd == "resolve":
            out = store.update(a.id, by=a.by or me, status="resolved", resolvedIn=a.resolved_in, **({"reply": a.reply} if a.reply else {}))
        elif a.cmd == "reopen":
            out = store.update(a.id, status="open")
        elif a.cmd == "reply":
            out = store.update(a.id, by=a.by or me, reply=a.text)
        elif a.cmd == "approve":
            out = store.approve(a.clip, None if a.clear else "changes" if a.changes else "approved", a.version, a.by or me)
        elif a.cmd == "import":
            return import_export(store, Path(a.path).expanduser(), dict(x.split("=", 1) for x in a.by_map))
        else:
            return store.sync(a.push)
        print(json.dumps(out, ensure_ascii=False))
    except KeyError as e:
        raise SystemExit(f"no note {e}")
    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
