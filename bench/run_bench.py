"""10단계: id로 찾기(B+ 트리)와 name으로 찾기(전체 스캔)의 시간을 비교한다. (원작성: somang)

사용법 (저장소 맨 위 폴더에서):
    python bench/run_bench.py                    # 1만, 10만, 100만 건
    python bench/run_bench.py 10000 100000       # 원하는 건수만

건수마다 임시 폴더를 만들고 다음 순서로 잰다. data/ 는 건드리지 않는다.
  1. make_sql.py로 INSERT SQL 파일을 만들고, `python -m minidb`(SQL 처리기 CLI)로 넣는다
  2. 실행기를 새로 만들고 첫 조회를 한다 (이때 파일을 읽어 B+ 트리를 다시 만듦)
  3. 무작위 id 여러 개로 같은 줄을 두 방식으로 찾아 한 번 평균 시간을 잰다
     - SELECT * FROM users WHERE id = i           -> used_index True
     - SELECT * FROM users WHERE name = 'user{i}' -> used_index False
  4. 마지막 1,000줄을 범위로 찾는다: WHERE id > n-1000 을 B+ 트리(range_search)와 전체 스캔(use_index=False)으로
시간은 time.perf_counter()로 잰다. 결과는 파싱 + 실행 전체 기준이다.

somang 원본과 다른 점: Engine 대신 minidb 의 Catalog / Storage / Executor 를 직접 만들고,
cli.py 대신 `python -m minidb --data-dir` 로 넣는다. 측정 방식과 출력 표는 같다.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_sql import make  # noqa: E402

from minidb.catalog import Catalog  # noqa: E402
from minidb.executor import Executor  # noqa: E402
from minidb.parser import parse  # noqa: E402
from minidb.storage import Storage  # noqa: E402

# 벤치마크 전용 테이블. data/schema.json 의 students 와 섞이지 않도록 임시 폴더에만 쓴다.
USERS_SCHEMA = {
    "users": {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "name", "type": "TEXT"},
            {"name": "age", "type": "INT"},
        ]
    }
}


def run_sql(executor, sql, use_index=True):
    (stmt,) = parse(sql)
    return executor.execute(stmt, use_index=use_index)


def avg_ms(executor, sql_list, use_index=True):
    start = time.perf_counter()
    for sql in sql_list:
        run_sql(executor, sql, use_index)
    return (time.perf_counter() - start) / len(sql_list) * 1000


def bench(n, samples):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        (data_dir / "schema.json").write_text(json.dumps(USERS_SCHEMA), encoding="utf-8")
        sql_path = Path(tmp) / "users.sql"
        make(n, sql_path)

        t = time.perf_counter()
        subprocess.run([sys.executable, "-m", "minidb", str(sql_path), "--data-dir", str(data_dir)],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        load_s = time.perf_counter() - t

        catalog = Catalog.load(data_dir / "schema.json")
        with Storage(data_dir, catalog) as storage:
            executor = Executor(catalog, storage)

            # 새 실행기의 첫 조회 = 파일 전체를 읽어 트리를 다시 만드는 시간 + 조회 한 번
            t = time.perf_counter()
            run_sql(executor, "SELECT * FROM users WHERE id = 1;")
            start_s = time.perf_counter() - t
            # 트리 높이는 확인용 정보라 실행기 내부(_load)를 직접 들여다본다.
            height = executor._load(catalog.table("users")).height()

            ids = [random.randint(1, n) for _ in range(samples)]
            # 두 방식이 같은 줄을 찾는지 먼저 확인
            for i in ids[:3]:
                a = run_sql(executor, f"SELECT * FROM users WHERE id = {i};")
                b = run_sql(executor, f"SELECT * FROM users WHERE name = 'user{i}';")
                assert a == b and a.used_index and not b.used_index, (a, b)

            id_ms = avg_ms(executor, [f"SELECT * FROM users WHERE id = {i};" for i in ids])
            name_ms = avg_ms(executor, [f"SELECT * FROM users WHERE name = 'user{i}';"
                                        for i in ids[:max(3, samples // 10)]])

            # 범위: 마지막 1,000줄. 같은 SQL을 B+ 트리와 전체 스캔으로 찾아 결과가 같은지 확인한 뒤 잰다
            range_sql = f"SELECT * FROM users WHERE id > {n - 1000};"
            a = run_sql(executor, range_sql)
            b = run_sql(executor, range_sql, use_index=False)
            assert a == b and a.used_index and not b.used_index and len(a.rows) == 1000, (len(a.rows), len(b.rows))
            range_idx_ms = avg_ms(executor, [range_sql] * 10)
            range_scan_ms = avg_ms(executor, [range_sql] * 3, use_index=False)
        return load_s, start_s, height, id_ms, name_ms, range_idx_ms, range_scan_ms


def main():
    sizes = [int(x) for x in sys.argv[1:]] or [10_000, 100_000, 1_000_000]
    print("| 건수 | CLI로 넣기 | 첫 조회(B+ 트리 다시 만들기 포함) | 트리 높이 | id로 찾기 (인덱스) | name으로 찾기 (전체 스캔) | 배 "
          "| id 범위 1,000줄 (인덱스) | 같은 범위 (전체 스캔) | 배 |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in sizes:
        load_s, start_s, h, id_ms, name_ms, r_idx, r_scan = bench(n, samples=100)
        print(f"| {n:,} | {load_s:.1f}초 | {start_s:.2f}초 | {h} | {id_ms:.3f}ms | {name_ms:.1f}ms "
              f"| {name_ms / id_ms:,.0f}배 | {r_idx:.2f}ms | {r_scan:.1f}ms | {r_scan / r_idx:,.0f}배 |", flush=True)


if __name__ == "__main__":
    main()
