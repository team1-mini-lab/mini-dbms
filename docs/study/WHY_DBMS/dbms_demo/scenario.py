"""시연: 목적이 다른 프로그램들이 같은 데이터를 쓸 때, 파일 직접 vs DBMS.

WHY_DBMS의 문제 1·2·3을 실제 프로그램(서버) 여러 개로 재현한다.
--all을 붙이면 차별화 후보 A·B·C까지 모두 보여 준다.
같은 프로그램 코드를 역할(회원·주문·배송·정산·마케팅)만 바꿔 띄우고,
저장 방식만 바꿔 끼운 뒤 똑같은 순서로 요청을 보낸다.
    1부  파일 직접   각 프로그램이 CSV 파일을 직접 열고 씀        (84xx 포트)
    2부  DBMS        각 프로그램이 SQL로 DBMS(SQLite)에 부탁함    (85xx 포트)

실행
    python -m dbms_demo.scenario               처음부터 끝까지 자동으로
    python -m dbms_demo.scenario --step        Enter를 누를 때마다 한 단계씩 (발표용)
    python -m dbms_demo.scenario --rows 200000 주문 수를 줄여서 빠르게 (기본 100만)
    python -m dbms_demo.scenario --all         차별화 후보 A·B·C까지 모두

서버는 이 스크립트가 직접 띄우고 끝나면 끈다. 데이터는 임시 폴더에 만든다.
표준 라이브러리만 쓴다.
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request

from dbms_demo.servers import ports, spawn
from dbms_demo.store import make_store

PARTS = [
    {"mode": "file", "title": "1부  파일 직접 (프로그램마다 파일을 직접 열고 씀)"},
    {"mode": "dbms", "title": "2부  DBMS (프로그램은 SQL로 부탁만, 파일은 DBMS만 만짐)"},
]


def call(method, port, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Demo:
    def __init__(self, rows, step, delay, all_scenes=False):
        self.rows, self.step, self.delay, self.all = rows, step, delay, all_scenes
        self.base = tempfile.mkdtemp(prefix="mini-dbms-demo-")
        self.procs = {}

    # ── 서버 ──────────────────────────────────────────
    def _wait(self, port):
        for _ in range(100):
            try:
                if call("GET", port, "/", timeout=0.5)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"{port}번 프로그램이 켜지지 않았습니다")

    def start(self, mode, role):
        port = self.p[role]
        try:
            call("GET", port, "/", timeout=0.3)
            raise RuntimeError(f"{port}번 포트를 이미 다른 프로그램이 쓰고 있습니다")
        except OSError:
            pass
        self.procs[role] = spawn(mode, role, port, self.data, self.delay)
        self._wait(port)

    def stop_all(self):
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
        self.procs = {}

    # ── 화면 ──────────────────────────────────────────
    def say(self, text):
        print(f"\n  {text}")

    def note(self, text):
        print(f"    {text}")

    def show(self, role, line):
        print(f"    {role}({self.p[role]}) · {line}")

    def pause(self):
        if self.step:
            input("    (Enter를 누르면 진행) ")

    # ── 한 부 ─────────────────────────────────────────
    def run_part(self, part):
        mode = part["mode"]
        file = mode == "file"
        self.p = ports(mode)
        self.data = os.path.join(self.base, mode)
        print("\n" + "━" * 70)
        print(f"  {part['title']}")
        print("━" * 70)
        t = time.perf_counter()
        make_store(mode, self.data).seed(self.rows)
        self.note(f"처음 상태: 회원 2명, 주문 {self.rows:,}건, 한정판 키보드 재고 1개 ({time.perf_counter() - t:.1f}초)")
        if file:
            self.note("파일: members.csv(회원팀) · shipping.csv(배송팀 복사본) · orders.csv · stock.txt …")
        else:
            self.note("DBMS: members · orders · stock … 테이블. 파일(jungle.db)은 DBMS만 만짐")
        for role in self.p:
            self.start(mode, role)
        r = {}

        # 문제 1 형식
        self.say("문제 1  정산이 매출을 계산 → 주문팀이 쿠폰 칸 추가 → 정산을 다시 실행")
        self.pause()
        _, v = call("GET", self.p["정산"], "/revenue")
        self.show("정산", f"매출 {v['revenue']:,}원")
        _, c = call("POST", self.p["주문"], "/admin/coupon")
        self.show("주문", f"쿠폰 칸 추가 → {c.get('new_format') or c.get('sql')}")
        code, v2 = call("GET", self.p["정산"], "/revenue")
        if code == 200:
            self.show("정산", f"매출 {v2['revenue']:,}원   (그대로 동작)")
        else:
            self.show("정산", f"{code} {v2['error']}   ← 정산이 멈춤!")
            self.note(f"  멈춘 줄: {v2.get('where')}")
        r["revenue_after"] = "정상" if code == 200 else f"멈춤({code})"
        if file:
            self.note("→ \"칸이 네 개, 넷째 칸이 가격\"이라는 약속이 정산 코드에 따로 적혀 있다")
            self.note("  주문팀이 칸을 바꿀 때마다, 이 파일을 읽는 코드를 모두 같이 고쳐야 한다")
        else:
            self.note("→ 정산은 칸 번호가 아니라 이름(price)으로 요청: SELECT SUM(price) FROM orders")
            self.note("  주문팀이 ALTER TABLE로 칸을 추가해도 정산 코드는 고칠 게 없다")

        # 문제 2 검색
        target = int(self.rows * 0.9)
        self.say(f"문제 2  주문 {self.rows:,}건 중 주문번호 {target:,} 찾기, 그리고 user77의 주문 세기")
        self.pause()
        _, g = call("GET", self.p["주문"], f"/orders/{target}")
        extra = f"{g['scanned_lines']:,}줄 읽음" if "scanned_lines" in g else g["how"]
        self.show("주문", f"주문번호로 찾기 {g['elapsed_ms']:>8.1f}ms · {extra}")
        _, u = call("GET", self.p["주문"], "/orders?user=user77")
        extra = f"{u['scanned_lines']:,}줄 읽음" if "scanned_lines" in u else u["how"]
        self.show("주문", f"user로 세기    {u['elapsed_ms']:>8.1f}ms · {extra}")
        r["by_id"], r["by_user"] = g["elapsed_ms"], u["elapsed_ms"]
        if file:
            self.note("→ 파일은 순서대로 읽는 것밖에 모른다. 뒤쪽 주문일수록 오래 걸림")
        else:
            self.note("→ SEARCH ... INTEGER PRIMARY KEY: id 인덱스(B-트리)로 바로 찾음")
            self.note("  SCAN orders: user에는 인덱스가 없어서 DBMS도 처음부터 훑음 → 인덱스가 핵심")
            self.note("  (파일 방식보다 빠른 건 DBMS가 C로 짜여 있어서. 전부 읽는다는 점은 같다)")

        # 문제 3 동시에 쓰기
        self.say("문제 3  남은 키보드 1개를 kim(주문 프로그램)과 lee(주문2 프로그램)가 동시에 구매")
        self.pause()
        call("POST", self.p["주문"], "/stock/reset", {"count": 1})
        results = {}

        def buy(role, user):
            results[user] = call("POST", self.p[role], "/buy", {"user": user})[1]
        th = [threading.Thread(target=buy, args=("주문", "kim")), threading.Thread(target=buy, args=("주문2", "lee"))]
        t0 = time.perf_counter()
        for t in th:
            t.start()
        for t in th:
            t.join()
        took = (time.perf_counter() - t0) * 1000
        for role, user in (("주문", "kim"), ("주문2", "lee")):
            b = results[user]
            self.show(role, f"{user}: 재고 {b['saw_stock']}개를 보고 → {'구매 성공' if b['ok'] else '품절'}")
        _, st = call("GET", self.p["주문"], "/stock")
        self.note(f"→ 재고 1개였는데 산 사람 {st['sold']}명 (두 요청 처리에 {took:.0f}ms)" + ("   ← 초과 판매!" if st["sold"] > 1 else ""))
        r["sold"] = st["sold"]
        if file:
            self.note("  둘 다 \"1개 남음\"을 읽은 뒤 각자 0을 씀. 순서를 정해 줄 누군가가 없다")
        else:
            self.note("  먼저 온 쪽이 lock을 잡고, 나머지는 기다렸다가 0을 봄 (그래서 시간이 두 배)")

        if self.all:
            # 차별화 A 주소
            self.say("차별화 A  kim이 이사해서 회원 프로그램으로 주소를 송파구로 바꾸고, 키보드를 주문")
            self.pause()
            _, a = call("PUT", self.p["회원"], "/members/kim", {"address": "송파구"})
            self.show("회원", f"주소 변경 → {a.get('changed') or a.get('sql')}")
            _, s = call("POST", self.p["배송"], "/ship", {"user": "kim"})
            wrong = s["sent_to"] != s["actual_address"]
            self.show("배송", f"{s['read_from']}에서 주소를 읽어 {s['sent_to']}로 발송" + ("   ← 옛날 집!" if wrong else ""))
            r["ship"] = s["sent_to"]
            if file:
                self.note("→ 회원 프로그램은 자기 파일만 고침. 배송팀이 복사해 둔 shipping.csv는 강남구 그대로")
                self.note("  (같은 데이터가 여러 파일에 복사되어 있고, 한쪽만 고쳐졌다)")
            else:
                self.note("→ 주소는 members 테이블 한 곳에만. 배송도 그 테이블을 조회하므로 새 주소로")

        if self.all:
            # 차별화 B 질문
            self.say("차별화 B  마케팅이 새 질문: \"가장 많이 팔린 상품 3개는?\"")
            self.pause()
            sql = "SELECT product, COUNT(*) AS n FROM orders GROUP BY product ORDER BY n DESC LIMIT 3"
            code, q = call("POST", self.p["마케팅"], "/query", {"sql": sql})
            if code == 200:
                self.show("마케팅", f"SQL 한 문장 → {q['rows']}")
                self.note("→ 새 코드 없이, 원하는 것만 SQL로 적으면 DBMS가 찾아서 돌려준다")
            else:
                self.show("마케팅", f"{code} {q['error']}")
                self.note("→ 데이터는 있는데 질문을 받을 곳이 없다. 개발자에게 요청하고 기다려야 한다")
            r["query"] = "SQL로 바로" if code == 200 else "코드 새로 짜야 함"

        if self.all:
            # 차별화 C 중간에 꺼짐
            self.say("차별화 C  주문 처리(1 결제 → 2 재고 → 3 주문) 도중, 2번 재고 단계에서 주문 프로그램 전원이 나감")
            self.pause()
            _, before = call("GET", self.p["정산"], "/consistency")
            self.show("정산", f"처리 전: 결제 {before['payments']} · 주문 {before['orders']} · 모니터 재고 {before['monitor_stock']}")
            try:
                call("POST", self.p["주문"], "/checkout?crash=1", timeout=10)
            except (OSError, urllib.error.URLError):
                pass
            self.show("주문", "응답 없음 (프로세스가 죽음)")
            self.procs["주문"].wait(timeout=5)
            self.start(mode, "주문")
            _, after = call("GET", self.p["정산"], "/consistency")
            self.show("정산", f"재시작 후: 결제 {after['payments']} · 주문 {after['orders']} · 모니터 재고 {after['monitor_stock']}")
            r["crash"] = f"결제 {after['payments']} · 주문 {after['orders']}"
            r["crash_stock"] = after["monitor_stock"] if isinstance(after["monitor_stock"], int) else "깨짐"
            if file:
                self.note("→ 결제는 기록됐는데 주문은 없고, 재고 파일은 반만 써져 읽을 수 없다")
                self.note("  (여러 파일의 변경을 \"전부 되거나 전부 안 되거나\"로 묶는 장치가 없다)")
            else:
                self.note("→ COMMIT 전이었으므로 결제·재고 변경이 모두 되돌려짐. 셋 다 없던 일 → 다시 시도하면 됨")

        self.stop_all()
        return r


def _w(t):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(t))


def _l(t, n):
    return str(t) + " " * max(0, n - _w(t))


def summary(f, d, all_scenes=False):
    ms = lambda x: f"{x:,.1f}ms"
    core = [
        ("문제 1  쿠폰 칸 추가 후 정산", f["revenue_after"], d["revenue_after"]),
        ("문제 2  주문번호로 찾기", ms(f["by_id"]), ms(d["by_id"])),
        ("문제 2  user로 세기 (인덱스 없음, 둘 다 전체)", ms(f["by_user"]), ms(d["by_user"])),
        ("문제 3  재고 1개, 산 사람", f"{f['sold']}명", f"{d['sold']}명"),
    ]
    rows = core if not all_scenes else core + [
        ("차별화 A  이사 후 택배가 간 곳", f["ship"], d["ship"]),
        ("차별화 B  마케팅의 새 질문", f["query"], d["query"]),
        ("차별화 C  정전 후 결제·주문", f["crash"], d["crash"]),
        ("차별화 C  정전 후 모니터 재고", f["crash_stock"], d["crash_stock"]),
    ]
    print("\n" + "━" * 70)
    print("  정리: 같은 프로그램, 같은 순서, 데이터 다루는 곳만 다름")
    print("━" * 70)
    print(f"  {_l('', 46)}{_l('파일 직접', 20)}DBMS")
    for label, a, b in rows:
        print(f"  {_l(label, 46)}{_l(a, 20)}{b}")
    print()
    print("  파일 방식은 형식·찾는 법·보호를 각 프로그램이 들고 있어서, 함께 쓰는 순간 어긋나고 깨진다.")
    print("  DBMS는 그 일을 한 곳이 맡아서, 프로그램은 무엇이 필요한지만 말하면 된다.")
    if not all_scenes:
        print("  차별화 후보(A 주소, B 새 질문, C 정전)까지 보려면 --all을 붙이세요.")
    print()


def main():
    ap = argparse.ArgumentParser(description="파일 직접 vs DBMS, 프로그램 여러 개로 비교")
    ap.add_argument("--step", action="store_true", help="Enter를 누를 때마다 한 단계씩")
    ap.add_argument("--rows", type=int, default=1_000_000, help="주문 수 (기본 100만)")
    ap.add_argument("--delay", type=float, default=0.3, help="문제 3에서 읽기와 쓰기 사이 시간(초)")
    ap.add_argument("--all", action="store_true", help="차별화 후보 A·B·C까지 모두")
    a = ap.parse_args()
    demo = Demo(a.rows, a.step, a.delay, a.all)
    print(f"주문 {a.rows:,}건으로 시연합니다. 프로그램(서버)들을 직접 띄웁니다.")
    print("한 줄 읽는 법:  정산(8404) · 매출 15,499,910,000원")
    print("               어느 프로그램이(포트) / 무엇을 했고 / 결과가 어땠나")
    try:
        f = demo.run_part(PARTS[0])
        d = demo.run_part(PARTS[1])
        summary(f, d, a.all)
    except KeyboardInterrupt:
        print("\n중단했습니다.")
    except RuntimeError as e:
        print(f"\n[오류] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        demo.stop_all()


if __name__ == "__main__":
    main()
