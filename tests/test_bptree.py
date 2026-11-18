"""7단계: B+ 트리 단독 테스트.

somang 브랜치의 checks/check_bptree.py 와 checks/check_index.py 를 pytest 로 옮겼다.
검사 내용(손으로 따라가는 예, 범위 조회 경계, 트리 모양 불변식, dict 와의 무작위 비교)은 그대로다.
"""

import random

import pytest

from minidb.bptree import BPlusTree


def shape_ok(tree: BPlusTree) -> bool:
    """모든 리프가 같은 깊이, 키 수 <= max_keys, 키 정렬, 표지판 키 범위, 부모 포인터."""
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


# --- 생성 --------------------------------------------------------------------

def test_max_keys_must_be_at_least_three():
    with pytest.raises(ValueError):
        BPlusTree(max_keys=2)


def test_empty_tree():
    t = BPlusTree()
    assert t.search(1) is None
    assert t.range_search(1, 10) == []
    assert t.height() == 1


# --- 분할 규칙: 손으로 따라가는 예 ----------------------------------------------

def test_leaf_split_copies_right_first_key_up():
    # 키 최대 3개, 10·20·30·40 을 넣으면 30 이 위로 올라가고 리프에도 남는다.
    t = BPlusTree(max_keys=3)
    for k in (10, 20, 30, 40):
        t.insert(k, k * 10)
    assert t.root.keys == [30]
    assert [c.keys for c in t.root.children] == [[10, 20], [30, 40]]
    assert t.root.children[0].next_leaf is t.root.children[1]
    assert t.height() == 2


# --- 인터페이스 (실행기가 기대하는 것) -------------------------------------------

def test_sequential_insert_and_search():
    # 실행기가 실제로 넣는 방식: id 1, 2, 3 ... 늘어나는 순서
    t = BPlusTree()
    for k in range(1, 10001):
        t.insert(k, k * 18)
    assert all(t.search(k) == k * 18 for k in range(1, 10001))
    assert t.search(0) is None and t.search(10001) is None


def test_random_order_insert_and_search():
    keys = list(range(1, 10001))
    random.Random(1).shuffle(keys)
    t = BPlusTree()
    for k in keys:
        t.insert(k, k + 1000)
    assert all(t.search(k) == k + 1000 for k in range(1, 10001))


def test_duplicate_key_overwrites():
    t = BPlusTree()
    t.insert(5, 100)
    t.insert(5, 200)
    assert t.search(5) == 200


def test_value_zero_is_not_none():
    # 첫 행의 오프셋은 0 이다. 0 과 '없음' 을 헷갈리면 첫 행을 못 찾는다.
    t = BPlusTree()
    t.insert(1, 0)
    assert t.search(1) == 0


# --- 범위 조회 ----------------------------------------------------------------

@pytest.fixture
def hundred():
    t = BPlusTree(max_keys=3)
    for k in range(1, 101):
        t.insert(k, k * 18)
    return t


def test_range_inclusive(hundred):
    assert hundred.range_search(10, 13) == [(k, k * 18) for k in range(10, 14)]


def test_range_single(hundred):
    assert hundred.range_search(50, 50) == [(50, 900)]


def test_range_start_after_end(hundred):
    assert hundred.range_search(20, 10) == []


def test_range_outside(hundred):
    assert hundred.range_search(200, 300) == []


def test_range_past_end(hundred):
    assert hundred.range_search(95, 1000) == [(k, k * 18) for k in range(95, 101)]


# --- 무작위: 차수마다 dict 정답과 비교 ------------------------------------------

@pytest.mark.parametrize("max_keys", [3, 4, 5, 32])
def test_random_against_dict(max_keys):
    rng = random.Random(7)
    t, ref = BPlusTree(max_keys=max_keys), {}
    for _ in range(5000):
        k, v = rng.randint(1, 8000), rng.randint(0, 10**6)
        t.insert(k, v)
        ref[k] = v
    keys = sorted(ref)

    assert shape_ok(t)
    assert all(t.search(k) == ref[k] for k in keys)
    for _ in range(100):
        a, b = sorted(rng.sample(range(0, 8100), 2))
        assert t.range_search(a, b) == [(k, ref[k]) for k in keys if a <= k <= b]
