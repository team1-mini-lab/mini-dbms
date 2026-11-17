import pytest

from minidb.ast import Condition, Insert, Select
from minidb.errors import (
    ColumnNotFoundError, ExecutionError, MiniDBError, TableNotFoundError, TypeMismatchError,
)
from minidb.executor import Executor, QueryResult
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
    """SQL 한 문장을 파싱해 실행한다. 테스트 편의용이며 실행기는 문장 객체만 받는다."""
    (stmt,) = parse(sql)
    return ex.execute(stmt)


def run_all(ex, sql):
    return [ex.execute(s) for s in parse(sql)]


def file_rows(storage):
    return [row for _, row in storage.table("students").scan()]


# --- INSERT ------------------------------------------------------------------

def test_insert_assigns_ids_from_one(ex):
    assert run(ex, "INSERT INTO students (name, grade) VALUES ('Kim', 3);") == QueryResult(
        ("id",), ((1,),)
    )
    assert run(ex, "INSERT INTO students (name, grade) VALUES ('Lee', 2);").rows == ((2,),)
    assert run(ex, "INSERT INTO students (name, grade) VALUES ('Park', 1);").rows == ((3,),)


def test_insert_writes_row_in_schema_order(ex, storage):
    run(ex, "INSERT INTO students (grade, name) VALUES (3, 'Kim');")  # 순서를 바꿔 썼다
    assert file_rows(storage) == [(1, "Kim", 3)]


def test_insert_without_columns(ex, storage):
    run(ex, "INSERT INTO students VALUES ('Kim', 3);")
    assert file_rows(storage) == [(1, "Kim", 3)]


def test_insert_result_shape(ex):
    r = run(ex, "INSERT INTO students VALUES ('Kim', 3);")
    assert r.columns == ("id",)
    assert r.rowcount == 1


def test_insert_special_text_roundtrips(ex):
    run(ex, "INSERT INTO students VALUES ('a\tb\nc\\d''e', 1);")
    r = run(ex, "SELECT name FROM students;")
    assert r.rows == (("a\tb\nc\\d'e",),)


# --- INSERT 오류: 파일과 id 카운터를 건드리지 않는다 ---------------------------

def _insert_fails(ex, storage, sql, exc):
    with pytest.raises(exc):
        run(ex, sql)
    assert file_rows(storage) == []
    # 실패한 INSERT 는 id 를 소비하지 않는다
    assert run(ex, "INSERT INTO students VALUES ('ok', 0);").rows == ((1,),)


def test_insert_unknown_table(ex, storage):
    with pytest.raises(TableNotFoundError):
        run(ex, "INSERT INTO teachers VALUES ('Kim', 3);")


def test_insert_unknown_column(ex, storage):
    _insert_fails(ex, storage, "INSERT INTO students (name, age) VALUES ('Kim', 3);", ColumnNotFoundError)


def test_insert_cannot_specify_id(ex, storage):
    _insert_fails(ex, storage, "INSERT INTO students (id, name, grade) VALUES (9, 'Kim', 3);", ExecutionError)


def test_insert_missing_column_value(ex, storage):
    # NULL 이 없으므로 grade 를 빼놓을 수 없다
    _insert_fails(ex, storage, "INSERT INTO students (name) VALUES ('Kim');", ExecutionError)


def test_insert_omitted_columns_wrong_count(ex, storage):
    _insert_fails(ex, storage, "INSERT INTO students VALUES ('Kim');", ExecutionError)
    with pytest.raises(ExecutionError):
        run(ex, "INSERT INTO students VALUES ('Kim', 3, 4);")


def test_insert_type_mismatch_int_column(ex, storage):
    _insert_fails(ex, storage, "INSERT INTO students VALUES ('Kim', 'three');", TypeMismatchError)


def test_insert_type_mismatch_text_column(ex, storage):
    _insert_fails(ex, storage, "INSERT INTO students VALUES (42, 3);", TypeMismatchError)


def test_insert_error_message_names_column(ex):
    with pytest.raises(TypeMismatchError) as e:
        run(ex, "INSERT INTO students VALUES ('Kim', 'three');")
    assert "'grade'" in str(e.value) and "INT" in str(e.value)


# --- id 부여 ---------------------------------------------------------------------

def test_ids_continue_after_restart(catalog, storage):
    ex1 = Executor(catalog, storage)
    run(ex1, "INSERT INTO students VALUES ('Kim', 3);")
    run(ex1, "INSERT INTO students VALUES ('Lee', 2);")
    ex2 = Executor(catalog, storage)  # 새 실행기 = 재시작
    assert run(ex2, "INSERT INTO students VALUES ('Park', 1);").rows == ((3,),)


def test_next_id_is_max_plus_one_even_if_sparse(tmp_path, catalog):
    (tmp_path / "students.tbl").write_bytes(b"1\tKim\t3\n9\tLee\t2\n5\tPark\t1\n")
    with Storage(tmp_path, catalog) as st:
        ex = Executor(catalog, st)
        assert run(ex, "INSERT INTO students VALUES ('Choi', 4);").rows == ((10,),)


def test_next_id_scans_only_once(catalog, storage, monkeypatch):
    ex = Executor(catalog, storage)
    run(ex, "INSERT INTO students VALUES ('Kim', 3);")
    calls = []
    tf = storage.table("students")
    original = tf.scan
    monkeypatch.setattr(tf, "scan", lambda: calls.append(1) or original())
    run(ex, "INSERT INTO students VALUES ('Lee', 2);")
    run(ex, "INSERT INTO students VALUES ('Park', 1);")
    assert calls == []  # 두 번째부터는 scan 하지 않는다


# --- SELECT ------------------------------------------------------------------

@pytest.fixture
def seeded(ex):
    run_all(ex, """
        INSERT INTO students VALUES ('Kim', 3);
        INSERT INTO students VALUES ('Lee', 2);
        INSERT INTO students VALUES ('Park', 3);
        INSERT INTO students VALUES ('kim', 1);
    """)
    return ex


def test_select_star(seeded):
    assert run(seeded, "SELECT * FROM students;") == QueryResult(
        ("id", "name", "grade"),
        ((1, "Kim", 3), (2, "Lee", 2), (3, "Park", 3), (4, "kim", 1)),
    )


def test_select_columns_in_requested_order(seeded):
    r = run(seeded, "SELECT grade, name FROM students WHERE id = 1;")
    assert r == QueryResult(("grade", "name"), ((3, "Kim"),))


def test_select_same_column_twice(seeded):
    assert run(seeded, "SELECT name, name FROM students WHERE id = 2;").rows == (("Lee", "Lee"),)


def test_select_empty_table(ex):
    assert run(ex, "SELECT * FROM students;") == QueryResult(("id", "name", "grade"), ())


def test_select_no_match(seeded):
    r = run(seeded, "SELECT * FROM students WHERE grade = 99;")
    assert r.rows == () and r.columns == ("id", "name", "grade")


@pytest.mark.parametrize(
    "op, expected_ids",
    [("=", [1, 3]), ("!=", [2, 4]), ("<", [2, 4]), ("<=", [1, 2, 3, 4]), (">", []), (">=", [1, 3])],
)
def test_select_int_operators(seeded, op, expected_ids):
    r = run(seeded, f"SELECT id FROM students WHERE grade {op} 3;")
    assert [row[0] for row in r.rows] == expected_ids


@pytest.mark.parametrize(
    "op, expected_ids",
    [("=", [1]), ("!=", [2, 3, 4]), ("<", []), ("<=", [1]), (">", [2, 3, 4]), (">=", [1, 2, 3, 4])],
)
def test_select_text_operators(seeded, op, expected_ids):
    r = run(seeded, f"SELECT id FROM students WHERE name {op} 'Kim';")
    assert [row[0] for row in r.rows] == expected_ids


def test_text_comparison_is_case_sensitive(seeded):
    assert run(seeded, "SELECT id FROM students WHERE name = 'kim';").rows == ((4,),)
    assert run(seeded, "SELECT id FROM students WHERE name < 'L';").rows == ((1,),)  # 'Kim' 만. 'kim' 은 소문자라 뒤


def test_select_by_id(seeded):
    assert run(seeded, "SELECT name FROM students WHERE id = 3;").rows == (("Park",),)


def test_select_negative_literal(seeded):
    assert run(seeded, "SELECT id FROM students WHERE grade > -1;").rowcount == 4


# --- SELECT 오류 -----------------------------------------------------------------

def test_select_unknown_table(ex):
    with pytest.raises(TableNotFoundError):
        run(ex, "SELECT * FROM teachers;")


def test_select_unknown_output_column(seeded):
    with pytest.raises(ColumnNotFoundError):
        run(seeded, "SELECT age FROM students;")


def test_select_unknown_where_column(seeded):
    with pytest.raises(ColumnNotFoundError):
        run(seeded, "SELECT * FROM students WHERE age = 1;")


def test_select_where_type_mismatch(seeded):
    with pytest.raises(TypeMismatchError):
        run(seeded, "SELECT * FROM students WHERE grade = 'three';")
    with pytest.raises(TypeMismatchError):
        run(seeded, "SELECT * FROM students WHERE name = 3;")


def test_errors_validated_before_scan(ex):
    # 빈 테이블이라도 조건 검증은 scan 과 무관하게 일어난다
    with pytest.raises(TypeMismatchError):
        run(ex, "SELECT * FROM students WHERE grade = 'x';")


# --- 실행기는 문장 객체를 직접 받는다 -------------------------------------------

def test_execute_takes_ast_objects(ex):
    assert ex.execute(Insert("students", None, ("Kim", 3))).rows == ((1,),)
    r = ex.execute(Select("students", ("name",), Condition("id", "=", 1)))
    assert r == QueryResult(("name",), (("Kim",),))


def test_script_stops_at_first_execution_error(ex, storage):
    # "멈춤" 은 문장을 차례로 넘기는 쪽의 책임이다. 그 방식이 가능함을 확인한다.
    stmts = parse("""
        INSERT INTO students VALUES ('Kim', 3);
        INSERT INTO teachers VALUES ('X', 1);
        INSERT INTO students VALUES ('Lee', 2);
    """)
    done = []
    with pytest.raises(MiniDBError):
        for s in stmts:
            done.append(ex.execute(s))
    assert len(done) == 1
    assert file_rows(storage) == [(1, "Kim", 3)]  # 앞 문장은 반영, 뒤 문장은 미반영


def test_execution_error_is_minidb_error():
    assert issubclass(ExecutionError, MiniDBError)
