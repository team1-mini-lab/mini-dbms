"""B+ 트리(index.BPlusTree) 전용 확인. 담당: 소망

사용법 (저장소 맨 위 폴더에서):
    python3 checks/check_bptree.py

check_index.py가 보는 접점 3(insert/search)에 더해 아래를 본다.
- range_search(start, end): 양 끝 포함, (id, 파일 위치) 목록, id 오름차순
- 트리 모양: 모든 리프가 같은 깊이, 키 수 <= max_keys, 표지판 키 범위, 부모 포인터
- 차수(max_keys) 3, 4, 5, 32에서 모두 같은 결과
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from index import BPlusTree  # noqa: E402

results = []


def check(name, ok):
    results.append(ok)
    print(("통과  " if ok else "실패  ") + name)


def shape_ok(tree):
    depths = set()

    def walk(node, depth, lo, hi):
        if len(node.keys) > tree.max_keys or node.keys != sorted(node.keys):
            return False
        if any((lo is not None and k < lo) or (hi is not None and k >= hi) for k in node.keys):
            return False
        if node.is_leaf:
            depths.add(depth)
            return True
        if len(node.children) != len(node.keys) + 1:
            return False
        bounds = [lo] + node.keys + [hi]
        return all(c.parent is node and walk(c, depth + 1, bounds[i], bounds[i + 1])
                   for i, c in enumerate(node.children))

    return walk(tree.root, 1, None, None) and len(depths) == 1


# 1. 손으로 따라가는 예: 키 최대 3개, 10·20·30·40을 넣으면 30이 위로 올라가고 리프에도 남음
t = BPlusTree(max_keys=3)
for k in (10, 20, 30, 40):
    t.insert(k, k * 10)
check("10,20,30,40 → 루트 [30], 리프 [10,20] [30,40]",
      t.root.keys == [30] and [c.keys for c in t.root.children] == [[10, 20], [30, 40]])

# 2. 범위 조회 기본
t = BPlusTree(max_keys=3)
for k in range(1, 101):
    t.insert(k, k * 18)
check("range_search(10, 13) = 10~13 (양 끝 포함)",
      t.range_search(10, 13) == [(k, k * 18) for k in range(10, 14)])
check("range_search(50, 50) = 한 건", t.range_search(50, 50) == [(50, 900)])
check("start > end면 빈 목록", t.range_search(20, 10) == [])
check("범위 밖(200~300)은 빈 목록", t.range_search(200, 300) == [])
check("범위가 끝을 넘어도(95~1000) 있는 것만", t.range_search(95, 1000) == [(k, k * 18) for k in range(95, 101)])
check("빈 트리의 range_search는 빈 목록", BPlusTree().range_search(1, 10) == [])

# 3. 무작위: 차수마다 dict 정답과 비교
random.seed(7)
for m in (3, 4, 5, 32):
    t, ref = BPlusTree(max_keys=m), {}
    for _ in range(5000):
        k, v = random.randint(1, 8000), random.randint(0, 10 ** 6)
        t.insert(k, v)
        ref[k] = v
    keys = sorted(ref)
    ok = shape_ok(t) and all(t.search(k) == ref[k] for k in keys)
    for _ in range(100):
        a, b = sorted(random.sample(range(0, 8100), 2))
        ok = ok and t.range_search(a, b) == [(k, ref[k]) for k in keys if a <= k <= b]
    check(f"max_keys={m}: 무작위 5000번 넣기 후 모양·search·range_search 모두 맞음 (높이 {t.height()})", ok)

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
