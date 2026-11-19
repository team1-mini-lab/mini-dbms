"""Phase 3(16단계)용: 읽기만 하는 명령(SELECT)은 같이, 파일에 쓰는 명령(INSERT)은 혼자 들어가는지 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_rw.py             # 행 30만 건으로 (기본)
    python3 checks/check_rw.py 1000000     # 행 수를 바꿔서

임시 폴더에서 돌리므로 data/users.tbl은 건드리지 않습니다.

긴 SELECT(전체 스캔)가 도는 도중에 세 요청을 차례로 보내고, 각자 lock을 얼마나 기다렸는지 잽니다.
  B  짧은 SELECT (id = 1)            → 읽기 lock. 긴 SELECT와 같이 들어가 바로 끝나야 함
  C  INSERT                          → 쓰기 lock. 긴 SELECT가 끝날 때까지 기다려야 함
  D  C가 기다리는 중에 온 짧은 SELECT → C 뒤에 서야 함 (쓰는 명령이 영영 못 들어가는 일을 막는 규칙)
비교를 위해 lock을 하나로 합친 경우(읽기 lock도 혼자 들어가게)도 같은 순서로 돌립니다.
"""
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from engine import Engine, ReadWriteLock  # noqa: E402
from minidb.storage import encode_row  # noqa: E402

ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 300_000
LONG_SQL = "SELECT * FROM users WHERE name = '없는 이름';"   # 목차가 없는 열이라 전체 스캔
SHORT_SQL = "SELECT * FROM users WHERE id = 1;"              # B+ 트리로 한 줄만


def make_engine():
    """임시 폴더에 행 ROWS개짜리 users 테이블을 만들고 엔진을 연다 (INSERT ROWS번보다 훨씬 빠름)."""
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    engine = Engine(tmp)
    table = engine.catalog.table("users")
    engine.close()
    with open(os.path.join(tmp, "users.tbl"), "wb") as f:
        f.writelines(encode_row(table, (i, f"user{i}", 20 + i % 50)) for i in range(1, ROWS + 1))
    return tmp, Engine(tmp)   # 켤 때 B+ 트리를 미리 만듦 (예열)


def send(engine, sql, out, key):
    """요청 하나를 보내고 (lock 종류, 기다린 ms, 끝난 시각)을 out[key]에 남긴다."""
    _, lock = engine.execute(sql, with_stats=True)
    out[key] = (lock["mode"], lock["wait_ms"], time.perf_counter())


def wait_until(condition, timeout=10):
    end = time.perf_counter() + timeout
    while not condition():
        if time.perf_counter() > end:
            raise RuntimeError("기다리던 상태가 오지 않았습니다")
        time.sleep(0.001)


def run(single_lock):
    tmp, engine = make_engine()
    rw = engine._lock
    if single_lock:
        rw.read = lambda: rw          # 읽기 lock을 달라고 해도 쓰기 lock을 줌 = lock 하나와 같음

    out = {}
    started = time.perf_counter()
    a = threading.Thread(target=send, args=(engine, LONG_SQL, out, "A"))
    a.start()
    wait_until(lambda: rw.stats()["readers"] or rw.stats()["writer"])   # A가 lock 안에 들어갈 때까지

    b = threading.Thread(target=send, args=(engine, SHORT_SQL, out, "B"))
    b.start()
    b.join(timeout=0.5)               # B가 같이 들어갔다면 이 안에 끝남

    c = threading.Thread(target=send, args=(engine, "INSERT INTO users (name, age) VALUES ('새 사람', 30);", out, "C"))
    c.start()
    wait_until(lambda: rw.stats()["writers_waiting"] or "C" in out)     # C가 줄을 설 때까지

    d = threading.Thread(target=send, args=(engine, SHORT_SQL, out, "D"))
    d.start()
    for t in (a, b, c, d):
        t.join()

    engine.close()
    shutil.rmtree(tmp)
    return {k: (mode, wait, round((end - started) * 1000)) for k, (mode, wait, end) in out.items()}


def report(title, single_lock):
    r = run(single_lock)
    names = {"A": "긴 SELECT (전체 스캔)", "B": "짧은 SELECT", "C": "INSERT", "D": "C 뒤의 짧은 SELECT"}
    print(f"[{title}] 행 {ROWS:,}건, 긴 SELECT가 도는 중에 B·C·D를 차례로 보냄")
    for k in "ABCD":
        mode, wait, end = r[k]
        lock = "lock 하나" if single_lock else f"{'읽기' if mode == 'read' else '쓰기'} lock"
        print(f"  {k} {names[k]}: {lock}, 기다림 {wait:,.1f}ms, 시작 후 {end:,}ms에 끝남")
    return r


if __name__ == "__main__":
    rw = report("읽기·쓰기 lock (지금 코드)", single_lock=False)
    print()
    one = report("lock 하나였다면 (비교용)", single_lock=True)
    print()
    long_ms = rw["A"][2]
    ok = (rw["B"][1] < long_ms * 0.2            # B는 거의 안 기다림
          and rw["C"][1] > long_ms * 0.5        # C는 A가 끝날 때까지 기다림
          and rw["D"][2] >= rw["C"][2]          # D는 C 뒤에 끝남
          and one["B"][1] > long_ms * 0.5)      # lock 하나면 B도 기다림
    print("→ 통과: 짧은 SELECT는 긴 SELECT와 같이 들어가 바로 끝나고, INSERT는 긴 SELECT가 끝난 뒤 혼자 들어감"
          if ok else "→ 실패: 위 숫자를 확인하세요")
    sys.exit(0 if ok else 1)
