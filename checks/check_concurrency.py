"""Phase 3(16단계)용: 여러 스레드가 동시에 INSERT해도 id가 겹치지 않는지 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_concurrency.py            # lock 끔 / lock 켬 두 번 돌려서 비교
    python3 checks/check_concurrency.py 200        # 스레드 수를 바꿔서 (기본 100)

임시 폴더에서 돌리므로 data/users.tbl은 건드리지 않습니다.

lock을 끈 쪽에서 id가 확실히 겹치도록, 이 스크립트 안에서만 "번호 읽기"와 "번호 올리기" 사이에 아주 짧게 쉬게 합니다.
(실제 코드에는 쉬는 부분이 없습니다. minidb는 번호를 읽자마자 바로 올려서 틈이 아주 좁고,
 그래서 쉬지 않으면 우연히 안 겹칠 때가 많습니다. 틈이 좁을 뿐 0은 아니라서 lock이 필요합니다.)
"""
import contextlib
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from engine import Engine  # noqa: E402

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SLOW_WRITE_SECONDS = 0.001     # 끼어들 틈을 넓히는 시간 (이 스크립트 안에서만)


def run(use_lock):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)
    engine = Engine(tmp)
    if not use_lock:
        engine._lock = contextlib.nullcontext()          # lock 대신 "아무것도 안 하는 것"을 끼움

    next_ids = engine.executor._next_ids                  # minidb 실행기가 테이블별 다음 번호를 적어 두는 곳

    def slow_next_id(table):                              # minidb의 _next_id와 같은 일을 하되, 읽기와 올리기 사이를 넓힘
        if table.name not in next_ids:
            next_ids[table.name] = 1 + max((int(row[0]) for _, row in engine.storage.scan(table.name)), default=0)
        new_id = next_ids[table.name]                     # ① 번호 읽기
        time.sleep(SLOW_WRITE_SECONDS)                    #    ← 이 틈에 다른 스레드도 같은 번호를 읽음
        next_ids[table.name] = new_id + 1                 # ② 번호 올리기
        return new_id

    engine.executor._next_id = slow_next_id

    start_together = threading.Barrier(THREADS)           # 모든 스레드가 준비되면 동시에 출발
    ids = []
    ids_guard = threading.Lock()                          # 결과를 모으는 목록 보호용 (엔진과 무관)

    def worker(n):
        start_together.wait()
        result = engine.execute(f"INSERT INTO users (name, age) VALUES ('u{n}', {n});")[0]
        with ids_guard:
            ids.append(result.get("id"))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    file_ids = [row[0] for _, row in engine.storage.scan("users")]
    shutil.rmtree(tmp)
    duplicated = {i: c for i, c in Counter(file_ids).items() if c > 1}
    missing = sorted(set(range(1, THREADS + 1)) - set(file_ids))
    return ids, file_ids, duplicated, missing


def report(title, use_lock):
    ids, file_ids, duplicated, missing = run(use_lock)
    ok = not duplicated and not missing and len(file_ids) == THREADS
    print(f"[{title}] 스레드 {THREADS}개가 동시에 INSERT")
    print(f"  파일에 저장된 줄: {len(file_ids)}줄")
    print(f"  서로 다른 id: {len(set(file_ids))}개")
    if duplicated:
        sample = ", ".join(f"id {i} × {c}번" for i, c in sorted(duplicated.items())[:5])
        print(f"  겹친 id: {len(duplicated)}개 (예: {sample})")
    if missing:
        print(f"  빠진 id: {len(missing)}개 (예: {missing[:5]})")
    print(f"  → {'통과: id 1~' + str(THREADS) + '이 빠짐없이, 겹치지 않음' if ok else '실패: id가 겹치거나 빠짐'}\n")
    return ok


print("Phase 3(16단계) 동시 INSERT 확인\n")
without = report("lock 끔", use_lock=False)
with_lock = report("lock 켬", use_lock=True)
print("요약")
print(f"  lock 끔: {'겹침 없음 (이번에는 우연히 안 겹침. 다시 돌려 보세요)' if without else '겹침 발생 → lock이 필요한 이유'}")
print(f"  lock 켬: {'통과' if with_lock else '실패'}")
sys.exit(0 if with_lock else 1)
