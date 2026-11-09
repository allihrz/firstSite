"""A local browser-based YouTube downloader.

Run: py -m pip install flask "yt-dlp[default]"
     py youtube_web.py
Visit http://127.0.0.1:5000

Use only for content you have permission to download.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from flask import Flask, jsonify, render_template_string, request, send_file
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

app = Flask(__name__)
DOWNLOADS = Path(__file__).resolve().parent / "downloads"
DOWNLOADS.mkdir(exist_ok=True)
JOBS = {}
LOCK = Lock()
POOL = ThreadPoolExecutor(max_workers=2)

HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VideoBox | تنزيل فيديو</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; font-family: Tahoma, Arial, sans-serif;
      color: #f8fafc; background: radial-gradient(circle at 15% 0%, #183b5c 0%, transparent 32%),
      linear-gradient(135deg,#090e1c,#101c34); }
    header { max-width: 1100px; margin: auto; padding: 30px 24px; font-size: 24px; font-weight: bold; }
    header span, h1 span { color: #38bdf8; }
    main { min-height: calc(100vh - 160px); display: flex; align-items: center;
      justify-content: center; padding: 24px; }
    .box { width: min(100%, 650px); background: #15233baa; border: 1px solid #354a67;
      border-radius: 22px; padding: 42px 34px; text-align: center; box-shadow: 0 24px 65px #02061775; }
    .icon { font-size: 47px; margin-bottom: 12px; }
    h1 { font-size: clamp(26px, 5vw, 39px); margin: 0 0 12px; }
    .subtitle { color: #adc0d9; font-size: 15px; line-height: 1.9; margin: 0 0 30px; }
    label { display: block; text-align: right; margin-bottom: 10px; font-weight: bold; }
    input { width: 100%; padding: 17px; background: #0b1428; border: 1px solid #405773;
      color: white; border-radius: 12px; outline: none; font-size: 15px; direction: ltr; }
    input:focus { border-color: #38bdf8; }
    button, .download-link { display: block; width: 100%; margin-top: 15px; border: 0;
      border-radius: 12px; padding: 16px; font-size: 16px; font-weight: bold; cursor: pointer;
      color: #04111e; background: #38bdf8; text-decoration: none; }
    button:hover, .download-link:hover { background: #7dd3fc; }
    button:disabled { opacity: .6; cursor: progress; }
    #status { margin-top: 22px; color: #cfdeee; min-height: 25px; }
    progress { display: none; margin: 12px auto 0; width: 100%; height: 16px; }
    .error { color: #fca5a5 !important; }
    .note { font-size: 12px; color: #91a5c1; margin: 22px 0 0; }
    footer { text-align: center; padding: 18px; color: #738aa9; font-size: 12px; }
    @media(max-width:550px) { .box { padding: 33px 18px; } }
  </style>
</head>
<body>
  <header>▶ <span>VideoBox</span></header>
  <main>
    <section class="box">
      <div class="icon">🎬</div>
      <h1>نزّل فيديوك <span>بسهولة</span></h1>
      <p class="subtitle">ألصق رابط فيديو YouTube ثم اضغط تحميل.<br>التنزيل يتم بواسطة جهازك، وليس GitHub Pages.</p>
      <form id="form">
        <label for="url">رابط الفيديو</label>
        <input id="url" name="url" type="url" dir="ltr" required
          placeholder="https://www.youtube.com/watch?v=..." autocomplete="off">
        <button id="start" type="submit">⬇ بدء التحميل</button>
      </form>
      <div id="status" role="status" aria-live="polite"></div>
      <progress id="progress" max="100" value="0"></progress>
      <a id="file" class="download-link" style="display:none">⬇ حفظ الفيديو على جهازك</a>
      <p class="note">استخدم الصفحة لتنزيل المحتوى المسموح لك بحفظه فقط.</p>
    </section>
  </main>
  <footer>VideoBox — موقع تجريبي محلي</footer>
  <script>
    const form = document.getElementById('form');
    const start = document.getElementById('start');
    const status = document.getElementById('status');
    const progress = document.getElementById('progress');
    const file = document.getElementById('file');
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    form.addEventListener('submit', async event => {
      event.preventDefault();
      start.disabled = true;
      file.style.display = 'none';
      progress.style.display = 'block';
      progress.value = 0;
      status.classList.remove('error');
      status.textContent = 'جاري الاتصال وتحضير الفيديو...';
      try {
        const response = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({url: document.getElementById('url').value.trim()})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'فشل بدء التنزيل');
        while (true) {
          await sleep(900);
          const r = await fetch('/api/status/' + data.id);
          if (!r.ok) throw new Error('تعذر قراءة حالة التحميل');
          const job = await r.json();
          status.textContent = job.message;
          if (typeof job.percent === 'number') progress.value = job.percent;
          if (job.state === 'error') throw new Error(job.message);
          if (job.state === 'ready') {
            progress.value = 100;
            file.href = '/file/' + data.id;
            file.style.display = 'block';
            file.click();
            break;
          }
        }
      } catch (e) {
        status.textContent = e.message;
        status.classList.add('error');
      } finally {
        start.disabled = false;
      }
    });
  </script>
</body>
</html>"""


def is_youtube_video_url(value):
    try:
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http") or parsed.port is not None:
            return False
        host = (parsed.hostname or "").lower()
        if host in ("youtu.be", "www.youtu.be"):
            return bool(parsed.path.strip("/"))
        if host not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            return False
        path = parsed.path.strip("/")
        return (path == "watch" and bool(parse_qs(parsed.query).get("v"))) or any(
            path.startswith(prefix) and len(path) > len(prefix)
            for prefix in ("shorts/", "live/", "embed/")
        )
    except (ValueError, TypeError):
        return False


def set_job(job_id, **changes):
    with LOCK:
        JOBS[job_id].update(changes)


def worker(job_id, url):
    directory = DOWNLOADS / job_id
    directory.mkdir(exist_ok=True)

    def on_progress(data):
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            current = data.get("downloaded_bytes", 0)
            percent = round(current * 100 / total, 1) if total else 0
            set_job(job_id, percent=min(percent, 99), message=f"جاري تنزيل الفيديو... {percent:.0f}%")
        elif data.get("status") == "finished":
            set_job(job_id, message="اكتمل التنزيل، جاري تجهيز الملف...")

    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(directory / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [on_progress],
    }
    try:
        set_job(job_id, state="downloading", message="جاري تجهيز الرابط...")
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        video_files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in
                       (".mp4", ".mkv", ".webm", ".mov", ".m4v")]
        if not video_files:
            raise RuntimeError("لم يتم العثور على ملف الفيديو. تأكد من تثبيت FFmpeg.")
        path = max(video_files, key=lambda p: p.stat().st_size)
        title = (info.get("title") or "الفيديو") if isinstance(info, dict) else "الفيديو"
        set_job(job_id, state="ready", percent=100, message=f"اكتمل: {title}", file=str(path))
    except (DownloadError, Exception) as exc:
        set_job(job_id, state="error", message=f"تعذّر التنزيل: {str(exc)[:260]}")


@app.get("/")
def home():
    return render_template_string(HTML)


@app.post("/api/start")
def start_download():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not is_youtube_video_url(url):
        return jsonify(error="ضع رابط فيديو YouTube صحيحًا، وليس رابط قناة أو قائمة تشغيل."), 400
    job_id = uuid4().hex
    with LOCK:
        JOBS[job_id] = {"state": "queued", "percent": 0, "message": "بانتظار بدء التنزيل..."}
    POOL.submit(worker, job_id, url)
    return jsonify(id=job_id)


@app.get("/api/status/<job_id>")
def job_status(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="الطلب غير موجود"), 404
        return jsonify({k: v for k, v in job.items() if k != "file"})


@app.get("/file/<job_id>")
def get_file(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job["state"] != "ready":
            return "الملف غير جاهز", 404
        path = Path(job["file"])
    return send_file(path, as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    print("افتح الموقع على: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
