import sys

from engine import Engine


def main():
    engine = Engine("data")
    with open(sys.argv[1], encoding="utf-8") as f:
        for result in engine.execute(f.read()):
            print(result)


if __name__ == "__main__":
    main()
