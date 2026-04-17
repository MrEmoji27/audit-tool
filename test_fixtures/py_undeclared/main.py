import flask


def main():
    app = flask.Flask(__name__)
    print("Created app:", app.name)


if __name__ == "__main__":
    main()
