"""Phase 2(14단계): id로 찾기(B+ 트리)와 name으로 찾기(처음부터 읽기)의 시간을 비교한다. 담당: 소망

사용법 (저장소 맨 위 폴더에서):
    python3 bench/run_bench.py                    # 1만, 10만, 100만 건
    python3 bench/run_bench.py 10000 100000       # 원하는 건수만

건수마다 임시 폴더를 만들고 다음 순서로 잰다. data/users.tbl은 건드리지 않는다.
  1. make_sql.py로 INSERT SQL 파일을 만들고, cli.py(SQL 처리기)로 넣는다
  2. Engine을 새로 켠다 (켤 때 파일을 읽어 B+ 트리를 다시 만듦)
  3. 무작위 id 여러 개로 같은 줄을 두 방식으로 찾아 한 번 평균 시간을 잰다
     - SELECT * FROM users WHERE id = i           → used_index True
     - SELECT * FROM users WHERE name = 'user{i}' → used_index False
시간은 time.perf_counter()로 잰다. 결과는 엔진 execute 전체(파싱 포함) 기준이다.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from engine import Engine  # noqa: E402
from make_sql import make  # noqa: E402


def avg_ms(engine, sql_list):
    start = time.perf_counter()
    for sql in sql_list:
        engine.execute(sql)
    return (time.perf_counter() - start) / len(sql_list) * 1000


def bench(n, samples):
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "data"))
        shutil.copy(os.path.join(ROOT, "data", "schema.json"), os.path.join(tmp, "data"))
        sql_path = os.path.join(tmp, "users.sql")
        make(n, sql_path)

        t = time.perf_counter()
        subprocess.run([sys.executable, os.path.join(ROOT, "cli.py"), sql_path],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        load_s = time.perf_counter() - t

        t = time.perf_counter()
        engine = Engine(os.path.join(tmp, "data"))
        start_s = time.perf_counter() - t

        ids = [random.randint(1, n) for _ in range(samples)]
        # 두 방식이 같은 줄을 찾는지 먼저 확인
        for i in ids[:3]:
            a = engine.execute(f"SELECT * FROM users WHERE id = {i};")[0]
            b = engine.execute(f"SELECT * FROM users WHERE name = 'user{i}';")[0]
            assert a["rows"] == b["rows"] and a["used_index"] and not b["used_index"], (a, b)

        id_ms = avg_ms(engine, [f"SELECT * FROM users WHERE id = {i};" for i in ids])
        name_ms = avg_ms(engine, [f"SELECT * FROM users WHERE name = 'user{i}';" for i in ids[:max(3, samples // 10)]])
        return load_s, start_s, engine.index["users"].height(), id_ms, name_ms
    finally:
        shutil.rmtree(tmp)


def main():
    sizes = [int(x) for x in sys.argv[1:]] or [10_000, 100_000, 1_000_000]
    print("| 건수 | CLI로 넣기 | 엔진 켜기(B+ 트리 다시 만들기) | 트리 높이 | id로 찾기 (인덱스) | name으로 찾기 (처음부터) | 배 |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for n in sizes:
        load_s, start_s, h, id_ms, name_ms = bench(n, samples=100)
        print(f"| {n:,} | {load_s:.1f}초 | {start_s:.2f}초 | {h} | {id_ms:.3f}ms | {name_ms:.1f}ms | {name_ms / id_ms:,.0f}배 |",
              flush=True)


if __name__ == "__main__":
    main()
