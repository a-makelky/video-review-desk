"""The review page: one row per clip with its versions, a timeline rail of notes, and an approval per clip.

render(manifest) returns the page's HTML body (the server adds the doctype and viewport). The manifest is the
project's desk.json:
  {"title": "...", "eyebrow": "...", "heading": "...", "note": "paragraphs, blank-line separated",
   "clips": [{"id": "C01", "title": "...", "why": "...", "opens": "...", "ends": "...",
              "versions": [{"v": "v1", "src": "media/C01-v1.mp4", "duration": 41.2, "lufs": -16.0, "tp": -5.1,
                            "checkpoints": [{"t": 12.5, "note": "listen here"}]}],
              "scenes": [{"kicker": "graphic name", "at": 3.0, "until": 9.5}]}]}
Only id, title and versions (v, src) are required.

Notes come from the server it is served by (desk.py serve). Opened as a Claude Artifact with the db capability, the
page uses the artifact's database instead.
"""
import html
import json

TEMPLATE = r"""<title>__TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&family=Syne:wght@700&family=DM+Mono:wght@500&display=swap">
<style>
/* Review desk: one row per clip, the phone-shaped player left and the notes right; a note rail under each player
   puts every note and every graphic on the clip's own timeline. Navy, blue and teal tokens; light and dark themes. */
:root{--bg:#F5F7FC;--panel:#FFFFFF;--ink:#000957;--ink-2:#2A3A7A;--muted:#55628F;--line:#D9E1F2;--rail:#E6EBF7;
--accent:#0B7A6E;--accent-soft:#D5F4EF;--warn:#9A5B00;--warn-soft:#FFF1D6;--done:#5E6B94;--focus:#344CB7;
--display:"Syne","DM Sans",system-ui,sans-serif;--body:"DM Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"DM Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#000216;--panel:#060E4A;--ink:#FFFFFF;--ink-2:#C9D4F2;--muted:#9AAAD6;--line:#1E2A78;--rail:#121C66;
--accent:#2DD4BF;--accent-soft:#0B3B44;--warn:#F3C969;--warn-soft:#2A2208;--done:#8E9AC4;--focus:#8FA3FF;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#000216;--panel:#060E4A;--ink:#FFFFFF;--ink-2:#C9D4F2;--muted:#9AAAD6;--line:#1E2A78;--rail:#121C66;
--accent:#2DD4BF;--accent-soft:#0B3B44;--warn:#F3C969;--warn-soft:#2A2208;--done:#8E9AC4;--focus:#8FA3FF;color-scheme:dark}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{background:var(--bg);color:var(--ink);font:16px/1.5 var(--body);margin:0}
.wrap{max-width:1080px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:24px 64px;display:grid;gap:20px}
h1,h2{font-family:var(--display);font-weight:700;line-height:1.15;margin:0;text-wrap:balance}
h1{font-size:clamp(26px,4.5vw,38px)}
h2{font-size:20px}
.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600}
.lede{margin:6px 0 0;color:var(--ink-2);max-width:68ch}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}
.who{display:flex;gap:8px;align-items:center;font-size:14px;color:var(--muted);margin-top:10px}.who input{font:inherit;color:var(--ink);background:transparent;border:1px solid var(--line);border-radius:6px;padding:4px 8px;width:14em;max-width:100%}
.src{font-size:13px;color:var(--muted);margin:6px 0 0;overflow-wrap:anywhere}
.tally{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px;color:var(--muted);font-variant-numeric:tabular-nums}
.tally b{color:var(--ink);font-size:18px;margin-right:4px}
.filters{display:flex;gap:6px;flex-wrap:wrap}
button{font:inherit;color:inherit;cursor:pointer}
button:focus-visible,textarea:focus-visible,video:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.chipbtn{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:5px 12px;font-size:14px}
.chipbtn[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.banner{border:1px solid var(--line);background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:10px 14px;font-size:14px}
.clip{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;display:grid;grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:20px}
@media (max-width:720px){.clip{grid-template-columns:minmax(0,1fr)}.player{max-width:320px;width:100%;justify-self:center}}
.player{display:grid;gap:8px;align-content:start}
.player video{width:100%;max-width:100%;aspect-ratio:9/16;background:#000;border-radius:6px;display:block}
.vers{display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted)}
.vers button{border:1px solid var(--line);background:transparent;border-radius:6px;padding:2px 10px;font-family:var(--mono);font-size:13px}
.vers button[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--ink)}
.rail{position:relative;height:30px;background:var(--rail);border-radius:6px;cursor:pointer;touch-action:none}
.rail .scene{position:absolute;top:4px;bottom:4px;background:var(--accent-soft);border:1px solid var(--accent);border-radius:4px;opacity:.75}
.rail .head{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink)}
.rail .pin{position:absolute;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:2px solid var(--panel);background:var(--warn);padding:0}
.rail .pin.done{background:var(--done)}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}
.side{display:grid;gap:12px;align-content:start;min-width:0}
.head-row{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.cid{font-family:var(--mono);font-size:13px;color:var(--muted)}
.state{font-size:12px;font-weight:600;border-radius:999px;padding:2px 10px;border:1px solid var(--line);color:var(--muted)}
.state.approved{background:var(--accent-soft);border-color:var(--accent);color:var(--ink)}
.state.changes{background:var(--warn-soft);border-color:var(--warn);color:var(--warn)}
.why{margin:0;color:var(--ink-2);max-width:65ch}
.ends{margin:0;font-size:14px;color:var(--muted)}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:8px;padding:8px 14px;font-weight:600}
.btn.ghost{background:transparent;color:var(--ink)}
.btn.ok[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#00131A}
.btn.no[aria-pressed="true"]{background:var(--warn);border-color:var(--warn);color:#1A1000}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.composer{display:grid;gap:8px;border:1px solid var(--line);border-radius:8px;padding:10px}
.composer textarea{width:100%;min-height:72px;resize:vertical;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px}
.composer .hint{font-size:12px;color:var(--muted)}
.notes{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.note{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:start;border-top:1px solid var(--line);padding-top:8px}
.note .tc{border:1px solid var(--line);background:var(--bg);border-radius:6px;padding:1px 8px;font-family:var(--mono);font-size:13px;white-space:nowrap}
.note .txt{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.note .meta{grid-column:2;font-size:12px;color:var(--muted)}
.note .reply{grid-column:2;margin:2px 0 0;font-size:14px;color:var(--ink-2);border-left:3px solid var(--accent);padding-left:8px}
.note.done .txt{color:var(--muted)}
.note .ops{display:flex;gap:4px}
.note .ops button{border:none;background:transparent;color:var(--muted);font-size:13px;padding:2px 6px;border-radius:4px}
.note .ops button:hover{color:var(--ink);background:var(--rail)}
details summary{cursor:pointer;color:var(--ink-2);font-size:14px}
details ul{margin:6px 0 0;padding-left:18px;font-size:14px}
details li button{border:none;background:none;padding:0;color:var(--accent);font-family:var(--mono);font-size:13px}
.empty{font-size:14px;color:var(--muted);margin:0}
.toast{position:fixed;left:50%;bottom:calc(16px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:8px;font-size:14px}
@media (prefers-reduced-motion:no-preference){.rail .pin{transition:transform .12s}.rail .pin:hover{transform:scale(1.25)}}
</style>
<main class="wrap">
  <header>
    <div class="eyebrow">__EYEBROW__</div>
    <h1>__HEADING__</h1>
    <p class="lede">Pause on anything and add a note at that moment. Notes save as you go; the editor fixes each one in the next version and marks it resolved. Approve a clip when it's ready to post.</p>
    <div class="who" id="who" hidden><label for="who-in">Reviewing as</label> <input id="who-in" autocomplete="name"></div>
    <p class="src" id="store-src" hidden></p>
  </header>
  <div class="bar">
    <div class="tally" id="tally"></div>
    <div class="filters" role="group" aria-label="Show">
      <button class="chipbtn" data-f="all" aria-pressed="true">All clips</button>
      <button class="chipbtn" data-f="open">Open notes</button>
      <button class="chipbtn" data-f="todo">Not approved</button>
    </div>
  </div>
  <div class="banner" id="banner" hidden></div>
  __NOTE__
  <div id="clips" style="display:grid;gap:16px"></div>
</main>
<div class="toast" id="toast" hidden></div>
<script>
const CLIPS = __DATA__;
const $ = (s, el = document) => el.querySelector(s);
const fmt = t => { t = Math.max(0, t || 0); const m = Math.floor(t / 60), s = t - m * 60; return m + ":" + s.toFixed(1).padStart(4, "0"); };
let db = null, me = null, canWrite = true, backend = "", notes = [], approvals = {}, filter = "all";
const state = {};  // per clip: {v, composing}

function toast(msg) { const el = $("#toast"); el.textContent = msg; el.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => el.hidden = true, 2600); }
function latest(c) { return c.versions.length ? c.versions[c.versions.length - 1].v : null; }
function ver(c) { return c.versions.find(x => x.v === state[c.id].v) || c.versions[c.versions.length - 1]; }

function build() {
  const root = $("#clips");
  for (const c of CLIPS) {
    state[c.id] = { v: latest(c), composing: null };
    const el = document.createElement("article");
    el.className = "clip"; el.id = c.id;
    el.innerHTML = `
      <div class="player">
        <video controls playsinline preload="metadata"></video>
        <div class="vers" role="group" aria-label="Version"></div>
        <div class="rail" role="slider" tabindex="0" aria-label="Timeline with notes"></div>
        <div class="legend"><span><i style="background:var(--warn)"></i>open note</span><span><i style="background:var(--done)"></i>resolved</span><span><i style="background:var(--accent-soft);border:1px solid var(--accent);border-radius:2px"></i>graphic</span></div>
      </div>
      <div class="side">
        <div class="head-row"><span class="cid"></span><h2></h2><span class="state"></span></div>
        <p class="why"></p>
        <p class="ends"></p>
        <div class="actions">
          <button class="btn add">Add note at 0:00.0</button>
          <button class="btn ghost ok" aria-pressed="false">Approve</button>
          <button class="btn ghost no" aria-pressed="false">Needs changes</button>
        </div>
        <div class="composer" hidden>
          <label class="hint" for="ta-${c.id}"></label>
          <textarea id="ta-${c.id}" placeholder="What should change here?"></textarea>
          <div class="actions"><button class="btn save">Save note</button><button class="btn ghost cancel">Cancel</button><span class="hint">⌘/Ctrl + Enter saves</span></div>
        </div>
        <ul class="notes"></ul>
        <details class="listen"><summary></summary><ul></ul></details>
      </div>`;
    $(".cid", el).textContent = c.id;
    $("h2", el).textContent = c.title;
    $(".why", el).textContent = c.why;
    $(".ends", el).textContent = c.opens ? `Opens “${c.opens}…” · ends “…${c.ends}”` : "";
    const video = $("video", el);
    video.addEventListener("timeupdate", () => { $(".add", el).textContent = "Add note at " + fmt(video.currentTime); drawHead(c); });
    video.addEventListener("loadedmetadata", () => drawRail(c));
    $(".add", el).addEventListener("click", () => openComposer(c));
    $(".cancel", el).addEventListener("click", () => closeComposer(c));
    $(".save", el).addEventListener("click", () => saveNote(c));
    $("textarea", el).addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveNote(c); } if (e.key === "Escape") closeComposer(c); });
    $(".ok", el).addEventListener("click", () => setApproval(c, "approved"));
    $(".no", el).addEventListener("click", () => setApproval(c, "changes"));
    const rail = $(".rail", el);
    const seekFromRail = e => { const r = rail.getBoundingClientRect(); const d = video.duration || ver(c)?.duration || 1; video.currentTime = Math.min(d, Math.max(0, (e.clientX - r.left) / r.width * d)); };
    rail.addEventListener("pointerdown", e => { if (e.target.classList.contains("pin")) return; seekFromRail(e); });
    rail.addEventListener("keydown", e => { if (e.key === "ArrowRight") video.currentTime += 1; if (e.key === "ArrowLeft") video.currentTime -= 1; });
    root.appendChild(el);
    setVersion(c, state[c.id].v);
  }
}

function setVersion(c, v) {
  state[c.id].v = v;
  const el = document.getElementById(c.id), video = $("video", el), x = ver(c);
  if (x && video.getAttribute("src") !== x.src) { const t = video.currentTime || 0; video.src = x.src; video.addEventListener("loadedmetadata", () => { video.currentTime = Math.min(t, video.duration || t); }, { once: true }); }
  const vs = $(".vers", el); vs.textContent = "";
  const lab = document.createElement("span"); lab.textContent = "Version"; vs.appendChild(lab);
  for (const y of c.versions) {
    const b = document.createElement("button"); b.textContent = y.v + (y.v === latest(c) ? " (latest)" : "");
    b.setAttribute("aria-pressed", String(y.v === v)); b.addEventListener("click", () => setVersion(c, y.v)); vs.appendChild(b);
  }
  const det = $(".listen", el);
  $("summary", det).textContent = x && x.lufs != null ? `Listen with headphones (${x.lufs} LUFS, peak ${x.tp} dBFS)` : "Listen with headphones";
  det.hidden = !(x?.checkpoints || []).length;
  const ul = $("ul", det); ul.textContent = "";
  for (const p of (x?.checkpoints || [])) {
    const li = document.createElement("li"); const b = document.createElement("button"); b.textContent = fmt(p.t);
    b.addEventListener("click", () => seek(c, p.t)); li.append(b, " " + p.note); ul.appendChild(li);
  }
  renderClip(c);
}

function seek(c, t, v) {
  if (v && v !== state[c.id].v && c.versions.some(x => x.v === v)) setVersion(c, v);
  const video = $("#" + c.id + " video");
  const go = () => { video.currentTime = t; video.pause(); drawHead(c); };
  video.readyState >= 1 ? go() : video.addEventListener("loadedmetadata", go, { once: true });
  document.getElementById(c.id).scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function dur(c) { const v = $("#" + c.id + " video"); return v.duration || ver(c)?.duration || 60; }
function drawHead(c) {
  const rail = $("#" + c.id + " .rail"); let h = $(".head", rail);
  if (!h) { h = document.createElement("div"); h.className = "head"; rail.appendChild(h); }
  const v = $("#" + c.id + " video"); h.style.left = (100 * (v.currentTime || 0) / dur(c)) + "%";
  rail.setAttribute("aria-valuenow", String(Math.round(v.currentTime || 0)));
}
function drawRail(c) {
  const rail = $("#" + c.id + " .rail"); rail.textContent = ""; const d = dur(c);
  for (const s of c.scenes) { const b = document.createElement("div"); b.className = "scene"; b.title = s.kicker; b.style.left = (100 * s.at / d) + "%"; b.style.width = (100 * Math.max(0.3, s.until - s.at) / d) + "%"; rail.appendChild(b); }
  for (const n of notesFor(c).filter(n => n.version === state[c.id].v)) {
    const p = document.createElement("button"); p.className = "pin" + (n.status === "resolved" ? " done" : "");
    p.style.left = (100 * Math.min(n.t, d) / d) + "%"; p.title = fmt(n.t) + " " + n.text; p.setAttribute("aria-label", "Note at " + fmt(n.t));
    p.addEventListener("click", e => { e.stopPropagation(); seek(c, n.t); }); rail.appendChild(p);
  }
  drawHead(c);
}

function notesFor(c) { return notes.filter(n => n.clip === c.id).sort((a, b) => (a.version === b.version ? a.t - b.t : b.version.localeCompare(a.version, undefined, { numeric: true }))); }

function renderClip(c) {
  const el = document.getElementById(c.id), ns = notesFor(c), ap = approvals[c.id];
  const st = $(".state", el);
  const open = ns.filter(n => n.status !== "resolved").length;
  st.className = "state" + (ap ? " " + ap.approval : "");
  st.textContent = ap?.approval === "approved" ? `Approved (${ap.version})` : ap?.approval === "changes" ? "Needs changes" : open ? `${open} open note${open > 1 ? "s" : ""}` : "Not reviewed";
  $(".ok", el).setAttribute("aria-pressed", String(ap?.approval === "approved"));
  $(".no", el).setAttribute("aria-pressed", String(ap?.approval === "changes"));
  for (const b of el.querySelectorAll(".add,.ok,.no")) b.disabled = !db || !canWrite;
  const ul = $(".notes", el); ul.textContent = "";
  if (!ns.length) { const p = document.createElement("li"); p.className = "empty"; p.textContent = "No notes yet."; ul.appendChild(p); }
  for (const n of ns) {
    const li = document.createElement("li"); li.className = "note" + (n.status === "resolved" ? " done" : "");
    const tc = document.createElement("button"); tc.className = "tc"; tc.textContent = fmt(n.t); tc.title = "Go to this moment in " + n.version;
    tc.addEventListener("click", () => seek(c, n.t, n.version));
    const tx = document.createElement("p"); tx.className = "txt"; tx.textContent = n.text;
    const ops = document.createElement("div"); ops.className = "ops";
    if (db && canWrite) {
      const r = document.createElement("button"); r.textContent = n.status === "resolved" ? "Reopen" : "Resolve";
      r.addEventListener("click", () => toggleNote(n)); ops.appendChild(r);
      if (n.by && n.by === me) { const d = document.createElement("button"); d.textContent = "Delete"; d.addEventListener("click", () => deleteNote(n)); ops.appendChild(d); }
    }
    const meta = document.createElement("div"); meta.className = "meta";
    meta.textContent = `${n.version}${n.by && n.by !== me && !/^u_/.test(n.by) ? " · " + n.by : ""}${n.status === "resolved" ? " · resolved" + (n.resolvedIn ? " in " + n.resolvedIn : "") : " · open"}`;
    li.append(tc, tx, ops, meta);
    if (n.reply) { const rp = document.createElement("p"); rp.className = "reply"; rp.textContent = n.reply; li.appendChild(rp); }
    ul.appendChild(li);
  }
  drawRail(c);
  el.hidden = (filter === "open" && !open) || (filter === "todo" && ap?.approval === "approved");
}
function renderAll() {
  for (const c of CLIPS) renderClip(c);
  const open = notes.filter(n => n.status !== "resolved").length, appr = CLIPS.filter(c => approvals[c.id]?.approval === "approved").length;
  const t = $("#tally"); t.textContent = "";
  for (const [n, l] of [[CLIPS.length, "clips"], [open, "open notes"], [notes.length - open, "resolved"], [appr + "/" + CLIPS.length, "approved"]]) {
    const s = document.createElement("span"); const b = document.createElement("b"); b.textContent = n; s.append(b, l); t.appendChild(s);
  }
}

function openComposer(c) {
  const el = document.getElementById(c.id), video = $("video", el); video.pause();
  state[c.id].composing = { t: Math.round((video.currentTime || 0) * 10) / 10, v: state[c.id].v };
  $(".composer", el).hidden = false; $("label", el).textContent = `Note at ${fmt(state[c.id].composing.t)} in ${state[c.id].v}`;
  $("textarea", el).focus();
}
function closeComposer(c) { const el = document.getElementById(c.id); $(".composer", el).hidden = true; $("textarea", el).value = ""; state[c.id].composing = null; }

async function saveNote(c) {
  const el = document.getElementById(c.id), text = $("textarea", el).value.trim(), at = state[c.id].composing;
  if (!text || !at || !db) return;
  const btn = $(".save", el); btn.disabled = true;
  try {
    await db.add({ clip: c.id, version: at.v, t: at.t, text, status: "open", createdAt: new Date().toISOString() });
    closeComposer(c); toast("Note saved");
  } catch (e) { writeFailed(e); } finally { btn.disabled = false; }
}
async function toggleNote(n) {
  try { await db.update(n.id, { status: n.status === "resolved" ? "open" : "resolved" }); } catch (e) { writeFailed(e); }
}
async function deleteNote(n) {
  try { await db.remove(n.id); toast("Note deleted"); } catch (e) { writeFailed(e); }
}
async function setApproval(c, kind) {
  const cur = approvals[c.id]?.approval;
  try {
    await db.approve(c.id, cur === kind ? null : { approval: kind, version: state[c.id].v, at: new Date().toISOString() });
  } catch (e) { writeFailed(e); }
}
function writeFailed(e) {
  if (e && e.code === "invalid_argument") { canWrite = false; renderAll(); toast("This view can read notes but not change them."); return; }
  toast(e && e.code === "quota_exceeded" ? "The notes store is full." : "Couldn't save. Try again in a moment.");
}

function showBanner(msg) { const b = $("#banner"); b.textContent = msg; b.hidden = !msg; }
for (const b of document.querySelectorAll(".filters button")) b.addEventListener("click", () => {
  filter = b.dataset.f; for (const x of document.querySelectorAll(".filters button")) x.setAttribute("aria-pressed", String(x === b)); renderAll();
});

// The desk server (kit/desk.py): notes are files in the repo. Same calls as the artifact db below.
function deskStore(health) {
  const req = async (method, url, body) => {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json", "X-Desk": "1" }, body: body && JSON.stringify(body) });
    if (!r.ok) { const e = new Error((await r.json().catch(() => ({}))).error || r.statusText); e.code = r.status; throw e; }
    return r.json();
  };
  let stamp = null, poller = null;
  const pull = async () => {
    try {
      const s = await req("GET", "api/state");
      if (s.stamp !== stamp) { stamp = s.stamp; notes = s.notes; approvals = s.approvals; renderAll(); }
      showBanner("");
    } catch (e) { showBanner("Can't reach the desk server. Is desk.py serve still running?"); }
  };
  const by = () => (localStorage.getItem("desk-name") || health.by || "reviewer");
  return {
    kind: "repo",
    me: by,
    start() { pull(); poller = setInterval(pull, 2500); },
    add: n => req("POST", "api/notes", { ...n, by: by() }).then(pull),
    update: (id, patch) => req("POST", "api/notes/" + id, { ...patch, by: by() }).then(pull),
    remove: id => req("DELETE", "api/notes/" + id).then(pull),
    approve: (clip, a) => req("POST", "api/approvals/" + clip, a ? { ...a, by: by() } : { approval: null, version: "v1" }).then(pull),
  };
}
// Claude Artifact fallback (claude.use("db")).
function claudeStore(cdb) {
  return {
    kind: "claude",
    start() {
      cdb.collection("notes").onSnapshot(s => { notes = s.docs.map(d => ({ id: d.id, ...d.data() })); renderAll(); }, () => showBanner("Lost the connection to the notes. Reload the page."));
      cdb.collection("clips").onSnapshot(s => { approvals = {}; for (const d of s.docs) approvals[d.id] = d.data(); renderAll(); }, () => {});
    },
    add: n => cdb.collection("notes").add({ ...n, by: me || null }),
    update: (id, patch) => cdb.doc("notes/" + id).update(patch),
    remove: id => cdb.doc("notes/" + id).delete(),
    approve: (clip, a) => a ? cdb.doc("clips/" + clip).set({ ...a, by: me || null }) : cdb.doc("clips/" + clip).delete(),
  };
}

build(); renderAll();
showBanner("Connecting to the notes…");
(async () => {
  const health = await fetch("api/health", { cache: "no-store" }).then(r => r.ok ? r.json() : null).catch(() => null);
  if (health && health.ok) {
    db = deskStore(health);
    me = db.me();
    const who = $("#who");
    if (who) { who.hidden = false; const inp = $("input", who); inp.value = me; inp.addEventListener("change", () => { try { localStorage.setItem("desk-name", inp.value.trim()); } catch (e) {} me = db.me(); renderAll(); }); }
    const src = $("#store-src"); if (src) { src.hidden = false; src.textContent = "Notes are files in " + (health.repo ? health.repo.replace(/^https:\/\/github.com\//, "").replace(/\.git$/, "") + " · " : "") + health.store; }
    db.start(); renderAll(); return;
  }
  const cdb = await window.claude?.use?.("db") ?? null;
  const user = await window.claude?.use?.("user") ?? null;
  if (!cdb) { showBanner("Notes aren't available in this view. Open it through desk.py serve (or signed in to claude.ai). The clips still play."); renderAll(); return; }
  db = claudeStore(cdb);
  me = user ? await user.id() : null;
  const cw = user ? await user.can("data.write") : null;
  canWrite = cw !== false;
  showBanner(canWrite ? "" : "You can read the notes here but not add them.");
  db.start();
  renderAll();
})();
</script>
"""


def render(manifest):
    note = manifest.get("note") or ""
    note_html = ""
    if note.strip():
        note_html = ('<details><summary>What changed in this batch</summary>'
                     + "".join(f"<p>{html.escape(p)}</p>" for p in note.split("\n\n") if p.strip()) + "</details>")
    clips = []
    for c in manifest["clips"]:
        clips.append(dict(id=c["id"], title=c.get("title", c["id"]), layout=c.get("layout", ""), loop=bool(c.get("loop")),
                          why=c.get("why", ""), opens=c.get("opens", ""), ends=c.get("ends", ""), scenes=c.get("scenes", []),
                          versions=[dict(v=v["v"], src=v.get("src") or f"media/{v['file']}", lufs=v.get("lufs"), tp=v.get("tp"),
                                         duration=v.get("duration"), checkpoints=v.get("checkpoints", []))
                                    for v in c.get("versions", [])]))
    data = json.dumps(clips, ensure_ascii=False).replace("</", "<\\/")
    title = manifest.get("title") or "Video review"
    return (TEMPLATE.replace("__TITLE__", html.escape(title))
            .replace("__EYEBROW__", html.escape(manifest.get("eyebrow", "")))
            .replace("__HEADING__", html.escape(manifest.get("heading") or title))
            .replace("__NOTE__", note_html).replace("__DATA__", data))
