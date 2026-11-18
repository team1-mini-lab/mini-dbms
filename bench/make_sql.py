"""10단계: INSERT N줄짜리 SQL 파일을 만든다. (원작성: somang, 사용법만 minidb 에 맞춤)

사용법 (저장소 맨 위 폴더에서):
    python bench/make_sql.py 1000000 bench/users_1000000.sql

i번째 줄은 name = 'user{i}', age = 20 + i % 50 이다.
실행기가 id를 1부터 붙이므로, 빈 테이블에 넣으면 id i인 사람의 name은 'user{i}'가 된다.
그래서 WHERE id = i 와 WHERE name = 'user{i}' 가 같은 한 줄을 찾는다 (벤치마크 비교 조건).
"""
import sys


def make(n, path):
    with open(path, "w", encoding="utf-8") as f:
        for i in range(1, n + 1):
            f.write(f"INSERT INTO users (name, age) VALUES ('user{i}', {20 + i % 50});\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("사용법: python bench/make_sql.py <줄 수> <저장할 파일>")
    make(int(sys.argv[1]), sys.argv[2])
