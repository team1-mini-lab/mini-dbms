"""Phase 3(17단계) 필수: 오류 응답이 모두 정해진 JSON 모양인지 확인한다 (server.py의 Handler, PooledHTTPServer만).

엣지 케이스 방어(server_guard.py)는 checks/check_guard.py가 따로 확인합니다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_errors.py

서버를 직접 켜지 않아도 됩니다. 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다. data/users.tbl은 건드리지 않습니다.
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
from minidb.errors import StorageError  # noqa: E402
from server import Handler, PooledHTTPServer  # noqa: E402

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
    "문법이 틀린 SQL 섞임 → 400 bad_sql, 아무 문장도 실행 안 함",
    st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_sql"
    and body.get("results") == [] and "아무 문장도 실행하지 않았습니다" in body["error"]["message"],
    body,
)

st, body, _ = request(
    port, "POST", "/query",
    sql_body("INSERT INTO users (name, age) VALUES ('현지', 25); SELECT * FROM users WHERE email = 'x'; INSERT INTO users (name, age) VALUES ('민수', 31);")
)
check(
    "실행 중 틀린 SQL 섞임(없는 열) → 400 bad_sql + 앞 결과 포함",
    st == 400 and has_error_shape(body) and body["error"]["code"] == "bad_sql"
    and len(body.get("results", [])) == 1 and "2번째 문장" in body["error"]["message"],
    body,
)

# 1-2. http.server 안에서 나는 오류, 다른 방식
s = socket.create_connection(("localhost", port)); s.settimeout(3)
s.sendall(b"\x16\x03\x01garbage\r\n\r\n"); got = b""
while True:
    c = s.recv(65536)
    if not c:
        break
    got += c
s.close()
b = safe_json(got.partition(b"\r\n\r\n")[2])
check("문법이 틀린 요청 줄 → 400 JSON", b"400 " in got[:20] and has_error_shape(b), b)
st, body, _ = request(port, "PUT", "/query", sql_body("SELECT * FROM users;"))
check("PUT /query → 405 method_not_allowed", st == 405 and has_error_shape(body) and body["error"]["code"] == "method_not_allowed", body)
line, body = raw_request(port, b"POST /query HTTP/2.0\r\n\r\n")
check("HTTP/2.0 요청 줄 → 400 bad_request (505를 우리 목록 번호로)", b" 400 " in line and body.get("error", {}).get("code") == "bad_request", line)
line, body = raw_request(port, b"POST /query HTTP/1.0\r\nX: " + b"a" * 70000 + b"\r\n\r\n")
check("요청 머리 한 줄이 아주 김 → 413 too_large (431을 우리 목록 번호로)", b" 413 " in line and body.get("error", {}).get("code") == "too_large", line)
line, body = raw_request(port, b"POST /" + b"a" * 70000 + b" HTTP/1.0\r\n\r\n")
check("요청 줄이 아주 김 → 413 too_large (414를 우리 목록 번호로)", b" 413 " in line and body.get("error", {}).get("code") == "too_large", line)
st, body, _ = request(port, "POST", "/query", b"[" * 200000)
check("아주 깊게 중첩된 JSON → 400 bad_request (끊기지 않음)", st == 400 and body.get("error", {}).get("code") == "bad_request", st)

# 2. 500 internal (내부 오류 숨김)
print("\n2. 예상 못 한 오류 → 500 internal")
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


def broken_append(row):                      # 디스크가 꽉 찬 것처럼: 진짜 엔진 안에서 OSError
    raise OSError(28, "No space left on device", os.path.join(tmp, "users.tbl"))


users_file = server.engine.storage.table("users")       # 실행기가 append를 부르는 파일 객체
orig_append = users_file.append
users_file.append = broken_append
__import__("traceback").print_exc = lambda *a, **kw: None
st, body, _ = request(port, "POST", "/query", sql_body("INSERT INTO users (name, age) VALUES ('현지', 25);"))
__import__("traceback").print_exc = orig_print_exc
users_file.append = orig_append
check("엔진 안의 디스크 오류 → 500 internal, 응답에 파일 경로 없음", st == 500 and body.get("error", {}).get("code") == "internal"
      and tmp not in json.dumps(body, ensure_ascii=False), st)
st, body, _ = request(port, "POST", "/query", sql_body("INSERT INTO users (name, age) VALUES ('현지', 25);"))
check("그 뒤 정상 INSERT → 200 (lock이 풀려 있음)", st == 200, st)


def broken_scan():                             # 테이블 파일 중간에 손상된 행이 있는 것처럼
    raise StorageError("users: 손상된 행 (줄 2)")


orig_scan = users_file.scan
users_file.scan = broken_scan
__import__("traceback").print_exc = lambda *a, **kw: None
st, body, _ = request(port, "POST", "/query", sql_body("SELECT * FROM users;"))
__import__("traceback").print_exc = orig_print_exc
users_file.scan = orig_scan
check("손상된 행(StorageError) → 500 internal (SQL 오류인 400이 아님)", st == 500 and body.get("error", {}).get("code") == "internal", st)
stop_server(server, tmp)

# 3. 스레드 1개·큐 1칸을 꽉 채우고 작은 요청 → 503
print("\n3. 스레드 1개·큐 1칸을 꽉 채우고 503")
server, tmp = start_server(workers=1, queue_size=1, request_timeout=5)
port = server.server_address[1]
hold = [socket.create_connection(("localhost", port))]
time.sleep(0.2)
hold.append(socket.create_connection(("localhost", port)))
time.sleep(0.2)
st, body, _ = request(port, "POST", "/query", sql_body("SELECT * FROM users;"), timeout=3)
check("스레드와 큐가 꽉 차면 503 busy", st == 503 and body.get("error", {}).get("code") == "busy", st)
answers = Counter(request(port, "POST", "/query", sql_body("SELECT * FROM users;") + b" " * 200000, timeout=3)[0] for _ in range(30))
check("본문 200KB짜리 요청 30번 → 30번 모두 503을 읽음 (linger_close)", answers == Counter({503: 30}), dict(answers))

# 4. 큐가 꽉 찬 채로 끄기 (안 멈추는지)
print("\n4. 큐가 꽉 찬 채로 끄기")
t0 = time.monotonic()
server.shutdown()
server.server_close()
close_elapsed = time.monotonic() - t0
for s in hold:
    s.close()
shutil.rmtree(tmp)
check(f"큐가 꽉 찬 채로 꺼도 멈추지 않고 종료 ({close_elapsed:.2f}초, 2초 안)", close_elapsed < 2.0)

# 5. 실행 옵션 검사 (--workers 0, --queue 0)
print("\n5. 실행 옵션 검사와 켜기 실패 메시지")
for flag in ["--workers", "--queue"]:
    p = subprocess.run([sys.executable, os.path.join(ROOT, "server.py"), flag, "0"], capture_output=True, text=True)
    check(f"{flag} 0 거부", p.returncode != 0 and "1 이상이어야 합니다" in p.stderr, p.stderr.strip().splitlines()[-1] if p.stderr else "")

busy = socket.socket()
busy.bind(("localhost", 0))
busy.listen()
used = busy.getsockname()[1]
p = subprocess.run([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(used)],
                   cwd=ROOT, capture_output=True, text=True, timeout=10)
busy.close()
last = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
check("이미 쓰는 포트 → 마지막 줄에 진짜 이유, AttributeError 없음",
      p.returncode == 1 and "서버를 켤 수 없습니다" in last and "AttributeError" not in p.stderr, last)
empty = tempfile.mkdtemp()
p = subprocess.run([sys.executable, os.path.join(os.path.abspath(ROOT), "server.py"), "--port", "1"],
                   cwd=empty, capture_output=True, text=True, timeout=10)
shutil.rmtree(empty)
last = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
check("data 폴더가 없는 곳에서 실행 → 데이터 폴더 문제라고 알려 줌", p.returncode == 1 and "데이터 폴더" in last, last)

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
