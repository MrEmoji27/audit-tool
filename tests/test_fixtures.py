"""Integration tests: run static audit on each test_fixture, assert expected verdict."""
import pytest
from pathlib import Path

from audit import (
    audit_static, compute_verdict, compute_score,
    check_install, check_runs, check_tests, _find_test_files,
)

FIXTURES_DIR = Path(__file__).parent.parent / "test_fixtures"

# (fixture_name, expected_verdict)
STATIC_CASES = [
    ("node_scoped_ok",     "ACCEPTED"),
    ("node_undeclared",    "REJECTED"),
    ("py_abs_path",        "REJECTED"),
    ("py_clean_stdlib",    "ACCEPTED"),
    ("py_clean_with_deps", "ACCEPTED"),
    ("py_external_ref",    "REJECTED"),
    ("py_relative_safe",   "ACCEPTED"),
    ("py_undeclared",      "REJECTED"),
]


@pytest.mark.parametrize("name,expected", STATIC_CASES)
def test_static_verdict(name, expected):
    proj = FIXTURES_DIR / name
    r = audit_static(proj)
    r.verdict = compute_verdict(r)
    assert r.verdict == expected, (
        f"[{name}] expected {expected}, got {r.verdict}.\n"
        + "\n".join(f"  {k}: {c.status} — {c.detail}" for k, c in r.checks.items())
    )


@pytest.mark.parametrize("name,_", STATIC_CASES)
def test_score_in_valid_range(name, _):
    proj = FIXTURES_DIR / name
    r = audit_static(proj)
    r.verdict = compute_verdict(r)
    r.score = compute_score(r)
    from audit import TOTAL_WEIGHT
    assert 0 <= r.score <= TOTAL_WEIGHT, f"[{name}] score {r.score} out of range"


@pytest.mark.parametrize("name,verdict", [
    (n, v) for n, v in STATIC_CASES if v == "ACCEPTED"
])
def test_accepted_fixtures_score_100_static(name, verdict):
    """ACCEPTED projects (with absent dynamic checks counting as full marks) must score 100."""
    proj = FIXTURES_DIR / name
    r = audit_static(proj)
    r.verdict = compute_verdict(r)
    r.score = compute_score(r)
    from audit import TOTAL_WEIGHT
    assert r.score == TOTAL_WEIGHT, f"[{name}] expected score {TOTAL_WEIGHT}, got {r.score}"


@pytest.mark.parametrize("name,verdict", [
    (n, v) for n, v in STATIC_CASES if v == "REJECTED"
])
def test_rejected_fixtures_score_below_100(name, verdict):
    proj = FIXTURES_DIR / name
    r = audit_static(proj)
    r.verdict = compute_verdict(r)
    r.score = compute_score(r)
    assert r.score < 100, f"[{name}] REJECTED project scored {r.score}, expected < 100"


# ─── dynamic check integration (slow) ────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.parametrize("name", ["py_clean_stdlib", "py_clean_with_deps"])
def test_dynamic_install_passes(name):
    proj = FIXTURES_DIR / name
    r = audit_static(proj)
    c5, tmp_dir = check_install(proj, r.stack)
    try:
        assert c5.passed or c5.na, f"[{name}] Check 5 failed: {c5.detail}"
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.slow
def test_dynamic_run_detects_missing_module():
    proj = FIXTURES_DIR / "py_undeclared"
    r = audit_static(proj)
    c5, tmp_dir = check_install(proj, r.stack)
    try:
        c6 = check_runs(proj, r.stack, tmp_dir)
        assert not c6.passed, "Expected Check 6 to fail for py_undeclared"
        assert any(err in c6.detail for err in ["ModuleNotFoundError", "ImportError"])
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Check 8 (test suite) ────────────────────────────────────────────────────


def test_find_test_files_in_fixture(tmp_path):
    """Sanity: the py_with_tests fixture actually has test files."""
    proj = FIXTURES_DIR / "py_with_tests"
    # Simulate a proj_copy (the real project dir, not a tmp copy)
    files = _find_test_files(proj, "python")
    assert len(files) >= 1, "Expected at least one test file in py_with_tests"


def test_no_test_files_in_plain_fixture():
    proj = FIXTURES_DIR / "py_clean_stdlib"
    files = _find_test_files(proj, "python")
    assert files == [], "py_clean_stdlib should have no test files"


@pytest.mark.slow
def test_check8_passes_for_good_tests():
    proj = FIXTURES_DIR / "py_with_tests"
    r = audit_static(proj)
    c5, tmp_dir = check_install(proj, r.stack)
    try:
        c8 = check_tests(proj, r.stack, tmp_dir)
        assert c8.passed, f"Check 8 should pass for py_with_tests, got: {c8.detail}"
        assert "passed" in c8.detail.lower()
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.slow
def test_check8_fails_for_broken_tests():
    proj = FIXTURES_DIR / "py_with_failing_tests"
    r = audit_static(proj)
    c5, tmp_dir = check_install(proj, r.stack)
    try:
        c8 = check_tests(proj, r.stack, tmp_dir)
        assert not c8.passed, f"Check 8 should fail for py_with_failing_tests, got: {c8.detail}"
        assert not c8.na
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.slow
def test_check8_na_when_no_tests():
    """Projects without test files should get N/A, not FAIL."""
    proj = FIXTURES_DIR / "py_clean_with_deps"
    r = audit_static(proj)
    c5, tmp_dir = check_install(proj, r.stack)
    try:
        c8 = check_tests(proj, r.stack, tmp_dir)
        assert c8.na, f"Expected N/A for project with no tests, got: {c8.detail}"
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
