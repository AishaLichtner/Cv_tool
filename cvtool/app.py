#!/usr/bin/env python3
"""cvtool – browser UI. Start: python app.py  (or start.bat / start.command)"""
import socket, threading, traceback, webbrowser
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

import cvtool

VERSION = "11"
app = Flask(__name__, static_folder=str(cvtool.HERE / "static"), static_url_path="/static")
lock = threading.Lock()


def file_url(p):
    if not p:
        return None
    return "/files/" + Path(p).resolve().relative_to(cvtool.OUT.resolve()).as_posix()

def api(fn):
    def wrapper(*a, **k):
        try:
            with lock:
                return jsonify(fn(*a, **k))
        except cvtool.UserError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    wrapper.__name__ = fn.__name__
    return wrapper

def body():
    return request.get_json(silent=True) or {}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.get("/files/<path:p>")
def files(p):
    if not (cvtool.OUT / p).resolve().is_relative_to(cvtool.OUT.resolve()):
        abort(404)
    return send_from_directory(cvtool.OUT, p, max_age=0)

@app.get("/api/state")
@api
def state():
    f, s = cvtool.load_facts(), cvtool.load_settings()
    return {"version": VERSION, "lang": cvtool.lang(), "has_key": bool(cvtool.api_key()),
            "has_profile": bool(f["profile"].get("last_name")),
            "has_entries": bool(f["experience"] or f["projects"]),
            "max_pages": int(s.get("max_pages", 2)), "data_dir": str(cvtool.DATA)}

@app.get("/api/settings")
@api
def get_settings():
    s = cvtool.load_settings()
    k = cvtool.api_key()
    return {"lang": cvtool.lang(), "model": s.get("model"), "max_pages": s.get("max_pages", 2),
            "api_key_set": bool(k), "api_key_hint": (k[:10] + "…" + k[-4:]) if len(k) > 16 else ""}

@app.put("/api/settings")
@api
def put_settings():
    b = body()
    patch = {k: b.get(k) for k in ("lang", "model", "max_pages")}
    if b.get("api_key"):
        patch["api_key"] = b["api_key"].strip()
    cvtool.save_settings(patch)
    return {"ok": True}

@app.post("/api/tailor")
@api
def tailor():
    b = body()
    r = cvtool.run_tailor(b.get("jd") or "", b.get("name"), bool(b.get("llm_check")), int(b.get("max_pages") or 0) or None)
    return {"name": r["name"], "pdf": file_url(r["pdf"]), "pages": r["pages"],
            "report": file_url(r["dir"] / "report.md"), "tex": file_url(r["dir"] / "cv.tex"),
            "coverage": [{**k, "status": s} for k, s in r["coverage"]], "changed": r["changed"],
            "log": r["log"], "evidence": r["evidence"], "gaps": r["gaps"], "latex_error": cvtool.LAST_LATEX_ERROR}

@app.post("/api/render")
@api
def render_base():
    r = cvtool.run_render()
    return {"pdf": file_url(r["pdf"]), "pages": r["pages"], "log": r["log"], "latex_error": cvtool.LAST_LATEX_ERROR}

@app.post("/api/synonyms")
@api
def synonyms():
    return cvtool.add_synonyms(body().get("additions") or [])

@app.post("/api/add/propose")
@api
def add_propose():
    b = body()
    return cvtool.add_propose(b.get("text") or "", b.get("qa") or [], int(b.get("rounds") or 0))

@app.post("/api/add/apply")
@api
def add_apply():
    b = body()
    return cvtool.add_apply(b.get("text") or "", b.get("proposal") or {})

@app.post("/api/import/propose")
@api
def import_propose():
    b = body()
    text = b.get("text") or ""
    if b.get("b64"):
        text = cvtool.extract_text_from_upload(b.get("filename") or "", b["b64"]) + "\n" + text
    return cvtool.import_propose(text)

@app.post("/api/import/apply")
@api
def import_apply():
    b = body()
    return cvtool.import_apply(b.get("proposal") or {}, b.get("mode") or "replace")

@app.get("/api/entries")
@api
def get_entries():
    return cvtool.get_entries()

@app.put("/api/entries")
@api
def put_entries():
    return cvtool.save_entries(body())

@app.get("/api/profile")
@api
def get_profile():
    return cvtool.get_profile()

@app.put("/api/profile")
@api
def put_profile():
    return cvtool.save_profile(body())

@app.get("/api/skills")
@api
def get_skills():
    return cvtool.get_skill_table()

@app.put("/api/skills")
@api
def put_skills():
    b = body()
    return cvtool.save_skill_table(b.get("rows") or [], b.get("groups"))

@app.get("/api/facts")
@api
def get_facts():
    import json
    return {"text": json.dumps(cvtool.load_facts(), indent=2, ensure_ascii=False)}

@app.put("/api/facts")
@api
def put_facts():
    return cvtool.save_raw_facts(body().get("text") or "")

@app.get("/api/history")
@api
def history():
    if not cvtool.OUT.exists():
        return []
    rows = []
    for d in sorted((p for p in cvtool.OUT.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        jd = d / "jobad.txt"
        if not jd.exists():
            jd = d / "stellenanzeige.txt"
        rows.append({"name": d.name, "pdf": file_url(d / "cv.pdf") if (d / "cv.pdf").exists() else None,
                     "report": next((file_url(d / n) for n in ("report.md", "bericht.md") if (d / n).exists()), None),
                     "jd": jd.read_text(encoding="utf-8")[:200] if jd.exists() else ""})
    return rows

@app.post("/api/diagnose")
@api
def diagnose():
    checks = cvtool.diagnose()
    pdf = cvtool.OUT / "cv_base.pdf"
    return {"checks": checks, "pdf": file_url(pdf) if pdf.exists() else None}

@app.post("/api/tectonic")
@api
def tectonic():
    return {"path": cvtool.download_tectonic()}

@app.get("/api/export")
def export():
    data = cvtool.export_app_zip()
    return Response(data, mimetype="application/zip",
                    headers={"Content-Disposition": "attachment; filename=cvtool.zip"})


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

if __name__ == "__main__":
    port = 5000
    if not port_free(port):
        print("\n!!! Port 5000 is busy – probably an older cvtool is still running in another window.")
        print("!!! Port 5000 ist belegt – vermutlich laeuft noch ein altes cvtool in einem anderen Fenster.")
        port = next(p for p in range(5001, 5100) if port_free(p))
    url = f"http://127.0.0.1:{port}"
    print(f"\ncvtool version {VERSION}\nProgram: {cvtool.HERE}\nData:    {cvtool.DATA}\n\nOpen / Oeffne: {url}\n"
          "Stop / Beenden: Ctrl-C\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
