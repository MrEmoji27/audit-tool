"""Unit tests for individual audit check functions."""
import json
from pathlib import Path

import pytest

from audit import (
    ALL_CHECK_KEYS,
    CHECK_WEIGHTS,
    TOTAL_WEIGHT,
    CheckResult,
    ProjectResult,
    _find_entry_point,
    _find_test_files,
    _has_main_guard,
    _verify_github_url,
    check_abs_paths,
    check_readme,
    compute_score,
    compute_verdict,
    detect_stack,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _proj(checks: dict[str, bool | None]) -> ProjectResult:
    r = ProjectResult(name="test", path=Path("."), stack="python")
    for key, val in checks.items():
        if val is None:
            r.add(CheckResult(key, True, na=True, detail="n/a"))
        else:
            r.add(CheckResult(key, val, detail="ok" if val else "fail"))
    return r


# ─── check_abs_paths ────────────────────────────────────────────────────────


def test_abs_paths_clean(tmp_path):
    (tmp_path / "main.py").write_text('x = "hello world"')
    assert check_abs_paths(tmp_path).passed


def test_abs_paths_windows_drive(tmp_path):
    (tmp_path / "main.py").write_text('DATA = "C:\\\\Users\\\\student\\\\data.csv"')
    r = check_abs_paths(tmp_path)
    assert not r.passed
    assert r.findings


def test_abs_paths_unix_home(tmp_path):
    (tmp_path / "config.py").write_text('BASE = "/home/ubuntu/app"')
    assert not check_abs_paths(tmp_path).passed


def test_abs_paths_unix_users(tmp_path):
    (tmp_path / "config.py").write_text('MODEL = "/Users/alice/models/bert"')
    assert not check_abs_paths(tmp_path).passed


def test_abs_paths_url_not_flagged(tmp_path):
    # http:// must NOT trigger the Windows drive-letter lookbehind guard
    (tmp_path / "api.py").write_text('URL = "http://example.com/api"')
    assert check_abs_paths(tmp_path).passed


def test_abs_paths_relative_dot_dot_not_flagged(tmp_path):
    (tmp_path / "loader.py").write_text('path = "../data/file.csv"')
    assert check_abs_paths(tmp_path).passed


def test_abs_paths_notebook(tmp_path):
    nb = {
        "cells": [
            {"cell_type": "code", "source": ['path = "C:\\\\Users\\\\student\\\\nb.csv"']}
        ]
    }
    (tmp_path / "analysis.ipynb").write_text(json.dumps(nb))
    assert not check_abs_paths(tmp_path).passed


# ─── detect_stack ────────────────────────────────────────────────────────────


def test_detect_stack_python_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    assert detect_stack(tmp_path) == "python"


def test_detect_stack_python_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_stack(tmp_path) == "python"


def test_detect_stack_node(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"app","dependencies":{}}')
    assert detect_stack(tmp_path) == "node"


def test_detect_stack_unknown(tmp_path):
    (tmp_path / "README.md").write_text("# nothing")
    assert detect_stack(tmp_path) == "unknown"


def test_detect_stack_both(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "package.json").write_text('{"name":"app"}')
    assert detect_stack(tmp_path) == "both"


def test_detect_stack_flutter(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: my_app\n")
    assert detect_stack(tmp_path) == "flutter"


# ─── compute_verdict ─────────────────────────────────────────────────────────


def test_verdict_all_pass():
    r = _proj({"1_abs_paths": True, "2_external_refs": True})
    assert compute_verdict(r) == "ACCEPTED"


def test_verdict_one_fail():
    r = _proj({"1_abs_paths": False, "2_external_refs": True})
    assert compute_verdict(r) == "REJECTED"


def test_verdict_na_counts_as_pass():
    r = _proj({"1_abs_paths": True, "3_manifest": None})
    assert compute_verdict(r) == "ACCEPTED"


def test_verdict_na_plus_fail():
    r = _proj({"1_abs_paths": False, "3_manifest": None})
    assert compute_verdict(r) == "REJECTED"


def test_verdict_skipped_preserved():
    r = ProjectResult(name="x", path=Path("."), stack="empty")
    r.verdict = "SKIPPED"
    assert compute_verdict(r) == "SKIPPED"


def test_verdict_early_rejected_preserved():
    r = ProjectResult(name="x", path=Path("."), stack="unknown")
    r.verdict = "REJECTED"
    assert compute_verdict(r) == "REJECTED"


# ─── compute_score ────────────────────────────────────────────────────────────


def test_score_all_pass():
    r = _proj({k: True for k in CHECK_WEIGHTS})
    assert compute_score(r) == TOTAL_WEIGHT


def test_score_all_fail():
    r = _proj({k: False for k in CHECK_WEIGHTS})
    assert compute_score(r) == 0


def test_score_one_fail_abs_paths():
    checks = {k: True for k in CHECK_WEIGHTS}
    checks["1_abs_paths"] = False
    r = _proj(checks)
    assert compute_score(r) == TOTAL_WEIGHT - CHECK_WEIGHTS["1_abs_paths"]


def test_score_na_earns_full_marks():
    checks = {k: True for k in CHECK_WEIGHTS}
    checks["3_manifest"] = None
    checks["4_imports_declared"] = None
    r = _proj(checks)
    assert compute_score(r) == TOTAL_WEIGHT


def test_score_absent_check_earns_full_marks():
    # Only supply one check; absent ones should not reduce score
    r = _proj({"1_abs_paths": True})
    assert compute_score(r) == TOTAL_WEIGHT


def test_score_skipped_is_zero():
    r = ProjectResult(name="x", path=Path("."), stack="empty")
    r.verdict = "SKIPPED"
    assert compute_score(r) == 0


def test_score_within_bounds():
    r = _proj({k: False for k in list(CHECK_WEIGHTS)[:3]})
    score = compute_score(r)
    assert 0 <= score <= TOTAL_WEIGHT


def test_score_weights_sum_to_total():
    assert TOTAL_WEIGHT == sum(CHECK_WEIGHTS.values())


# ─── _find_entry_point ───────────────────────────────────────────────────────


def test_entry_point_main_py(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')")
    ep = _find_entry_point(tmp_path, "python")
    assert ep is not None and ep.name == "main.py"


def test_entry_point_prefers_main_over_app(tmp_path):
    (tmp_path / "main.py").write_text("print('main')")
    (tmp_path / "app.py").write_text("print('app')")
    ep = _find_entry_point(tmp_path, "python")
    assert ep is not None and ep.name == "main.py"


def test_entry_point_dunder_main_fallback(tmp_path):
    (tmp_path / "server.py").write_text('if __name__ == "__main__":\n    pass\n')
    ep = _find_entry_point(tmp_path, "python")
    assert ep is not None


def test_entry_point_node_index(tmp_path):
    (tmp_path / "index.js").write_text("console.log('hi')")
    ep = _find_entry_point(tmp_path, "node")
    assert ep is not None and ep.name == "index.js"


def test_entry_point_node_package_main(tmp_path):
    (tmp_path / "package.json").write_text('{"main":"src/app.js"}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("// app")
    ep = _find_entry_point(tmp_path, "node")
    assert ep is not None and ep.name == "app.js"


def test_entry_point_none_empty(tmp_path):
    assert _find_entry_point(tmp_path, "python") is None


def test_entry_point_none_no_main_pattern(tmp_path):
    (tmp_path / "utils.py").write_text("def helper(): pass")
    assert _find_entry_point(tmp_path, "python") is None


# ─── _find_test_files ────────────────────────────────────────────────────────


def test_find_test_files_none(tmp_path):
    (tmp_path / "main.py").write_text("x = 1")
    assert _find_test_files(tmp_path, "python") == []


def test_find_test_files_test_prefix(tmp_path):
    (tmp_path / "test_utils.py").write_text("def test_x(): pass")
    files = _find_test_files(tmp_path, "python")
    assert len(files) == 1 and files[0].name == "test_utils.py"


def test_find_test_files_test_suffix(tmp_path):
    (tmp_path / "utils_test.py").write_text("def test_x(): pass")
    files = _find_test_files(tmp_path, "python")
    assert len(files) == 1 and files[0].name == "utils_test.py"


def test_find_test_files_in_subdir(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_x(): pass")
    files = _find_test_files(tmp_path, "python")
    assert len(files) == 1


def test_find_test_files_skips_venv(tmp_path):
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "test_something.py").write_text("def test_x(): pass")
    # No non-venv test files
    assert _find_test_files(tmp_path, "python") == []


def test_find_test_files_node_spec(tmp_path):
    (tmp_path / "app.test.js").write_text("test('x', () => {})")
    files = _find_test_files(tmp_path, "node")
    assert len(files) == 1 and files[0].name == "app.test.js"


def test_find_test_files_node_skips_node_modules(tmp_path):
    nm = tmp_path / "node_modules" / "somelib"
    nm.mkdir(parents=True)
    (nm / "lib.test.js").write_text("test('x', () => {})")
    assert _find_test_files(tmp_path, "node") == []


# ─── check_weights sanity ────────────────────────────────────────────────────


def test_check8_in_weights():
    assert "8_tests" in CHECK_WEIGHTS


def test_check8_weight_positive():
    assert CHECK_WEIGHTS["8_tests"] > 0


# ─── check_readme ─────────────────────────────────────────────────────────────


def _make_readme(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "README.md"
    p.write_text(content)
    return p


def test_readme_missing(tmp_path):
    _, c7b = check_readme(tmp_path)
    assert not c7b.passed


def test_readme_git_clone_fails(tmp_path):
    _make_readme(tmp_path, "## Setup\ngit clone https://github.com/user/repo\npip install -r requirements.txt\n## Run\npython main.py")
    _, c7b = check_readme(tmp_path)
    assert not c7b.passed
    assert any("git" in f["issue"].lower() for f in c7b.findings)


def test_readme_git_pull_fails(tmp_path):
    _make_readme(tmp_path, "## Setup\ngit pull origin main\npip install -r requirements.txt\n## Run\npython main.py")
    _, c7b = check_readme(tmp_path)
    assert not c7b.passed


def test_readme_no_install_fails(tmp_path):
    _make_readme(tmp_path, "## Run\npython main.py")
    _, c7b = check_readme(tmp_path)
    assert not c7b.passed
    assert any("installation" in f["issue"].lower() for f in c7b.findings)


def test_readme_no_run_fails(tmp_path):
    _make_readme(tmp_path, "## Setup\npip install -r requirements.txt")
    _, c7b = check_readme(tmp_path)
    assert not c7b.passed
    assert any("execution" in f["issue"].lower() for f in c7b.findings)


def test_readme_good_passes(tmp_path):
    content = (
        "## About\nA student project for the data structures course. "
        "Implements a binary search tree with insert, delete, and traversal.\n\n"
        "## Setup\npip install -r requirements.txt\n\n"
        "## Run\npython main.py\n"
    )
    _make_readme(tmp_path, content)
    _, c7b = check_readme(tmp_path)
    assert c7b.passed


# ─── _verify_github_url ───────────────────────────────────────────────────────


def test_verify_github_url_valid():
    reachable, detail = _verify_github_url("https://github.com/python/cpython")
    # Non-fatal on network error — either True or True-with-skip
    assert reachable


def test_verify_github_url_nonexistent():
    # 404 or network skip — either way the detail is a non-empty string
    reachable, detail = _verify_github_url("https://github.com/this-user-does-not-exist-xyz/no-repo-abc-123")
    assert isinstance(detail, str) and len(detail) > 0


def test_readme_dead_github_url_does_not_fail(tmp_path):
    """A broken GitHub link is informational only — should not cause a FAIL."""
    _make_readme(tmp_path,
        "## About\nA student project for the algorithms course.\n\n"
        "## Setup\npip install -r requirements.txt\n\n"
        "## Run\npython main.py\n\n"
        "Repo: https://github.com/this-user-does-not-exist-xyz/no-repo-abc-123"
    )
    _, c7b = check_readme(tmp_path)
    assert c7b.passed


# ─── rubric registry ─────────────────────────────────────────────────────────


def test_rubric_weight_keys_match_all_check_keys():
    """CHECK_WEIGHTS must cover exactly the same keys as ALL_CHECK_KEYS."""
    assert set(CHECK_WEIGHTS.keys()) == set(ALL_CHECK_KEYS), (
        f"Mismatch: weights={sorted(CHECK_WEIGHTS)}, all_keys={sorted(ALL_CHECK_KEYS)}"
    )


def test_rubric_total_weight_is_105():
    assert TOTAL_WEIGHT == 105, f"Expected 105, got {TOTAL_WEIGHT}"


def test_rubric_all_weights_positive():
    assert all(v > 0 for v in CHECK_WEIGHTS.values()), "All weights must be positive"


# ─── _has_main_guard ─────────────────────────────────────────────────────────


def test_has_main_guard_real_guard():
    code = 'def foo():\n    pass\n\nif __name__ == "__main__":\n    foo()\n'
    assert _has_main_guard(code) is True


def test_has_main_guard_commented_out():
    """A commented-out guard must NOT be detected."""
    code = '# if __name__ == "__main__":\n#     main()\ndef foo(): pass\n'
    assert _has_main_guard(code) is False


def test_has_main_guard_in_docstring():
    """Guard in a docstring must NOT be detected."""
    code = '"""Example:\n    if __name__ == "__main__": pass\n"""\ndef foo(): pass\n'
    assert _has_main_guard(code) is False


def test_has_main_guard_single_quote_variant():
    code = "if __name__ == '__main__':\n    print('hi')\n"
    assert _has_main_guard(code) is True


def test_has_main_guard_no_guard():
    code = "import os\ndef foo(): pass\n"
    assert _has_main_guard(code) is False


# ─── entry-point ignores commented guard ────────────────────────────────────


def test_entry_point_ignores_commented_main_guard(tmp_path):
    """_find_entry_point must not pick a file whose only main guard is in a comment."""
    helper = tmp_path / "helper.py"
    helper.write_text(
        "# if __name__ == '__main__':\n#     main()\ndef helper_fn(): pass\n",
        encoding="utf-8",
    )
    # No real entry point should be found
    result = _find_entry_point(tmp_path, "python")
    assert result is None


def test_entry_point_prefers_real_guard_over_commented(tmp_path):
    """_find_entry_point picks the file with a real guard, not the one with a comment."""
    (tmp_path / "helper.py").write_text(
        "# if __name__ == '__main__': pass\n",
        encoding="utf-8",
    )
    real = tmp_path / "real_entry.py"
    real.write_text(
        'def run(): print("ok")\nif __name__ == "__main__":\n    run()\n',
        encoding="utf-8",
    )
    result = _find_entry_point(tmp_path, "python")
    assert result is not None and result.name == "real_entry.py"
