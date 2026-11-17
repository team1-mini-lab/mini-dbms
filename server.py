"""미니 DBMS API 서버: POST /query 로 SQL을 받아 엔진(engine.py)에서 실행하고 JSON으로 답한다.

이 파일에는 과제에 꼭 필요한 것만 있습니다.
- Phase 3(15단계) Thread Pool: 요청을 큐에 줄 세우고, 미리 만든 스레드 N개가 꺼내서 처리. 큐가 꽉 차면 503
- Phase 3(17단계) 오류 응답: 모든 오류를 {"error": {"code", "message"}} 한 모양의 JSON으로

느린 연결, 이상한 Content-Length 같은 엣지 케이스 방어는 server_guard.py에 따로 있습니다.
`python3 server.py`로 켜면 그 방어까지 켜진 서버가 뜹니다 (맨 아래 참고).
"""
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


def error_body(code, message, **extra):
    """Phase 3(17단계): 모든 오류를 {"error": {"code", "message"}} 한 모양으로 만든다."""
    return {"error": {"code": code, "message": message}, **extra}


# Phase 3(17단계): http.server가 스스로 내는 오류를 우리 오류 목록(D38)의 번호와 code로 바꿔 줌
#   501(모르는 방식) → 405, 414·431(주소·머리가 너무 김) → 413, 505와 그 밖 → 400
HTTP_ERRORS = {
    400: (400, "bad_request", "요청 형식이 잘못됐습니다"),
    408: (408, "timeout", "요청을 제한 시간 안에 다 받지 못했습니다"),
    414: (413, "too_large", "주소가 너무 깁니다"),
    431: (413, "too_large", "요청 머리가 너무 큽니다"),
    501: (405, "method_not_allowed", "POST만 받습니다"),
    505: (400, "bad_request", "HTTP/1.0 또는 HTTP/1.1만 받습니다"),
}

BUSY_BODY = json.dumps(
    error_body("busy", "서버가 바쁩니다. 잠시 후 다시 보내 주세요"), ensure_ascii=False
).encode("utf-8")
BUSY_RESPONSE = (                             # 503은 받는 스레드가 Handler 없이 바로 보내므로 미리 만들어 둠
    b"HTTP/1.0 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    + f"Content-Length: {len(BUSY_BODY)}\r\n".encode()
    + b"Connection: close\r\n\r\n"
    + BUSY_BODY
)


def linger_close(sock, timeout=0.2, idle=0.02):
    """Phase 3(15·17단계): 답을 보낸 뒤 '보내기'만 먼저 닫고, 클라이언트가 보내던 요청을 잠깐 읽어 버린다.

    요청을 읽지 않은 채 바로 닫으면 운영체제가 연결을 강제로 끊어서(RST) 클라이언트가 503을 못 읽을 수 있다.
    최대 timeout초까지 읽되, idle초 동안 아무것도 안 오면 바로 끝낸다 (받는 스레드를 오래 붙잡지 않게).
    """
    try:
        sock.shutdown(socket.SHUT_WR)             # "답은 다 보냈다"고 알림
    except OSError:
        return
    try:
        sock.settimeout(idle)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not sock.recv(65536):              # 클라이언트가 닫으면 끝
                break
    except OSError:                               # idle초 동안 아무것도 안 옴(timeout)도 여기로
        pass


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/query":
            self._error(404, "not_found", f"없는 주소입니다: {self.path} (POST /query 만 있습니다)")
            return
        raw = self._read_body()
        if raw is None:                           # 이미 오류로 답함
            return
        sql = self._parse_sql(raw)
        if sql is None:                           # 이미 오류로 답함
            return
        try:
            results = self.server.engine.execute(sql, stop_on_error=True)   # 첫 오류에서 멈춤 (D30)
        except Exception:
            # Phase 3(17단계, D39): SQL이 틀린 게 아니라 서버가 고장. 자세한 내용은 서버 로그에만
            traceback.print_exc()
            self._error(500, "internal", "서버 내부 오류입니다. 이 요청의 앞쪽 문장은 이미 저장됐을 수 있습니다")
            return
        if results and results[-1]["type"] == "error":
            done = results[:-1]                   # 실패 전까지 실행된(이미 저장된) 문장
            message = f"{len(done) + 1}번째 문장: {results[-1]['message']}"
            self._send(400, error_body("bad_sql", message, results=done))
            return
        self._send(200, {"results": results})

    def _read_body(self):
        """본문을 Content-Length만큼 읽는다. 숫자가 아니면 400으로 답하고 None. (server_guard.py가 검사를 더함)"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._error(400, "bad_request", f"잘못된 Content-Length입니다: {self.headers.get('Content-Length')}")
            return None
        return self.rfile.read(length)

    def _parse_sql(self, raw):
        """본문 JSON에서 sql 문자열을 꺼낸다. 틀리면 400으로 답하고 None."""
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or "sql" not in body:
                raise ValueError('본문은 {"sql": "..."} 모양이어야 합니다')
            if not isinstance(body["sql"], str):
                raise ValueError("sql은 문자열이어야 합니다")
            return body["sql"]
        except (ValueError, RecursionError) as e:   # JSON 오류도 ValueError. RecursionError는 [[[[... 처럼 아주 깊은 JSON
            self._error(400, "bad_request", f"본문을 읽을 수 없습니다: {e}")
            return None

    def send_error(self, code, message=None, explain=None):
        """Phase 3(17단계): http.server가 스스로 내는 오류도 JSON으로 (원래는 HTML).

        요청 줄이 깨졌거나, 주소·머리가 너무 길거나, do_GET 같은 함수가 없을 때 http.server가 이 함수를 부른다.
        """
        self.close_connection = True
        status, error_code, text = HTTP_ERRORS.get(code, HTTP_ERRORS[400])
        if status == 405:
            text = f"{self.command}는 받지 않습니다. POST /query 를 쓰세요"
        elif message and status == 400:
            text = f"{text} ({message})"           # 파이썬이 준 원래 설명(영어)을 괄호로 붙임
        self._error(status, error_code, text)

    def _error(self, status, code, message):
        self._send(status, error_body(code, message))

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


class PooledHTTPServer(HTTPServer):
    """Phase 3(15단계): 요청을 큐에 넣고, 미리 만든 스레드 N개가 꺼내서 처리하는 서버.

    받는 스레드(serve_forever를 돌리는 스레드)는 연결을 받아 큐에 넣기만 하고 바로 다음 연결을 받는다.
    실제 처리(요청 읽기 → engine.execute → 응답 쓰기)는 일하는 스레드들이 한다.
    """

    request_queue_size = 128                  # 운영체제가 받아 두는 연결 수 (동시 요청이 많을 때 연결이 거절되지 않게)

    def __init__(self, address, handler, engine, workers=4, queue_size=16, request_timeout=5):
        # Phase 3(17단계): 포트가 이미 쓰이면 super().__init__ 안에서 server_close()가 불린다.
        # 그때 server_close가 쓰는 것(jobs, workers)이 없으면 진짜 이유가 AttributeError에 가려지므로 먼저 만든다
        self.engine = engine                  # 모든 스레드가 같은 엔진 하나를 씀 (lock은 엔진 안에)
        self.request_timeout = request_timeout
        self.jobs = queue.Queue(maxsize=queue_size)
        self.workers = []
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # 한 번 받을 때 기다리는 최대 시간
        super().__init__(address, handler)
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
        """큐가 꽉 찼을 때: 503 JSON을 보내고, 클라이언트가 읽을 수 있게 닫는다."""
        try:
            request.sendall(BUSY_RESPONSE)
        except OSError:
            return
        linger_close(request)

    def server_close(self):
        super().server_close()
        while True:                               # Phase 3(17단계): 아직 못 꺼낸 연결은 닫고 버려서 "그만" 신호 자리를 만듦
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                self.shutdown_request(job[0])
        for _ in self.workers:
            try:
                self.jobs.put_nowait(None)        # 스레드마다 "그만" 신호 하나씩
            except queue.Full:
                break
        for worker in self.workers:
            worker.join(timeout=1)


def positive_int(text):
    """Phase 3(17단계): 1 이상의 정수만 받는다. --queue 0이면 Queue(0) = 크기 제한 없음이 되어 503이 사라짐."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"1 이상이어야 합니다: {text}")
    return value


def parse_arguments():
    parser = argparse.ArgumentParser(description="미니 DBMS API 서버")
    parser.add_argument("--host", default="localhost", help="받을 주소 (기본 localhost. 배포할 때는 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="받을 포트 (기본 8000)")
    parser.add_argument("--workers", type=positive_int, default=4, help="미리 만들어 둘 스레드 수 (기본 4)")
    parser.add_argument("--queue", type=positive_int, default=16, help="기다릴 수 있는 요청 수 (기본 16)")
    return parser.parse_args()


def main(server_class=PooledHTTPServer, handler_class=Handler):
    args = parse_arguments()
    try:
        engine = Engine("data")
    except OSError as e:                      # Phase 3(17단계): data/ 폴더가 없는 곳에서 켠 경우
        sys.exit(f"데이터 폴더를 열 수 없습니다 (저장소 맨 위 폴더에서 실행하세요): {e}")
    try:
        server = server_class((args.host, args.port), handler_class, engine, args.workers, args.queue)
    except (OSError, OverflowError) as e:     # Phase 3(17단계): 포트가 이미 쓰임, 없는 포트 번호 등
        sys.exit(f"서버를 켤 수 없습니다 (포트 {args.port}): {e}")
    port = server.server_address[1]           # --port 0이면 운영체제가 고른 빈 포트
    print(f"http://{args.host}:{port} 에서 POST /query 를 기다립니다 (스레드 {args.workers}개, 큐 {args.queue}칸)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 끕니다")
    finally:
        server.server_close()


if __name__ == "__main__":
    import server_guard                      # 기본으로 엣지 케이스 방어(server_guard.py)를 켠 서버를 띄움
    server_guard.main()
