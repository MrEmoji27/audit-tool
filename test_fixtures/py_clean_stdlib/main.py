import json
import os


def main():
    data = {"hello": "world", "pid": os.getpid()}
    print(json.dumps(data))


if __name__ == "__main__":
    main()
