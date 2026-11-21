# Clip Cutter

Paste a YouTube link (or upload a video) and get vertical 9:16 clips (20/30/40/45/60 s):
gameplay as a 1:1 square on top, face cam filling the bottom.

Only use videos you own or have permission to use.

## Deploy from your phone (free)

1. On github.com (phone browser, "Desktop site" helps), create a new repository.
2. Tap Add file > Upload files, and upload: app.py, index.html, requirements.txt, Dockerfile, README.md. Commit.
3. On render.com sign up (use your GitHub login) > New > Web Service > pick your repo.
4. Set Runtime to Docker, choose the Free instance, and Deploy.
5. When it finishes, open the https://....onrender.com link on your phone.

## Notes

- Free hosts sleep when idle; the first load can take about a minute.
- Free hosts may have limited disk and CPU, so keep source videos short (under about 30 min) and clip counts small.
- YouTube often blocks downloads from cloud servers. If the link fails, download the video on your phone and use the upload option on the page.
- Face cam position: use the sliders and tap Update preview. Defaults are set for a face cam on the left, middle.
