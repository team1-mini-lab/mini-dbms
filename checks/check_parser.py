"""Phase 1용: parse()가 접점 2(제안)의 모양을 돌려주는지 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_parser.py

지금 임시 파서는 일부만 통과합니다. "언제" 열의 단계가 끝나면 통과해야 합니다.
Phase 1(4단계)에서 parse가 글자 대신 단어 목록을 받기로 정했다면, 아래 to_input()만 고치면 됩니다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from parser import Insert, Select, Where, parse  # noqa: E402


def to_input(sql):
    """parse()에 넘길 값. 지금은 SQL 글자 그대로. Phase 1(4단계)에서 바뀌면 여기만 고친다."""
    return sql


CASES = [
    # (언제까지 통과해야 하나, SQL, 기대하는 모양)
    ("지도 만들기(1단계)", "INSERT INTO users (name, age) VALUES ('현지', 25)",
     Insert("users", ["name", "age"], ["현지", 25])),
    ("지도 만들기(1단계)", "INSERT INTO users VALUES ('현지', 25)",
     Insert("users", None, ["현지", 25])),
    ("지도 만들기(1단계)", "SELECT * FROM users",
     Select("users", ["*"], None)),
    ("지도 만들기(1단계)", "SELECT * FROM users WHERE id = 3",
     Select("users", ["*"], Where("id", "=", 3))),
    ("Phase 1(4단계)", "INSERT INTO users (name, age) VALUES ('김,철수', 25)",
     Insert("users", ["name", "age"], ["김,철수", 25])),
    ("Phase 1(4단계)", "INSERT INTO users (name, age) VALUES ('It''s', 25)",
     Insert("users", ["name", "age"], ["It's", 25])),
    ("Phase 1(5단계)", "SELECT name FROM users WHERE id = 3",
     Select("users", ["name"], Where("id", "=", 3))),
    ("Phase 1(5단계)", "SELECT name, age FROM users",
     Select("users", ["name", "age"], None)),
]

ERROR_CASES = [
    ("Phase 1(5단계)", "SELEC * FROM users"),
    ("Phase 1(5단계)", "INSERT INTO users (name, age) VALUES ('a', 1"),
]

print(f"{'결과':4}  {'언제':14}  SQL")
passed = 0
for when, sql, expected in CASES:
    try:
        got = parse(to_input(sql))
        ok = got == expected
    except Exception as e:  # noqa: BLE001
        got, ok = f"오류: {e}", False
    passed += ok
    print(f"{'통과' if ok else '아직':4}  {when:14}  {sql}")
    if not ok:
        print(f"                     기대: {expected}\n                     실제: {got}")

for when, sql in ERROR_CASES:
    try:
        parse(to_input(sql))
        ok = False
    except Exception:  # noqa: BLE001
        ok = True
    passed += ok
    print(f"{'통과' if ok else '아직':4}  {when:14}  {sql}   (오류가 나야 정상)")

print(f"\n{passed}/{len(CASES) + len(ERROR_CASES)} 통과")
