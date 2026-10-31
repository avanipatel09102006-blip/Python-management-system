"""Premium File Manager: Flask + SQLite metadata + safe on-disk storage.
Files are stored under random names in ./uploads, so user-supplied names
can never touch the filesystem (no path traversal)."""
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

BASE = Path(__file__).parent
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = BASE / "files.db"
MAX_FILE = 25 * 1024 * 1024       # per file
QUOTA = 500 * 1024 * 1024         # total storage
INLINE_OK = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript(
            """CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, parent_id INTEGER,
                starred INTEGER DEFAULT 0, trashed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, stored TEXT NOT NULL,
                size INTEGER NOT NULL, mime TEXT NOT NULL, folder_id INTEGER,
                starred INTEGER DEFAULT 0, trashed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""
        )


def clean(name):
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    return name[:120]


def unique(conn, table, name, parent):
    col = "folder_id" if table == "files" else "parent_id"
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while conn.execute(f"SELECT 1 FROM {table} WHERE name=? AND {col} IS ? AND trashed=0", (candidate, parent)).fetchone():
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


def remove_file(stored):
    try:
        (UPLOAD_DIR / stored).unlink()
    except FileNotFoundError:
        pass


def purge_folder(conn, fid):
    for f in conn.execute("SELECT stored FROM files WHERE folder_id=?", (fid,)).fetchall():
        remove_file(f["stored"])
    conn.execute("DELETE FROM files WHERE folder_id=?", (fid,))
    for ch in conn.execute("SELECT id FROM folders WHERE parent_id=?", (fid,)).fetchall():
        purge_folder(conn, ch["id"])
    conn.execute("DELETE FROM folders WHERE id=?", (fid,))


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/items")
def items():
    view = request.args.get("view", "files")
    folder = request.args.get("folder", type=int)
    q = request.args.get("q", "").strip()
    sort = {"date": "created_at DESC", "size": "size DESC"}.get(request.args.get("sort"), "name COLLATE NOCASE")
    with db() as c:
        if q:
            where_f, where_d, a = "trashed=0 AND name LIKE ?", "trashed=0 AND name LIKE ?", [f"%{q}%"]
        elif view == "starred":
            where_f = where_d = "starred=1 AND trashed=0"; a = []
        elif view == "trash":
            where_f = where_d = "trashed=1"; a = []
        else:
            where_f, where_d, a = "trashed=0 AND folder_id IS ?", "trashed=0 AND parent_id IS ?", [folder]
        files = [dict(r) for r in c.execute(f"SELECT id,name,size,mime,starred,trashed,created_at FROM files WHERE {where_f} ORDER BY {sort}", a)]
        fsort = "name COLLATE NOCASE" if sort.startswith("name") else "created_at DESC"
        folders = [dict(r) for r in c.execute(f"SELECT id,name,starred,trashed,created_at FROM folders WHERE {where_d} ORDER BY {fsort}", a)]
        crumbs, cur = [], folder
        while cur and view == "files" and not q:
            row = c.execute("SELECT id,name,parent_id FROM folders WHERE id=?", (cur,)).fetchone()
            if not row:
                break
            crumbs.insert(0, {"id": row["id"], "name": row["name"]})
            cur = row["parent_id"]
        used = c.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0]
    return jsonify(files=files, folders=folders, crumbs=crumbs, used=used, quota=QUOTA)


@app.post("/api/folders")
def new_folder():
    d = request.get_json(silent=True) or {}
    name, parent = clean(d.get("name")), d.get("parent")
    if not name:
        return jsonify(error="Folder name is required"), 400
    with db() as c:
        cur = c.execute("INSERT INTO folders (name,parent_id) VALUES (?,?)", (unique(c, "folders", name, parent), parent))
    return jsonify(id=cur.lastrowid), 201


@app.post("/api/upload")
def upload():
    folder = request.form.get("folder", type=int)
    saved, rejected = 0, []
    with db() as c:
        used = c.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0]
        for f in request.files.getlist("files"):
            name = clean(f.filename)
            if not name:
                continue
            stored = uuid.uuid4().hex
            path = UPLOAD_DIR / stored
            f.save(path)
            size = path.stat().st_size
            if size > MAX_FILE or used + size > QUOTA:
                path.unlink()
                rejected.append(name)
                continue
            used += size
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            c.execute("INSERT INTO files (name,stored,size,mime,folder_id) VALUES (?,?,?,?,?)",
                      (unique(c, "files", name, folder), stored, size, mime, folder))
            saved += 1
    if not saved and rejected:
        return jsonify(error="Too large (25 MB max per file) or storage full", saved=0, rejected=rejected), 400
    return jsonify(saved=saved, rejected=rejected)


def patch(table, item_id):
    d = request.get_json(silent=True) or {}
    sets, args = [], []
    if "name" in d:
        name = clean(d["name"])
        if not name:
            return jsonify(error="Name is required"), 400
        sets.append("name=?"); args.append(name)
    for key in ("starred", "trashed"):
        if key in d:
            sets.append(f"{key}=?"); args.append(1 if d[key] else 0)
    if not sets:
        return jsonify(error="Nothing to update"), 400
    with db() as c:
        cur = c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", (*args, item_id))
    return (jsonify(ok=True), 200) if cur.rowcount else (jsonify(error="Not found"), 404)


@app.patch("/api/files/<int:item_id>")
def patch_file(item_id):
    return patch("files", item_id)


@app.patch("/api/folders/<int:item_id>")
def patch_folder(item_id):
    return patch("folders", item_id)


@app.delete("/api/files/<int:item_id>")
def delete_file(item_id):
    with db() as c:
        row = c.execute("SELECT stored FROM files WHERE id=?", (item_id,)).fetchone()
        if row:
            remove_file(row["stored"])
            c.execute("DELETE FROM files WHERE id=?", (item_id,))
    return jsonify(ok=True)


@app.delete("/api/folders/<int:item_id>")
def delete_folder(item_id):
    with db() as c:
        purge_folder(c, item_id)
    return jsonify(ok=True)


@app.delete("/api/trash")
def empty_trash():
    with db() as c:
        for f in c.execute("SELECT id,stored FROM files WHERE trashed=1").fetchall():
            remove_file(f["stored"])
            c.execute("DELETE FROM files WHERE id=?", (f["id"],))
        for d in c.execute("SELECT id FROM folders WHERE trashed=1").fetchall():
            purge_folder(c, d["id"])
    return jsonify(ok=True)


def file_row(item_id):
    with db() as c:
        row = c.execute("SELECT * FROM files WHERE id=?", (item_id,)).fetchone()
    if not row:
        abort(404)
    return row


@app.get("/api/files/<int:item_id>/download")
def download(item_id):
    r = file_row(item_id)
    return send_file(UPLOAD_DIR / r["stored"], as_attachment=True, download_name=r["name"])


@app.get("/api/files/<int:item_id>/preview")
def preview(item_id):
    r = file_row(item_id)
    if r["mime"] not in INLINE_OK:   # SVG/HTML etc. are never rendered inline
        abort(415)
    return send_file(UPLOAD_DIR / r["stored"], mimetype=r["mime"])


init_db()
if __name__ == "__main__":
    app.run(debug=True)
