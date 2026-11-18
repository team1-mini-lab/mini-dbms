import copy
import json
from pathlib import Path

import pytest

from minidb.catalog import Catalog, Column
from minidb.errors import ColumnNotFoundError, MiniDBError, SchemaError, TableNotFoundError
from tests.conftest import STUDENTS_SCHEMA

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- 정상 로딩 -------------------------------------------------------------

def test_load_from_repo_schema_file():
    catalog = Catalog.load(REPO_ROOT / "data" / "schema.json")
    assert {"users", "students"} <= set(catalog.table_names)   # Phase 3 서버가 쓰는 users 추가


def test_table_columns(catalog):
    t = catalog.table("students")
    assert t.column_names == ("id", "name", "grade")
    assert t.columns[0] == Column("id", "INT")
    assert t.user_columns == (Column("name", "TEXT"), Column("grade", "INT"))


def test_column_lookup(catalog):
    t = catalog.table("students")
    assert t.column("grade") == Column("grade", "INT")
    assert t.column_index("grade") == 2


# --- 없는 것을 참조 -------------------------------------------------------

def test_unknown_table(catalog):
    with pytest.raises(TableNotFoundError):
        catalog.table("teachers")


def test_unknown_column(catalog):
    t = catalog.table("students")
    with pytest.raises(ColumnNotFoundError):
        t.column("age")
    with pytest.raises(ColumnNotFoundError):
        t.column_index("age")


def test_errors_are_minidb_errors():
    # CLI 와 서버는 MiniDBError 하나만 잡는다. 하위 타입이 모두 그 아래 있어야 한다.
    assert issubclass(TableNotFoundError, SchemaError)
    assert issubclass(ColumnNotFoundError, SchemaError)
    assert issubclass(SchemaError, MiniDBError)


# --- 카탈로그 파일 검증 규칙 ----------------------------------------------

def _schema_with(**changes):
    """students 스키마를 복사해 일부만 바꾼다."""
    raw = copy.deepcopy(STUDENTS_SCHEMA)
    cols = raw["students"]["columns"]
    if "columns" in changes:
        raw["students"]["columns"] = changes["columns"]
    if "rename_table" in changes:
        raw[changes["rename_table"]] = raw.pop("students")
    return raw, cols


@pytest.mark.parametrize(
    "columns, reason",
    [
        ([{"name": "name", "type": "TEXT"}, {"name": "id", "type": "INT"}], "id 가 첫 컬럼이 아님"),
        ([{"name": "id", "type": "TEXT"}, {"name": "name", "type": "TEXT"}], "id 가 INT 가 아님"),
        ([{"name": "id", "type": "INT"}], "id 뿐인 테이블"),
        ([{"name": "id", "type": "INT"}, {"name": "name", "type": "FLOAT"}], "지원하지 않는 타입"),
        ([{"name": "id", "type": "INT"}, {"name": "name", "type": "TEXT"}, {"name": "name", "type": "INT"}], "컬럼 중복"),
        ([{"name": "id", "type": "INT"}, {"name": "Name", "type": "TEXT"}], "대문자 컬럼명"),
        ([{"name": "id", "type": "INT"}, {"name": "name"}], "type 누락"),
        ("not a list", "columns 가 목록이 아님"),
    ],
)
def test_invalid_columns_rejected(columns, reason):
    raw, _ = _schema_with(columns=columns)
    with pytest.raises(SchemaError):
        Catalog.from_dict(raw)


def test_uppercase_table_name_rejected():
    raw, _ = _schema_with(rename_table="Students")
    with pytest.raises(SchemaError):
        Catalog.from_dict(raw)


def test_top_level_must_be_object():
    with pytest.raises(SchemaError):
        Catalog.from_dict(["students"])


# --- 파일 수준 오류 --------------------------------------------------------

def test_missing_file(tmp_path):
    with pytest.raises(SchemaError):
        Catalog.load(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    p = tmp_path / "schema.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SchemaError):
        Catalog.load(p)


def test_load_roundtrip_through_file(tmp_path):
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(STUDENTS_SCHEMA), encoding="utf-8")
    assert Catalog.load(p).table("students").column_names == ("id", "name", "grade")
