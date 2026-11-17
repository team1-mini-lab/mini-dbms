import argparse
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from engine import Engine


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
        results = self.server.engine.execute(sql, stop_on_error=True)   # 첫 오류에서 멈춤
        if results and results[-1]["type"] == "error":
            done = results[:-1]                                   # 실패 전까지 실행된(이미 저장된) 문장
            message = f"{len(done) + 1}번째 문장: {results[-1]['message']}"
            self._send(400, {"error": {"code": "bad_sql", "message": message}, "results": done})
            return
        self._send(200, {"results": results})

    def _send(self, status, obj):
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("X-Worker", threading.current_thread().name)   # Phase 3(15단계): 어느 스레드가 처리했는지
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, format, *args):
        # Phase 3(15단계): 로그 앞에 처리한 스레드 이름을 붙임. 여러 스레드가 나눠 처리하는 것을 눈으로 확인
        print(f"[{threading.current_thread().name}] {self.address_string()} - {format % args}")


BUSY_BODY = json.dumps(
    {"error": {"code": "busy", "message": "서버가 바쁩니다. 잠시 후 다시 보내 주세요"}}, ensure_ascii=False
).encode("utf-8")
BUSY_RESPONSE = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    + f"Content-Length: {len(BUSY_BODY)}\r\n".encode()
    + b"Connection: close\r\n\r\n"
    + BUSY_BODY
)


class PooledHTTPServer(HTTPServer):
    """Phase 3(15단계): 요청을 큐에 넣고, 미리 만든 스레드 N개가 꺼내서 처리하는 서버.

    받는 스레드(serve_forever를 돌리는 스레드)는 연결을 받아 큐에 넣기만 하고 바로 다음 연결을 받는다.
    실제 처리(요청 읽기 → engine.execute → 응답 쓰기)는 일하는 스레드들이 한다.
    """

    request_queue_size = 128                  # 운영체제가 받아 두는 연결 수 (동시 요청이 많을 때 연결이 거절되지 않게)

    def __init__(self, address, handler, engine, workers=4, queue_size=16, request_timeout=5):
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # 요청 하나당 시간 제한
        super().__init__(address, handler)
        self.engine = engine                  # 모든 스레드가 같은 엔진 하나를 씀 (lock은 엔진 안에)
        self.jobs = queue.Queue(maxsize=queue_size)
        self.workers = [
            threading.Thread(target=self._work, name=f"worker-{n}", daemon=True)
            for n in range(1, workers + 1)
        ]
        for worker in self.workers:
            worker.start()

    def process_request(self, request, client_address):
        """받는 스레드가 연결 하나를 받을 때마다 부름. 큐에 넣기만 한다."""
        try:
            self.jobs.put_nowait((request, client_address))   # 기다리지 않음. 꽉 차 있으면 바로 Full
        except queue.Full:
            self._reject_busy(request)
            self.shutdown_request(request)

    def _work(self):
        """일하는 스레드 하나가 하는 일: 큐에서 꺼내 처리하기를 계속 반복한다."""
        while True:
            job = self.jobs.get()                 # 큐가 비어 있으면 일이 들어올 때까지 여기서 기다림
            if job is None:                       # 서버를 끌 때 넣는 "그만" 신호
                return
            request, client_address = job
            try:
                self.finish_request(request, client_address)   # Handler를 만들어 do_POST 등을 실행
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)    # 연결 닫기

    def _reject_busy(self, request):
        try:
            request.sendall(BUSY_RESPONSE)
        except OSError:
            pass

    def server_close(self):
        super().server_close()
        for _ in self.workers:
            self.jobs.put(None)                   # 스레드마다 "그만" 신호 하나씩
        for worker in self.workers:
            worker.join(timeout=1)


def parse_arguments():
    parser = argparse.ArgumentParser(description="미니 DBMS API 서버")
    parser.add_argument("--port", type=int, default=8000, help="받을 포트 (기본 8000)")
    parser.add_argument("--workers", type=int, default=4, help="미리 만들어 둘 스레드 수 (기본 4)")
    parser.add_argument("--queue", type=int, default=16, help="기다릴 수 있는 요청 수 (기본 16)")
    return parser.parse_args()


def main():
    args = parse_arguments()
    engine = Engine("data")
    server = PooledHTTPServer(("localhost", args.port), Handler, engine, args.workers, args.queue)
    print(f"http://localhost:{args.port} 에서 POST /query 를 기다립니다 (스레드 {args.workers}개, 큐 {args.queue}칸)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 끕니다")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
