const $ = id => document.getElementById(id);
const S = {view: "files", folder: null, q: "", sort: "name", mode: localStorage.getItem("mode") || "grid"};
const EXT = {image:"png jpg jpeg gif webp svg bmp", doc:"pdf doc docx txt md rtf ppt pptx xls xlsx csv", code:"py js html css json java c cpp php sql xml", archive:"zip rar 7z tar gz"};
const cat = n => { const e = (n.split(".").pop() || "").toLowerCase(); return Object.keys(EXT).find(k => EXT[k].split(" ").includes(e)) || "other"; };
const fmt = b => b < 1024 ? b + " B" : b < 1048576 ? (b/1024).toFixed(1) + " KB" : (b/1048576).toFixed(1) + " MB";
const day = s => new Date(s.replace(" ", "T") + "Z").toLocaleDateString();
const PREVIEW = new Set(["image/png","image/jpeg","image/gif","image/webp","application/pdf","text/plain"]);
const send = (url, method, body) => fetch(url, {method, headers:{"Content-Type":"application/json"}, body: body && JSON.stringify(body)}).then(async r => ({ok:r.ok, d:await r.json()}));
let tt; const toast = m => { const t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 2600); };

function ask(title, value) {
  return new Promise(res => {
    const d = $("dlg"); $("dlgTitle").textContent = title; $("dlgInput").value = value || ""; d.returnValue = "";
    d.onclose = () => res(d.returnValue === "ok" ? $("dlgInput").value.trim() : null);
    d.showModal(); $("dlgInput").select();
  });
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function btn(label, fn, cls) { const b = el("button", cls, label); b.onclick = e => { e.stopPropagation(); fn(); }; return b; }

async function load() {
  const p = new URLSearchParams({view:S.view, q:S.q, sort:S.sort}); if (S.folder) p.set("folder", S.folder);
  render(await (await fetch("/api/items?" + p)).json());
}

function render(d) {
  const g = $("grid"); g.innerHTML = ""; g.className = "grid" + (S.mode === "list" ? " list" : "");
  $("modeBtn").textContent = S.mode === "list" ? "Grid" : "List";
  $("emptyTrash").hidden = S.view !== "trash" || !(d.files.length + d.folders.length);
  $("newFolder").hidden = $("uploadBtn").hidden = S.view !== "files";
  const c = $("crumbs"); c.innerHTML = "";
  if (S.q) c.append(el("strong", "", `Results for "${S.q}"`));
  else if (S.view !== "files") c.append(el("strong", "", S.view === "trash" ? "Trash" : "Starred"));
  else {
    c.append(btn("My files", () => { S.folder = null; load(); }));
    d.crumbs.forEach(x => { c.append(el("span", "", "/"), btn(x.name, () => { S.folder = x.id; load(); })); });
  }
  d.folders.forEach(f => g.append(card("folder", f)));
  d.files.forEach(f => g.append(card("file", f)));
  const none = !d.files.length && !d.folders.length;
  $("empty").hidden = !none;
  $("empty").textContent = S.q ? "No matches found." : S.view === "trash" ? "Trash is empty." : S.view === "starred" ? "Star items to find them here." : "This folder is empty. Drag files here or press Upload.";
  const pct = Math.min(100, d.used / d.quota * 100);
  $("meter").style.width = pct + "%"; $("usageText").textContent = `${fmt(d.used)} of ${fmt(d.quota)} used`;
}

function card(kind, it) {
  const li = el("div", "item"), isF = kind === "folder", api = `/api/${kind}s/${it.id}`;
  const ico = el("div", "ico", isF ? "DIR" : ((it.name.split(".").pop() || "file").slice(0, 4).toUpperCase())); ico.dataset.c = isF ? "folder" : cat(it.name);
  const info = el("div", "info"); info.append(el("div", "name", it.name), el("div", "meta", isF ? "Folder · " + day(it.created_at) : fmt(it.size) + " · " + day(it.created_at)));
  info.firstChild.title = it.name;
  const acts = el("div", "acts"), after = () => load();
  if (S.view === "trash") {
    acts.append(btn("Restore", async () => { await send(api, "PATCH", {trashed:false}); after(); }),
      btn("Delete forever", async () => { await send(api, "DELETE"); after(); }, "del"));
  } else {
    acts.append(btn(it.starred ? "Starred" : "Star", async () => { await send(api, "PATCH", {starred:!it.starred}); after(); }, it.starred ? "on" : ""),
      btn("Rename", async () => { const n = await ask("Rename", it.name); if (n) { const r = await send(api, "PATCH", {name:n}); if (!r.ok) toast(r.d.error); after(); } }));
    if (!isF) acts.append(btn("Download", () => { location.href = api + "/download"; }));
    acts.append(btn("Trash", async () => { await send(api, "PATCH", {trashed:true}); toast("Moved to trash"); after(); }, "del"));
  }
  const left = el("div", S.mode === "list" ? "" : ""); li.append(ico, info, acts);
  li.onclick = () => isF ? (S.folder = it.id, S.view = "files", S.q = "", $("search").value = "", syncNav(), load()) : open(it);
  return li;
}

async function open(f) {
  if (!PREVIEW.has(f.mime)) { location.href = `/api/files/${f.id}/download`; return; }
  const b = $("pvBody"); b.innerHTML = ""; $("pvName").textContent = f.name; const url = `/api/files/${f.id}/preview`;
  if (f.mime.startsWith("image/")) { const i = el("img"); i.src = url; i.alt = f.name; b.append(i); }
  else if (f.mime === "application/pdf") { const i = el("iframe"); i.src = url; b.append(i); }
  else { const pre = el("pre", "", await (await fetch(url)).text()); b.append(pre); }
  $("pv").showModal();
}

function upload(files) {
  if (!files.length) return;
  if (S.view !== "files") return toast("Open My files to upload");
  const fd = new FormData(); [...files].forEach(f => fd.append("files", f)); if (S.folder) fd.append("folder", S.folder);
  const x = new XMLHttpRequest(); x.open("POST", "/api/upload"); $("prog").hidden = false;
  x.upload.onprogress = e => { if (e.lengthComputable) $("prog").firstChild.style.width = e.loaded / e.total * 100 + "%"; };
  x.onload = () => {
    $("prog").hidden = true; $("prog").firstChild.style.width = "0";
    let d = {}; try { d = JSON.parse(x.responseText); } catch {}
    toast(x.status >= 400 ? (d.error || "Upload failed (file too large?)") : `${d.saved} uploaded` + (d.rejected.length ? `, ${d.rejected.length} skipped (over 25 MB)` : ""));
    load();
  };
  x.onerror = () => { $("prog").hidden = true; toast("Upload failed"); };
  x.send(fd);
}

function syncNav() { document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("on", b.dataset.v === S.view)); }
$("nav").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.view = b.dataset.v; S.folder = null; S.q = ""; $("search").value = ""; syncNav(); load(); };
let st; $("search").oninput = e => { clearTimeout(st); st = setTimeout(() => { S.q = e.target.value.trim(); load(); }, 250); };
$("sort").onchange = e => { S.sort = e.target.value; load(); };
$("modeBtn").onclick = () => { S.mode = S.mode === "list" ? "grid" : "list"; localStorage.setItem("mode", S.mode); load(); };
$("uploadBtn").onclick = () => $("picker").click();
$("picker").onchange = e => { upload(e.target.files); e.target.value = ""; };
$("newFolder").onclick = async () => { const n = await ask("New folder"); if (n) { const r = await send("/api/folders", "POST", {name:n, parent:S.folder}); if (!r.ok) toast(r.d.error); load(); } };
$("emptyTrash").onclick = async () => { if (confirm("Permanently delete everything in Trash?")) { await send("/api/trash", "DELETE"); load(); } };
$("pvClose").onclick = () => $("pv").close();
let depth = 0;
addEventListener("dragenter", e => { if ([...(e.dataTransfer.types || [])].includes("Files")) { depth++; $("drop").hidden = false; } });
addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; $("drop").hidden = true; } });
addEventListener("dragover", e => e.preventDefault());
addEventListener("drop", e => { e.preventDefault(); depth = 0; $("drop").hidden = true; upload(e.dataTransfer.files); });
load();
