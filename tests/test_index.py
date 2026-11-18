"""8~9단계: 실행기와 B+ 트리 연동.

- 8단계: INSERT 하면 트리에 등록되고, 새 실행기(= 재시작)는 파일을 읽어 트리를 다시 만든다.
- 9단계: `WHERE id = 값` 과 id 범위 조건(<, <=, >, >=)은 인덱스를 타고, 그 외에는 전체 스캔한다.
  두 경로의 결과는 같아야 한다.
"""

import pytest

from minidb.executor import Executor
from minidb.parser import parse
from minidb.storage import Storage


@pytest.fixture
def storage(tmp_path, catalog):
    with Storage(tmp_path, catalog) as st:
        yield st


@pytest.fixture
def ex(catalog, storage):
    return Executor(catalog, storage)


def run(ex, sql):
    (stmt,) = parse(sql)
    return ex.execute(stmt)


@pytest.fixture
def seeded(ex):
    for name, grade in [("Kim", 3), ("Lee", 2), ("Park", 3), ("Choi", 1)]:
        run(ex, f"INSERT INTO students VALUES ('{name}', {grade});")
    return ex


# --- 9단계: 경로 선택 ----------------------------------------------------------

def test_id_equals_uses_index(seeded):
    r = run(seeded, "SELECT * FROM students WHERE id = 3;")
    assert r.rows == ((3, "Park", 3),)
    assert r.used_index is True


def test_first_row_offset_zero_is_found(seeded):
    r = run(seeded, "SELECT * FROM students WHERE id = 1;")
    assert r.rows == ((1, "Kim", 3),)
    assert r.used_index is True


def test_missing_id_returns_empty_via_index(seeded):
    r = run(seeded, "SELECT * FROM students WHERE id = 99;")
    assert r.rows == ()
    assert r.used_index is True


@pytest.mark.parametrize("where", [
    "id != 2",                    # id 지만 거의 모든 행이 해당
    "name = 'Lee'", "grade = 3",  # id 가 아님
])
def test_other_conditions_scan(seeded, where):
    r = run(seeded, f"SELECT * FROM students WHERE {where};")
    assert r.used_index is False


def test_no_where_scans(seeded):
    assert run(seeded, "SELECT * FROM students;").used_index is False


def test_index_and_scan_give_same_row(seeded):
    by_id = run(seeded, "SELECT * FROM students WHERE id = 2;")
    by_name = run(seeded, "SELECT * FROM students WHERE name = 'Lee';")
    assert by_id.used_index and not by_name.used_index
    assert by_id == by_name  # used_index 는 비교에서 빠진다


def test_index_path_respects_column_list(seeded):
    r = run(seeded, "SELECT name, grade FROM students WHERE id = 4;")
    assert r.columns == ("name", "grade")
    assert r.rows == (("Choi", 1),)


def test_index_path_still_type_checks(seeded):
    from minidb.errors import TypeMismatchError
    with pytest.raises(TypeMismatchError):
        run(seeded, "SELECT * FROM students WHERE id = 'abc';")


def test_insert_result_does_not_claim_index(ex):
    assert run(ex, "INSERT INTO students VALUES ('Kim', 3);").used_index is False


# --- 8단계: 등록과 재구성 -------------------------------------------------------

def test_inserted_row_is_found_immediately(ex):
    run(ex, "INSERT INTO students VALUES ('Kim', 3);")
    run(ex, "INSERT INTO students VALUES ('Lee', 2);")
    assert run(ex, "SELECT name FROM students WHERE id = 2;").rows == (("Lee",),)


def test_restart_rebuilds_index(catalog, storage):
    ex1 = Executor(catalog, storage)
    for i in range(50):
        run(ex1, f"INSERT INTO students VALUES ('s{i}', {i % 4});")
    ex2 = Executor(catalog, storage)  # 새 실행기 = 재시작. 트리는 메모리에만 있었다.
    r = run(ex2, "SELECT * FROM students WHERE id = 37;")
    assert r.rows == ((37, "s36", 0),)
    assert r.used_index is True


def test_select_first_after_restart_builds_index(catalog, storage):
    # 재시작 후 첫 문장이 INSERT 가 아니라 SELECT 여도 트리가 만들어져야 한다.
    run(Executor(catalog, storage), "INSERT INTO students VALUES ('Kim', 3);")
    ex2 = Executor(catalog, storage)
    assert run(ex2, "SELECT name FROM students WHERE id = 1;").rows == (("Kim",),)
    assert run(ex2, "INSERT INTO students VALUES ('Lee', 2);").rows == ((2,),)


def test_rebuild_from_existing_file_with_sparse_ids(tmp_path, catalog):
    (tmp_path / "students.tbl").write_bytes(b"1\tKim\t3\n9\tLee\t2\n5\tPark\t1\n")
    with Storage(tmp_path, catalog) as st:
        ex = Executor(catalog, st)
        assert run(ex, "SELECT name FROM students WHERE id = 9;").rows == (("Lee",),)
        assert run(ex, "SELECT name FROM students WHERE id = 2;").rows == ()


def test_index_lookup_does_not_scan(seeded, storage, monkeypatch):
    run(seeded, "SELECT * FROM students WHERE id = 1;")  # 트리는 이미 만들어져 있다
    tf = storage.table("students")
    monkeypatch.setattr(tf, "scan", lambda: pytest.fail("인덱스 경로에서 scan 을 불렀다"))
    assert run(seeded, "SELECT * FROM students WHERE id = 4;").rows == ((4, "Choi", 1),)


def test_failed_write_does_not_consume_id(ex, storage, monkeypatch):
    from minidb.errors import StorageError
    run(ex, "INSERT INTO students VALUES ('Kim', 3);")
    tf = storage.table("students")
    original = tf.append

    def broken(row):
        raise StorageError("디스크 가득 참")

    monkeypatch.setattr(tf, "append", broken)
    with pytest.raises(StorageError):
        run(ex, "INSERT INTO students VALUES ('Lee', 2);")
    monkeypatch.setattr(tf, "append", original)
    assert run(ex, "INSERT INTO students VALUES ('Lee', 2);").rows == ((2,),)
    assert run(ex, "SELECT name FROM students WHERE id = 2;").rows == (("Lee",),)


# --- 범위 조건 ------------------------------------------------------------------

@pytest.mark.parametrize("where, ids", [
    ("id < 3", [1, 2]),
    ("id <= 3", [1, 2, 3]),
    ("id > 2", [3, 4]),
    ("id >= 2", [2, 3, 4]),
    ("id < 1", []),             # 첫 행 앞
    ("id > 4", []),             # 마지막 행 뒤
    ("id <= 1", [1]),           # 오프셋 0 인 첫 행 포함
    ("id >= 4", [4]),
    ("id < -5", []),
    ("id > 1000", []),
])
def test_id_range_uses_index(seeded, where, ids):
    r = run(seeded, f"SELECT id FROM students WHERE {where};")
    assert r.rows == tuple((i,) for i in ids)
    assert r.used_index is True


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 5])
def test_range_index_matches_scan(seeded, storage, op, value):
    by_index = run(seeded, f"SELECT * FROM students WHERE id {op} {value};")
    # 같은 조건을 전체 스캔으로 직접 계산
    import operator as o
    cmp = {"<": o.lt, "<=": o.le, ">": o.gt, ">=": o.ge}[op]
    expected = tuple(row for _off, row in storage.table("students").scan() if cmp(row[0], value))
    assert by_index.used_index
    assert by_index.rows == expected


def test_range_lookup_does_not_scan(seeded, storage, monkeypatch):
    run(seeded, "SELECT * FROM students WHERE id = 1;")  # 트리는 이미 만들어져 있다
    tf = storage.table("students")
    monkeypatch.setattr(tf, "scan", lambda: pytest.fail("인덱스 경로에서 scan 을 불렀다"))
    assert run(seeded, "SELECT name FROM students WHERE id >= 3;").rows == (("Park",), ("Choi",))


def test_range_path_still_type_checks(seeded):
    from minidb.errors import TypeMismatchError
    with pytest.raises(TypeMismatchError):
        run(seeded, "SELECT * FROM students WHERE id < 'abc';")


def test_range_keeps_file_order_with_unsorted_ids(tmp_path, catalog):
    # 파일을 직접 편집해 id 가 파일 순서와 다를 때도 스캔과 같은 순서(파일 순서)로 낸다.
    (tmp_path / "students.tbl").write_bytes(b"1\tKim\t3\n9\tLee\t2\n5\tPark\t1\n")
    with Storage(tmp_path, catalog) as st:
        ex = Executor(catalog, st)
        r = run(ex, "SELECT id FROM students WHERE id > 1;")
        assert r.used_index
        assert r.rows == ((9,), (5,))


def test_range_after_restart(catalog, storage, seeded):
    fresh = Executor(catalog, storage)  # 트리 없이 시작
    r = run(fresh, "SELECT id FROM students WHERE id > 2;")
    assert r.used_index and r.rows == ((3,), (4,))
