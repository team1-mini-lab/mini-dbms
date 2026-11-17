"""실행기: 파서의 문장 객체를 받아 카탈로그로 뜻을 확정하고 저장소에 동작을 시킨다.

카탈로그와 저장소를 둘 다 아는 유일한 층이다. 하는 일은 셋이다.
  - 해석: columns=None 을 실제 컬럼으로, 사용자가 쓴 컬럼 순서를 스키마 순서로.
  - 검증: 테이블과 컬럼이 있는가, 타입이 맞는가.
  - 절차: 어떤 순서로 저장소를 부를까.

실행기는 SQL 문자열도, 파일 포맷도 모른다.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass

from minidb.ast import Condition, Insert, Literal, Select, Statement
from minidb.catalog import ID_COLUMN, INT, TEXT, Catalog, Column, Table
from minidb.errors import ExecutionError, TypeMismatchError
from minidb.storage import Row, Storage


@dataclass(frozen=True)
class QueryResult:
    """모든 문장의 결과. SELECT 는 요청한 컬럼과 행, INSERT 는 ("id",) 와 부여된 id 한 행."""

    columns: tuple[str, ...]
    rows: tuple[Row, ...]

    @property
    def rowcount(self) -> int:
        return len(self.rows)


_OPERATORS: dict[str, Callable[[object, object], bool]] = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _literal_matches(col: Column, value: Literal) -> bool:
    """파서가 넘긴 리터럴(int 또는 str)이 컬럼 타입에 맞는가."""
    if col.type == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if col.type == TEXT:
        return isinstance(value, str)
    return False


def _type_name(value: Literal) -> str:
    return "숫자" if isinstance(value, int) else "문자열"


class Executor:
    def __init__(self, catalog: Catalog, storage: Storage):
        self.catalog = catalog
        self.storage = storage
        # 테이블별 다음 id. 테이블을 처음 사용할 때 한 번 scan 해서 채운다.
        self._next_ids: dict[str, int] = {}

    # --- 진입점 -------------------------------------------------------------

    def execute(self, stmt: Statement) -> QueryResult:
        if isinstance(stmt, Insert):
            return self._execute_insert(stmt)
        if isinstance(stmt, Select):
            return self._execute_select(stmt)
        raise ExecutionError(f"알 수 없는 문장: {type(stmt).__name__}")  # 파서가 막는다

    # --- INSERT -------------------------------------------------------------

    def _execute_insert(self, stmt: Insert) -> QueryResult:
        table = self.catalog.table(stmt.table)
        user_values = self._resolve_insert_values(table, stmt)  # 검증은 여기서 전부 끝난다

        new_id = self._next_id(table)
        row: Row = (new_id, *user_values)  # 스키마 순서. 사용자가 쓴 순서는 사라진다.
        self.storage.table(table.name).append(row)
        return QueryResult(columns=(ID_COLUMN,), rows=((new_id,),))

    def _resolve_insert_values(self, table: Table, stmt: Insert) -> tuple[Literal, ...]:
        """사용자가 준 (컬럼, 값) 을 검증하고, id 를 뺀 스키마 순서의 값 튜플로 만든다."""
        if stmt.columns is None:
            columns = table.user_columns
            if len(stmt.values) != len(columns):
                raise ExecutionError(
                    f"테이블 '{table.name}' 은 값이 {len(columns)}개 필요한데 "
                    f"{len(stmt.values)}개가 왔습니다"
                )
        else:
            columns = tuple(table.column(name) for name in stmt.columns)  # ColumnNotFoundError
            if ID_COLUMN in stmt.columns:
                raise ExecutionError(f"'{ID_COLUMN}' 는 자동으로 부여되므로 지정할 수 없습니다")
            # 파서가 길이와 중복은 이미 확인했다.

        given = dict(zip(columns, stmt.values))

        for col, value in given.items():
            if not _literal_matches(col, value):
                raise TypeMismatchError(
                    f"컬럼 '{col.name}' 은 {col.type} 인데 {_type_name(value)} {value!r} 가 왔습니다"
                )

        # NULL 이 없으므로 모든 사용자 컬럼에 값이 있어야 한다.
        missing = [c.name for c in table.user_columns if c not in given]
        if missing:
            raise ExecutionError(f"컬럼 {', '.join(repr(m) for m in missing)} 의 값이 없습니다")

        return tuple(given[c] for c in table.user_columns)

    def _next_id(self, table: Table) -> int:
        """테이블을 처음 건드릴 때 한 번 scan 해 최대 id 를 찾고, 이후에는 카운터만 올린다."""
        if table.name not in self._next_ids:
            max_id = 0
            for _offset, row in self.storage.table(table.name).scan():
                max_id = max(max_id, int(row[0]))
            self._next_ids[table.name] = max_id + 1
        new_id = self._next_ids[table.name]
        self._next_ids[table.name] = new_id + 1
        return new_id

    # --- SELECT -------------------------------------------------------------

    def _execute_select(self, stmt: Select) -> QueryResult:
        table = self.catalog.table(stmt.table)

        if stmt.columns is None:
            out_names = table.column_names
        else:
            for name in stmt.columns:
                table.column(name)  # ColumnNotFoundError
            out_names = stmt.columns
        out_indexes = [table.column_index(n) for n in out_names]

        predicate = self._make_predicate(table, stmt.where)

        # 전체 스캔. 9단계에서 "조건이 id = ? 이면 인덱스로 read_at" 이 이 자리에 들어간다.
        rows: list[Row] = []
        for _offset, row in self.storage.table(table.name).scan():
            if predicate(row):
                rows.append(tuple(row[i] for i in out_indexes))

        return QueryResult(columns=tuple(out_names), rows=tuple(rows))

    def _make_predicate(self, table: Table, cond: Condition | None) -> Callable[[Row], bool]:
        """조건을 검증하고 '행을 받아 참/거짓을 돌려주는 함수' 를 만든다."""
        if cond is None:
            return lambda row: True

        col = table.column(cond.column)  # ColumnNotFoundError
        if not _literal_matches(col, cond.value):
            raise TypeMismatchError(
                f"컬럼 '{col.name}' 은 {col.type} 인데 {_type_name(cond.value)} "
                f"{cond.value!r} 와 비교했습니다"
            )
        index = table.column_index(cond.column)
        compare = _OPERATORS[cond.op]  # 파서가 여섯 개만 넘긴다
        value = cond.value
        return lambda row: compare(row[index], value)
