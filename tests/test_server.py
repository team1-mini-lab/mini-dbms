"""Phase 3 서버(server.py) 테스트: 임시 포트에 서버를 띄워 HTTP로 요청하고 응답 번호와 JSON 모양을 확인한다."""
import http.client
import json
import socket
import threading
import time

import pytest

from server import Handler, PooledHTTPServer
from tests.test_engine import make_engine


def start(tmp_path, workers=4, queue_size=16):
    srv = PooledHTTPServer(("localhost", 0), Handler, make_engine(tmp_path), workers, queue_size, request_timeout=2)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server(tmp_path):
    srv = start(tmp_path)
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def call(port, method="POST", path="/query", body=b""):
    c = http.client.HTTPConnection("localhost", port, timeout=5)
    c.request(method, path, body)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, json.loads(data) if data.startswith(b"{") else data


def sql(text):
    return json.dumps({"sql": text}).encode()


def test_query_ok(server):
    st, body = call(server, body=sql("INSERT INTO users (name, age) VALUES ('a', 1); SELECT * FROM users WHERE id = 1;"))
    assert st == 200
    assert body["results"][0] == {"type": "insert", "id": 1}
    assert body["results"][1]["rows"] == [[1, "a", 1]] and body["results"][1]["used_index"] is True


def test_bad_sql_400_keeps_done_results(server):
    st, body = call(server, body=sql("INSERT INTO users (name, age) VALUES ('a', 1); SELECT email FROM users;"))
    assert st == 400 and body["error"]["code"] == "bad_sql"
    assert body["error"]["message"].startswith("2번째 문장") and len(body["results"]) == 1


def test_syntax_error_400_runs_nothing(server):
    st, body = call(server, body=sql("INSERT INTO users (name, age) VALUES ('a', 1); SELEC 1;"))
    assert st == 400 and body["results"] == [] and "1:" in body["error"]["message"]


@pytest.mark.parametrize("body", [b"hello", b"[]", b'{"sql": 1}', b"{}"])
def test_bad_body_400(server, body):
    st, res = call(server, body=body)
    assert st == 400 and res["error"]["code"] == "bad_request"


def test_not_found_and_method(server):
    assert call(server, path="/users", body=sql("SELECT 1;"))[1]["error"]["code"] == "not_found"
    assert call(server, method="GET", path="/query")[1]["error"]["code"] == "method_not_allowed"


def test_health_and_stats(server):
    assert call(server, method="GET", path="/health") == (200, {"status": "ok"})
    call(server, body=sql("SELECT * FROM users;"))
    st, s = call(server, method="GET", path="/stats")
    assert st == 200 and s["workers"] == 4 and s["queue"]["max"] == 16
    assert s["busy"] >= 1 and s["handled"] >= 2 and s["rejected_503"] == 0


def test_full_queue_503_and_counted(tmp_path):
    srv = start(tmp_path, workers=1, queue_size=1)
    port = srv.server_address[1]
    hold = []
    for _ in range(2):                         # 하나씩: 워커가 첫 연결을 꺼내 간 뒤에 둘째가 대기열 1칸을 채우게
        hold.append(socket.create_connection(("localhost", port)))
        time.sleep(0.3)
    st, body = call(port, body=sql("SELECT * FROM users;"))
    assert st == 503 and body["error"]["code"] == "busy"
    for s in hold:
        s.close()
    time.sleep(0.3)
    assert call(port, method="GET", path="/stats")[1]["rejected_503"] >= 1
    srv.shutdown()
    srv.server_close()
