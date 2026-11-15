# mini-dbms

세 단계(SQL 처리기 → B+ 트리 인덱스 → API 서버)로 만드는 미니 DBMS입니다.

| 문서 | 내용 |
| --- | --- |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 과제 요구사항 |
| [docs/DESIGN.md](docs/DESIGN.md) | 요구사항, 구조와 접점, 개발 단계, 결정 |
| [docs/study/OVERVIEW.md](docs/study/OVERVIEW.md) | 전체 그림: 왜 DBMS인가, 세 Phase의 연결, 레디스와의 차이 |
| [docs/study/WALKTHROUGH.md](docs/study/WALKTHROUGH.md) | 예시 하나로 따라가는 장면별 동작 |
| [docs/study/WHY_DBMS/](docs/study/WHY_DBMS/WHY_DBMS_GUIDE.md) | 왜 DBMS인가: 설명자료, 시뮬레이터, 슬라이드, 발표 대본, [터미널 시연](docs/study/WHY_DBMS/dbms_demo/README.md) |

## 왜 DBMS인가 터미널 시연 실행

```bash
cd docs/study/WHY_DBMS
python3 -m dbms_demo.scenario --step    # Enter로 한 단계씩
```
