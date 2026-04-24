# Audit Tool

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A self-contained verification tool that audits student mini-projects against a 10-point rubric. Produces detailed Markdown and CSV reports with ACCEPTED/REJECTED verdicts and weighted scores per project.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Checks](#checks)
- [Scoring](#scoring)
- [Reports](#reports)
- [Sequence Gap Detection](#sequence-gap-detection)
- [Duplicate Detection](#duplicate-detection)
- [Testing](#testing)
- [Windows Notes](#windows-notes)

---

## Features

- **10-point rubric** covering static analysis, dynamic checks, documentation quality, and submission hygiene
- **Weighted scoring** — every project gets a 0–105 score alongside its binary verdict
- **Multi-language support** — Python (`.py`, `.ipynb`), Node.js (`.js`/`.ts`/`.jsx`/`.tsx`), Flutter (`pubspec.yaml`), and mixed stacks
- **Sequence gap detection** — identifies missing submissions in numbered folder sets; handles mixed zero-padding (`C01` + `C7`), year-suffixed titles (`C10-NLP-2024`), and multiple independent cohorts in the same directory
- **Duplicate detection** — SHA-256 fingerprint of source files flags identical submissions
- **Unpinned dependency warnings** — highlights `requirements.txt` entries with no version specifier
- **README quality analysis** — checks for minimum content, installation/run instructions, and git-clone anti-patterns
- **Detailed reporting** — Markdown (human-readable) + CSV (machine-readable), updated incrementally after each project; rejection breakdown names individual projects and failure reasons per check
- **Resume support** — skip already-audited projects and warn if flags changed between runs
- **Temp-dir isolation** — projects are copied to `%TEMP%` (or `AUDIT_TMP`) for dynamic checks; originals are never modified
- **108-test suite** — fast unit tests + slow integration tests with real installs and runs

---

## Installation

### Requirements

- Python 3.11+ (uses `tomllib`)
- `colorama` for colored terminal output
- Node.js + npm on PATH _(required only for Node.js project checks 5/6/8)_

### Setup

```bash
git clone https://github.com/MrEmoji27/audit-tool.git
cd audit-tool
pip install -r requirements.txt
```

---

## Usage

```bash
python audit.py <root_dir>                              # audit all subfolders
python audit.py <root_dir> --single <project_name>      # audit one project
python audit.py <root_dir> --resume                     # skip already-reported projects
python audit.py <root_dir> --only-static                # skip install/run/test (faster)
python audit.py <root_dir> --report-dir <path>          # write reports to a custom folder
python audit.py <root_dir> --strict                     # treat unreadable files as findings
python audit.py <root_dir> --verbose                    # debug logging to stderr
python audit.py <root_dir> --log-file audit.log         # also write logs to a file
python audit.py                                         # auto-detect: CWD or parent
```

**Auto-detect mode** (no `root_dir`): if the current directory looks like a single project (has `requirements.txt`, `package.json`, or `.py` files at the top level) it audits that project. Otherwise it treats the current directory as the root containing project subfolders.

**`--resume` flag tracking**: on each run the tool saves flags to `audit_flags.json` alongside the report. On `--resume`, it warns if `--only-static` or `--strict` differ from the previous run, since skipped projects were audited under different settings.

---

## Checks

Projects are evaluated against 10 checks. A project is **ACCEPTED** only if it passes all applicable checks. `N/A` checks (not relevant to the project) count as full marks.

| # | Key | Check | What passes | What fails |
|---|-----|-------|-------------|------------|
| 1 | `1_abs_paths` | **Absolute paths** | No hardcoded `C:\`, `/Users/`, `/home/`, `/mnt/`, `/root/` in any code or config file | Any absolute path found in source |
| 2 | `2_external_refs` | **External references** | All `../` path literals stay within the project root | A string literal resolves outside the project directory |
| 3 | `3_manifest` | **Manifest exists** | `requirements.txt` / `pyproject.toml` (Python), `package.json` (Node), `pubspec.yaml` (Flutter) | Missing, empty, or unreadable manifest |
| 3† | _(informational)_ | **Unpinned dependencies** | All `requirements.txt` entries have version specifiers | Entries with no `==`, `>=`, etc. are flagged as a warning on Check 3 (does not fail the check) |
| 4 | `4_imports_declared` | **Imports declared** | Every third-party import appears in the manifest; covers 100+ common import→package aliases and transitive dependencies | Any import not traceable to a declared package |
| 5 | `5_install` | **Install succeeds** | `pip install -r requirements.txt` or `npm install` completes without errors in an isolated temp venv | Install failure or timeout (600s) |
| 6 | `6_runs` | **Runs without errors** | Entry point starts without `ModuleNotFoundError`, `ImportError`, or `SyntaxError` | Any of the above errors detected in combined stdout/stderr |
| 7 | `7_readme` | **README present** | A `README.*` file exists at the project root | No README found |
| 7b | `7b_readme_quality` | **README quality** | ≥ 150 chars, ≥ 5 meaningful lines, contains installation instructions, contains run instructions, no `git clone`/`git pull` commands, not a GitHub-template README | Any of the above missing or disqualifying content |
| 8 | `8_tests` | **Test suite passes** | `pytest` passes all collected tests (Python) or `npm test` exits 0 (Node) — **N/A if no test files found** | One or more test failures, collection errors, or timeout |
| 9 | `9_env_example` | **`.env.example` present** | A `.env.example` / `.env.sample` / `.env.template` file exists when `os.environ`, `load_dotenv`, or `process.env` is used — **N/A if no env var usage detected** | Env vars used but no example file provided |

### Entry point discovery

**Python**: looks for `main.py` → `app.py` → `run.py` at the project root, then falls back to any `.py` file containing a real `if __name__ == "__main__":` guard. The guard is detected via AST parsing so patterns in comments or docstrings are not matched.

**Node**: reads the `scripts.start` field in `package.json` first, then `main`, then falls back to `index.js` → `server.js` → `app.js`.

### Import alias coverage

Check 4 recognises over 100 common import-name → PyPI-name mappings (e.g. `cv2` → `opencv-python`, `sklearn` → `scikit-learn`, `yaml` → `pyyaml`) and understands transitive dependencies for major frameworks (Flask, Django, FastAPI, PyTorch, TensorFlow, pandas, etc.) so that sub-packages of a declared dependency are not incorrectly flagged.

---

## Scoring

Each check carries a point weight. Passing (or N/A) earns the full weight; failing earns 0. The maximum score is **105**.

| Check | Weight |
|-------|--------|
| 1 — Absolute paths | 15 |
| 2 — External references | 15 |
| 3 — Manifest exists | 15 |
| 4 — Imports declared | 15 |
| 5 — Install succeeds | 10 |
| 6 — Runs without errors | 10 |
| 7 — README present | 5 |
| 7b — README quality | 5 |
| 8 — Test suite passes | 10 |
| 9 — `.env.example` present | 5 |
| **Total** | **105** |

Projects that trigger an early exit (unknown stack, path too long) are REJECTED and show `0/—` — scoring was not applicable. SKIPPED projects (empty folders) are excluded from scoring statistics entirely.

---

## Reports

### Console output

The terminal shows a live box per project as it is audited, then a summary panel with:

- Total / accepted / rejected / skipped counts
- Average, highest, and lowest scores
- Score distribution (perfect / good / partial / weak / poor)
- Rejection reason breakdown (which checks caused the most rejections)
- Sequence gap report (if a numbered folder pattern is detected)
- Duplicate submission list (if any identical projects are found)
- Per-project results table with score bars

### `audit_report.md`

Per-project section with check table, specific findings (file path + line number), score, verdict, and a one-line reproduction command. The **Rejection Reasons Breakdown** section lists individual project names and their specific failure reasons per check (up to 5 shown, remainder counted). Summary section includes score distribution table and leaderboard.

### `audit_report.csv`

One row per project with columns: `project_name`, `stack`, `verdict`, `score`, one column per check (`PASS` / `FAIL` / `N/A`), `duplicate_of`, and `failure_summary`. Sortable and importable into Excel / Google Sheets.

Both files are written **incrementally** — after every project — so an interrupted run never loses completed work.

---

## Sequence Gap Detection

When project folders follow a numbered naming pattern, the tool automatically:

- Detects one or more patterns (prefix + number + optional suffix) — multiple independent cohorts in the same directory are each reported separately
- Handles mixed zero-padding: `C01` and `C7` and `C08` all land in the same `C` bucket
- Handles year-suffixed or descriptive titles: `C10-NLP-2024` is correctly parsed as prefix `C`, number `10` — not fragmented by the trailing year
- Reports the sequence range found and the count expected
- Lists any missing folder names (e.g. `C04`, `C12`)
- Lists folders that don't match any pattern

This works for zero-padded (`A01–A10`) and non-padded (`A1–A10`) sequences, and is case- and whitespace-insensitive when grouping. Reported in both the console summary and the Markdown report.

---

## Duplicate Detection

After all projects are audited, the tool computes a SHA-256 fingerprint of every source file (`.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.mjs`, `.cjs`) sorted by relative path. Projects with identical fingerprints are flagged in the console DUPLICATES section, marked in the Markdown report, and recorded in the `duplicate_of` CSV column.

---

## Testing

### Automated test suite

```bash
python -m pytest tests/                       # all tests (fast + slow)
python -m pytest tests/ -m "not slow"         # fast unit tests only (~3s)
python -m pytest tests/ -m "slow"             # integration tests with real installs
```

108 tests cover: absolute path detection, stack detection, verdict and score logic, entry point discovery (including AST-based guard detection), sequence gap detection (mixed padding, year-in-title, multi-cohort), test file discovery, README quality checks, rubric invariant, all fixture verdicts, and dynamic install/run/test checks.

### Fixture projects

The `test_fixtures/` directory contains 11 synthetic projects:

| Fixture | Expected | Tests |
|---------|----------|-------|
| `py_clean_stdlib` | ACCEPTED | Stdlib-only Python; no manifest required |
| `py_clean_with_deps` | ACCEPTED | Correct dependency declaration |
| `py_abs_path` | REJECTED | Hardcoded absolute path (Check 1) |
| `py_undeclared` | REJECTED | Undeclared third-party import (Check 4) |
| `py_relative_safe` | ACCEPTED | Safe relative references within project |
| `py_external_ref` | REJECTED | `../` reference escaping project root (Check 2) |
| `py_with_tests` | ACCEPTED | Passing pytest suite (Check 8) |
| `py_with_failing_tests` | REJECTED | Failing pytest suite (Check 8) |
| `py_with_env_vars` | REJECTED | Uses `os.environ` with no `.env.example` (Check 9) |
| `node_scoped_ok` | ACCEPTED | Scoped npm packages (`@scope/pkg`) handled correctly |
| `node_undeclared` | REJECTED | Undeclared Node.js dependency (Check 4) |

Run the tool against the fixtures directly:

```bash
python audit.py test_fixtures
```

Expected console output: 5 ACCEPTED, 6 REJECTED.

---

## Windows Notes

- Dynamic checks copy the project to `%TEMP%\audit_<id>\` — originals are never modified
- **MAX_PATH**: if projects are stored in a deeply nested directory (common with `node_modules`), set `AUDIT_TMP=C:\T` (or any short path) to avoid Windows MAX_PATH errors during install:
  ```
  set AUDIT_TMP=C:\T
  python audit.py <root_dir>
  ```
- Cleanup runs in a `finally` block so temp dirs are removed even if a check crashes
- `CREATE_NO_WINDOW` flag prevents subprocess console popups
- stdout is reconfigured to UTF-8 so box-drawing characters render correctly
- Projects whose resolved path exceeds 240 characters are rejected early (Windows MAX_PATH guard)
- pip install timeout is 600 seconds to accommodate large ML dependencies (torch, tensorflow, transformers) on a cold cache
