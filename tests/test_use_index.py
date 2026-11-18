"""시연용 기능 테스트: use_index 옵션, 실행 정보(rows_scanned·elapsed_ms·lock), 읽기 전용, 실행 옵션.

핵심은 '인덱스로 찾든 전체 스캔으로 찾든 같은 행이 나온다' 이다.
풀스캔 경로도 같은 predicate로 거르고, 파일의 id는 decode_row가 int로 돌려주므로 정수끼리 비교한다.
"""
import json

import pytest

from engine import Engine
from minidb.errors import TypeMismatchError
from minidb.parser import parse
from server import Handler, PooledHTTPServer, parse_arguments
from tests.test_engine import make_engine
from tests.test_server import call, sql

N = 5  # 미리 넣는 행 수. id 1..5


@pytest.fixture
def engine(tmp_path):
    e = make_engine(tmp_path)
    for n in range(1, N + 1):
        e.execute(f"INSERT INTO users (name, age) VALUES ('u{n}', {n * 10});")
    yield e
    e.close()


def run(engine, text, use_index):
    return engine.executor.execute(parse(text)[0], use_index=use_index)


# --- 실행기: use_index=True/False 결과 비교 ----------------------------------------

@pytest.mark.parametrize("rid, expected", [
    (1, ((1, "u1", 10),)),     # 첫 번째 행 (오프셋 0)
    (3, ((3, "u3", 30),)),     # 가운데
    (N, ((N, f"u{N}", N * 10),)),  # 마지막 행
    (999, ()),                 # 없는 id
    (0, ()),                   # id는 1부터
    (-1, ()),
])
def test_same_result_with_and_without_index(engine, rid, expected):
    by_index = run(engine, f"SELECT * FROM users WHERE id = {rid};", use_index=True)
    by_scan = run(engine, f"SELECT * FROM users WHERE id = {rid};", use_index=False)
    assert by_index.rows == by_scan.rows == expected
    assert by_index.used_index is True and by_scan.used_index is False
    assert by_index.rows_scanned == len(expected)   # 트리가 가리킨 행만 읽음 (없으면 0)
    assert by_scan.rows_scanned == N                # 모든 행을 읽음


def test_first_row_is_at_offset_zero(engine):
    first_offset, first_row = next(engine.storage.table("users").scan())
    assert first_offset == 0 and first_row == (1, "u1", 10)


def test_scan_path_compares_id_as_int(engine):
    """파일에서 읽은 id는 int라서, 정수 리터럴과 바로 비교된다."""
    _offset, row = next(engine.storage.table("users").scan())
    assert isinstance(row[0], int)


def test_scan_path_still_rejects_string_id(engine):
    with pytest.raises(TypeMismatchError):
        run(engine, "SELECT * FROM users WHERE id = '2';", use_index=False)


@pytest.mark.parametrize("where", ["id < 3", "id <= 3", "id > 3", "id >= 3", "id != 3"])
def test_range_same_result_with_and_without_index(engine, where):
    by_index = run(engine, f"SELECT * FROM users WHERE {where};", use_index=True)
    by_scan = run(engine, f"SELECT * FROM users WHERE {where};", use_index=False)
    assert by_index == by_scan and by_scan.used_index is False and by_scan.rows_scanned == N


def test_column_list_same_with_and_without_index(engine):
    a = run(engine, "SELECT name FROM users WHERE id = 4;", use_index=True)
    b = run(engine, "SELECT name FROM users WHERE id = 4;", use_index=False)
    assert a.rows == b.rows == (("u4",),)


def test_non_id_condition_counts_all_rows(engine):
    r = run(engine, "SELECT * FROM users WHERE age > 20;", use_index=True)
    assert r.used_index is False and r.rows_scanned == N and len(r.rows) == 3


def test_scan_does_not_touch_tree_when_index_off(engine, monkeypatch):
    tree = engine.executor._indexes["users"]
    monkeypatch.setattr(tree, "search", lambda key: pytest.fail("use_index=False인데 트리를 썼음"))
    assert run(engine, "SELECT * FROM users WHERE id = 2;", use_index=False).rows == ((2, "u2", 20),)


# --- 엔진: 실행 정보와 읽기 전용 -----------------------------------------------------

def test_execute_shape_unchanged(engine):
    r = engine.execute("SELECT name FROM users WHERE id = 1;")[0]
    assert r == {"type": "select", "columns": ["name"], "rows": [["u1"]], "used_index": True}


def test_execute_passes_use_index(engine):
    r = engine.execute("SELECT * FROM users WHERE id = 1;", use_index=False)[0]
    assert r["rows"] == [[1, "u1", 10]] and r["used_index"] is False


def test_execute_with_stats(engine):
    results, lock = engine.execute("SELECT * FROM users WHERE id = 2;", use_index=False, with_stats=True)
    r = results[0]
    assert r["used_index"] is False and r["rows_scanned"] == N
    assert isinstance(r["elapsed_ms"], float) and r["elapsed_ms"] >= 0
    assert lock["mode"] == "read" and lock["wait_ms"] >= 0


def test_stats_insert_shape_and_write_lock(engine):
    results, lock = engine.execute("INSERT INTO users (name, age) VALUES ('x', 1);", with_stats=True)
    assert results == [{"type": "insert", "id": N + 1}] and lock["mode"] == "write"


def test_stats_parse_error_has_no_lock(engine):
    results, lock = engine.execute("SELEC 1;", with_stats=True)
    assert results[0]["stage"] == "parse" and lock is None


def test_read_only_rejects_insert_and_runs_nothing(tmp_path):
    make_engine(tmp_path).execute("INSERT INTO users (name, age) VALUES ('a', 1);")
    e = Engine(tmp_path, read_only=True)
    r = e.execute("SELECT * FROM users; INSERT INTO users (name, age) VALUES ('b', 2);")
    assert len(r) == 1 and r[0]["stage"] == "read_only"
    assert e.execute("SELECT * FROM users;")[0]["rows"] == [[1, "a", 1]]   # SELECT는 됨, INSERT는 안 들어감


# --- 서버 ----------------------------------------------------------------------

def start_server(engine):
    import threading
    srv = PooledHTTPServer(("localhost", 0), Handler, engine, 2, 4, request_timeout=2)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def port(engine):
    srv = start_server(engine)
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def body(text, **extra):
    return json.dumps({"sql": text, **extra}).encode()


def test_server_default_uses_index(port):
    st, res = call(port, body=sql("SELECT * FROM users WHERE id = 3;"))
    r = res["results"][0]
    assert st == 200 and r["rows"] == [[3, "u3", 30]]
    assert r["used_index"] is True and r["rows_scanned"] == 1 and r["elapsed_ms"] >= 0
    assert res["lock"]["mode"] == "read" and res["lock"]["wait_ms"] >= 0


def test_server_use_index_false(port):
    st, res = call(port, body=body("SELECT * FROM users WHERE id = 3;", use_index=False))
    r = res["results"][0]
    assert st == 200 and r["rows"] == [[3, "u3", 30]]
    assert r["used_index"] is False and r["rows_scanned"] == N


@pytest.mark.parametrize("bad", ["false", 0, None, "no"])
def test_server_use_index_must_be_bool(port, bad):
    st, res = call(port, body=body("SELECT * FROM users;", use_index=bad))
    assert st == 400 and res["error"]["code"] == "bad_request"


def test_server_insert_has_no_stats_keys(port):
    st, res = call(port, body=sql("INSERT INTO users (name, age) VALUES ('x', 1);"))
    assert st == 200 and res["results"] == [{"type": "insert", "id": N + 1}] and res["lock"]["mode"] == "write"


def test_server_read_only_400(tmp_path):
    make_engine(tmp_path).close()
    srv = start_server(Engine(tmp_path, read_only=True))
    try:
        p = srv.server_address[1]
        st, res = call(p, body=sql("INSERT INTO users (name, age) VALUES ('x', 1);"))
        assert st == 400 and res["error"]["code"] == "bad_sql" and "읽기 전용" in res["error"]["message"]
        assert res["results"] == [] and res["lock"] is None
        assert call(p, method="GET", path="/stats")[1]["read_only"] is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_stats_shows_lock(port):
    st, s = call(port, method="GET", path="/stats")
    assert st == 200 and s["read_only"] is False
    assert s["lock"] == {"readers": 0, "writer": False, "writers_waiting": 0}


# --- 실행 옵션 -------------------------------------------------------------------

def test_arguments_default(monkeypatch):
    for k in ("PORT", "WORKERS", "QUEUE", "DATA_DIR", "READ_ONLY", "HOST"):
        monkeypatch.delenv(k, raising=False)
    a = parse_arguments([])
    assert (a.port, a.workers, a.queue, a.data_dir, a.read_only) == (8000, 4, 16, "data", False)


def test_arguments_from_env(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("WORKERS", "1")
    monkeypatch.setenv("READ_ONLY", "1")
    a = parse_arguments([])
    assert (a.port, a.workers, a.read_only) == (9001, 1, True)


def test_cli_beats_env(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("WORKERS", "1")
    a = parse_arguments(["--port", "9000", "--workers", "8", "--read-only"])
    assert (a.port, a.workers, a.read_only) == (9000, 8, True)


def test_bad_env_value_is_rejected(monkeypatch):
    monkeypatch.setenv("WORKERS", "0")
    with pytest.raises(SystemExit):
        parse_arguments([])
