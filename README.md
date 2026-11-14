# mini-dbms

세 단계(SQL 처리기 → B+ 트리 인덱스 → API 서버)로 만드는 미니 DBMS입니다.

| 문서 | 내용 |
| --- | --- |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 과제 요구사항 |
| [docs/DESIGN.md](docs/DESIGN.md) | 요구사항, 구조와 접점, 개발 단계, 결정 |
| [docs/study/](docs/study/) | 학습 문서 (전체 그림, 장면별 동작, 학습 노트) |
| [docs/study/WHY_DBMS/](docs/study/WHY_DBMS/WHY_DBMS_GUIDE.md) | 왜 DBMS인가: 설명자료, 시뮬레이터, 슬라이드, 발표 대본, [터미널 시연](docs/study/WHY_DBMS/dbms_demo/README.md) |

## 왜 DBMS인가 터미널 시연 실행

```bash
cd docs/study/WHY_DBMS
python3 -m dbms_demo.scenario --step    # Enter로 한 단계씩
```
