import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from engine import Engine

engine = Engine("data")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/query":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            sql = body["sql"]
            if not isinstance(sql, str):
                raise ValueError("sql은 문자열이어야 합니다")
        except (ValueError, KeyError, TypeError) as e:   # JSON 오류·UnicodeDecodeError는 ValueError의 하위
            self._send(400, {"error": {"code": "bad_request", "message": str(e)}})   # 모양은 17단계에서 확정
            return
        self._send(200, {"results": engine.execute(sql)})

    def _send(self, status, obj):
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    print("http://localhost:8000 에서 POST /query 를 기다립니다")
    HTTPServer(("localhost", 8000), Handler).serve_forever()   # 3단계: 아직 스레드 하나
