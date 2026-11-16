import re
from dataclasses import dataclass


@dataclass
class Where:
    column: str
    op: str
    value: object


@dataclass
class Insert:
    table: str
    columns: list
    values: list


@dataclass
class Select:
    table: str
    columns: list
    where: object


def _value(text):
    text = text.strip()
    if text.startswith("'"):
        return text.strip("'")
    return int(text)


def parse(stmt):
    """1단계 임시 파서: 예제 SQL만 처리한다. 4~5단계에서 진짜 토크나이저/파서로 바꾼다."""
    m = re.match(r"INSERT\s+INTO\s+(\w+)\s*(?:\((.*?)\))?\s*VALUES\s*\((.*)\)\s*$", stmt, re.I | re.S)
    if m:
        columns = [c.strip() for c in m.group(2).split(",")] if m.group(2) else None
        values = [_value(v) for v in m.group(3).split(",")]
        return Insert(m.group(1), columns, values)
    m = re.match(r"SELECT\s+\*\s+FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*(\S+))?\s*$", stmt, re.I | re.S)
    if m:
        where = Where(m.group(2), "=", _value(m.group(3))) if m.group(2) else None
        return Select(m.group(1), ["*"], where)
    raise ValueError(f"아직 처리할 수 없는 SQL입니다: {stmt}")
