"""Phase 3(15단계) D35(기본 스레드 4개, 큐 16칸)의 숫자 근거를 재는 스크립트. 담당: 은기

사용법 (저장소 맨 위 폴더에서):
    python3 bench/load_test.py        # 1분쯤 걸림

서버를 직접 켜지 않아도 됩니다. 임시 폴더에 1만 줄을 넣고 서버를 잠깐 띄웠다가 끕니다. data/는 건드리지 않습니다.

재는 것
  A. 빠른 손님만 100명이 동시에: 스레드 수에 따라 전체 시간·초당 처리량(req/s)이 달라지나
  B. 느린 손님 K명 + 빠른 손님 60명: 스레드가 느린 손님에게 붙잡혀 있을 때 빠른 손님이 얼마나 기다리나
     - 느린 손님: 요청 머리만 보내고 1초 뒤에 본문을 보냄 (네트워크가 느린 손님을 흉내 냄)
     - 빠른 손님: 0.01초 간격으로 와서 요청을 한 번에 보냄. 이 손님들의 응답 시간을 봄
  C. 큐 칸 수에 따라 200을 받은 손님이 평균·최대 얼마나 기다렸나, 503(거절률)과 초당 처리량은 어떠한가

C만 돌리기: python3 bench/load_test.py C
"""
import json
import os
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from engine import Engine  # noqa: E402
from server import Handler, PooledHTTPServer  # noqa: E402

ROWS = 10_000
REPEAT = 3                                   # 같은 실험을 몇 번 돌려 중앙값을 쓸지
SQL = json.dumps({"sql": "SELECT * FROM users WHERE id = 5000;"}).encode()
HEAD = b"POST /query HTTP/1.0\r\nContent-Length: %d\r\n\r\n" % len(SQL)


def prepare_data():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    with open(os.path.join(tmp, "users.tbl"), "w", encoding="utf-8") as f:
        for i in range(1, ROWS + 1):
            f.write(json.dumps([i, f"user{i}", 20 + i % 50], ensure_ascii=False) + "\n")
    return tmp


def start(data, workers, queue_size=256):
    server = PooledHTTPServer(("localhost", 0), Handler, Engine(data), workers, queue_size, request_timeout=15)
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server):
    server.shutdown()
    server.server_close()


def read_all(sock):
    got = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return got
        got += chunk


def fast_client(port):
    """요청을 한 번에 보내는 손님. (응답 번호, 걸린 ms)"""
    start_time = time.perf_counter()
    s = socket.create_connection(("localhost", port), timeout=30)
    s.sendall(HEAD + SQL)
    got = read_all(s)
    s.close()
    status = int(got.split(b" ", 2)[1]) if got else 0
    return status, (time.perf_counter() - start_time) * 1000


def slow_client(port, wait=1.0):
    """머리만 보내고 wait초 뒤에 본문을 보내는 손님. 그동안 이 손님을 맡은 일하는 스레드는 본문을 기다림."""
    s = socket.create_connection(("localhost", port), timeout=30)
    s.sendall(HEAD)
    time.sleep(wait)
    s.sendall(SQL)
    read_all(s)
    s.close()


def all_at_once(data, workers, n=100, queue_size=256):
    """빠른 손님 n명이 같은 순간에. (전체 ms, 응답 번호 Counter, 200 받은 손님 중 가장 오래 걸린 ms, 200 받은 손님 평균 ms)"""
    server = start(data, workers, queue_size)
    port = server.server_address[1]
    together = threading.Barrier(n)
    out = []
    lock = threading.Lock()

    def run():
        together.wait()
        r = fast_client(port)
        with lock:
            out.append(r)

    threads = [threading.Thread(target=run) for _ in range(n)]
    start_time = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = (time.perf_counter() - start_time) * 1000
    stop(server)
    ok = [ms for status, ms in out if status == 200]
    return total, Counter(status for status, _ in out), max(ok) if ok else 0, statistics.mean(ok) if ok else 0


def mixed(data, workers, slow, fast=60, gap=0.01):
    """느린 손님 slow명이 먼저 오고, 빠른 손님 fast명이 gap초 간격으로 옴. 빠른 손님 응답 ms (중앙값, 최대)"""
    server = start(data, workers)
    port = server.server_address[1]
    times = []
    lock = threading.Lock()

    def run_fast():
        status, ms = fast_client(port)
        if status == 200:
            with lock:
                times.append(ms)

    slows = [threading.Thread(target=slow_client, args=(port,)) for _ in range(slow)]
    for t in slows:
        t.start()
    time.sleep(0.05)                           # 느린 손님이 먼저 스레드를 차지하게
    fasts = []
    for _ in range(fast):
        t = threading.Thread(target=run_fast)
        t.start()
        fasts.append(t)
        time.sleep(gap)
    for t in fasts + slows:
        t.join()
    stop(server)
    return statistics.median(times), max(times)


def median_of(fn, *args):
    runs = [fn(*args) for _ in range(REPEAT)]
    return [statistics.median(r[i] for r in runs) for i in range(len(runs[0]))]


def main():
    print(f"데이터 {ROWS:,}줄 준비 (id로 찾기만 보냄, {REPEAT}번 중앙값)", flush=True)
    data = prepare_data()
    only = sys.argv[1:] or ["A", "B", "C"]
    try:
        if "A" in only:
            print("\nA. 빠른 손님만 100명이 동시에 (큐 256칸)\n")
            print("| 스레드 | 전체 시간 | 초당 처리량 |")
            print("|---:|---:|---:|")
            for workers in [1, 4, 16]:
                runs = [all_at_once(data, workers) for _ in range(REPEAT)]
                total = statistics.median(r[0] for r in runs)
                rps = statistics.median(r[1][200] / (r[0] / 1000) for r in runs if r[0] > 0)
                print(f"| {workers} | {total:.0f}ms | {rps:.0f} req/s |", flush=True)

        if "B" in only:
            print("\nB. 느린 손님 K명(1초 동안 본문을 안 보냄) + 빠른 손님 60명 → 빠른 손님 응답 시간\n")
            print("| 느린 손님 | 스레드 | 빠른 손님 중앙값 | 빠른 손님 최대 |")
            print("|---:|---:|---:|---:|")
            for slow, workers in [(0, 4), (3, 4), (4, 4), (4, 8), (8, 8), (8, 9)]:
                med, worst = median_of(mixed, data, workers, slow)
                print(f"| {slow} | {workers} | {med:.1f}ms | {worst:.1f}ms |", flush=True)

        if "C" in only:
            print("\nC. 빠른 손님 100명이 동시에, 스레드 4개 → 큐 칸 수에 따라\n")
            print("| 큐 칸 | 200 | 503 (거절률) | 초당 처리량 | 200 받은 손님 평균 | 200 받은 손님 중 가장 오래 걸림 |")
            print("|---:|---:|---:|---:|---:|---:|")
            for queue_size in [1, 4, 16, 64]:
                runs = [all_at_once(data, 4, 100, queue_size) for _ in range(REPEAT)]
                ok = statistics.median(r[1][200] for r in runs)
                busy = statistics.median(r[1][503] for r in runs)
                rps = statistics.median(r[1][200] / (r[0] / 1000) for r in runs if r[0] > 0)
                worst = statistics.median(r[2] for r in runs)
                avg = statistics.median(r[3] for r in runs)
                print(f"| {queue_size} | {ok:.0f} | {busy:.0f} ({busy:.0f}%) | {rps:.0f} req/s | {avg:.1f}ms | {worst:.1f}ms |", flush=True)
    finally:
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
