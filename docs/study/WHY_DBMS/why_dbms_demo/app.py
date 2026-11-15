"""정글마켓의 "프로그램" 하나. 같은 코드를 역할만 바꿔 여러 개 띄운다.

    python -m why_dbms_demo.app --role 주문 --mode file --port 8402 --data ./demo_data

--mode file   프로그램이 CSV 파일을 직접 읽고 쓴다
--mode dbms   프로그램이 SQL로 DBMS(SQLite)에 부탁한다

표준 라이브러리만 쓴다 (설치할 것 없음).
"""
import argparse
import json
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from why_dbms_demo.store import make_store


def make_handler(store, role, delay):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):          # 시연 화면을 어지럽히지 않게
            pass

        def _send(self, code, body):
            body = dict(body, program=role, mode=store.mode)
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n))
            except ValueError:
                return {}

        def _route(self, method):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path.rstrip("/") or "/"
            try:
                if method == "GET" and p == "/":
                    return self._send(200, {"ok": True})
                m = re.fullmatch(r"/members/(\w+)", p)
                if method == "PUT" and m:
                    return self._send(200, store.set_address(m.group(1), self._body().get("address", "")))
                if method == "POST" and p == "/ship":
                    return self._send(200, store.ship(self._body().get("user", "kim")))
                if method == "POST" and p == "/admin/coupon":
                    return self._send(200, store.add_coupon_column())
                if method == "GET" and p == "/revenue":
                    return self._send(200, store.revenue())
                if method == "POST" and p == "/query":
                    try:
                        return self._send(200, store.query(self._body().get("sql", "")))
                    except NotImplementedError as e:
                        return self._send(501, {"error": str(e)})
                m = re.fullmatch(r"/orders/(\d+)", p)
                if method == "GET" and m:
                    return self._send(200, store.get_order(int(m.group(1))))
                if method == "GET" and p == "/orders":
                    return self._send(200, store.orders_of(q.get("user", "")))
                if method == "POST" and p == "/stock/reset":
                    return self._send(200, store.reset_stock(int(self._body().get("count", 1))))
                if method == "POST" and p == "/buy":
                    return self._send(200, store.buy(self._body().get("user", "?"), float(q.get("delay", delay))))
                if method == "GET" and p == "/stock":
                    return self._send(200, store.stock_status())
                if method == "POST" and p == "/checkout":
                    return self._send(200, store.checkout(q.get("crash") == "1"))
                if method == "GET" and p == "/consistency":
                    return self._send(200, store.consistency())
                return self._send(404, {"error": "no such endpoint"})
            except Exception as e:                       # 프로그램이 깨진 모습을 그대로 보여 준다
                last = traceback.extract_tb(e.__traceback__)[-1]
                return self._send(500, {"error": f"{type(e).__name__}: {e}", "where": last.line})

        def do_GET(self): self._route("GET")
        def do_POST(self): self._route("POST")
        def do_PUT(self): self._route("PUT")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default="주문")
    ap.add_argument("--mode", choices=["file", "dbms"], default="file")
    ap.add_argument("--port", type=int, default=8402)
    ap.add_argument("--data", default="./demo_data")
    ap.add_argument("--delay", type=float, default=0.3, help="장면 ⑤에서 읽기와 쓰기 사이 시간(초)")
    a = ap.parse_args()
    store = make_store(a.mode, a.data if a.mode == "dbms" else a.data)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(store, a.role, a.delay)).serve_forever()


if __name__ == "__main__":
    main()
