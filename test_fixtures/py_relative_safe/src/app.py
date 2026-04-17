import json
from pathlib import Path

CONFIG_PATH = "../config/settings.json"


def main():
    resolved = Path(__file__).parent / CONFIG_PATH
    with open(resolved) as fh:
        print(json.load(fh))


if __name__ == "__main__":
    main()
