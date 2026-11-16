import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from engine import Engine

engine = Engine("data")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/query":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        out = json.dumps({"results": engine.execute(body["sql"])}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    print("http://localhost:8000 에서 POST /query 를 기다립니다")
    HTTPServer(("localhost", 8000), Handler).serve_forever()   # 3단계: 아직 스레드 하나
