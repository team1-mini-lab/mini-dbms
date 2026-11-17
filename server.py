import argparse
import json
import queue
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

from engine import Engine

MAX_BODY = 1024 * 1024   # 1MB


def error_body(code, message, **extra):
    return {"error": {"code": code, "message": message}, **extra}


BUSY_BODY = json.dumps(
    error_body("busy", "서버가 바쁩니다. 잠시 후 다시 보내 주세요"), ensure_ascii=False
).encode("utf-8")
BUSY_RESPONSE = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    + f"Content-Length: {len(BUSY_BODY)}\r\n".encode()
    + b"Connection: close\r\n\r\n"
    + BUSY_BODY
)


def linger_close(sock, timeout=0.2):
    """답을 먼저 보낸 뒤 클라이언트가 읽을 틈을 주고 닫는다 (큰 본문 도중 503/413 시 RST 방지)."""
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        return
    try:
        sock.settimeout(timeout)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            data = sock.recv(65536)
            if not data:
                break
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        self.requestline = ""
        self.request_version = ""
        self.command = ""
        self._read_timed_out = threading.Event()
        token = self.server._watch(self.connection, self._read_timed_out)
        try:
            try:
                self.raw_requestline = self.rfile.readline(65537)
            except TimeoutError:
                self._read_timed_out.set()
                self.raw_requestline = b""
            if self._read_timed_out.is_set():
                self.close_connection = True
                self._error(408, "timeout", f"{self.server.request_timeout}초 안에 요청을 받지 못했습니다")
                return
            if len(self.raw_requestline) > 65536:
                self.requestline = ""
                self.request_version = ""
                self.command = ""
                self.close_connection = True
                self._error(400, "bad_request", "요청 줄이 너무 깁니다")
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            if self._read_timed_out.is_set():
                self.close_connection = True
                self._error(408, "timeout", f"{self.server.request_timeout}초 안에 요청을 받지 못했습니다")
                return
            if self.command != "POST":
                self.server._unwatch(token)
                token = None
                self._error(405, "method_not_allowed", f"{self.command}는 받지 않습니다. POST /query 를 쓰세요")
                return
            self._handle_post(token)
            token = None
        finally:
            if token is not None:
                self.server._unwatch(token)

    def _handle_post(self, watch_token):
        if self.path != "/query":
            self.server._unwatch(watch_token)
            self._error(404, "not_found", f"없는 주소입니다: {self.path} (POST /query 만 있습니다)")
            return

        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            self.server._unwatch(watch_token)
            self._error(400, "bad_request", "Content-Length 헤더가 필요합니다")
            return
        try:
            length = int(raw_len)
            if length < 0:
                raise ValueError
        except ValueError:
            self.server._unwatch(watch_token)
            self._error(400, "bad_request", f"잘못된 Content-Length입니다: {raw_len}")
            return

        if length > MAX_BODY:
            self.server._unwatch(watch_token)
            self.close_connection = True
            self._error(413, "too_large", f"요청 본문이 너무 큽니다 (최대 {MAX_BODY}바이트)")
            linger_close(self.connection)
            return

        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            self._read_timed_out.set()
            raw = b""
        timed_out = self._read_timed_out.is_set()
        self.server._unwatch(watch_token)

        if timed_out:
            self.close_connection = True
            self._error(408, "timeout", f"{self.server.request_timeout}초 안에 본문을 다 받지 못했습니다")
            return
        if len(raw) < length:
            self.close_connection = True
            self._error(400, "bad_request", "본문이 Content-Length보다 짧습니다")
            return

        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise TypeError("요청 본문은 JSON 객체({...})여야 합니다")
            sql = body["sql"]
            if not isinstance(sql, str):
                raise ValueError("sql은 문자열이어야 합니다")
        except (ValueError, KeyError, TypeError) as e:
            self._error(400, "bad_request", f"본문을 읽을 수 없습니다: {e}")
            return

        try:
            results = self.server.engine.execute(sql, stop_on_error=True)
        except Exception:
            traceback.print_exc()
            self._error(500, "internal", "서버 내부 오류")
            return

        if results and results[-1]["type"] == "error":
            done = results[:-1]
            message = f"{len(done) + 1}번째 문장: {results[-1]['message']}"
            self._send(400, error_body("bad_sql", message, results=done))
            return
        self._send(200, {"results": results})

    def send_error(self, code, message=None, explain=None):
        """parse_request 등 http.server 내부에서 나는 오류도 JSON으로 통일한다."""
        self.close_connection = True
        if getattr(self, "_read_timed_out", None) and self._read_timed_out.is_set():
            self._error(408, "timeout", f"{self.server.request_timeout}초 안에 요청을 받지 못했습니다")
            return
        self._error(code, "bad_request", message or "잘못된 HTTP 요청입니다")

    def _error(self, status, code, message):
        self._send(status, error_body(code, message))

    def _send(self, status, obj):
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("X-Worker", threading.current_thread().name)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(out)

    def log_message(self, format, *args):
        print(f"[{threading.current_thread().name}] {self.address_string()} - {format % args}")


class PooledHTTPServer(HTTPServer):
    """Phase 3(15·17단계): 요청을 큐에 넣고, 미리 만든 스레드 N개가 꺼내서 처리하는 서버."""

    request_queue_size = 128

    def __init__(self, address, handler, engine, workers=4, queue_size=16, request_timeout=5):
        self.request_timeout = request_timeout
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout + 0.5})
        super().__init__(address, handler)
        self.engine = engine
        self.jobs = queue.Queue(maxsize=queue_size)
        self._watch_lock = threading.Lock()
        self._watching = {}
        self._next_token = 0
        self._stop_watch = threading.Event()
        self._watcher = threading.Thread(target=self._watch_loop, name="watcher", daemon=True)
        self._watcher.start()
        self.workers = [
            threading.Thread(target=self._work, name=f"worker-{n}", daemon=True)
            for n in range(1, workers + 1)
        ]
        for worker in self.workers:
            worker.start()

    def _watch(self, sock, event):
        with self._watch_lock:
            self._next_token += 1
            token = self._next_token
            self._watching[token] = (time.monotonic() + self.request_timeout, sock, event)
            return token

    def _unwatch(self, token):
        with self._watch_lock:
            self._watching.pop(token, None)

    def _watch_loop(self):
        while not self._stop_watch.is_set():
            now = time.monotonic()
            expired = []
            with self._watch_lock:
                for token, (deadline, sock, event) in list(self._watching.items()):
                    if now >= deadline:
                        expired.append((sock, event))
                        del self._watching[token]
            for sock, event in expired:
                event.set()
                try:
                    sock.shutdown(socket.SHUT_RD)   # 읽기만 깨워 408 응답을 보낼 수 있게 함
                except OSError:
                    pass
            self._stop_watch.wait(0.05)

    def process_request(self, request, client_address):
        try:
            self.jobs.put_nowait((request, client_address))
        except queue.Full:
            self._reject_busy(request)
            self.shutdown_request(request)

    def _work(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            request, client_address = job
            try:
                self.finish_request(request, client_address)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)

    def _reject_busy(self, request):
        try:
            request.sendall(BUSY_RESPONSE)
            linger_close(request)
        except OSError:
            pass

    def server_close(self):
        self._stop_watch.set()
        with self._watch_lock:
            active_socks = [sock for _, sock, _ in self._watching.values()]
            for _, _, ev in self._watching.values():
                ev.set()
            self._watching.clear()
        for sock in active_socks:
            try:
                sock.shutdown(socket.SHUT_RD)
            except OSError:
                pass
        super().server_close()
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                self.shutdown_request(job[0])
        for _ in self.workers:
            self.jobs.put(None)
        for worker in self.workers:
            worker.join(timeout=1)
        self._watcher.join(timeout=1)


def positive_int(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"정수여야 합니다: {value}")
    if n < 1:
        raise argparse.ArgumentTypeError(f"1 이상이어야 합니다: {value}")
    return n


def port_int(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"정수여야 합니다: {value}")
    if not (1 <= n <= 65535):
        raise argparse.ArgumentTypeError(f"1~65535 사이여야 합니다: {value}")
    return n


def parse_arguments():
    parser = argparse.ArgumentParser(description="미니 DBMS API 서버")
    parser.add_argument("--port", type=port_int, default=8000, help="받을 포트 (기본 8000)")
    parser.add_argument("--workers", type=positive_int, default=4, help="미리 만들어 둘 스레드 수 (기본 4)")
    parser.add_argument("--queue", type=positive_int, default=16, help="기다릴 수 있는 요청 수 (기본 16)")
    return parser.parse_args()


def main():
    args = parse_arguments()
    try:
        engine = Engine("data")
        server = PooledHTTPServer(("localhost", args.port), Handler, engine, args.workers, args.queue)
    except OSError as e:
        print(f"서버를 켤 수 없습니다 (포트 {args.port}): {e}", file=sys.stderr)
        sys.exit(1)
    print(f"http://localhost:{args.port} 에서 POST /query 를 기다립니다 (스레드 {args.workers}개, 큐 {args.queue}칸)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 끕니다")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
