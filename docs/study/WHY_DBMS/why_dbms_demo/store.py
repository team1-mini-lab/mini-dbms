"""두 가지 저장 방식. 같은 함수 이름, 다른 속.

FileStore  파일 직접: 프로그램이 CSV 파일을 직접 열고, 쉼표로 나누고, 처음부터 읽는다.
DbStore    DBMS: 프로그램은 SQL로 부탁만 한다. 파일 형식, 인덱스, lock, 트랜잭션은 DBMS가 맡는다.
           (미니 DBMS가 아직 없어서 파이썬 내장 SQLite를 DBMS 자리에 둔다.)

시연용이라 일부러 단순하게, 그리고 "그 시절 프로그램"처럼 짰다.
예를 들어 FileStore.revenue()는 "칸이 네 개"라고 가정한 채로 1년 전에 짠 코드다.
"""
import json
import os
import sqlite3
import time

PRODUCTS = ["키보드", "마우스", "모니터", "이어폰", "웹캠"]


def _ms(start):
    return round((time.perf_counter() - start) * 1000, 1)


class FileStore:
    mode = "file"

    def __init__(self, data_dir):
        self.d = data_dir

    def _p(self, name):
        return os.path.join(self.d, name)

    # ── 처음 상태 만들기 ──────────────────────────────
    def seed(self, rows):
        os.makedirs(self.d, exist_ok=True)
        with open(self._p("members.csv"), "w", encoding="utf-8") as f:     # 회원팀 파일
            f.write("kim,강남구\nlee,마포구\n")
        with open(self._p("shipping.csv"), "w", encoding="utf-8") as f:    # 배송팀이 복사해 둔 파일
            f.write("kim,강남구\nlee,마포구\n")
        with open(self._p("orders.csv"), "w", encoding="utf-8") as f:      # id,user,product,price
            for i in range(1, rows + 1):
                f.write(f"{i},user{i % 5000},{PRODUCTS[i % 5]},{(i % 30 + 1) * 1000}\n")
        self.reset_stock(1)
        for name in ("sales.csv", "payments.csv", "checkout_orders.csv"):
            open(self._p(name), "w").close()
        with open(self._p("stock.json"), "w", encoding="utf-8") as f:
            json.dump({"monitor": 10}, f)

    # ── 장면 ① 주소 ───────────────────────────────────
    def set_address(self, user, address):
        """회원 프로그램: 자기 파일(members.csv)만 고친다. shipping.csv는 모른다."""
        lines = []
        for line in open(self._p("members.csv"), encoding="utf-8"):
            name, addr = line.strip().split(",")
            lines.append(f"{name},{address if name == user else addr}")
        with open(self._p("members.csv"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return {"changed": "members.csv", "address": address}

    def ship(self, user):
        """배송 프로그램: 자기 팀 파일(shipping.csv)에서 주소를 읽는다."""
        for line in open(self._p("shipping.csv"), encoding="utf-8"):
            name, addr = line.strip().split(",")
            if name == user:
                actual = self._member_address(user)
                return {"sent_to": addr, "read_from": "shipping.csv", "actual_address": actual}
        return {"sent_to": None}

    def _member_address(self, user):
        for line in open(self._p("members.csv"), encoding="utf-8"):
            name, addr = line.strip().split(",")
            if name == user:
                return addr

    # ── 장면 ② 형식 ───────────────────────────────────
    def add_coupon_column(self):
        """주문팀: orders.csv의 가격 앞에 쿠폰 칸을 끼워 넣는다."""
        src, tmp = self._p("orders.csv"), self._p("orders.tmp")
        with open(src, encoding="utf-8") as r, open(tmp, "w", encoding="utf-8") as w:
            for line in r:
                cols = line.rstrip("\n").split(",")
                if len(cols) == 4:
                    i, u, p, price = cols
                    w.write(f"{i},{u},{p},500,{price}\n")
                else:                               # 이미 추가됨
                    w.write(line)
        os.replace(tmp, src)
        return {"changed": "orders.csv", "new_format": "id,user,product,coupon,price"}

    def revenue(self):
        """정산 프로그램 (1년 전 작성): 칸이 네 개라고 가정한다."""
        total = 0
        for line in open(self._p("orders.csv"), encoding="utf-8"):
            order_id, user, product, price = line.strip().split(",")   # ← 형식 지식이 코드에
            total += int(price)
        return {"revenue": total}

    # ── 장면 ③ 질문 ───────────────────────────────────
    def query(self, sql):
        raise NotImplementedError("파일 방식에는 질문을 받는 곳이 없습니다. 질문마다 반복문 코드를 새로 짜서 배포해야 합니다.")

    # ── 장면 ④ 검색 ───────────────────────────────────
    def get_order(self, order_id):
        t = time.perf_counter()
        scanned = 0
        for line in open(self._p("orders.csv"), encoding="utf-8"):     # 처음부터 한 줄씩
            scanned += 1
            cols = line.strip().split(",")
            if cols[0] == str(order_id):
                return {"order": cols, "scanned_lines": scanned, "how": "처음부터 한 줄씩 비교", "elapsed_ms": _ms(t)}
        return {"order": None, "scanned_lines": scanned, "how": "처음부터 한 줄씩 비교", "elapsed_ms": _ms(t)}

    def orders_of(self, user):
        t = time.perf_counter()
        n = scanned = 0
        for line in open(self._p("orders.csv"), encoding="utf-8"):
            scanned += 1
            if line.split(",")[1] == user:
                n += 1
        return {"count": n, "scanned_lines": scanned, "how": "처음부터 끝까지 비교", "elapsed_ms": _ms(t)}

    # ── 장면 ⑤ 동시에 쓰기 ────────────────────────────
    def reset_stock(self, count):
        with open(self._p("stock.txt"), "w") as f:
            f.write(str(count))
        open(self._p("sales.csv"), "w").close()
        return {"stock": count}

    def buy(self, user, delay):
        """주문 프로그램: 재고 읽기 → (판단하는 사이) → 쓰기. 순서를 정해 주는 사람이 없다."""
        n = int(open(self._p("stock.txt")).read().strip() or 0)    # 읽기
        time.sleep(delay)                                         # 판단하는 시간 (결제 확인 등)
        if n <= 0:
            return {"ok": False, "user": user, "saw_stock": n}
        with open(self._p("stock.txt"), "w") as f:                # 쓰기
            f.write(str(n - 1))
        with open(self._p("sales.csv"), "a", encoding="utf-8") as f:
            f.write(f"{user},키보드\n")
        return {"ok": True, "user": user, "saw_stock": n}

    def stock_status(self):
        stock = open(self._p("stock.txt")).read().strip()
        sold = sum(1 for _ in open(self._p("sales.csv"), encoding="utf-8"))
        return {"stock_file": stock, "sold": sold, "initial_stock": 1}

    # ── 장면 ⑥ 중간에 꺼짐 ────────────────────────────
    def checkout(self, crash):
        """주문 처리 = 파일 세 개 수정. crash면 ②를 쓰는 도중에 프로세스가 죽는다."""
        with open(self._p("payments.csv"), "a") as f:            # ① 결제 기록
            f.write("paid\n")
        stock = json.load(open(self._p("stock.json"), encoding="utf-8"))
        stock["monitor"] -= 1
        text = json.dumps(stock)
        f = open(self._p("stock.json"), "w", encoding="utf-8")    # ② 재고 (파일을 비우고 다시 씀)
        if crash:
            f.write(text[: len(text) // 2])                       # 반쯤 쓴 순간
            f.flush()
            os._exit(1)                                           # 전원이 나감
        f.write(text)
        f.close()
        with open(self._p("checkout_orders.csv"), "a") as f:     # ③ 주문 기록
            f.write("order\n")
        return {"ok": True}

    def consistency(self):
        pay = sum(1 for _ in open(self._p("payments.csv")))
        orders = sum(1 for _ in open(self._p("checkout_orders.csv")))
        raw = open(self._p("stock.json"), encoding="utf-8").read()
        try:
            stock = json.loads(raw)["monitor"]
        except Exception:
            stock = f"읽을 수 없음 (내용: {raw!r})"
        return {"payments": pay, "orders": orders, "monitor_stock": stock}


class DbStore:
    mode = "dbms"

    def __init__(self, data_dir):
        self.d = data_dir
        self.path = os.path.join(data_dir, "jungle.db")

    def _c(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)   # 트랜잭션은 직접 BEGIN
        return c

    def seed(self, rows):
        os.makedirs(self.d, exist_ok=True)
        if os.path.exists(self.path):
            os.remove(self.path)
        c = self._c()
        c.executescript("""
            CREATE TABLE members (name TEXT PRIMARY KEY, address TEXT);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, user TEXT, product TEXT, price INTEGER);
            CREATE TABLE stock (product TEXT PRIMARY KEY, count INTEGER CHECK (count >= 0));
            CREATE TABLE sales (user TEXT, product TEXT);
            CREATE TABLE payments (id INTEGER PRIMARY KEY);
            CREATE TABLE checkout_orders (id INTEGER PRIMARY KEY);
            INSERT INTO members VALUES ('kim', '강남구'), ('lee', '마포구');
            INSERT INTO stock VALUES ('키보드', 1), ('monitor', 10);
        """)
        c.execute("BEGIN")
        c.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)",
                      ((i, f"user{i % 5000}", PRODUCTS[i % 5], (i % 30 + 1) * 1000) for i in range(1, rows + 1)))
        c.execute("COMMIT")
        c.close()

    def set_address(self, user, address):
        c = self._c()
        c.execute("UPDATE members SET address = ? WHERE name = ?", (address, user))
        return {"sql": "UPDATE members SET address = ? WHERE name = ?", "address": address}

    def ship(self, user):
        """배송 프로그램: 주소를 따로 복사해 두지 않고 회원 테이블에서 조회한다."""
        row = self._c().execute("SELECT address FROM members WHERE name = ?", (user,)).fetchone()
        return {"sent_to": row[0] if row else None, "read_from": "members 테이블", "actual_address": row[0] if row else None}

    def add_coupon_column(self):
        c = self._c()
        cols = [r[1] for r in c.execute("PRAGMA table_info(orders)")]
        if "coupon" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN coupon INTEGER DEFAULT 500")
        return {"sql": "ALTER TABLE orders ADD COLUMN coupon INTEGER"}

    def revenue(self):
        """정산 프로그램: 칸 번호가 아니라 이름(price)으로 요청한다."""
        return {"revenue": self._c().execute("SELECT SUM(price) FROM orders").fetchone()[0],
                "sql": "SELECT SUM(price) FROM orders"}

    def query(self, sql):
        if not sql.lstrip().lower().startswith("select"):
            raise ValueError("시연에서는 SELECT만 받습니다")
        c = self._c()
        cur = c.execute(sql)
        return {"columns": [d[0] for d in cur.description], "rows": cur.fetchmany(20)}

    def _plan(self, c, sql, args):
        return " / ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args))

    def get_order(self, order_id):
        c = self._c()
        sql = "SELECT * FROM orders WHERE id = ?"
        t = time.perf_counter()
        row = c.execute(sql, (order_id,)).fetchone()
        return {"order": list(row) if row else None, "how": self._plan(c, sql, (order_id,)), "elapsed_ms": _ms(t)}

    def orders_of(self, user):
        c = self._c()
        sql = "SELECT COUNT(*) FROM orders WHERE user = ?"
        t = time.perf_counter()
        n = c.execute(sql, (user,)).fetchone()[0]
        return {"count": n, "how": self._plan(c, sql, (user,)), "elapsed_ms": _ms(t)}

    def reset_stock(self, count):
        c = self._c()
        c.execute("UPDATE stock SET count = ? WHERE product = '키보드'", (count,))
        c.execute("DELETE FROM sales")
        return {"stock": count}

    def buy(self, user, delay):
        """같은 "읽기 → 판단 → 쓰기"지만 트랜잭션 안에서. BEGIN IMMEDIATE가 쓰기 lock을 잡는다."""
        c = self._c()
        c.execute("BEGIN IMMEDIATE")                     # 다른 쓰기는 여기서 기다림
        n = c.execute("SELECT count FROM stock WHERE product = '키보드'").fetchone()[0]
        time.sleep(delay)
        if n <= 0:
            c.execute("COMMIT")
            return {"ok": False, "user": user, "saw_stock": n}
        c.execute("UPDATE stock SET count = count - 1 WHERE product = '키보드'")
        c.execute("INSERT INTO sales VALUES (?, '키보드')", (user,))
        c.execute("COMMIT")
        return {"ok": True, "user": user, "saw_stock": n}

    def stock_status(self):
        c = self._c()
        return {"stock_file": c.execute("SELECT count FROM stock WHERE product = '키보드'").fetchone()[0],
                "sold": c.execute("SELECT COUNT(*) FROM sales").fetchone()[0], "initial_stock": 1}

    def checkout(self, crash):
        c = self._c()
        c.execute("BEGIN")
        c.execute("INSERT INTO payments DEFAULT VALUES")                             # ① 결제
        c.execute("UPDATE stock SET count = count - 1 WHERE product = 'monitor'")    # ② 재고
        if crash:
            os._exit(1)                                                              # COMMIT 전에 전원이 나감
        c.execute("INSERT INTO checkout_orders DEFAULT VALUES")                      # ③ 주문
        c.execute("COMMIT")
        return {"ok": True}

    def consistency(self):
        c = self._c()
        return {"payments": c.execute("SELECT COUNT(*) FROM payments").fetchone()[0],
                "orders": c.execute("SELECT COUNT(*) FROM checkout_orders").fetchone()[0],
                "monitor_stock": c.execute("SELECT count FROM stock WHERE product = 'monitor'").fetchone()[0]}


def make_store(mode, data_dir):
    return FileStore(data_dir) if mode == "file" else DbStore(data_dir)
