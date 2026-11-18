import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from tools.guanshi_preview import CLIENT, SET_LOCAL_API, GuanshiPreview


def test_local_quote_endpoint_is_inserted_only_in_the_guanshi_http_response(tmp_path):
    original = b"<head>" + CLIENT + b"</head>"
    target = tmp_path / "guanshi.html"
    target.write_bytes(original)
    (tmp_path / "home.html").write_bytes(original)
    handler = partial(GuanshiPreview, directory=str(tmp_path))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/guanshi.html?asset=sh600519", timeout=5) as response:
                body = response.read()
                assert body.count(SET_LOCAL_API) == 1 and body.index(SET_LOCAL_API) < body.index(CLIENT)
                assert int(response.headers["Content-Length"]) == len(body)
                assert response.headers["Cache-Control"] == "no-store"
            with urlopen(Request(base + "/guanshi.html", method="HEAD"), timeout=5) as head:
                assert int(head.headers["Content-Length"]) == len(body)
                assert head.read() == b""
            with urlopen(base + "/home.html", timeout=5) as other:
                assert other.read() == original
            assert target.read_bytes() == original
        finally:
            server.shutdown()
            thread.join()
