"""Serve an assembled Guanshi site against the local instance of the stock Worker."""

import argparse
import io
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8797
CLIENT = b'<script defer src="app/lppl-data.js"></script>'
SET_LOCAL_API = b'<script>window.LPPL_QUERY_API = "http://127.0.0.1:8798";</script>'


class GuanshiPreview(SimpleHTTPRequestHandler):
    def send_head(self):
        if urlsplit(self.path).path != "/guanshi.html":
            return super().send_head()
        html = (Path(self.directory) / "guanshi.html").read_bytes()
        if html.count(CLIENT) != 1:
            self.send_error(500, "Cannot locate the shared data client in the built page")
            return None
        html = html.replace(CLIENT, SET_LOCAL_API + b"\n  " + CLIENT)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(html)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True, help="Built site with lab/mock/data")
    args = parser.parse_args()
    site = args.site.resolve()
    if not (site / "guanshi.html").is_file() or not (site / "lab/mock/data").is_dir():
        parser.error("--site must be the output of scripts/build_site.sh")
    handler = partial(GuanshiPreview, directory=str(site))
    with ThreadingHTTPServer((HOST, PORT), handler) as server:
        print(f"Guanshi: http://{HOST}:{PORT}/guanshi.html", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
