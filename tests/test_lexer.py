import pytest

from minidb.errors import MiniDBError, ParseError
from minidb.lexer import (
    EOF, IDENTIFIER, KEYWORD, NUMBER, OPERATOR, STRING, SYMBOL, Token, tokenize,
)


def kinds_and_values(sql):
    """위치를 뺀 (종류, 값) 목록. 대부분의 테스트는 위치까지는 보지 않는다."""
    return [(t.kind, t.value) for t in tokenize(sql)]


# --- 기본 문장 ---------------------------------------------------------------

def test_select_statement():
    assert kinds_and_values("SELECT * FROM students WHERE id = 1;") == [
        (KEYWORD, "SELECT"),
        (SYMBOL, "*"),
        (KEYWORD, "FROM"),
        (IDENTIFIER, "students"),
        (KEYWORD, "WHERE"),
        (IDENTIFIER, "id"),
        (OPERATOR, "="),
        (NUMBER, 1),
        (SYMBOL, ";"),
        (EOF, None),
    ]


def test_insert_statement():
    assert kinds_and_values("INSERT INTO students (name, grade) VALUES ('Kim', 3);") == [
        (KEYWORD, "INSERT"),
        (KEYWORD, "INTO"),
        (IDENTIFIER, "students"),
        (SYMBOL, "("),
        (IDENTIFIER, "name"),
        (SYMBOL, ","),
        (IDENTIFIER, "grade"),
        (SYMBOL, ")"),
        (KEYWORD, "VALUES"),
        (SYMBOL, "("),
        (STRING, "Kim"),
        (SYMBOL, ","),
        (NUMBER, 3),
        (SYMBOL, ")"),
        (SYMBOL, ";"),
        (EOF, None),
    ]


def test_empty_input_is_just_eof():
    assert kinds_and_values("") == [(EOF, None)]
    assert kinds_and_values("   \n\t ") == [(EOF, None)]


def test_multiple_statements_are_one_token_stream():
    toks = kinds_and_values("SELECT * FROM a; SELECT * FROM b;")
    assert toks.count((SYMBOL, ";")) == 2
    assert toks[-1] == (EOF, None)


# --- 정규화 ------------------------------------------------------------------

def test_keywords_are_case_insensitive():
    assert kinds_and_values("select FROM Where") == [
        (KEYWORD, "SELECT"), (KEYWORD, "FROM"), (KEYWORD, "WHERE"), (EOF, None),
    ]


def test_identifiers_are_lowercased():
    assert kinds_and_values("Students NAME grade_2") == [
        (IDENTIFIER, "students"), (IDENTIFIER, "name"), (IDENTIFIER, "grade_2"), (EOF, None),
    ]


def test_underscore_identifier():
    assert kinds_and_values("_tmp") == [(IDENTIFIER, "_tmp"), (EOF, None)]


# --- 문자열 ------------------------------------------------------------------

def test_string_with_spaces_and_semicolon():
    assert kinds_and_values("'Kim Lee; FROM'") == [(STRING, "Kim Lee; FROM"), (EOF, None)]


def test_string_with_escaped_quote():
    assert kinds_and_values("'it''s'") == [(STRING, "it's"), (EOF, None)]


def test_empty_string():
    assert kinds_and_values("''") == [(STRING, ""), (EOF, None)]


def test_two_adjacent_strings():
    # '' 는 이스케이프이므로 'a''b' 는 문자열 하나다. 'a' 'b' 는 둘이다.
    assert kinds_and_values("'a''b'") == [(STRING, "a'b"), (EOF, None)]
    assert kinds_and_values("'a' 'b'") == [(STRING, "a"), (STRING, "b"), (EOF, None)]


def test_string_may_contain_newline():
    assert kinds_and_values("'a\nb'") == [(STRING, "a\nb"), (EOF, None)]


def test_string_with_korean():
    assert kinds_and_values("'김철수'") == [(STRING, "김철수"), (EOF, None)]


# --- 숫자 --------------------------------------------------------------------

def test_numbers_are_ints():
    assert kinds_and_values("0 42 1000000") == [
        (NUMBER, 0), (NUMBER, 42), (NUMBER, 1000000), (EOF, None),
    ]


def test_negative_number():
    assert kinds_and_values("grade = -3") == [
        (IDENTIFIER, "grade"), (OPERATOR, "="), (NUMBER, -3), (EOF, None),
    ]


def test_float_is_rejected():
    with pytest.raises(ParseError) as e:
        tokenize("3.14")
    assert e.value.col == 2  # '.' 의 위치


# --- 연산자와 기호 -----------------------------------------------------------

def test_all_operators():
    assert kinds_and_values("= != < <= > >=") == [
        (OPERATOR, "="), (OPERATOR, "!="), (OPERATOR, "<"),
        (OPERATOR, "<="), (OPERATOR, ">"), (OPERATOR, ">="), (EOF, None),
    ]


def test_operators_without_spaces():
    assert kinds_and_values("grade<=3") == [
        (IDENTIFIER, "grade"), (OPERATOR, "<="), (NUMBER, 3), (EOF, None),
    ]
    assert kinds_and_values("a<b") == [
        (IDENTIFIER, "a"), (OPERATOR, "<"), (IDENTIFIER, "b"), (EOF, None),
    ]


def test_symbols_without_spaces():
    assert kinds_and_values("(a,b);") == [
        (SYMBOL, "("), (IDENTIFIER, "a"), (SYMBOL, ","), (IDENTIFIER, "b"),
        (SYMBOL, ")"), (SYMBOL, ";"), (EOF, None),
    ]


# --- 주석 --------------------------------------------------------------------

def test_comment_to_end_of_line():
    assert kinds_and_values("SELECT * -- 전체 조회; FROM x\nFROM t") == [
        (KEYWORD, "SELECT"), (SYMBOL, "*"), (KEYWORD, "FROM"), (IDENTIFIER, "t"), (EOF, None),
    ]


def test_comment_at_end_of_input():
    assert kinds_and_values("SELECT -- 끝") == [(KEYWORD, "SELECT"), (EOF, None)]


def test_comment_only():
    assert kinds_and_values("-- 주석뿐") == [(EOF, None)]


def test_double_dash_inside_string_is_not_comment():
    assert kinds_and_values("'a--b'") == [(STRING, "a--b"), (EOF, None)]


# --- 위치 --------------------------------------------------------------------

def test_positions_single_line():
    toks = tokenize("SELECT name FROM t;")
    assert [(t.value, t.line, t.col) for t in toks] == [
        ("SELECT", 1, 1), ("name", 1, 8), ("FROM", 1, 13), ("t", 1, 18), (";", 1, 19), (None, 1, 20),
    ]


def test_positions_multi_line():
    sql = "INSERT INTO t\n  VALUES ('x',\n    7);"
    toks = tokenize(sql)
    by_value = {t.value: (t.line, t.col) for t in toks}
    assert by_value["INSERT"] == (1, 1)
    assert by_value["VALUES"] == (2, 3)
    assert by_value["x"] == (2, 11)
    assert by_value[7] == (3, 5)
    assert by_value[";"] == (3, 7)


def test_position_after_multiline_string():
    toks = tokenize("'a\nb' x")
    x = toks[1]
    assert (x.value, x.line, x.col) == ("x", 2, 4)


def test_string_token_position_is_opening_quote():
    toks = tokenize("  'abc'")
    assert (toks[0].line, toks[0].col) == (1, 3)


# --- 오류 --------------------------------------------------------------------

def test_unterminated_string():
    with pytest.raises(ParseError) as e:
        tokenize("VALUES ('Kim)")
    assert (e.value.line, e.value.col) == (1, 9)
    assert "닫히지 않은 문자열" in str(e.value)
    assert str(e.value).startswith("1:9: ")


def test_unterminated_string_with_escaped_quote_at_end():
    with pytest.raises(ParseError):
        tokenize("'abc''")


def test_illegal_character():
    with pytest.raises(ParseError) as e:
        tokenize("SELECT # FROM t")
    assert (e.value.line, e.value.col) == (1, 8)
    assert "#" in str(e.value)


def test_lone_minus_is_illegal():
    with pytest.raises(ParseError) as e:
        tokenize("WHERE id - 1")
    assert (e.value.line, e.value.col) == (1, 10)


def test_error_on_second_line_reports_line_two():
    with pytest.raises(ParseError) as e:
        tokenize("SELECT *\nFROM t @")
    assert (e.value.line, e.value.col) == (2, 8)


def test_non_ascii_identifier_is_illegal():
    with pytest.raises(ParseError):
        tokenize("SELECT 이름 FROM t")


def test_parse_error_is_minidb_error():
    assert issubclass(ParseError, MiniDBError)


def test_parse_error_without_position():
    assert str(ParseError("그냥 메시지")) == "그냥 메시지"


def test_token_is_immutable():
    t = Token(NUMBER, 1, 1, 1)
    with pytest.raises(Exception):
        t.value = 2  # type: ignore[misc]
