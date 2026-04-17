# Audit Tool

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A self-contained verification tool that audits student mini-projects against a comprehensive 7-point rubric. Produces detailed Markdown and CSV reports with binary ACCEPTED/REJECTED verdicts per project.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Acceptance Criteria](#acceptance-criteria)
- [Report Interpretation](#report-interpretation)
- [Testing](#testing)
- [Windows Notes](#windows-notes)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Comprehensive Auditing**: Evaluates projects across 7 critical checks for self-containment and correctness
- **Multi-Language Support**: Handles Python and Node.js projects
- **Detailed Reporting**: Generates both human-readable Markdown and machine-readable CSV reports
- **Incremental Processing**: Processes projects one by one, saving progress even if interrupted
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Test Fixtures**: Includes synthetic test cases covering edge cases

## Installation

### Requirements

- Python 3.11+ (uses `tomllib`)
- `colorama` for colored output
- Node.js + npm on PATH (required only for Node.js project checks 5/6)

### Setup

```bash
git clone https://github.com/MrEmoji27/audit-tool.git
cd audit-tool
pip install -r requirements.txt
```

## Usage

```bash
python audit.py <root_dir>
python audit.py <root_dir> --single <project_name>
python audit.py <root_dir> --resume
python audit.py <root_dir> --only-static
python audit.py <root_dir> --report-dir <where_to_write>
```

- `<root_dir>`: Directory containing one subfolder per student team project
- `--single`: Audit only the specified project subfolder
- `--resume`: Skip projects already present in existing `audit_report.csv`
- `--only-static`: Skip dynamic checks (install and runtime) for faster static analysis
- `--report-dir`: Custom directory for output reports (defaults to current directory)

## Acceptance Criteria

Projects are evaluated against 7 mandatory checks. A project is **ACCEPTED** only if it passes ALL checks. Any single failure results in **REJECTION**.

| # | Check | Description | Accept Criteria | Reject Reason |
|---|---|---|---|---|
| 1 | Absolute Paths | No hardcoded absolute paths in code/config | No `C:\...`, `/Users/...`, `/home/...`, etc. | Hardcoded system paths found |
| 2 | External References | No references outside project root | All file references stay within project boundaries | References escape project directory |
| 3 | Manifest Exists | Proper dependency declaration file | `requirements.txt`/`pyproject.toml` (Python) or `package.json` (Node) | Missing or empty manifest |
| 4 | Imports Declared | All third-party imports declared | Every import matches manifest dependencies | Undeclared dependencies used |
| 5 | Install Succeeds | Clean installation works | `pip install` or `npm install` completes without errors | Installation failures |
| 6 | Runs Without Errors | Entry point starts successfully | No import/module errors on startup | Runtime import failures |
| 7 | README Present | Documentation exists | `README.md`, `README.txt`, etc. at root | No README file found |

### How We Accept and Reject

- **ACCEPTED**: All 7 checks pass. The project is self-contained, properly configured, and ready for evaluation.
- **REJECTED**: One or more checks fail. The report provides specific failure details, including file locations and suggested fixes.
- **Verdict Logic**: Strict AND condition - every check must pass. No partial credit or weighted scoring.
- **Appeal Process**: Review the detailed `audit_report.md` for specific findings. Fix issues and re-submit for re-audit.

## Report Interpretation

- **`audit_report.md`**: Detailed per-project analysis with check results, specific findings (file + line numbers), and reproduction commands
- **`audit_report.csv`**: Tabular format with one row per project, sortable columns for each check (`PASS`/`FAIL`/`N/A`), and failure summaries
- **Incremental Writing**: Reports update after each project - interruptions don't lose progress

## Testing

The `test_fixtures/` directory contains 8 synthetic projects covering key scenarios:

| Fixture | Expected | Tests |
|---|---|---|
| `py_clean_stdlib` | ACCEPTED | Stdlib-only Python, no manifest needed |
| `py_clean_with_deps` | ACCEPTED | Proper dependency declaration and usage |
| `py_abs_path` | REJECTED | Hardcoded absolute paths (Check 1) |
| `py_undeclared` | REJECTED | Undeclared imports (Check 4) |
| `py_relative_safe` | ACCEPTED | Safe relative references within project |
| `py_external_ref` | REJECTED | References outside project root (Check 2) |
| `node_scoped_ok` | ACCEPTED | Scoped npm packages handled correctly |
| `node_undeclared` | REJECTED | Undeclared Node.js dependencies (Check 4) |

Run tests:

```bash
python audit.py test_fixtures
```

Expected: 4 ACCEPTED, 4 REJECTED.

## Windows Notes

- Projects copied to `%TEMP%\audit_<name>\` for dynamic checks - originals unmodified
- Handles Windows file locking with retry mechanisms
- Uses `CREATE_NO_WINDOW` to prevent console popups
- Path length limit: Projects exceeding ~240 characters rejected (Windows MAX_PATH)

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and add tests
4. Run tests: `python audit.py test_fixtures`
5. Commit changes: `git commit -am 'Add feature'`
6. Push to branch: `git push origin feature-name`
7. Submit a pull request
