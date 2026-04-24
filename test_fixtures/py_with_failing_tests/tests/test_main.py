from main import multiply, divide


def test_multiply_passes():
    assert multiply(3, 4) == 12


def test_multiply_wrong_expectation():
    # intentionally wrong — student made a bad assertion
    assert multiply(3, 4) == 99


def test_divide_by_zero():
    # intentionally broken — will raise ZeroDivisionError
    assert divide(10, 0) == 0
