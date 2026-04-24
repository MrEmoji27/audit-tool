import os

API_KEY = os.getenv("API_KEY")
SECRET = os.environ["SECRET_TOKEN"]

if __name__ == "__main__":
    print(f"API_KEY={API_KEY}, SECRET={SECRET}")
