"""Phase 1 끝에서 끝까지의 엣지 케이스 (docs/hnjee/step06-edge-cases.md).

핵심 원칙: 사용자 입력이나 데이터 상태 때문에 MiniDBError 가 아닌 예외가 CLI 밖으로
새어 나오면 안 된다. 실제 서브프로세스로 실행해 트레이스백이 없는지 본다.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from minidb.cli import EXIT_EXECUTION, EXIT_INPUT, EXIT_OK, main
from tests.conftest import STUDENTS_SCHEMA

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "schema.json").write_text(json.dumps(STUDENTS_SCHEMA), encoding="utf-8")
    return d


def run_cli(tmp_path, data_dir, sql, extra=()):
    f = tmp_path / "q.sql"
    f.write_text(sql, encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = main([str(f), "--data-dir", str(data_dir), *extra], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def run_process(sql_path, data_dir, extra=()):
    """실제 python -m minidb 실행. (종료코드, stdout, stderr)."""
    p = subprocess.run(
        [sys.executable, "-m", "minidb", str(sql_path), "--data-dir", str(data_dir), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return p.returncode, p.stdout, p.stderr


def assert_clean_failure(code, err, expected_code):
    assert code == expected_code
    assert "Traceback" not in err
    assert err.count("\n") == 1  # 한 줄 메시지


# --- 2절: 고친 버그 (트레이스백이 나던 경우) -----------------------------------

def test_utf16_sql_file(tmp_path, data_dir):
    f = tmp_path / "u16.sql"
    f.write_bytes("SELECT * FROM students;".encode("utf-16"))
    code, out, err = run_process(f, data_dir)
    assert_clean_failure(code, err, EXIT_INPUT)
    assert "UTF-8 로 읽을 수 없는 파일" in err
    assert out == ""


def test_bom_sql_file_is_accepted(tmp_path, data_dir):
    f = tmp_path / "bom.sql"
    f.write_bytes(b"\xef\xbb\xbfINSERT INTO students VALUES ('Kim', 3);")
    code, out, err = run_process(f, data_dir)
    assert (code, out, err) == (EXIT_OK, "1 row inserted (id=1)\n", "")


def test_invalid_utf8_in_table_file(tmp_path, data_dir):
    (data_dir / "students.tbl").write_bytes(b"1\tKim\t3\n2\t\xff\xfe\t2\n")
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM students;", encoding="utf-8")
    code, out, err = run_process(f, data_dir)
    assert_clean_failure(code, err, EXIT_EXECUTION)
    assert "손상된 행" in err and "UTF-8" in err


def test_data_dir_is_a_regular_file(tmp_path, data_dir):
    not_a_dir = tmp_path / "notadir"
    not_a_dir.write_text("x")
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM students;", encoding="utf-8")
    code, _, err = run_process(f, not_a_dir, ["--schema", str(data_dir / "schema.json")])
    assert_clean_failure(code, err, EXIT_EXECUTION)
    assert "테이블 파일을 열 수 없습니다" in err


# --- 3절: 끝에서 끝까지 확인 ----------------------------------------------------

def test_twenty_thousand_rows(tmp_path, data_dir):
    n = 20_000
    sql = "".join(f"INSERT INTO students VALUES ('s{i}', {i % 6});\n" for i in range(1, n + 1))
    code, out, err = run_cli(tmp_path, data_dir, sql)
    assert code == EXIT_OK and err == ""
    lines = out.splitlines()
    assert len(lines) == n
    assert lines[0] == "1 row inserted (id=1)" and lines[-1] == f"1 row inserted (id={n})"

    code, out, _ = run_cli(tmp_path, data_dir, f"SELECT name FROM students WHERE id = {n};")
    assert out == f"name\n------\ns{n}\n"

    code, out, _ = run_cli(tmp_path, data_dir, "SELECT id FROM students WHERE grade = 0;")
    assert len(out.splitlines()) - 2 == n // 6  # 헤더와 구분선을 뺀 행 수

    assert (data_dir / "students.tbl").read_bytes().count(b"\n") == n


def test_corrupted_middle_row(tmp_path, data_dir):
    (data_dir / "students.tbl").write_bytes(b"1\tKim\t3\nbroken line\n3\tPark\t1\n")
    code, out, err = run_cli(tmp_path, data_dir, "SELECT * FROM students;")
    assert_clean_failure(code, err, EXIT_EXECUTION)
    assert "'students'" in err and "손상된 행" in err
    assert out == ""  # 표는 행을 다 받은 뒤에 찍으므로 일부만 찍히지 않는다


def test_corrupted_row_blocks_insert_too(tmp_path, data_dir):
    # INSERT 는 처음에 최대 id 를 세려고 scan 하므로 손상을 발견한다. 파일은 그대로다.
    original = b"1\tKim\tthree\n"
    (data_dir / "students.tbl").write_bytes(original)
    code, _, err = run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Lee', 2);")
    assert_clean_failure(code, err, EXIT_EXECUTION)
    assert (data_dir / "students.tbl").read_bytes() == original


def test_table_file_does_not_exist_yet(tmp_path, data_dir):
    assert not (data_dir / "students.tbl").exists()
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT * FROM students;")
    assert code == EXIT_OK and out.endswith("(0 rows)\n")
    assert (data_dir / "students.tbl").read_bytes() == b""


def test_insert_after_partial_last_row(tmp_path, data_dir):
    (data_dir / "students.tbl").write_bytes(b"1\tKim\t3\n2\tLee\t2\n3\tPa")
    code, out, _ = run_cli(tmp_path, data_dir, "INSERT INTO students VALUES ('Choi', 4);\nSELECT * FROM students;")
    assert code == EXIT_OK
    assert out.startswith("1 row inserted (id=3)\n")  # 반쪽 행의 id 3 은 없던 것
    assert (data_dir / "students.tbl").read_bytes() == b"1\tKim\t3\n2\tLee\t2\n3\tChoi\t4\n"


@pytest.mark.parametrize(
    "sql_literal, expected",
    [
        ("''", ""),                                  # 빈 문자열
        ("'a\tb'", "a\tb"),                           # 탭
        ("'line1\nline2'", "line1\nline2"),           # 줄바꿈
        ("'C:\\new\\table'", "C:\\new\\table"),       # 백슬래시 + n, t (이스케이프와 혼동 금지)
        ("'it''s'", "it's"),                          # 따옴표
        ("'김철수 ☕'", "김철수 ☕"),                  # 한글, 이모지
        ("'  앞뒤 공백  '", "  앞뒤 공백  "),
    ],
)
def test_special_values_end_to_end(tmp_path, data_dir, sql_literal, expected):
    from minidb.catalog import Catalog
    from minidb.executor import Executor
    from minidb.parser import parse
    from minidb.storage import Storage

    code, _, err = run_cli(tmp_path, data_dir, f"INSERT INTO students VALUES ({sql_literal}, 1);")
    assert code == EXIT_OK, err
    # 화면 표는 줄바꿈 등으로 깨질 수 있으므로 값 자체는 실행기로 확인한다 (새 프로세스와 같은 조건)
    catalog = Catalog.load(data_dir / "schema.json")
    with Storage(data_dir, catalog) as st:
        (stmt,) = parse(f"SELECT name FROM students WHERE name = {sql_literal};")
        assert Executor(catalog, st).execute(stmt).rows == ((expected,),)


def test_very_long_string(tmp_path, data_dir):
    long = "가" * 100_000
    code, _, _ = run_cli(tmp_path, data_dir, f"INSERT INTO students VALUES ('{long}', 1);")
    assert code == EXIT_OK
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT name FROM students WHERE id = 1;")
    assert out.splitlines()[2] == long


def test_integer_extremes(tmp_path, data_dir):
    big = 10**30
    run_cli(tmp_path, data_dir, f"INSERT INTO students VALUES ('big', {big}); INSERT INTO students VALUES ('neg', -{big});")
    code, out, _ = run_cli(tmp_path, data_dir, f"SELECT name FROM students WHERE grade > {big - 1};")
    assert out.splitlines()[2:] == ["big"]
    code, out, _ = run_cli(tmp_path, data_dir, "SELECT name FROM students WHERE grade < 0;")
    assert out.splitlines()[2:] == ["neg"]


def test_windows_line_endings_in_sql(tmp_path, data_dir):
    f = tmp_path / "crlf.sql"
    f.write_bytes(b"INSERT INTO students VALUES ('Kim', 3);\r\nSELECT name FROM students;\r\n")
    code, out, err = run_process(f, data_dir)
    assert (code, err) == (EXIT_OK, "")
    assert out == "1 row inserted (id=1)\nname\n----\nKim\n"


def test_sql_file_is_directory(tmp_path, data_dir):
    out, err = io.StringIO(), io.StringIO()
    code = main([str(tmp_path), "--data-dir", str(data_dir)], stdout=out, stderr=err)
    assert_clean_failure(code, err.getvalue(), EXIT_INPUT)
