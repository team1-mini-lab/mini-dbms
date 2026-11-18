"""발표 데모용: 쇼핑몰 상품 테이블(products)에 N건(기본 100만 건)을 만든다.

사용법 (저장소 맨 위 폴더에서, 서버를 켜기 전에):
    python bench/make_products.py              # data/products.tbl 이 비어 있을 때만 만든다
    python bench/make_products.py --reset      # 기존 products 데이터를 지우고 새로 만든다
    python bench/make_products.py --rows 1000 --data-dir /tmp/x --reset

테이블: products (id INT, name TEXT, category TEXT, price INT)  ← data/schema.json
  - id: 1부터 차례로. 실행기가 INSERT 때 붙이는 값(최대 id + 1)과 같다.
  - name: 대부분 "상품_000001" 형식. DEMO_PRODUCTS 의 id 자리에만 데모용 이름이 들어간다.
  - category: CATEGORIES 중 하나
  - price: 1,000 ~ 500,000 사이 정수 (100원 단위)
  - 시드가 고정이라 몇 번을 다시 돌려도 같은 파일이 나온다.

빠르게 만드는 방법 (SQL INSERT 를 한 건씩 실행하지 않는다):
  INSERT 한 건은 해석 → 검증 → 파일 끝에 한 줄 쓰기 + flush → B+ 트리 등록 이다.
  이 중 디스크에 남는 것은 "파일 끝에 쓴 한 줄" 뿐이다. B+ 트리와 다음 id 는 메모리에만 있고,
  엔진을 켤 때 파일을 처음부터 scan 해서 다시 만든다 (executor._load).
  그래서 이 스크립트는 그 한 줄을 만드는 함수(storage.encode_row)를 그대로 불러
  줄들을 한 번에 이어 쓴다. 파일 형식이 INSERT 와 같으므로 B+ 트리도 서버가 켤 때 똑같이 만들어진다.
  확인: 본 작업 전에 앞쪽 일부 행(데모 이름 포함)을 진짜 INSERT SQL 로도 넣어 보고 두 파일이
  바이트 단위로 같은지 비교한다 (self_check). 다르면 아무것도 쓰지 않고 멈춘다.

안전장치:
  - 임시 파일(products.tbl.tmp)에 다 쓴 뒤 이름을 바꾼다. 중간에 끊겨도 기존 파일은 그대로다.
  - 서버는 B+ 트리를 켤 때 한 번만 만들므로, 서버가 켜져 있는 동안 이 스크립트를 돌리면 안 된다.
    서버를 끄고 → 이 스크립트 → 서버를 켠다.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 저장소 맨 위의 minidb 를 import

from minidb.catalog import Catalog, Table
from minidb.executor import Executor
from minidb.parser import parse
from minidb.storage import Storage, encode_row

TABLE = "products"
EXPECTED_COLUMNS = (("id", "INT"), ("name", "TEXT"), ("category", "TEXT"), ("price", "INT"))
CATEGORIES = ("전자기기", "의류", "식품", "도서", "생활용품", "뷰티", "스포츠", "가구")
SEED = 20261118
PROGRESS_EVERY = 100_000
WRITE_BATCH = 10_000          # 이만큼 줄을 모아서 한 번에 쓴다

# 데모용 상품: {id: (이름, 분류, 가격)}. 데이터 중간(50만 근처)과 뒤쪽(75만~99만)에 섞는다.
# 100만 건보다 적게 만들면 범위 밖의 것은 빠진다.
DEMO_PRODUCTS = {
    500_000: ("에어팟 프로", "전자기기", 359_000),
    500_001: ("갤럭시 버즈", "전자기기", 199_000),
    750_000: ("맥북 에어", "전자기기", 499_000),
    900_000: ("아이패드 미니", "전자기기", 449_000),
    990_000: ("다이슨 에어랩", "생활용품", 499_000),
}


def make_rows(n, demos=DEMO_PRODUCTS, seed=SEED):
    """id 1..n 의 행 튜플을 차례로 내놓는다. (id, name, category, price) — 스키마 순서."""
    rng = random.Random(seed)
    for i in range(1, n + 1):
        # 데모 행이어도 난수는 똑같이 뽑는다. 그래야 데모 목록을 바꿔도 다른 행이 안 바뀐다.
        category = CATEGORIES[rng.randrange(len(CATEGORIES))]
        price = rng.randint(10, 5000) * 100
        if i in demos:
            yield (i, *demos[i])
        else:
            yield (i, f"상품_{i:06d}", category, price)


def check_schema(catalog):
    table = catalog.table(TABLE)   # 없으면 TableNotFoundError
    got = tuple((c.name, c.type) for c in table.columns)
    if got != EXPECTED_COLUMNS:
        sys.exit(f"data/schema.json 의 {TABLE} 컬럼이 예상과 다릅니다: {got}")
    return table


def write_bulk(path: Path, table: Table, rows, total, progress=True):
    """행들을 encode_row 로 줄로 만들어 path 에 이어 쓴다."""
    started = time.perf_counter()
    batch = []
    with open(path, "wb") as f:
        for row in rows:
            batch.append(encode_row(table, row))
            row_id = row[0]
            if len(batch) >= WRITE_BATCH:
                f.write(b"".join(batch))
                batch.clear()
            if progress and row_id % PROGRESS_EVERY == 0:
                print(f"  {row_id:>9,} / {total:,} 건  ({time.perf_counter() - started:.1f}초)", flush=True)
        f.write(b"".join(batch))
        f.flush()
        os.fsync(f.fileno())


def _sql_text(value):
    return "'" + value.replace("'", "''") + "'" if isinstance(value, str) else str(value)


def self_check(catalog, table, n=2000):
    """앞쪽 n건을 (1) 이 스크립트 방식과 (2) 진짜 INSERT SQL 로 각각 만들어 파일이 같은지 본다.

    데모 이름(공백이 있는 한글)도 확인하도록, 데모 상품들을 앞쪽 id 에 옮겨 놓고 비교한다.
    """
    demos = {10 + k: v for k, v in enumerate(DEMO_PRODUCTS.values())}
    rows = list(make_rows(n, demos))
    with tempfile.TemporaryDirectory() as tmp:
        bulk_path = Path(tmp) / "bulk.tbl"
        write_bulk(bulk_path, table, rows, n, progress=False)

        sql_dir = Path(tmp) / "sql"
        with Storage(sql_dir, catalog) as storage:
            executor = Executor(catalog, storage)
            for row_id, name, category, price in rows:
                sql = (f"INSERT INTO {TABLE} (name, category, price) "
                       f"VALUES ({_sql_text(name)}, {_sql_text(category)}, {price});")
                result = executor.execute(parse(sql)[0])
                if result.rows[0][0] != row_id:
                    sys.exit(f"자체 확인 실패: INSERT 가 id {result.rows[0][0]} 를 줬는데 기대는 {row_id}")
        if bulk_path.read_bytes() != (sql_dir / f"{TABLE}.tbl").read_bytes():
            sys.exit("자체 확인 실패: 일괄 쓰기 결과가 INSERT 결과와 바이트 단위로 다릅니다. 아무것도 쓰지 않았습니다.")
    print(f"자체 확인: 앞쪽 {n:,}건을 INSERT SQL 로 넣은 파일과 바이트 단위로 같습니다")


def main(argv=None):
    parser = argparse.ArgumentParser(description="products 테이블 데모 데이터 생성 (서버를 켜기 전에 실행)")
    parser.add_argument("--rows", type=int, default=1_000_000, help="만들 행 수 (기본 1,000,000)")
    parser.add_argument("--data-dir", default="data", help="schema.json 이 있는 폴더 (기본 data)")
    parser.add_argument("--reset", action="store_true", help="기존 products 데이터를 지우고 새로 만든다")
    args = parser.parse_args(argv)
    if args.rows < 1:
        sys.exit("--rows 는 1 이상이어야 합니다")

    data_dir = Path(args.data_dir)
    catalog = Catalog.load(data_dir / "schema.json")
    table = check_schema(catalog)
    path = data_dir / f"{TABLE}.tbl"
    if path.exists() and path.stat().st_size > 0 and not args.reset:
        sys.exit(f"{path} 에 이미 데이터가 있습니다. 지우고 새로 만들려면 --reset 을 붙이세요.")

    self_check(catalog, table)

    print(f"{path} 에 {args.rows:,}건을 만듭니다")
    started = time.perf_counter()
    tmp_path = path.with_name(path.name + ".tmp")
    write_bulk(tmp_path, table, make_rows(args.rows), args.rows)
    os.replace(tmp_path, path)   # 다 쓴 뒤에 한 번에 바꾼다 (--reset 이면 여기서 기존 데이터가 사라짐)
    elapsed = time.perf_counter() - started

    print(f"완료: {args.rows:,}건, {path.stat().st_size / 1024 / 1024:.1f} MB, {elapsed:.1f}초")
    demos = [(i, v[0]) for i, v in sorted(DEMO_PRODUCTS.items()) if i <= args.rows]
    if demos:
        print("데모용 상품:")
        for i, name in demos:
            print(f"  id {i:>9,}  {name}")


if __name__ == "__main__":
    main()
