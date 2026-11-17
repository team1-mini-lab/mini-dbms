import pytest

from minidb.catalog import Catalog, Column, Table
from minidb.errors import MiniDBError, StorageError, TableNotFoundError
from minidb.storage import Storage, TableFile, decode_row, encode_row


@pytest.fixture
def students(catalog) -> Table:
    return catalog.table("students")


@pytest.fixture
def table(tmp_path, students):
    tf = TableFile(tmp_path / "students.tbl", students)
    yield tf
    tf.close()


# --- 포맷: encode / decode -----------------------------------------------------

def test_encode_simple_row(students):
    assert encode_row(students, (1, "Kim", 3)) == b"1\tKim\t3\n"


def test_decode_simple_row(students):
    assert decode_row(students, b"1\tKim\t3") == (1, "Kim", 3)


@pytest.mark.parametrize(
    "name",
    [
        "Kim\tLee",          # 탭
        "Kim\nLee",          # 줄바꿈
        "C:\\path",          # 백슬래시
        "\\t",               # 백슬래시 + t 라는 두 글자 (이스케이프와 구분되어야 함)
        "\\\\",              # 백슬래시 두 개
        "\t\n\\",            # 전부 섞임
        "",                  # 빈 문자열
        "김철수",            # 한글
        "it's, \"ok\"",      # 따옴표와 쉼표는 특별 취급 없음
        "   ",               # 공백만
    ],
)
def test_roundtrip_special_values(students, name):
    line = encode_row(students, (7, name, 0))
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1          # 값 안의 줄바꿈이 행을 쪼개지 않는다
    assert line.count(b"\t") == 2          # 값 안의 탭이 구분자가 되지 않는다
    assert decode_row(students, line[:-1]) == (7, name, 0)


def test_encode_negative_and_large_int(students):
    assert encode_row(students, (-5, "x", 10**12)) == b"-5\tx\t1000000000000\n"


def test_encode_rejects_wrong_arity(students):
    with pytest.raises(StorageError):
        encode_row(students, (1, "Kim"))


def test_encode_rejects_wrong_types(students):
    with pytest.raises(StorageError):
        encode_row(students, ("1", "Kim", 3))     # id 가 문자열
    with pytest.raises(StorageError):
        encode_row(students, (1, 2, 3))           # name 이 숫자
    with pytest.raises(StorageError):
        encode_row(students, (True, "Kim", 3))    # bool 은 INT 가 아니다


def test_decode_rejects_corrupted_rows(students):
    with pytest.raises(StorageError):
        decode_row(students, b"1\tKim")           # 값 부족
    with pytest.raises(StorageError):
        decode_row(students, b"1\tKim\t3\textra")  # 값 과다
    with pytest.raises(StorageError):
        decode_row(students, b"one\tKim\t3")      # INT 자리에 글자
    with pytest.raises(StorageError):
        decode_row(students, b"1\tKi\\qm\t3")     # 알 수 없는 이스케이프


# --- TableFile: append / scan / read_at ---------------------------------------

def test_append_returns_offsets(table):
    assert table.append((1, "Kim", 3)) == 0
    assert table.append((2, "Lee", 2)) == len(b"1\tKim\t3\n")
    assert table.append((3, "Park", 1)) == len(b"1\tKim\t3\n2\tLee\t2\n")


def test_scan_yields_offsets_and_rows(table):
    o1 = table.append((1, "Kim", 3))
    o2 = table.append((2, "Lee", 2))
    assert list(table.scan()) == [(o1, (1, "Kim", 3)), (o2, (2, "Lee", 2))]


def test_scan_empty_table(table):
    assert list(table.scan()) == []


def test_read_at_matches_append_offsets(table):
    offsets = [table.append((i, f"n{i}", i % 4)) for i in range(1, 51)]
    for i, off in enumerate(offsets, start=1):
        assert table.read_at(off) == (i, f"n{i}", i % 4)


def test_read_at_with_multibyte_and_escaped_values(table):
    o1 = table.append((1, "김철수", 3))
    o2 = table.append((2, "a\tb\nc", 2))
    o3 = table.append((3, "end", 1))
    assert table.read_at(o2) == (2, "a\tb\nc", 2)
    assert table.read_at(o3) == (3, "end", 1)
    assert table.read_at(o1) == (1, "김철수", 3)


def test_read_at_invalid_offsets(table):
    o1 = table.append((1, "Kim", 3))
    o2 = table.append((2, "Lee", 2))
    with pytest.raises(StorageError):
        table.read_at(-1)
    with pytest.raises(StorageError):
        table.read_at(o2 + 100)                  # 파일 밖
    with pytest.raises(StorageError):
        table.read_at(o1 + 1)                    # 줄 중간
    with pytest.raises(StorageError):
        table.read_at(o2 + len(b"2\tLee\t2\n"))  # 정확히 파일 끝


def test_append_bad_row_does_not_touch_file(table):
    table.append((1, "Kim", 3))
    with pytest.raises(StorageError):
        table.append((2, "Lee"))
    with pytest.raises(StorageError):
        table.append(("2", "Lee", 2))
    assert [row for _, row in table.scan()] == [(1, "Kim", 3)]


def test_scan_can_be_repeated(table):
    table.append((1, "Kim", 3))
    assert list(table.scan()) == list(table.scan())


def test_scan_then_append_then_scan(table):
    table.append((1, "Kim", 3))
    list(table.scan())
    table.append((2, "Lee", 2))
    assert [row for _, row in table.scan()] == [(1, "Kim", 3), (2, "Lee", 2)]


# --- 영속성 -------------------------------------------------------------------

def test_rows_survive_reopen(tmp_path, students):
    path = tmp_path / "students.tbl"
    with TableFile(path, students) as t:
        o1 = t.append((1, "Kim", 3))
        o2 = t.append((2, "Lee", 2))
    with TableFile(path, students) as t:
        assert list(t.scan()) == [(o1, (1, "Kim", 3)), (o2, (2, "Lee", 2))]
        assert t.read_at(o2) == (2, "Lee", 2)
        assert t.append((3, "Park", 1)) == o2 + len(b"2\tLee\t2\n")


def test_file_is_human_readable(tmp_path, students):
    path = tmp_path / "students.tbl"
    with TableFile(path, students) as t:
        t.append((1, "Kim", 3))
        t.append((2, "Lee", 2))
    assert path.read_bytes() == b"1\tKim\t3\n2\tLee\t2\n"


def test_flush_after_each_append(tmp_path, students):
    # close 하지 않아도 파일에 이미 쓰여 있어야 한다.
    path = tmp_path / "students.tbl"
    t = TableFile(path, students)
    t.append((1, "Kim", 3))
    assert path.read_bytes() == b"1\tKim\t3\n"
    t.close()


# --- 쓰다 만 행 ----------------------------------------------------------------

def test_partial_last_row_is_truncated_on_open(tmp_path, students):
    path = tmp_path / "students.tbl"
    path.write_bytes(b"1\tKim\t3\n2\tLe")
    with TableFile(path, students) as t:
        assert list(t.scan()) == [(0, (1, "Kim", 3))]
        off = t.append((2, "Lee", 2))
        assert off == len(b"1\tKim\t3\n")
        assert list(t.scan()) == [(0, (1, "Kim", 3)), (off, (2, "Lee", 2))]
    assert path.read_bytes() == b"1\tKim\t3\n2\tLee\t2\n"


def test_partial_only_row_is_truncated_to_empty(tmp_path, students):
    path = tmp_path / "students.tbl"
    path.write_bytes(b"1\tKi")
    with TableFile(path, students) as t:
        assert list(t.scan()) == []
        assert t.append((1, "Kim", 3)) == 0
    assert path.read_bytes() == b"1\tKim\t3\n"


def test_partial_row_longer_than_search_block(tmp_path, students):
    # 마지막 \n 을 뒤에서부터 블록 단위로 찾는 코드가 블록 경계를 넘어도 동작해야 한다.
    path = tmp_path / "students.tbl"
    good = b"1\tKim\t3\n"
    path.write_bytes(good + b"2\t" + b"x" * 10000)
    with TableFile(path, students) as t:
        assert list(t.scan()) == [(0, (1, "Kim", 3))]
    assert path.read_bytes() == good


def test_complete_file_is_not_modified_on_open(tmp_path, students):
    path = tmp_path / "students.tbl"
    path.write_bytes(b"1\tKim\t3\n")
    with TableFile(path, students):
        pass
    assert path.read_bytes() == b"1\tKim\t3\n"


def test_corrupted_middle_row_raises_on_scan(tmp_path, students):
    path = tmp_path / "students.tbl"
    path.write_bytes(b"1\tKim\t3\nbroken\n3\tPark\t1\n")
    with TableFile(path, students) as t:
        it = t.scan()
        assert next(it) == (0, (1, "Kim", 3))
        with pytest.raises(StorageError):
            next(it)


# --- 수명 -----------------------------------------------------------------------

def test_closed_table_rejects_operations(tmp_path, students):
    t = TableFile(tmp_path / "s.tbl", students)
    t.close()
    assert t.closed
    with pytest.raises(StorageError):
        t.append((1, "Kim", 3))
    with pytest.raises(StorageError):
        list(t.scan())
    with pytest.raises(StorageError):
        t.read_at(0)
    t.close()  # 두 번 닫아도 안전


def test_creates_missing_directory(tmp_path, students):
    path = tmp_path / "nested" / "dir" / "s.tbl"
    with TableFile(path, students) as t:
        t.append((1, "Kim", 3))
    assert path.exists()


# --- Storage ----------------------------------------------------------------------

def test_storage_opens_table_by_name(tmp_path, catalog):
    with Storage(tmp_path, catalog) as st:
        t = st.table("students")
        t.append((1, "Kim", 3))
        assert st.table("students") is t          # 두 번째 요청은 같은 객체
        assert (tmp_path / "students.tbl").exists()


def test_storage_unknown_table(tmp_path, catalog):
    with Storage(tmp_path, catalog) as st:
        with pytest.raises(TableNotFoundError):
            st.table("teachers")


def test_storage_close_closes_all_tables(tmp_path):
    catalog = Catalog.from_dict({
        "a": {"columns": [{"name": "id", "type": "INT"}, {"name": "v", "type": "TEXT"}]},
        "b": {"columns": [{"name": "id", "type": "INT"}, {"name": "n", "type": "INT"}]},
    })
    st = Storage(tmp_path, catalog)
    ta, tb = st.table("a"), st.table("b")
    ta.append((1, "x"))
    tb.append((1, 2))
    st.close()
    assert ta.closed and tb.closed
    # 다시 열면 새 객체이고 데이터는 남아 있다
    assert list(st.table("a").scan()) == [(0, (1, "x"))]
    st.close()


def test_storage_errors_are_minidb_errors():
    assert issubclass(StorageError, MiniDBError)
