import pytest

from minidb.ast import Condition, Insert, Select
from minidb.errors import ParseError
from minidb.parser import parse


def parse_one(sql):
    stmts = parse(sql)
    assert len(stmts) == 1
    return stmts[0]


# --- SELECT ------------------------------------------------------------------

def test_select_star():
    assert parse_one("SELECT * FROM students;") == Select("students", None, None)


def test_select_columns():
    assert parse_one("SELECT name, grade FROM students;") == Select(
        "students", ("name", "grade"), None
    )


def test_select_single_column():
    assert parse_one("SELECT name FROM students;") == Select("students", ("name",), None)


def test_select_with_where():
    assert parse_one("SELECT name FROM students WHERE id = 1;") == Select(
        "students", ("name",), Condition("id", "=", 1)
    )


def test_select_star_with_where_string():
    assert parse_one("SELECT * FROM students WHERE name = 'Kim';") == Select(
        "students", None, Condition("name", "=", "Kim")
    )


@pytest.mark.parametrize("op", ["=", "!=", "<", "<=", ">", ">="])
def test_select_all_operators(op):
    stmt = parse_one(f"SELECT * FROM t WHERE grade {op} 3;")
    assert stmt.where == Condition("grade", op, 3)


def test_select_where_negative_number():
    assert parse_one("SELECT * FROM t WHERE grade > -1;").where == Condition("grade", ">", -1)


def test_select_is_case_insensitive_and_lowercases_identifiers():
    assert parse_one("select Name from Students where ID = 1;") == Select(
        "students", ("name",), Condition("id", "=", 1)
    )


# --- INSERT ------------------------------------------------------------------

def test_insert_with_columns():
    assert parse_one("INSERT INTO students (name, grade) VALUES ('Kim', 3);") == Insert(
        "students", ("name", "grade"), ("Kim", 3)
    )


def test_insert_without_columns():
    assert parse_one("INSERT INTO students VALUES ('Kim', 3);") == Insert(
        "students", None, ("Kim", 3)
    )


def test_insert_single_value():
    assert parse_one("INSERT INTO t (a) VALUES (1);") == Insert("t", ("a",), (1,))


def test_insert_string_with_escaped_quote():
    assert parse_one("INSERT INTO t (a) VALUES ('it''s');").values == ("it's",)


# --- 여러 문장 ---------------------------------------------------------------

def test_multiple_statements():
    stmts = parse(
        "INSERT INTO students (name, grade) VALUES ('Kim', 3);\n"
        "INSERT INTO students VALUES ('Lee', 2);\n"
        "SELECT * FROM students WHERE id = 1;\n"
    )
    assert stmts == [
        Insert("students", ("name", "grade"), ("Kim", 3)),
        Insert("students", None, ("Lee", 2)),
        Select("students", None, Condition("id", "=", 1)),
    ]


def test_statement_lines():
    stmts = parse("SELECT * FROM a;\n\n-- 주석\nSELECT * FROM b;\nINSERT INTO c\n VALUES (1);")
    assert [s.line for s in stmts] == [1, 4, 5]


def test_line_is_not_part_of_equality():
    assert Select("t", None, None, line=1) == Select("t", None, None, line=9)


def test_empty_input():
    assert parse("") == []
    assert parse("-- 주석만\n") == []


def test_statements_on_one_line():
    assert len(parse("SELECT * FROM a; SELECT * FROM b;")) == 2


# --- 문법 오류: 메시지와 위치 ------------------------------------------------

def _err(sql):
    with pytest.raises(ParseError) as e:
        parse(sql)
    return e.value


def test_missing_from():
    e = _err("SELECT name students;")
    assert (e.line, e.col) == (1, 13)
    assert "FROM 이 와야 하는데" in e.message
    assert "식별자 'students'" in e.message


def test_missing_semicolon_at_end():
    e = _err("SELECT * FROM t")
    assert (e.line, e.col) == (1, 16)
    assert "';' 이 와야 하는데 입력이 끝났습니다" in e.message


def test_missing_semicolon_between_statements():
    e = _err("SELECT * FROM a\nSELECT * FROM b;")
    assert (e.line, e.col) == (2, 1)
    assert "';' 이 와야 하는데 SELECT 가 왔습니다" in e.message


def test_unknown_statement():
    e = _err("DELETE FROM t;")
    assert (e.line, e.col) == (1, 1)
    assert "SELECT 또는 INSERT 이 와야 하는데" in e.message
    assert "'delete'" in e.message


def test_star_mixed_with_columns():
    e = _err("SELECT *, name FROM t;")
    assert (e.line, e.col) == (1, 9)
    assert "FROM 이 와야 하는데 ',' 가 왔습니다" in e.message


def test_empty_select_list():
    e = _err("SELECT FROM t;")
    assert (e.line, e.col) == (1, 8)
    assert "컬럼 이름 이 와야 하는데 FROM 가 왔습니다" in e.message


def test_trailing_comma_in_select_list():
    e = _err("SELECT a, FROM t;")
    assert (e.line, e.col) == (1, 11)


def test_keyword_as_table_name():
    e = _err("SELECT * FROM select;")
    assert "테이블 이름 이 와야 하는데 SELECT 가 왔습니다" in e.message


def test_where_without_condition():
    e = _err("SELECT * FROM t WHERE;")
    assert (e.line, e.col) == (1, 22)
    assert "컬럼 이름" in e.message


def test_where_missing_operator():
    e = _err("SELECT * FROM t WHERE id 1;")
    assert "비교 연산자 이 와야 하는데 숫자 1 가 왔습니다" in e.message


def test_where_value_must_be_literal():
    e = _err("SELECT * FROM t WHERE id = name;")
    assert (e.line, e.col) == (1, 28)
    assert "숫자 또는 문자열 이 와야 하는데 식별자 'name' 가 왔습니다" in e.message


def test_where_with_and_is_rejected():
    # AND 는 키워드가 아니므로 식별자로 들어오고, 조건 뒤에는 ';' 만 올 수 있다.
    e = _err("SELECT * FROM t WHERE a = 1 AND b = 2;")
    assert "';' 이 와야 하는데 식별자 'and' 가 왔습니다" in e.message


def test_insert_missing_values_keyword():
    e = _err("INSERT INTO t (a) (1);")
    assert "VALUES 이 와야 하는데 '(' 가 왔습니다" in e.message


def test_insert_missing_parens():
    e = _err("INSERT INTO t VALUES 1;")
    assert "'(' 이 와야 하는데 숫자 1 가 왔습니다" in e.message


def test_insert_unclosed_paren():
    e = _err("INSERT INTO t VALUES (1, 2;")
    assert (e.line, e.col) == (1, 27)
    assert "')' 이 와야 하는데 ';' 가 왔습니다" in e.message


def test_insert_value_cannot_be_identifier():
    e = _err("INSERT INTO t VALUES (name);")
    assert "숫자 또는 문자열 이 와야 하는데 식별자 'name' 가 왔습니다" in e.message


def test_insert_empty_values():
    e = _err("INSERT INTO t VALUES ();")
    assert "숫자 또는 문자열 이 와야 하는데 ')' 가 왔습니다" in e.message


def test_insert_column_value_count_mismatch():
    e = _err("INSERT INTO t (a, b) VALUES (1);")
    assert (e.line, e.col) == (1, 1)
    assert e.message == "컬럼 2개에 값 1개가 왔습니다"


def test_insert_duplicate_column():
    e = _err("INSERT INTO t (a, a) VALUES (1, 2);")
    assert e.message == "컬럼 'a' 이 두 번 나왔습니다"


def test_insert_without_columns_does_not_check_count():
    # 컬럼 생략 시 값 수가 스키마와 맞는지는 카탈로그가 필요하므로 파서는 보지 않는다.
    assert parse_one("INSERT INTO t VALUES (1, 2, 3, 4, 5);").values == (1, 2, 3, 4, 5)


def test_lexer_errors_propagate():
    e = _err("SELECT * FROM t WHERE name = 'Kim;")
    assert "닫히지 않은 문자열" in e.message


def test_error_in_second_statement_returns_nothing():
    # 전체 파싱 후 실행 원칙: 첫 문장이 멀쩡해도 리스트를 돌려주지 않는다.
    with pytest.raises(ParseError) as e:
        parse("INSERT INTO t VALUES (1);\nSELECT FROM t;")
    assert e.value.line == 2


def test_error_message_str_includes_position():
    e = _err("SELECT * FROM t")
    assert str(e) == "1:16: ';' 이 와야 하는데 입력이 끝났습니다"
