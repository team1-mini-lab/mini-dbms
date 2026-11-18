"""Phase 3(15단계)용: Thread Pool 서버가 요청을 여러 스레드로 나눠 처리하는지, 큐가 차면 503을 주는지 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_threadpool.py

서버를 직접 켜지 않아도 됩니다. 이 스크립트가 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다.
data/users.tbl은 건드리지 않습니다.
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from engine import Engine  # noqa: E402
from server import Handler, PooledHTTPServer  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("통과  " if ok else "실패  ") + name + (f"  ({detail})" if detail else ""))


def start_server(**options):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    server = PooledHTTPServer(("localhost", 0), Handler, Engine(tmp), **options)   # 0 = 빈 포트 아무거나
    server.RequestHandlerClass.log_message = lambda *a: None                      # 확인 중에는 로그를 끔
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, tmp


def stop_server(server, tmp):
    server.shutdown()
    server.server_close()
    shutil.rmtree(tmp)


def post(port, sql):
    conn = http.client.HTTPConnection("localhost", port, timeout=10)
    conn.request("POST", "/query", body=json.dumps({"sql": sql}))
    response = conn.getresponse()
    body = json.loads(response.read() or b"{}")
    worker = response.getheader("X-Worker")
    conn.close()
    return response.status, body, worker


# 1. 동시에 보낸 요청을 여러 스레드가 나눠 처리하는가
print("1. 요청 50개를 동시에 보냄 (스레드 4개, 큐 64칸)")
server, tmp = start_server(workers=4, queue_size=64)
port = server.server_address[1]
N = 50
start_together = threading.Barrier(N)
answers = []
guard = threading.Lock()


def client(n):
    start_together.wait()
    answer = post(port, f"INSERT INTO users (name, age) VALUES ('u{n}', {n});")
    with guard:
        answers.append(answer)


threads = [threading.Thread(target=client, args=(n,)) for n in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()

statuses = Counter(status for status, _, _ in answers)
ids = sorted(body["results"][0]["id"] for status, body, _ in answers if status == 200)
workers = Counter(worker for _, _, worker in answers)
check("50개 모두 200", statuses == {200: N}, dict(statuses))
check("id 1~50이 빠짐없이, 겹치지 않음 (lock 덕분)", ids == list(range(1, N + 1)))
check("여러 스레드가 나눠 처리함", len(workers) > 1, ", ".join(f"{w} {c}건" for w, c in sorted(workers.items())))
stop_server(server, tmp)

# 2. 큐가 가득 차면 503, 느린 클라이언트는 timeout으로 풀려나는가
print("\n2. 스레드 1개, 큐 1칸, timeout 1초로 줄여서 꽉 채움")
server, tmp = start_server(workers=1, queue_size=1, request_timeout=1)
port = server.server_address[1]
slow1 = socket.create_connection(("localhost", port))   # 연결만 하고 아무것도 안 보냄 → 스레드 1개를 붙잡음
time.sleep(0.3)
slow2 = socket.create_connection(("localhost", port))   # 이것도 아무것도 안 보냄 → 큐 1칸을 차지
time.sleep(0.3)
status, body, _ = post(port, "SELECT * FROM users;")    # 스레드도 큐도 꽉 참
check("스레드와 큐가 꽉 차면 503", status == 503, f"{status} {body.get('error', {}).get('code')}")

time.sleep(2.5)                                          # timeout 1초씩 지나 느린 연결 둘이 끊김
status, body, _ = post(port, "SELECT * FROM users;")
check("느린 연결이 timeout으로 끊긴 뒤 다시 처리됨", status == 200, str(status))
slow1.close()
slow2.close()

# 3. 끌 때 일하는 스레드가 모두 멈추는가
stop_server(server, tmp)
time.sleep(0.2)
check("서버를 끄면 일하는 스레드가 모두 멈춤", not any(w.is_alive() for w in server.workers))

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
