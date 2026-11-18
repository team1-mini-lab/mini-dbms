"""Phase 3 SQL 병렬 처리 테스트: SELECT끼리는 동시에, INSERT는 혼자 실행되는가.

- ReadWriteLock: 읽기끼리 동시에 들어가고, 쓰기는 혼자이며, 쓰기가 기다리면 새 읽기는 기다린다.
- Engine: SELECT 두 개가 실제로 동시에 실행 중일 수 있고, INSERT는 SELECT가 끝날 때까지 기다린다.
- Storage: pread로 읽으므로 여러 스레드가 동시에 read_at/scan 해도 행이 섞이지 않는다.
"""
import json
import threading
import time

from engine import Engine, ReadWriteLock

SCHEMA = {"users": {"columns": [
    {"name": "id", "type": "INT"}, {"name": "name", "type": "TEXT"}, {"name": "age", "type": "INT"}]}}

WAIT = 2  # 기다림이 영원히 걸리지 않게 하는 상한 (초)


def make_engine(path, rows=0):
    (path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    e = Engine(path)
    for n in range(1, rows + 1):
        e.execute(f"INSERT INTO users (name, age) VALUES ('u{n}', {n});")
    return e


def start(target, *args):
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


# --- ReadWriteLock ------------------------------------------------------------

def test_readers_enter_together():
    lock = ReadWriteLock()
    both_inside = threading.Barrier(2, timeout=WAIT)   # 둘 다 안에 있어야만 통과

    def reader():
        with lock.read():
            both_inside.wait()                         # 직렬이면 여기서 시간 초과 → BrokenBarrierError

    threads = [start(reader), start(reader)]
    for t in threads:
        t.join(WAIT)
    assert not both_inside.broken


def test_writer_waits_for_reader_and_excludes_others():
    lock = ReadWriteLock()
    reader_in, release_reader = threading.Event(), threading.Event()
    writer_done = threading.Event()

    def reader():
        with lock.read():
            reader_in.set()
            release_reader.wait(WAIT)

    def writer():
        with lock:
            assert lock.stats() == {"readers": 0, "writer": True, "writers_waiting": 0}
        writer_done.set()

    start(reader)
    assert reader_in.wait(WAIT)
    start(writer)
    time.sleep(0.1)
    assert not writer_done.is_set()                    # 읽는 중이면 쓰기는 못 들어감
    assert lock.stats()["writers_waiting"] == 1
    release_reader.set()
    assert writer_done.wait(WAIT)                      # 읽기가 나가면 들어감


def test_waiting_writer_blocks_new_readers():
    """쓰기 우선: 쓰기가 기다리는 중에 온 읽기는 쓰기 다음에 들어간다 (쓰기 굶주림 방지)."""
    lock = ReadWriteLock()
    first_in, release_first = threading.Event(), threading.Event()
    order = []

    def first_reader():
        with lock.read():
            first_in.set()
            release_first.wait(WAIT)

    def writer():
        with lock:
            order.append("writer")

    def late_reader():
        with lock.read():
            order.append("late_reader")

    start(first_reader)
    assert first_in.wait(WAIT)
    w = start(writer)
    while lock.stats()["writers_waiting"] == 0:        # 쓰기가 줄을 설 때까지
        time.sleep(0.01)
    r = start(late_reader)
    time.sleep(0.1)
    assert order == []                                 # 늦게 온 읽기도 못 들어감
    release_first.set()
    w.join(WAIT)
    r.join(WAIT)
    assert order == ["writer", "late_reader"]


def test_lock_released_after_exception():
    lock = ReadWriteLock()
    for enter in (lock.read, lambda: lock):
        try:
            with enter():
                raise ValueError
        except ValueError:
            pass
    assert lock.stats() == {"readers": 0, "writer": False, "writers_waiting": 0}


# --- Engine -------------------------------------------------------------------

def test_two_selects_run_at_the_same_time(tmp_path):
    """SELECT 두 개가 동시에 실행 중일 수 있다 = SQL 병렬 처리."""
    e = make_engine(tmp_path, rows=3)
    users = e.storage.table("users")
    original = users.scan
    both_scanning = threading.Barrier(2, timeout=WAIT)

    def scan_together():
        both_scanning.wait()                           # 다른 SELECT도 scan 중이어야 통과
        return original()

    users.scan = scan_together
    results = []
    threads = [start(lambda: results.append(e.execute("SELECT * FROM users WHERE age > 0;")))
               for _ in range(2)]
    for t in threads:
        t.join(WAIT)
    assert not both_scanning.broken
    assert len(results) == 2 and all(len(r[0]["rows"]) == 3 for r in results)


def test_insert_waits_for_running_select(tmp_path):
    e = make_engine(tmp_path, rows=1)
    users = e.storage.table("users")
    original = users.scan
    select_in, release_select = threading.Event(), threading.Event()

    def slow_scan():
        select_in.set()
        release_select.wait(WAIT)
        return original()

    users.scan = slow_scan
    select_result, insert_result = [], []
    start(lambda: select_result.append(e.execute("SELECT * FROM users WHERE age > 0;")))
    assert select_in.wait(WAIT)
    t = start(lambda: insert_result.append(e.execute("INSERT INTO users (name, age) VALUES ('x', 9);")))
    time.sleep(0.1)
    assert insert_result == []                         # SELECT가 끝나기 전에는 INSERT가 들어가지 않음
    release_select.set()
    t.join(WAIT)
    assert insert_result == [[{"type": "insert", "id": 2}]]
    assert len(select_result[0][0]["rows"]) == 1       # SELECT는 INSERT 전의 데이터만 봄


def test_mixed_select_insert_has_no_duplicate_or_broken_rows(tmp_path):
    e = make_engine(tmp_path, rows=20)
    errors = []
    go = threading.Barrier(40)

    def inserter(n):
        go.wait()
        e.execute(f"INSERT INTO users (name, age) VALUES ('w{n}', {n});")

    def selecter(n):
        go.wait()
        for _ in range(10):
            rid = n % 20 + 1
            by_index = e.execute(f"SELECT * FROM users WHERE id = {rid};")[0]["rows"]
            by_scan = e.execute(f"SELECT * FROM users WHERE name = 'u{rid}';")[0]["rows"]
            if by_index != [[rid, f"u{rid}", rid]] or by_scan != by_index:
                errors.append((rid, by_index, by_scan))

    threads = [start(inserter, n) for n in range(20)] + [start(selecter, n) for n in range(20)]
    for t in threads:
        t.join(10)
    assert errors == []
    ids = [row[0] for row in e.execute("SELECT id FROM users;")[0]["rows"]]
    assert sorted(ids) == list(range(1, 41))


# --- Storage (pread) ----------------------------------------------------------

def test_concurrent_read_at_and_scan_do_not_mix_rows(tmp_path):
    e = make_engine(tmp_path, rows=200)
    users = e.storage.table("users")
    offsets = [off for off, _row in users.scan()]
    expected = list(users.scan())
    errors = []
    go = threading.Barrier(16)

    def point_reader(k):
        go.wait()
        for i in range(k, 200, 8):                     # 스레드마다 다른 행을 섞어서 읽음
            if users.read_at(offsets[i]) != (i + 1, f"u{i + 1}", i + 1):
                errors.append(i)

    def full_scanner():
        go.wait()
        if list(users.scan()) != expected:
            errors.append("scan")

    threads = [start(point_reader, k) for k in range(8)] + [start(full_scanner) for _ in range(8)]
    for t in threads:
        t.join(10)
    assert errors == []
