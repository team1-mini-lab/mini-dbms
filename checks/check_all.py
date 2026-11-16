"""모두용: 파서나 인덱스를 바꾼 뒤 '원래 되던 것이 그대로 되는지' 한 번에 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_all.py

임시 폴더에서 돌리므로 data/users.tbl은 건드리지 않습니다.
"지금 통과" 줄이 하나라도 실패로 바뀌면, 내가 바꾼 곳이 기존 동작을 깨뜨린 것입니다.
"나중 단계" 줄은 그 단계가 끝나면 통과해야 합니다.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from engine import Engine  # noqa: E402

tmp = tempfile.mkdtemp()
shutil.copy(os.path.join(ROOT, "data", "schema.json"), tmp)


def run(engine, sql):
    return engine.execute(sql)


now, later = [], []


def check(when, name, ok):
    (now if when == "지금" else later).append(ok)
    label = "통과" if ok else ("실패" if when == "지금" else "아직")
    print(f"{label}  [{when:6}] {name}")


e = Engine(tmp)
r = run(e, "INSERT INTO users (name, age) VALUES ('현지', 25); INSERT INTO users (name, age) VALUES ('민수', 31);")
check("지금", "INSERT 두 번 → id 1, 2", [x.get("id") for x in r] == [1, 2])

r = run(e, "SELECT * FROM users WHERE id = 2;")[0]
check("지금", "WHERE id = 2 → 민수, 인덱스 사용", r.get("rows") == [[2, "민수", 31]] and r.get("used_index") is True)

r = run(e, "SELECT * FROM users WHERE id = 99;")[0]
check("지금", "WHERE id = 99 → 빈 결과", r.get("rows") == [])

r = run(e, "SELECT * FROM users WHERE name = '민수';")[0]
check("지금", "WHERE name = '민수' → 민수만, 처음부터 읽음", r.get("rows") == [[2, "민수", 31]] and r.get("used_index") is False)

r = run(e, "INSERT INTO users (age, name) VALUES (28, '지영');")[0]
r2 = run(e, "SELECT * FROM users WHERE id = 3;")[0]
check("지금", "열 순서를 바꿔 넣어도 schema 순서로 저장", r2.get("rows") == [[3, "지영", 28]])

r = run(e, "INSERT INTO users (name, age) VALUES ('a', 1); INSERT INTO users (email) VALUES ('x'); INSERT INTO users (name, age) VALUES ('b', 2);")
check("지금", "틀린 INSERT가 끼어도 번호가 안 건너뜀 (4, 오류, 5)",
      [x["type"] for x in r] == ["insert", "error", "insert"] and r[0]["id"] == 4 and r[2]["id"] == 5)

for sql, name in [("SELECT * FROM users WHERE email = 'x';", "없는 열로 찾기"),
                  ("SELECT * FROM users WHERE id = '2';", "id를 글자로 찾기"),
                  ("INSERT INTO users (id, name, age) VALUES (9, 'x', 1);", "id 직접 넣기")]:
    check("지금", f"{name} → 오류", run(e, sql)[0]["type"] == "error")

# 껐다 켜기: 새 엔진이 파일을 읽어 번호와 인덱스를 다시 만드는지
e = Engine(tmp)
check("지금", "다시 켜도 다음 id가 이어짐 (6)", run(e, "INSERT INTO users (name, age) VALUES ('c', 3);")[0].get("id") == 6)
check("지금", "다시 켜도 인덱스로 id 2를 찾음", run(e, "SELECT * FROM users WHERE id = 2;")[0].get("rows") == [[2, "민수", 31]])

# 나중 단계
r = run(e, "INSERT INTO users (name, age) VALUES ('a;b', 1);")
check("4단계", "글자 안의 ; → 문장 하나로 저장", len(r) == 1 and r[0]["type"] == "insert")
r = run(e, "INSERT INTO users (name, age) VALUES ('김,철수', 1);")
check("4단계", "글자 안의 쉼표 → 그대로 저장", r[0]["type"] == "insert")
r = run(e, "SELECT name FROM users WHERE id = 2;")[0]
check("6단계", "SELECT name → 이름 열만", r.get("rows") == [["민수"]])
r = run(e, "INSERT INTO users (name, age) VALUES ('d', 'abc');")[0]
check("6단계", "숫자 열에 글자 → 오류", r["type"] == "error")

shutil.rmtree(tmp)
print(f"\n지금 통과해야 하는 것: {sum(now)}/{len(now)}   나중 단계: {sum(later)}/{len(later)}")
