#!/usr/bin/env python3
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import os
import time


REPOSITORY = Path(os.environ.get("REPOSITORY_DIR", "/repository"))
PORT = int(os.environ.get("WEB_PORT", "80"))
PLAYLIST_EXTENSIONS = {".m3u", ".m3u8", ".pls", ".xspf"}


def scan_repository():
    mp3_count = 0
    playlist_count = 0
    total_bytes = 0
    last_modified = None

    for path in REPOSITORY.rglob("*"):
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        try:
            stat = path.stat()
        except OSError:
            continue

        if suffix == ".mp3":
            mp3_count += 1
            total_bytes += stat.st_size
            last_modified = max(last_modified or stat.st_mtime, stat.st_mtime)
        elif suffix in PLAYLIST_EXTENSIONS:
            playlist_count += 1
            last_modified = max(last_modified or stat.st_mtime, stat.st_mtime)

    return mp3_count, playlist_count, total_bytes, last_modified


def human_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def render_page():
    mp3_count, playlist_count, total_bytes, last_modified = scan_repository()
    updated = "sem arquivos de midia encontrados"
    if last_modified is not None:
        updated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_modified))

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PiCASSO Repo</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f7f8fa;
      color: #14171a;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }}
    main {{
      width: min(760px, calc(100vw - 32px));
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 32px;
      line-height: 1.1;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 0 0 24px;
      color: #5b6470;
      font-size: 15px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .stat {{
      border: 1px solid #d8dde4;
      border-radius: 8px;
      padding: 18px;
      background: #ffffff;
    }}
    .label {{
      color: #66717f;
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .value {{
      font-size: 28px;
      line-height: 1;
      font-weight: 700;
    }}
    .meta {{
      margin-top: 16px;
      color: #66717f;
      font-size: 13px;
    }}
    @media (max-width: 640px) {{
      .stats {{
        grid-template-columns: 1fr;
      }}
      h1 {{
        font-size: 28px;
      }}
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        background: #101316;
        color: #eef1f4;
      }}
      .subtitle, .label, .meta {{
        color: #a8b1bc;
      }}
      .stat {{
        background: #171b20;
        border-color: #2b333d;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>PiCASSO Repo</h1>
    <p class="subtitle">{escape(str(REPOSITORY))}</p>
    <section class="stats" aria-label="Resumo da biblioteca">
      <div class="stat">
        <div class="label">MP3</div>
        <div class="value">{mp3_count}</div>
      </div>
      <div class="stat">
        <div class="label">Playlists</div>
        <div class="value">{playlist_count}</div>
      </div>
      <div class="stat">
        <div class="label">Tamanho dos MP3</div>
        <div class="value">{human_size(total_bytes)}</div>
      </div>
    </section>
    <p class="meta">Ultima atualizacao: {escape(updated)}</p>
  </main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path != "/":
            self.send_error(404)
            return

        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving PiCASSO Repo status on port {PORT}", flush=True)
    server.serve_forever()
