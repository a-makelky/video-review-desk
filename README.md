# video-review-desk

Timecoded video review where every note is a JSON file in your repo.

Pause a clip, write a note, and it's saved as `notes/<id>.json`, pinned to that clip, that version and that second. Whoever fixes it renders the next version and marks the note resolved with the version that fixed it. Anyone with the repo can do that part: a teammate on GitHub, a script, or a coding agent like Codex, Claude Code or Gemini CLI. They read the same files and run the same commands.

One Python file serves the page and your videos on localhost. It runs on Python 3.9 or newer with only the standard library, so there's nothing to install or sign up for.

## Try it

```bash
git clone https://github.com/a-makelky/video-review-desk
cd video-review-desk
python3 desk.py --project example serve
```

Open http://localhost:8765/. The example has two clips with two versions each and one resolved note.

## Review your own videos

Name each render `<clip>-v<N>.mp4` (also `.mov`, `.m4v`, `.webm`) and put them in one folder:

```
review/
  media/
    hook-v1.mp4
    hook-v2.mp4
    walkthrough-v1.mp4
```

Then:

```bash
python3 desk.py init review --media media --title "Launch video"
python3 desk.py --project review serve --push
```

`init` writes `review/desk.json`, listing each clip and its versions. Edit it to add titles or a short "why this clip" line. When you render a new version, add it to the clip's `versions` list (or run `init` again), and the page picks it up on reload.

## What gets saved

```
review/
  desk.json               clips and versions
  notes/<id>.json         one note
  approvals/<clip>.json   approved, or changes requested, for one clip
```

A note:

```json
{
 "id": "3f9a1c2b7d10",
 "clip": "hook",
 "version": "v1",
 "t": 1.5,
 "text": "Captions cover the face here; move them lower.",
 "status": "resolved",
 "by": "Sam",
 "resolvedIn": "v2",
 "reply": "Caption band moved to the bottom in v2.",
 "resolvedBy": "Editor"
}
```

One file per record means two people can leave notes at once and git merges them without conflicts.

If the project folder is inside a git repo, every change from the page or the CLI is committed on its own, with a message like `Review note on hook v1 at 0:01.5`. Only the desk's files go into these commits. Pass `--push` to push after each one. Outside a repo, the files are still saved; nothing is committed.

## Working the notes from a terminal (or an agent)

```bash
python3 desk.py --project review notes --open                 # what's left to fix
python3 desk.py --project review notes --json                 # the same, for scripts
python3 desk.py --project review resolve 3f9a1c2b7d10 --in v2 --reply "Moved the captions down" --by Editor
python3 desk.py --project review reply 3f9a1c2b7d10 "Keeping this one, the logo needs the space" --by Editor
python3 desk.py --project review add hook v2 3.2 "Music comes in late" --by Sam
python3 desk.py --project review approve hook --version v2
```

To hand the fixes to a coding agent, point it at the project folder and this README. The loop is: list open notes, make each fix, render the next version, add it to `desk.json`, and resolve each note with `--in` set to the new version.

Some agent sandboxes can't write inside `.git`. Run their commands with `--no-commit`, then run `python3 desk.py --project review sync --push` from a normal shell to commit and push their changes.

## Phones and other reviewers

- `serve --lan` listens on your local network, so a phone on the same Wi-Fi can open `http://<your-computer>.local:8765/`. There is no login, so anyone on that network can add notes. Only use it on a network you trust.
- Reviewers somewhere else can't reach the page itself. They can still read the notes and add their own from the repo. Sharing the videos with them is up to you; they stay out of git because they're large.

## Commands

| Command | What it does |
| --- | --- |
| `init DIR --media MEDIA --title T` | Writes `desk.json` from videos named `<clip>-v<N>.mp4`. |
| `serve [--port 8765] [--lan] [--push]` | The review page and the videos. |
| `notes [--clip ID] [--open] [--json]` | Lists notes and approvals. |
| `add CLIP VERSION SECONDS TEXT [--by NAME]` | Adds a note. |
| `resolve ID --in VERSION [--reply TEXT]` | Marks a note fixed in a version. |
| `reopen ID` / `reply ID TEXT` | Reopens a note, or answers it without resolving. |
| `approve CLIP --version V [--changes] [--clear]` | Approves a clip, requests changes, or clears either. |
| `import PATH [--by-map OLD=New]` | Brings in notes exported as JSON files, one record per file. |
| `sync [--push]` | Commits hand edits, pulls with rebase, and pushes. |

Every command takes `--project DIR` (by default, the nearest folder above you with a `desk.json`) and `--no-commit`.

## Security

- The server listens on 127.0.0.1 unless you pass `--lan`.
- Changes are accepted only from the page itself. A request needs the page's `X-Desk` header, and one coming from another site is refused, so a web page you visit can't post notes to your desk.
- Video file names are checked against a strict pattern before anything is read from disk.

## License

MIT. See [LICENSE](LICENSE).
