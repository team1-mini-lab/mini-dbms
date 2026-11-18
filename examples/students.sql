-- 0단계 문서의 예시. 실행: python -m minidb examples/students.sql
INSERT INTO students (name, grade) VALUES ('Kim', 3);
INSERT INTO students (name, grade) VALUES ('Lee', 2);
SELECT * FROM students WHERE id = 1;
