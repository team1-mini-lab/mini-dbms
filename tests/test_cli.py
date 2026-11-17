import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from minidb.cli import EXIT_EXECUTION, EXIT_INPUT, EXIT_OK, format_insert, format_table, main
from minidb.executor import QueryResult
from tests.conftest import STUDENTS_SCHEMA

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "schema.json").write_text(json.dumps(STUDENTS_SCHEMA), encoding="utf-8")
    return d


def run_cli(tmp_path, data_dir, sql, extra_args=()):
    """SQL 을 파일에 쓰고 main() 을 함수로 부른다. (종료코드, stdout, stderr) 를 돌려준다."""
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(sql, encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = main([str(sql_file), "--data-dir", str(data_dir), *extra_args], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


# --- 포맷 함수 -----------------------------------------------------------------

def test_format_insert():
    assert format_insert(QueryResult(("id",), ((7,),))) == "1 row inserted (id=7)"


def test_format_table_widths():
    r = QueryResult(("id", "name", "grade"), ((1, "Kim", 3), (2, "Lee", 2)))
    assert format_table(r) == (
        "id | name | grade\n"
        "---+------+------\n"
        "1  | Kim  | 3\n"
        "2  | Lee  | 2"
    )


def test_format_table_long_value_widens_column():
    r = QueryResult(("id", "name"), ((1, "Alexander"),))
    assert format_table(r) == (
        "id | name\n"
        "---+----------\n"
        "1  | Alexander"
    )


def test_format_table_empty():
    r = QueryResult(("id", "name", "grade"), ())
    assert format_table(r) == (
        "id | name | grade\n"
        "---+------+------\n"
        "(0 rows)"
    )


def test_format_table_single_column():
    assert format_table(QueryResult(("name",), (("Kim",), ("Lee",)))) == "name\n----\nKim\nLee"


# --- 정상 흐름 -----------------------------------------------------------------

def test_example_output(tmp_path, data_dir):
    sql = (REPO_ROOT / "examples" / "students.sql").read_text(encoding="utf-8")
    code, out, err = run_cli(tmp_path, data_dir, sql)
    assert code == EXIT_OK
    assert err == ""
    assert out == (
        "1 row inserted (id=1)\n"
        "1 row inserted (id=2)\n"
        "id | name | grade\n"
        "---+------+------\n"
        "1  | Kim  | 3\n"
    )


def test_data_persists_across_runs(tmp_path, data_dir):
    run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Kim', 3); INSERT INTO students VALUES ('Lee', 2);")
    code, out, _ = run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Park', 1);\nSELECT name FROM students;")
    assert code == EXIT_OK
    assert out == "1 row inserted (id=3)\nname\n----\nKim\nLee\nPark\n"
    assert (data_dir / "students.tbl").read_bytes() == b"1\tKim\t3\n2\tLee\t2\n3\tPark\t1\n"


def test_empty_result(tmp_path, data_dir):
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT * FROM students WHERE grade = 9;")
    assert code == EXIT_OK
    assert out == "id | name | grade\n---+------+------\n(0 rows)\n"


def test_empty_sql_file(tmp_path, data_dir):
    code, out, err = run_cli(tmp_path, data_dir, "-- 주석만\n")
    assert (code, out, err) == (EXIT_OK, "", "")


def test_schema_option(tmp_path, data_dir):
    other = tmp_path / "elsewhere.json"
    other.write_text(json.dumps(STUDENTS_SCHEMA), encoding="utf-8")
    (data_dir / "schema.json").unlink()
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT * FROM students;", ["--schema", str(other)])
    assert code == EXIT_OK and "(0 rows)" in out


def test_default_data_dir_is_data(tmp_path, data_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)  # tmp_path/data 가 기본값 'data' 로 잡혀야 한다
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("INSERT INTO students VALUES ('Kim', 3);", encoding="utf-8")
    out = io.StringIO()
    assert main([str(sql_file)], stdout=out, stderr=io.StringIO()) == EXIT_OK
    assert (data_dir / "students.tbl").exists()


# --- 오류: 종료 코드와 메시지 ---------------------------------------------------

def test_missing_sql_file(tmp_path, data_dir):
    out, err = io.StringIO(), io.StringIO()
    code = main([str(tmp_path / "nope.sql"), "--data-dir", str(data_dir)], stdout=out, stderr=err)
    assert code == EXIT_INPUT
    assert out.getvalue() == ""
    assert err.getvalue().startswith("오류: 파일을 열 수 없습니다")


def test_parse_error_executes_nothing(tmp_path, data_dir):
    code, out, err = run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Kim', 3);\nSELECT FROM students;")
    assert code == EXIT_INPUT
    assert out == ""
    assert err == "문법 오류: 2:8: 컬럼 이름 이 와야 하는데 FROM 가 왔습니다\n"
    assert not (data_dir / "students.tbl").exists() or (data_dir / "students.tbl").read_bytes() == b""


def test_execution_error_stops_and_reports_line(tmp_path, data_dir):
    sql = (
        "INSERT INTO students VALUES ('Kim', 3);\n"
        "\n"
        "INSERT INTO teachers VALUES ('X', 1);\n"
        "INSERT INTO students VALUES ('Lee', 2);\n"
    )
    code, out, err = run_cli(tmp_path, data_dir, sql)
    assert code == EXIT_EXECUTION
    assert out == "1 row inserted (id=1)\n"                       # 앞 문장은 실행되고 출력됨
    assert err == "실행 오류 (3번째 줄): 테이블 'teachers' 이 없습니다\n"
    assert (data_dir / "students.tbl").read_bytes() == b"1\tKim\t3\n"  # 뒤 문장은 미반영


def test_type_mismatch_is_execution_error(tmp_path, data_dir):
    code, _, err = run_cli(tmp_path, data_dir, "SELECT * FROM students WHERE grade = 'x';")
    assert code == EXIT_EXECUTION
    assert err.startswith("실행 오류 (1번째 줄): 컬럼 'grade'")


def test_missing_schema_file(tmp_path, data_dir):
    (data_dir / "schema.json").unlink()
    code, out, err = run_cli(tmp_path, data_dir, "SELECT * FROM students;")
    assert code == EXIT_EXECUTION
    assert out == ""
    assert err.startswith("실행 오류: 스키마 파일이 없습니다")


def test_invalid_schema_file(tmp_path, data_dir):
    (data_dir / "schema.json").write_text('{"Bad": {"columns": []}}', encoding="utf-8")
    code, _, err = run_cli(tmp_path, data_dir, "SELECT * FROM students;")
    assert code == EXIT_EXECUTION and err.startswith("실행 오류:")


def test_storage_closed_after_execution_error(tmp_path, data_dir):
    # 오류 뒤에도 파일이 닫혔다면 다음 실행이 정상이어야 한다 (with 블록 확인)
    run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Kim', 3);\nSELECT * FROM nope;")
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT id FROM students;")
    assert code == EXIT_OK and out == "id\n--\n1\n"


# --- 진입점 ----------------------------------------------------------------------

def test_python_m_minidb_entry_point(tmp_path, data_dir):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("INSERT INTO students VALUES ('Kim', 3);\nSELECT * FROM students;", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "minidb", str(sql_file), "--data-dir", str(data_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == EXIT_OK
    assert proc.stdout == "1 row inserted (id=1)\nid | name | grade\n---+------+------\n1  | Kim  | 3\n"
    assert proc.stderr == ""


def test_entry_point_exit_code_on_error(tmp_path, data_dir):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT * FROM students", encoding="utf-8")  # 세미콜론 없음
    proc = subprocess.run(
        [sys.executable, "-m", "minidb", str(sql_file), "--data-dir", str(data_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == EXIT_INPUT
    assert proc.stdout == ""
    assert proc.stderr.startswith("문법 오류: 1:23:")
