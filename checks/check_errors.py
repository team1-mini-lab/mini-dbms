"""Phase 3(17단계) API 오류 응답과 서버 방어 확인 스크립트.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_errors.py
"""

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from engine import Engine  # noqa: E402
from server import Handler, MAX_BODY, PooledHTTPServer  # noqa: E402

results = []


def check(name, ok, detail=""):
    mark = "통과" if ok else "실패"
    print(f"{mark}  {name}" + (f"  ({detail})" if detail != "" else ""))
    results.append(ok)


def start_server(workers=4, queue_size=16, request_timeout=5):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    server = PooledHTTPServer(
        ("localhost", 0), Handler, Engine(tmp),
        workers=workers, queue_size=queue_size, request_timeout=request_timeout,
    )
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, tmp


def stop_server(server, tmp):
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp)


def sql_body(sql):
    return json.dumps({"sql": sql}).encode("utf-8")


def request(port, method="POST", path="/query", body=b"", headers=None, timeout=5):
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=timeout)
        hdrs = dict(headers or {})
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw) if raw else {}, dict(resp.getheaders())
    except Exception as e:
        return type(e).__name__, {}, {}


def has_error_shape(body):
    err = body.get("error")
    return isinstance(err, dict) and isinstance(err.get("code"), str) and isinstance(err.get("message"), str)


# 1. 오류 모양과 상태 코드 (404, 405, 400)
print("1. 오류 모양과 404 / 405 / 400 확인")
server, tmp = start_server(workers=2, queue_size=8, request_timeout=2)
port = server.server_address[1]

st, body, _ = request(port, "POST", "/nope", sql_body("SELECT * FROM users;"))
check("없는 주소 → 404 not_found", st == 404 and has_error_shape(body) and body["error"]["code"] == "not_found", body)

st, body, _ = request(port, "GET", "/query")
check("GET /query → 405 method_not_allowed", st == 405 and has_error_shape(body) and body["error"]["code"] == "method_not_allowed", body)

st, body, _ = request(port, "POST", "/query", b"not json")
check("JSON 아님 → 400 bad_request", st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_request", body)

st, body, _ = request(port, "POST", "/query", b'{"query": "SELECT * FROM users;"}')
check("sql 키 없음 → 400 bad_request", st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_request", body)

st, body, _ = request(port, "POST", "/query", b'{"sql": 123}')
check("sql이 문자열 아님 → 400 bad_request", st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_request", body)

st, body, _ = request(port, "POST", "/query", b"[1, 2]")
check("본문이 JSON 배열 → 400 bad_request", st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_request", body)

st, body, _ = request(
    port, "POST", "/query",
    sql_body("INSERT INTO users (name, age) VALUES ('현지', 25); SELEC 1; INSERT INTO users (name, age) VALUES ('민수', 31);")
)
check(
    "틀린 SQL 섞임 → 400 bad_sql + 앞 결과 포함",
    st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_sql"
    and len(body.get("results", [])) == 1 and "2번째 문장" in body["error"]["message"],
    body,
)

# 2. 413 too_large (1MB 초과)
print("\n2. 1MB 초과 → 413 too_large")
s = socket.create_connection(("localhost", port))
s.settimeout(3)
s.sendall(f"POST /query HTTP/1.1\r\nHost: localhost\r\nContent-Length: {MAX_BODY + 1}\r\n\r\n".encode())
raw = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    raw += chunk
s.close()
head, _, json_part = raw.partition(b"\r\n\r\n")
body413 = json.loads(json_part)
check("1MB 초과 요청 → 413 too_large", b"413 " in head and has_error_shape(body413) and body413["error"]["code"] == "too_large", body413)

# 3. 500 internal (내부 오류 숨김)
print("\n3. 예상 못 한 오류 → 500 internal")
orig_execute = server.engine.execute
orig_print_exc = __import__("traceback").print_exc
__import__("traceback").print_exc = lambda *a, **kw: None
server.engine.execute = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("/secret/path/boom"))
st, body, _ = request(port, "POST", "/query", sql_body("SELECT * FROM users;"))
server.engine.execute = orig_execute
__import__("traceback").print_exc = orig_print_exc
check(
    "엔진 예외 → 500 internal (내부 경로 노출 안 함)",
    st == 500 and has_error_shape(body) and body["error"]["code"] == "internal" and "/secret/path" not in json.dumps(body),
    body,
)
stop_server(server, tmp)

# 4. 408 timeout (받는 시간 전체 제한: 0바이트 대기 & 천천히 보내는 공격)
print("\n4. 느린 요청 → 408 timeout")
server, tmp = start_server(workers=2, queue_size=4, request_timeout=1)
port = server.server_address[1]

# 4-1. 연결만 하고 아무것도 안 보냄
s = socket.create_connection(("localhost", port))
s.settimeout(3)
start = time.monotonic()
got = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    got += chunk
elapsed = time.monotonic() - start
s.close()
body408 = json.loads(got.partition(b"\r\n\r\n")[2])
check(f"아무것도 안 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408["error"]["code"] == "timeout", body408)

# 4-2. 본문을 0.35초마다 1바이트씩 천천히 보냄 (전체 시간 초과)
s = socket.create_connection(("localhost", port))
s.settimeout(3)
s.sendall(b"POST /query HTTP/1.1\r\nHost: localhost\r\nContent-Length: 50\r\n\r\n")
start = time.monotonic()
for _ in range(5):
    try:
        s.sendall(b"{")
    except OSError:
        break
    time.sleep(0.35)
got = b""
while True:
    try:
        chunk = s.recv(65536)
    except OSError:
        break
    if not chunk:
        break
    got += chunk
elapsed = time.monotonic() - start
s.close()
body408_slow = json.loads(got.partition(b"\r\n\r\n")[2])
check(f"본문을 덜 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408_slow["error"]["code"] == "timeout", body408_slow)

# 4-3. 헤더를 끝내지 않고 천천히 보냄 (전체 시간 초과)
s = socket.create_connection(("localhost", port))
s.settimeout(3)
s.sendall(b"POST /query HTTP/1.1\r\nHost: localhost\r\n")
start = time.monotonic()
got = b""
while True:
    try:
        chunk = s.recv(65536)
    except OSError:
        break
    if not chunk:
        break
    got += chunk
elapsed = time.monotonic() - start
s.close()
body408_hdr = json.loads(got.partition(b"\r\n\r\n")[2])
check(f"헤더를 덜 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408_hdr["error"]["code"] == "timeout", body408_hdr)
stop_server(server, tmp)

# 5. 스레드 1개·큐 1칸 꽉 채우고 큰 본문(200KB) 30번 → 모두 503 읽음
print("\n5. 스레드 1개·큐 1칸을 꽉 채우고 503을 여러 번")
server, tmp = start_server(workers=1, queue_size=1, request_timeout=5)
port = server.server_address[1]
hold = [socket.create_connection(("localhost", port))]
time.sleep(0.2)
hold.append(socket.create_connection(("localhost", port)))
time.sleep(0.2)

big_payload = sql_body("SELECT * FROM users;") + b" " * 200000
counts = Counter()
for _ in range(30):
    st, body, _ = request(port, "POST", "/query", big_payload, timeout=3)
    counts[st] += 1
check("본문 200KB짜리 요청 30번 모두 503을 읽음", counts == {503: 30}, dict(counts))

# 6. 큐가 꽉 찬 채로 server_close() 호출해도 1초 안에 종료
print("\n6. 큐가 꽉 찬 채로 끄기")
t0 = time.monotonic()
server.shutdown()
server.server_close()
close_elapsed = time.monotonic() - t0
for s in hold:
    s.close()
shutil.rmtree(tmp)
check(f"큐가 꽉 찬 채로 꺼도 1초 안에 종료 ({close_elapsed:.2f}초)", close_elapsed < 1.0 and not any(w.is_alive() for w in server.workers))

# 7. 실행 옵션 검사 (--workers 0, --queue 0)
print("\n7. 실행 옵션 검사와 켜기 실패 메시지")
for flag in ["--workers", "--queue"]:
    p = subprocess.run([sys.executable, os.path.join(ROOT, "server.py"), flag, "0"], capture_output=True, text=True)
    check(f"{flag} 0 거부", p.returncode != 0 and "1 이상이어야 합니다" in p.stderr, p.stderr.strip().splitlines()[-1] if p.stderr else "")

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
