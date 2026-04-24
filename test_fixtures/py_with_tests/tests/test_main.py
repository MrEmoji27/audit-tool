from main import add, greet


def test_add_positive():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-1, 1) == 0


def test_greet():
    assert greet("Alice") == "Hello, Alice!"


def test_greet_empty():
    assert greet("") == "Hello, !"
