# Phase 3 시연 순서 (Render 배포)

`BASE`에 Render 주소를 넣고 순서대로 붙여 넣으면 됩니다. 명령은 **한 줄씩** 붙여 넣으세요 (`-d` 안에서 줄이 바뀌면 400이 납니다).

```bash
BASE=https://mini-dbms-xxxx.onrender.com      # Render 대시보드에 나오는 주소로 바꾸기
```

> Render 무료판은 15분 동안 요청이 없으면 잠듭니다. 시연 1분 전에 아래 0번을 한 번 보내 깨워 두세요. 잠들거나 다시 배포하면 저장한 데이터가 지워집니다 (무료판의 한계).

## 0. 깨우기 + 정상 동작

```bash
curl -s -X POST $BASE/query -d '{"sql": "SELECT * FROM users;"}'
```

## 1. 동시에 INSERT 6개 → 여러 스레드가 나눠 처리, id는 안 겹침 (15·16단계)

```bash
for i in 1 2 3 4 5 6; do curl -s -X POST $BASE/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('u$i', $i);\"}" & done; wait
```

- 각 응답의 `"id"`가 서로 다르면 lock이 동작한 것 ([STEP16](./STEP16.md))
- Render 대시보드 → Logs에 `[worker-1]`, `[worker-3]` 처럼 스레드 이름이 섞여 나오면 Thread Pool이 동작한 것 ([STEP15](./STEP15.md))
- 응답 머리로도 보기: `curl -si -X POST $BASE/query -d '{"sql": "SELECT * FROM users WHERE id = 1;"}' | grep -i x-worker`

## 2. id로 찾기 vs 다른 열로 찾기 (2단계, Phase 2)

```bash
curl -s -X POST $BASE/query -d '{"sql": "SELECT * FROM users WHERE id = 2;"}'
curl -s -X POST $BASE/query -d "{\"sql\": \"SELECT * FROM users WHERE name = 'u2';\"}"
```

첫째는 `"used_index": true`(목차로 바로 감), 둘째는 `false`(처음부터 읽음).

## 3. 오류는 모두 같은 JSON 모양 (17단계)

```bash
curl -s -X GET  $BASE/query
curl -s -X POST $BASE/abc -d '{"sql": "SELECT * FROM users;"}'
curl -s -X POST $BASE/query -d 'not json'
curl -s -X POST $BASE/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('a', 1); SELEC 1;\"}"
```

차례로 405 `method_not_allowed`, 404 `not_found`, 400 `bad_request`, 400 `bad_sql`(+ 앞 문장 결과). 모두 `{"error": {"code", "message"}}` ([STEP17](./STEP17.md)).

## 4. (노트북에서) 503과 디스크에 남는 것

배포 서버는 스레드 수를 바꾸기 어렵고 디스크가 지워지므로, 이 둘은 노트북에서 보여 줍니다.

```bash
python3 server.py --workers 1 --queue 1         # 터미널 1: 스레드 1개, 큐 1칸
```
```bash
# 터미널 2: 연결 두 개로 스레드와 큐를 채운 뒤 요청 → 503 busy
(nc localhost 8000 & nc localhost 8000 &) ; sleep 0.5; curl -s -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users;"}'
```

디스크: INSERT 몇 개 → 터미널 1에서 `Ctrl + C` → 다시 켜기 → `SELECT * FROM users;` 하면 그대로 있고, 다음 INSERT의 id가 이어집니다.

>  [Thread Pool · 큐(16) · 감시(408) · 503 시뮬레이터 실행하기](https://team1-mini-lab.github.io/mini-dbms/threadpool_simulator.html)**
