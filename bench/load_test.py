"""Phase 3 부하 테스트: 스레드 수, 큐 크기, lock 안의 일에 따른 응답 시간·처리량을 측정한다.

Expect: 100-continue 를 사용해 워커 스레드가 실제로 요청을 꺼내 읽을 때
네트워크 지연(30ms)이 lock 밖에서 발생하도록 재현한다.

사용법 (저장소 맨 위 폴더에서):
    python3 bench/load_test.py
"""

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

ROWS = 10000
NET_DELAY = 0.03   # 요청 본문 도착 지연 30ms (lock 밖 I/O)


class BenchHandler(Handler):
    protocol_version = "HTTP/1.1"


def prepare_data(n_rows=ROWS):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    tbl = os.path.join(tmp, "users.tbl")
    with open(tbl, "w", encoding="utf-8") as f:
        for i in range(1, n_rows + 1):
            f.write(json.dumps([i, f"user{i}", 20 + (i % 50)], ensure_ascii=False) + "\n")
    return tmp


def start_server(tmp, workers, queue_size):
    server = PooledHTTPServer(("localhost", 0), BenchHandler, Engine(tmp), workers=workers, queue_size=queue_size, request_timeout=15)
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def send_with_delay(port, sql, delay=NET_DELAY):
    payload = json.dumps({"sql": sql}).encode("utf-8")
    head = (
        f"POST /query HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Expect: 100-continue\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("localhost", port), timeout=20)
        s.sendall(head)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                s.close()
                return 0, (time.monotonic() - t0) * 1000
            buf += chunk
        first_head, _, rest = buf.partition(b"\r\n\r\n")
        first_status = int(first_head.split(b"\r\n", 1)[0].split()[1])
        if first_status != 100:
            s.close()
            return first_status, (time.monotonic() - t0) * 1000
        if delay > 0:
            time.sleep(delay)
        s.sendall(payload)
        raw = rest
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            raw += chunk
        s.close()
        elapsed_ms = (time.monotonic() - t0) * 1000
        status_line = raw.split(b"\r\n", 1)[0]
        status = int(status_line.split()[1]) if len(status_line.split()) >= 2 else 0
        return status, elapsed_ms
    except Exception:
        return 0, (time.monotonic() - t0) * 1000


def run_burst(tmp, workers, queue_size, clients, sql, delay=NET_DELAY, stagger=0.0):
    server = start_server(tmp, workers, queue_size)
    port = server.server_address[1]
    barrier = threading.Barrier(clients)
    out = []
    guard = threading.Lock()

    def worker(idx):
        barrier.wait()
        if stagger > 0:
            time.sleep(idx * stagger)
        res = send_with_delay(port, sql, delay=delay)
        with guard:
            out.append(res)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(clients)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_ms = (time.monotonic() - t0) * 1000
    server.shutdown()
    server.server_close()
    counts = Counter(st for st, _ in out)
    ok_times = [ms for st, ms in out if st == 200]
    avg_ms = sum(ok_times) / len(ok_times) if ok_times else 0
    max_ms = max(ok_times) if ok_times else 0
    return total_ms, avg_ms, max_ms, counts


def main():
    print(f"데이터 {ROWS:,}줄을 준비합니다...\n")
    tmp = prepare_data(ROWS)
    results = {"threads": [], "queue": [], "lock_work": []}

    try:
        print("## ① 스레드 수에 따라 (손님 100명이 동시에, 각자 네트워크 지연 30ms, id로 찾기, 큐 128칸)\n")
        print("| 스레드 | 전체 시간 | 평균 응답 | 가장 느린 응답 | 200 |")
        print("|---:|---:|---:|---:|---:|")
        for w in [1, 2, 4, 8, 16, 32]:
            total_ms, avg_ms, max_ms, counts = run_burst(tmp, w, 128, 100, "SELECT * FROM users WHERE id = 5000;")
            ok = counts.get(200, 0)
            print(f"| {w} | {total_ms:.0f}ms | {avg_ms:.0f}ms | {max_ms:.0f}ms | {ok}/100 |")
            results["threads"].append({"workers": w, "total_ms": round(total_ms), "avg_ms": round(avg_ms), "max_ms": round(max_ms), "ok": ok})

        print("\n## ② 큐 칸 수에 따라 (스레드 4개, 손님 100명, 2ms 간격 도착, 네트워크 지연 30ms)\n")
        print("| 큐 칸 | 200 | 503 | 200 받은 손님 중 가장 오래 기다림 |")
        print("|---:|---:|---:|---:|")
        for q in [1, 4, 16, 64]:
            _, _, max_ms, counts = run_burst(tmp, 4, q, 100, "SELECT * FROM users WHERE id = 5000;", stagger=0.002)
            ok = counts.get(200, 0)
            busy = counts.get(503, 0)
            print(f"| {q} | {ok} | {busy} | {max_ms:.0f}ms |")
            results["queue"].append({"queue": q, "ok": ok, "busy": busy, "max_ms": round(max_ms)})

        print(f"\n## ③ lock 안의 일에 따라 (손님 60명이 동시에, 네트워크 지연 30ms, 데이터 {ROWS:,}줄, 큐 128칸)\n")
        print("| 요청 종류 | 스레드 1 | 스레드 4 | 스레드 16 | 1 → 16 빨라진 배수 |")
        print("|---|---:|---:|---:|---:|")
        for label, sql in [
            ("id로 찾기만 (lock 안이 아주 짧음)", "SELECT * FROM users WHERE id = 5000;"),
            ("name으로 찾기만 (lock 안에서 처음부터 읽음)", "SELECT * FROM users WHERE name = 'user5000';"),
        ]:
            times = {}
            for w in [1, 4, 16]:
                total_ms, _, _, _ = run_burst(tmp, w, 128, 60, sql)
                times[w] = total_ms
            speedup = times[1] / times[16] if times[16] else 0
            print(f"| {label} | {times[1]:.0f}ms | {times[4]:.0f}ms | {times[16]:.0f}ms | {speedup:.1f}배 |")
            results["lock_work"].append({"label": label, "w1": round(times[1]), "w4": round(times[4]), "w16": round(times[16]), "speedup": round(speedup, 1)})

        with open(os.path.join(os.path.dirname(__file__), "results.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
