import os
import shutil
import subprocess
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

DATA = "/tmp/clipper"
os.makedirs(DATA, exist_ok=True)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB upload cap
jobs = {}

W, H = 1080, 1920
TOP = 1080          # gameplay square (1:1)
BOT = H - TOP       # face cam fills the rest (840 px)


def cleanup():
    now = time.time()
    for name in os.listdir(DATA):
        p = os.path.join(DATA, name)
        if now - os.path.getmtime(p) > 3600:
            shutil.rmtree(p, ignore_errors=True)
            jobs.pop(name, None)


def build_filter(gx, fx, fy, fw, fh):
    fw = max(0.05, min(fw, 1.0))
    fh = max(0.05, min(fh, 1.0))
    fx = max(0.0, min(fx, 1.0 - fw))
    fy = max(0.0, min(fy, 1.0 - fh))
    gx = max(0.0, min(gx, 1.0))
    return (
        "[0:v]split=2[a][b];"
        f"[a]crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))*{gx}:0,scale={W}:{TOP}[top];"
        f"[b]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},"
        f"scale={W}:{BOT}:force_original_aspect_ratio=increase,crop={W}:{BOT}[bot];"
        "[top][bot]vstack=inputs=2[v]"
    )


def params_from(d):
    f = lambda k, default: float(d.get(k, default))
    return dict(gx=f("gx", 0.5), fx=f("fx", 0.0), fy=f("fy", 0.3), fw=f("fw", 0.25), fh=f("fh", 0.4))


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def make_preview(jid, p):
    folder = os.path.join(DATA, jid)
    src = os.path.join(folder, "src.mp4")
    dur = jobs[jid]["duration"]
    name = f"preview_{uuid.uuid4().hex[:6]}.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(dur * 0.1), "-i", src, "-filter_complex",
         build_filter(**p), "-map", "[v]", "-frames:v", "1", "-q:v", "3",
         os.path.join(folder, name)],
        check=True, capture_output=True)
    return f"/files/{jid}/{name}"


def download_job(jid, url):
    folder = os.path.join(DATA, jid)
    try:
        import yt_dlp
        opts = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(folder, "src.%(ext)s"),
            "quiet": True,
            "noplaylist": True,
        }
        cookies = os.environ.get("YT_COOKIES_FILE")
        if cookies and os.path.exists(cookies):
            opts["cookiefile"] = cookies
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([url])
        finish_fetch(jid)
    except Exception as e:  # noqa
        jobs[jid].update(status="error", error=str(e)[:300])


def finish_fetch(jid):
    folder = os.path.join(DATA, jid)
    src = os.path.join(folder, "src.mp4")
    if not os.path.exists(src):
        for f in os.listdir(folder):
            if f.startswith("src."):
                os.rename(os.path.join(folder, f), src)
                break
    jobs[jid]["duration"] = probe_duration(src)
    jobs[jid]["preview"] = make_preview(jid, params_from({}))
    jobs[jid]["status"] = "ready"


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.route("/api/fetch", methods=["POST"])
def fetch():
    cleanup()
    jid = uuid.uuid4().hex[:10]
    folder = os.path.join(DATA, jid)
    os.makedirs(folder)
    jobs[jid] = {"status": "downloading", "clips": []}
    if "file" in request.files:
        request.files["file"].save(os.path.join(folder, "src.mp4"))
        try:
            finish_fetch(jid)
        except Exception as e:  # noqa
            jobs[jid].update(status="error", error=str(e)[:300])
    else:
        url = (request.form.get("url") or (request.json or {}).get("url") or "").strip()
        if not url:
            return jsonify(error="Paste a YouTube link or upload a video"), 400
        threading.Thread(target=download_job, args=(jid, url), daemon=True).start()
    return jsonify(id=jid)


@app.route("/api/preview/<jid>", methods=["POST"])
def preview(jid):
    if jid not in jobs or jobs[jid].get("status") == "downloading":
        return jsonify(error="Not ready"), 400
    try:
        return jsonify(preview=make_preview(jid, params_from(request.json or {})))
    except Exception as e:  # noqa
        return jsonify(error=str(e)[:300]), 500


def render_job(jid, dur, start, count, p):
    folder = os.path.join(DATA, jid)
    src = os.path.join(folder, "src.mp4")
    total = jobs[jid]["duration"]
    flt = build_filter(**p)
    jobs[jid].update(status="rendering", clips=[], done=0, count=count)
    try:
        for i in range(count):
            s = start + i * dur
            if s + 3 > total:
                break
            name = f"clip_{i + 1:02d}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(s), "-t", str(dur), "-i", src,
                 "-filter_complex", flt, "-map", "[v]", "-map", "0:a?",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart", os.path.join(folder, name)],
                check=True, capture_output=True)
            jobs[jid]["clips"].append(f"/files/{jid}/{name}")
            jobs[jid]["done"] = i + 1
        jobs[jid]["status"] = "done"
    except Exception as e:  # noqa
        jobs[jid].update(status="error", error=str(e)[:300])


@app.route("/api/render/<jid>", methods=["POST"])
def render(jid):
    if jid not in jobs or jobs[jid].get("status") in ("downloading", "rendering"):
        return jsonify(error="Not ready"), 400
    d = request.json or {}
    dur = int(d.get("duration", 30))
    dur = dur if dur in (15, 20, 30, 40, 45, 60) else 30
    start = max(0.0, float(d.get("start", 0)))
    count = max(1, min(int(d.get("count", 5)), 20))
    threading.Thread(target=render_job, args=(jid, dur, start, count, params_from(d)),
                     daemon=True).start()
    return jsonify(ok=True)


@app.route("/api/job/<jid>")
def job(jid):
    return jsonify(jobs.get(jid, {"status": "error", "error": "Job expired, start again"}))


@app.route("/api/zip/<jid>")
def zip_all(jid):
    folder = os.path.join(DATA, jid)
    base = os.path.join(DATA, f"{jid}_clips")
    tmp = os.path.join(DATA, f"zip_{jid}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for f in os.listdir(folder):
        if f.startswith("clip_"):
            shutil.copy(os.path.join(folder, f), tmp)
    shutil.make_archive(base, "zip", tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return send_from_directory(DATA, f"{jid}_clips.zip", as_attachment=True)


@app.route("/files/<jid>/<name>")
def files(jid, name):
    return send_from_directory(os.path.join(DATA, jid), name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
