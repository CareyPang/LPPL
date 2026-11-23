"""Loopback-only preview of local international research exports; no publication.

Usage: python scripts/preview_global_terminal.py --results D:/.../global-terminal
Local global JSON wins. Existing A-share JSON is read from the public Pages site.
POST is disabled. Do not expose this development server to the Internet.
"""
from argparse import ArgumentParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    parser = ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8796)
    args = parser.parse_args()
    front = Path(__file__).resolve().parents[1] / 'frontend'
    global_root = (args.results / 'global').resolve()

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            route = urlsplit(path).path
            base, relative = ((global_root, route[len('/lab/mock/data/global/'):])
                              if route.startswith('/lab/mock/data/global/') else (front, route.lstrip('/')))
            resolved = (base / relative).resolve()
            return str(resolved if resolved.is_relative_to(base) else base / '__invalid__')

        def send_data(self, data, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            route = urlsplit(self.path).path
            if route.startswith('/lab/mock/data/global/'):
                return super().do_GET()
            if route == '/app/lppl-data.js':
                return self.send_data(b"window.LPPL_QUERY_API='/api';\n" +
                                      (front / 'app/lppl-data.js').read_bytes(), 'text/javascript; charset=utf-8')
            if route.startswith('/lab/mock/data/') or route.startswith('/api/'):
                url = ('https://careypang.github.io/LPPL' + self.path if route.startswith('/lab/')
                       else 'https://lppl-stock-query.careypang.workers.dev' + self.path[4:])
                try:
                    with urlopen(url, timeout=20) as response:
                        self.send_data(response.read(), 'application/json; charset=utf-8')
                except HTTPError as error:
                    self.send_error(error.code)
                except (URLError, TimeoutError):
                    self.send_error(502)
                return
            return super().do_GET()

        def do_POST(self):
            self.send_error(405)

    print(f'Local research preview: http://127.0.0.1:{args.port}/home.html', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
