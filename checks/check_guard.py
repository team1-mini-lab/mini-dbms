"""Phase 3(17단계) 엣지 케이스 방어 확인 (server_guard.py의 GuardedHandler, GuardedServer).

필수 오류 응답(server.py)은 checks/check_errors.py가 확인합니다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_guard.py

서버를 직접 켜지 않아도 됩니다. 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다. 20초쯤 걸립니다.
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
from server_guard import MAX_BODY, GuardedHandler as Handler, GuardedServer as PooledHTTPServer  # noqa: E402

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


def raw_request(port, data, timeout=5):
    """소켓으로 바이트를 그대로 보내고, 서버가 닫을 때까지 받은 것을 (상태 줄, JSON 본문)으로 돌려준다."""
    s = socket.create_connection(("localhost", port), timeout=timeout)
    s.sendall(data)
    got = b""
    while True:
        c = s.recv(65536)
        if not c:
            break
        got += c
    s.close()
    return got.split(b"\r\n", 1)[0], safe_json(got.partition(b"\r\n\r\n")[2])


def safe_json(b):
    try:
        return json.loads(b)
    except ValueError:
        return {}


def has_error_shape(body):
    err = body.get("error")
    return isinstance(err, dict) and isinstance(err.get("code"), str) and isinstance(err.get("message"), str)


server, tmp = start_server(workers=2, queue_size=8, request_timeout=2)
port = server.server_address[1]
# 1. 413 too_large (1MB 초과)
print("1. Content-Length와 요청 형식 검사")
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

# 1-2. Content-Length 깊은 검사
for cl, want in [("-1", 400), ("abc", 400), ("1e3", 400), ("3_4", 400), ("99999999999999999999", 413)]:
    s = socket.create_connection(("localhost", port)); s.settimeout(3)
    s.sendall(f"POST /query HTTP/1.1\r\nContent-Length: {cl}\r\n\r\n".encode()); got = b""
    while True:
        c = s.recv(65536)
        if not c:
            break
        got += c
    s.close()
    check(f"Content-Length {cl} → {want}", f" {want} ".encode() in got[:20], got[:40])
line, body = raw_request(port, b"POST /query HTTP/1.0\r\n\r\n")
check("Content-Length 없음 → 400", b" 400 " in line and body.get("error", {}).get("code") == "bad_request", line)
line, body = raw_request(port, b"POST /query HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
check("본문을 나눠 보냄(chunked) → 400, 이유를 알려 줌", b" 400 " in line and "Transfer-Encoding" in body.get("error", {}).get("message", ""), line)
line, body = raw_request(port, b"GET /\r\n")
check("HTTP/0.9 형식 한 줄(GET /) → 상태 줄이 있는 400", line.startswith(b"HTTP/1.0 400") and body.get("error", {}).get("code") == "bad_request", line)
st, body, _ = request(port, "POST", "/query", b'{"sql": "SELECT * FROM users;"}', headers={})
check("그 뒤 정상 요청 → 200", st == 200, st)

stop_server(server, tmp)

# 2. 408 timeout (받는 시간 전체 제한: 아무것도 안 보냄 / 천천히 보냄)
print("\n2. 느린 요청 → 408 timeout (이 서버는 1초)")
server, tmp = start_server(workers=2, queue_size=4, request_timeout=1)
port = server.server_address[1]

# 2-1. 연결만 하고 아무것도 안 보냄
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
body408 = safe_json(got.partition(b"\r\n\r\n")[2])
check(f"아무것도 안 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408.get("error", {}).get("code") == "timeout", body408)

# 2-2. 본문을 0.35초마다 1바이트씩 천천히 보냄 (전체 시간 초과)
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
body408_slow = safe_json(got.partition(b"\r\n\r\n")[2])
check(f"본문을 덜 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408_slow.get("error", {}).get("code") == "timeout", body408_slow)

# 2-3. 헤더를 끝내지 않고 천천히 보냄 (전체 시간 초과)
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
body408_hdr = safe_json(got.partition(b"\r\n\r\n")[2])
check(f"헤더를 덜 보낸 연결 → 408 timeout ({elapsed:.1f}초)", b"408 " in got and body408_hdr.get("error", {}).get("code") == "timeout", body408_hdr)

# 2-4. 천천히 보내는 연결이 일하는 스레드를 모두 잡아도, 정상 요청은 곧 처리됨
stop_slow = threading.Event()
slow_socks = []


def slow_sender():
    """머리를 보낸 뒤 0.3초마다 한 글자씩. '한 번 받을 때마다 제한'으로는 끊기지 않는 연결."""
    c = socket.create_connection(("localhost", port))
    slow_socks.append(c)
    try:
        c.sendall(b"POST /query HTTP/1.0\r\nContent-Length: 1000\r\n\r\n")
        while not stop_slow.is_set():
            c.sendall(b"x")
            time.sleep(0.3)
    except OSError:
        pass


senders = [threading.Thread(target=slow_sender, daemon=True) for _ in range(2)]   # 이 서버의 스레드 2개를 다 잡음
for t in senders:
    t.start()
time.sleep(0.4)
start = time.monotonic()
st, _, _ = request(port, "POST", "/query", sql_body("SELECT * FROM users;"), timeout=8)
elapsed = time.monotonic() - start
stop_slow.set()
for c in slow_socks:
    c.close()
check(f"천천히 보내는 연결 2개가 스레드 2개를 다 잡아도 정상 요청은 200 ({elapsed:.1f}초)", st == 200 and elapsed < 3, st)
stop_server(server, tmp)

# 3. 스레드 1개·큐 1칸 꽉 채우고 큰 본문(200KB) 30번 → 모두 503 읽음
print("\n3. 스레드 1개·큐 1칸을 꽉 채우고 503을 여러 번")
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

idle = [socket.create_connection(("localhost", port)) for _ in range(30)]   # 아무것도 안 보내는 연결 30개
start = time.monotonic()
st, _, _ = request(port, "POST", "/query", sql_body("SELECT * FROM users;"), timeout=10)
elapsed = time.monotonic() - start
for c in idle:
    c.close()
check(f"아무것도 안 보내는 연결 30개 뒤에 온 손님도 곧 503을 받음 ({elapsed:.2f}초, 받는 스레드가 안 묶임)", st == 503 and elapsed < 2, st)

# 4. 큐가 꽉 찬 채로 server_close() 호출해도 1초 안에 종료
print("\n4. 큐가 꽉 찬 채로 끄기")
t0 = time.monotonic()
server.shutdown()
server.server_close()
close_elapsed = time.monotonic() - t0
for s in hold:
    s.close()
shutil.rmtree(tmp)
check(f"큐가 꽉 찬 채로 꺼도 1초 안에 종료 ({close_elapsed:.2f}초)", close_elapsed < 1.0 and not any(w.is_alive() for w in server.workers))

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
