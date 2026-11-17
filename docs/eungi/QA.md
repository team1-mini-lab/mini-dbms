# 회의록 보충: 실제 코드(`eungi` 브랜치)와 함께 보는 3가지 핵심 정리

---

## 1. 파서(`INSERT`, `SELECT`)가 엔진과 어떻게 연결되는가

파서(`parser.py`)는 `schema.json`이나 파일을 전혀 보지 않고, **SQL 글자를 `Insert`, `Select`라는 정해진 파이썬 상자에 담아 돌려주기만** 합니다.

실제로 `parser.py` **5~23줄**과 **33~44줄**을 보면 파일이나 스키마를 읽는 코드가 전혀 없고, 문자열을 받아 `Insert(...)`나 `Select(...)` 객체만 만들어 `return`합니다.

```python
# parser.py (5~23줄) — 엔진과 약속한 반환 상자 모양
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
