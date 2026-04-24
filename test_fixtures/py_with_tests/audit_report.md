# Audit Report

Generated: `2026-04-19T18:33:34`

Auditor environment: Python `3.13.0`, Node `v20.19.6`, npm `11.9.0`.

## Summary

- **ACCEPTED**: 1/1
- **REJECTED**: 0/1
- **Average score**: 100.0 / 100
- **Highest**: 100 | **Lowest**: 100

### Score Distribution

| Band | Count |
|------|-------|
| 100 (perfect) | 1 |
| 80–99 (good) | 0 |
| 60–79 (partial) | 0 |
| 40–59 (weak) | 0 |
| 0–39 (poor) | 0 |

### Score Leaderboard

| # | Project | Score | Verdict |
|---|---------|-------|---------|
| 1 | py_with_tests | 100/100 `██████████` | ACCEPTED |

## Per-Project Details

### py_with_tests

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Score**: 100/100
- **Path**: `C:\Users\mremo\OneDrive\Desktop\audit-tool\test_fixtures\py_with_tests`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (requirements.txt); no third-party imports |
| `4_imports_declared` | **N/A** | No third-party imports to declare |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |
