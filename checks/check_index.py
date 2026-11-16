"""Phase 2용: 인덱스 클래스가 접점 3(제안)을 지키는지 확인한다.

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_index.py                     # 지금 dict 인덱스 확인
    python3 checks/check_index.py bptree BPlusTree    # 내가 만든 B+ 트리 확인

엔진을 몰라도 됩니다. 여기서 전부 통과하면 engine.py의 두 줄만 바꿔 끼우면 됩니다.
"""
import importlib
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

module_name = sys.argv[1] if len(sys.argv) > 1 else "index"
class_name = sys.argv[2] if len(sys.argv) > 2 else "DictIndex"
Index = getattr(importlib.import_module(module_name), class_name)
print(f"확인하는 클래스: {module_name}.{class_name}\n")

results = []


def check(name, ok):
    results.append(ok)
    print(("통과  " if ok else "실패  ") + name)


# 1. 비어 있을 때
idx = Index()
check("빈 인덱스에서 search(1)은 None", idx.search(1) is None)

# 2. 엔진이 실제로 넣는 방식: 1, 2, 3 ... 늘어나는 순서
idx = Index()
for k in range(1, 10001):
    idx.insert(k, k * 18)            # 값 = 파일 위치(바이트)
check("1~10000을 순서대로 넣고 모두 찾음", all(idx.search(k) == k * 18 for k in range(1, 10001)))
check("없는 키 0, 10001은 None", idx.search(0) is None and idx.search(10001) is None)

# 3. 무작위 순서 (11단계 완료 기준)
idx = Index()
keys = list(range(1, 10001))
random.shuffle(keys)
for k in keys:
    idx.insert(k, k + 1000)
check("1~10000을 무작위 순서로 넣고 모두 찾음", all(idx.search(k) == k + 1000 for k in range(1, 10001)))

# 4. 같은 키를 다시 넣으면 덮어쓰기
idx = Index()
idx.insert(5, 100)
idx.insert(5, 200)
check("같은 키를 다시 넣으면 값을 덮어씀 (5 → 200)", idx.search(5) == 200)

# 5. 값이 0일 때도 None과 구별 (첫 줄의 위치는 0바이트)
idx = Index()
idx.insert(1, 0)
check("값이 0이어도 찾음 (첫 줄 위치는 0)", idx.search(1) == 0)

print(f"\n{sum(results)}/{len(results)} 통과")
if hasattr(idx, "height"):
    big = Index()
    for k in range(1, 10001):
        big.insert(k, k)
    print(f"참고: 키 10000개일 때 트리 높이 = {big.height()}")
