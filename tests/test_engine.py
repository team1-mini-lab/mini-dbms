"""Phase 3 엔진(engine.py) 단위 테스트: lock 아래에서 minidb 실행기를 부르고 결과를 dict로 바꾸는 규칙."""
import json
import threading

import pytest

from engine import Engine
from minidb.errors import StorageError

SCHEMA = {"users": {"columns": [
    {"name": "id", "type": "INT"}, {"name": "name", "type": "TEXT"}, {"name": "age", "type": "INT"}]}}


def make_engine(path):
    (path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    return Engine(path)


def test_missing_schema_is_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        Engine(tmp_path)


def test_insert_and_select_dict_shape(tmp_path):
    e = make_engine(tmp_path)
    assert e.execute("INSERT INTO users (name, age) VALUES ('현지', 25);") == [{"type": "insert", "id": 1}]
    r = e.execute("SELECT name FROM users WHERE id = 1;")[0]
    assert r == {"type": "select", "columns": ["name"], "rows": [["현지"]], "used_index": True}


def test_used_index_comes_from_executor(tmp_path):
    e = make_engine(tmp_path)
    e.execute("INSERT INTO users (name, age) VALUES ('a', 1); INSERT INTO users (name, age) VALUES ('b', 2);")
    assert e.execute("SELECT * FROM users WHERE id > 1;")[0]["used_index"] is True      # 범위도 B+ 트리
    assert e.execute("SELECT * FROM users WHERE age > 1;")[0]["used_index"] is False    # id가 아니면 전체 스캔


def test_syntax_error_runs_nothing(tmp_path):
    e = make_engine(tmp_path)
    r = e.execute("INSERT INTO users (name, age) VALUES ('a', 1); SELEC 1;")
    assert len(r) == 1 and r[0]["type"] == "error" and r[0]["stage"] == "parse"
    assert e.execute("SELECT * FROM users;")[0]["rows"] == []                  # 앞 INSERT도 안 들어감


def test_execution_error_stops_by_default(tmp_path):
    e = make_engine(tmp_path)
    r = e.execute("INSERT INTO users (name, age) VALUES ('a', 1); SELECT email FROM users; "
                  "INSERT INTO users (name, age) VALUES ('b', 2);")
    assert [x["type"] for x in r] == ["insert", "error"]                       # 세 번째는 실행 안 함
    assert "stage" not in r[1]


def test_execution_error_can_continue(tmp_path):
    e = make_engine(tmp_path)
    r = e.execute("SELECT email FROM users; INSERT INTO users (name, age) VALUES ('b', 2);", stop_on_error=False)
    assert [x["type"] for x in r] == ["error", "insert"]


def test_storage_error_goes_up_and_lock_is_released(tmp_path):
    e = make_engine(tmp_path)
    users = e.storage.table("users")
    original = users.scan
    users.scan = lambda: (_ for _ in ()).throw(StorageError("users: 손상된 행"))
    with pytest.raises(StorageError):                                          # 결과에 담지 않고 위로 → 서버 500
        e.execute("SELECT * FROM users;")
    users.scan = original
    assert e.execute("INSERT INTO users (name, age) VALUES ('a', 1);")[0]["id"] == 1   # lock이 풀려 있음


def test_warm_up_builds_tree_before_first_request(tmp_path):
    e = make_engine(tmp_path)
    e.execute("INSERT INTO users (name, age) VALUES ('a', 1);")
    e.close()
    e = Engine(tmp_path)                                                       # 다시 켜면 예열로 트리를 미리 만듦
    users = e.storage.table("users")
    users.scan = lambda: (_ for _ in ()).throw(AssertionError("첫 요청에서 파일을 다시 훑으면 안 됨"))
    assert e.execute("SELECT * FROM users WHERE id = 1;")[0]["rows"] == [[1, "a", 1]]


def test_concurrent_inserts_get_unique_ids(tmp_path):
    e = make_engine(tmp_path)
    ids, guard = [], threading.Lock()
    start = threading.Barrier(50)

    def work(n):
        start.wait()
        new_id = e.execute(f"INSERT INTO users (name, age) VALUES ('u{n}', {n});")[0]["id"]
        with guard:
            ids.append(new_id)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ids) == list(range(1, 51))
