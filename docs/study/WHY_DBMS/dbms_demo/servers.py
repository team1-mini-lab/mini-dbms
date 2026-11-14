"""curl로 직접 쳐 보기용: 한 방식의 프로그램들을 한꺼번에 띄운다.

    python -m dbms_demo.servers --mode file     # 파일 직접 (84xx 포트)
    python -m dbms_demo.servers --mode dbms     # DBMS      (85xx 포트)

두 터미널에서 각각 띄우면 같은 curl을 포트만 바꿔 비교할 수 있다. Ctrl+C로 끈다.
"""
import argparse
import os
import subprocess
import sys
import time

from dbms_demo.store import make_store

ROLES = [("회원", 1), ("주문", 2), ("배송", 3), ("정산", 4), ("주문2", 5), ("마케팅", 6)]
BASE = {"file": 8400, "dbms": 8500}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ports(mode):
    return {role: BASE[mode] + n for role, n in ROLES}


def spawn(mode, role, port, data, delay):
    return subprocess.Popen([sys.executable, "-m", "dbms_demo.app", "--mode", mode, "--role", role,
                             "--port", str(port), "--data", data, "--delay", str(delay)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["file", "dbms"], required=True)
    ap.add_argument("--rows", type=int, default=1_000_000, help="주문 수 (기본 100만)")
    ap.add_argument("--data", default="./demo_data")
    ap.add_argument("--delay", type=float, default=0.3)
    a = ap.parse_args()
    data = os.path.abspath(os.path.join(a.data, a.mode))
    print(f"주문 {a.rows:,}건으로 처음 상태를 만드는 중... ({data})")
    t = time.perf_counter()
    make_store(a.mode, data).seed(a.rows)
    print(f"  {time.perf_counter() - t:.1f}초")
    procs = [spawn(a.mode, role, port, data, a.delay) for role, port in ports(a.mode).items()]
    time.sleep(0.8)
    label = "파일 직접" if a.mode == "file" else "DBMS"
    print(f"\n{label} 방식 프로그램:")
    for role, port in ports(a.mode).items():
        print(f"  {role:<4} http://127.0.0.1:{port}")
    print("\nREADME의 curl 명령을 쳐 보세요. Ctrl+C로 끕니다.")
    try:
        while True:
            for p in procs:
                if p.poll() is not None:            # 장면 ⑥에서 일부러 죽은 프로그램은 다시 띄움
                    i = procs.index(p)
                    role, port = list(ports(a.mode).items())[i]
                    print(f"  ({role} 프로그램이 꺼져서 다시 띄웁니다)")
                    procs[i] = spawn(a.mode, role, port, data, a.delay)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
