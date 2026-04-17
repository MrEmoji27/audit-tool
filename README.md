# audit.py — Self-Contained Verification Tool

Audits student mini-projects against a 7-point rubric. Produces a detailed Markdown + CSV report with a binary `ACCEPTED` / `REJECTED` verdict per project.

## Requirements

- Python 3.11+ (uses `tomllib`)
- `colorama` (see `requirements.txt`)
- Node.js + npm on PATH (only needed for Node.js project Check 5/6)

```
py -m pip install -r requirements.txt
```

## Usage

```
python audit.py <root_dir>
python audit.py <root_dir> --single <project_name>
python audit.py <root_dir> --resume
python audit.py <root_dir> --only-static
python audit.py <root_dir> --report-dir <where_to_write>
```

- `<root_dir>` must contain one subfolder per student team project.
- `--single` audits only the named subfolder.
- `--resume` skips projects already in the existing `audit_report.csv`.
- `--only-static` skips Check 5 (install) and Check 6 (runs).

## The 7 Checks

| # | Check | What it means |
|---|---|---|
| 1 | Absolute paths | No `C:\...`, `/Users/...`, `/home/...`, `/mnt/...`, `/root/...` in code/config. Documentation (`.md`, `.txt`, `.rst`) is NOT scanned — mentioning a path in a README is fine. |
| 2 | External refs | No string literal in code resolves outside the project root. A `../config/settings.json` inside `src/` that points back into the project is OK; `../../../Users/evil/...` is not. |
| 3 | Manifest exists | Python: `requirements.txt` or `pyproject.toml` (required iff third-party imports exist; stdlib-only scripts may omit it). Node: `package.json` with a populated `dependencies` or `devDependencies`. |
| 4 | Imports declared | Every third-party import in code is declared in the manifest. Stdlib / built-ins / local modules are filtered out. Common Python alias gaps (`PIL`→`pillow`, `cv2`→`opencv-python`, `yaml`→`pyyaml`, etc.) are handled. |
| 5 | Install succeeds | In a clean copy: `python -m venv .venv && pip install -r requirements.txt` (Python) or `npm install` (Node). No cached `node_modules` / `.venv` from the student's machine. |
| 6 | Runs without import errors | Entry point starts without `ModuleNotFoundError`, `ImportError`, `SyntaxError` (Python) or `Cannot find module`, `MODULE_NOT_FOUND`, `SyntaxError` (Node). Runtime crashes later (missing config files, logic errors) are OK — we're verifying self-containment, not bug-freeness. |
| 7 | README | `README.md`, `README.txt`, `README`, or `README.rst` at project root. Contents don't matter. |

A project is **ACCEPTED** only if all 7 checks pass. Any failure → **REJECTED**.

## How to Interpret the Report

- `audit_report.md` — full details per project, including every check result, specific findings (file + line), and reproduce commands for rejections.
- `audit_report.csv` — one row per project, sortable in Excel. Columns for each of the 7 checks (`PASS` / `FAIL` / `N/A`) plus a `failure_summary` text column.
- Both reports are written **incrementally** after each project — a crash on project 19 does not lose projects 1–18.

## Windows Notes

- Copies projects to `%TEMP%\audit_<name>\` before running dynamic checks — originals are never modified.
- Works around Windows file-lock issues on cleanup with retry-rmtree.
- Uses `CREATE_NO_WINDOW` flag so subprocess calls don't spawn console popups.
- Path-length limit: projects whose path exceeds ~240 chars are REJECTED (Windows 260-char MAX_PATH).

## Testing

`test_fixtures/` contains 8 synthetic projects covering the key edge cases:

| # | Fixture | Expected verdict | What it tests |
|---|---|---|---|
| 1 | `py_clean_stdlib` | ACCEPTED | stdlib-only Python, no manifest required |
| 2 | `py_clean_with_deps` | ACCEPTED | Happy path, `requests` declared and imported |
| 3 | `py_abs_path` | REJECTED | Hardcoded `C:\...` literal → Check 1 |
| 4 | `py_undeclared` | REJECTED | Imports `flask`, declares `requests` → Check 4 |
| 5 | `py_relative_safe` | ACCEPTED | `../config` from `src/` stays in project → Check 2 |
| 6 | `py_external_ref` | REJECTED | `../../../Users/evil/...` escapes → Check 2 |
| 7 | `node_scoped_ok` | ACCEPTED | Scoped package `@babel/core` handled correctly |
| 8 | `node_undeclared` | REJECTED | Imports `lodash`, declares `express` → Check 4 |

Run:

```
python audit.py test_fixtures
```

Expected: 4 ACCEPTED, 4 REJECTED.
