"""Loopback-only frontend preview; API routes proxy only the isolated loopback runner."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/preview/'):
            return self.api()
        path = self.path.split('?', 1)[0]
        if path in ('/stock', '/stock.html', '/', '/home', '/home.html'):
            name = 'stock.html' if path in ('/stock', '/stock.html') else 'home.html'
            page = (FRONTEND / name).read_text(encoding='utf-8')
            if name == 'stock.html':
                page = page.replace('<script src="app/lppl-data.js"></script>',
                    '<script>window.LPPL_REAL_PREVIEW=true;window.LPPL_QUERY_API="/api/preview";</script>'
                    '<script src="app/lppl-data.js"></script>')
            raw = page.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split('?', 1)[0] != '/api/preview/query':
            self.send_error(405)
            return
        self.api()

    def api(self):
        origin = self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self.send_error(403)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 2048:
            self.send_error(413)
            return
        data = self.rfile.read(length) if self.command == 'POST' else None
        request = Request('http://127.0.0.1:8793' + self.path, data=data,
                          method=self.command, headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=25)
        except HTTPError as error:
            response = error
        except OSError:
            self.send_error(502, 'Isolated preview runner is unavailable')
            return
        with response:
            raw = response.read()
            self.send_response(response.status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8792)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Local real preview: http://127.0.0.1:{args.port}/home.html', flush=True)
    server.serve_forever()
