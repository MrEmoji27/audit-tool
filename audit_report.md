# Audit Report

Generated: `2026-04-17T16:48:33`

Auditor environment: Python `3.13.0`, Node `v20.19.6`, npm `11.9.0`.

## Summary

- **ACCEPTED**: 15/22
- **REJECTED**: 2/22
- **SKIPPED**: 5/22 (empty folders)

## Rejection Reasons Breakdown

- `3_manifest`: 1 project(s)
- `4_imports_declared`: 1 project(s)
- `7b_readme_quality`: 1 project(s)

## Per-Project Details

### C1-SMART COMMENT CLASSIFICATION

- **Stack**: `both`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C1-SMART COMMENT CLASSIFICATION`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (backend/requirements.txt) |
| `4_imports_declared` | **PASS** | All 11 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C10-AI DRIVEN PRODUCT RECOMMENDATION SYSTEM

- **Stack**: `both`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C10-AI DRIVEN PRODUCT RECOMMENDATION SYSTEM`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (SOURCE_CODE/requirements.txt) |
| `4_imports_declared` | **PASS** | All 8 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C11

- **Stack**: `empty`
- **Verdict**: **SKIPPED**
- **Path**: `D:\CSE-C\C11`
- **Notes**: Empty folder (no files)

| Check | Status | Detail |
|---|---|---|

### C12

- **Stack**: `python`
- **Verdict**: **REJECTED**
- **Path**: `D:\CSE-C\C12`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source Code/requirements.txt) |
| `4_imports_declared` | **PASS** | All 7 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **FAIL** | README tells user to 'git clone' from https://github.com/yourusername/FarmerAIAdvisorySystem.git — useless for a hard-drive submission; GitHub-style README (6 signals: badges, contributing/license sections, fork/PR language) |

**Findings for `7b_readme_quality`:**

- `{"issue": "README tells user to 'git clone' from https://github.com/yourusername/FarmerAIAdvisorySystem.git — useless for a hard-drive submission"}`
- `{"issue": "GitHub-style README (6 signals: badges, contributing/license sections, fork/PR language)"}`

**Reproduce these failures:**

```
python audit.py <root> --single C12
```

### C13-DEVELOPMENT OF STUDENT INFORMATION PLATFORM

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C13-DEVELOPMENT OF STUDENT INFORMATION PLATFORM`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (source code/requirements.txt) |
| `4_imports_declared` | **PASS** | All 1 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C14-SALES FORECASTING SYSTEM

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C14-SALES FORECASTING SYSTEM`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (requirements.txt, source_code/requirements.txt.txt) |
| `4_imports_declared` | **PASS** | All 5 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C15-EDUBOT

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C15-EDUBOT`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source_Code/requirements.txt) |
| `4_imports_declared` | **PASS** | All 6 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C16

- **Stack**: `empty`
- **Verdict**: **SKIPPED**
- **Path**: `D:\CSE-C\C16`
- **Notes**: Empty folder (no files)

| Check | Status | Detail |
|---|---|---|

### C17-EAILS

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C17-EAILS`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (requirements.txt) |
| `4_imports_declared` | **PASS** | All 12 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C18-SIGN LANGUAGE TO TEXT

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C18-SIGN LANGUAGE TO TEXT`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source_Code/requirements.txt); no third-party imports |
| `4_imports_declared` | **N/A** | No third-party imports to declare |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C19-SMART CAMPUS NAVIGATION

- **Stack**: `flutter`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C19-SMART CAMPUS NAVIGATION`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | pubspec.yaml present (SOURCE CODE/pubspec.yaml) |
| `4_imports_declared` | **N/A** | Dart import analysis not supported; manifest checked |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C2

- **Stack**: `empty`
- **Verdict**: **SKIPPED**
- **Path**: `D:\CSE-C\C2`
- **Notes**: Empty folder (no files)

| Check | Status | Detail |
|---|---|---|

### C20-E-GOVERNANCE

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C20-E-GOVERNANCE`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (requirements.txt, Source_Code/requirements.txt, Source_Code/egovernance_project/requirements.txt) |
| `4_imports_declared` | **PASS** | All 1 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C21-RESUME ANALYZER

- **Stack**: `both`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C21-RESUME ANALYZER`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source_Code/backend/requirements.txt) |
| `4_imports_declared` | **PASS** | All 7 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C22-LIVE SCORE X

- **Stack**: `both`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C22-LIVE SCORE X`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (02_Source_Code/livescoreX/requirements.txt) |
| `4_imports_declared` | **PASS** | All 1 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.txt |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C3-PNEUMONIA DETECTION

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C3-PNEUMONIA DETECTION`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source code/requirements.txt) |
| `4_imports_declared` | **PASS** | All 4 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C4-STUDENT ACADEMIC PERFORMANCE VISUALIZATION SYSTEM

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C4-STUDENT ACADEMIC PERFORMANCE VISUALIZATION SYSTEM`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source_Code/requirements.txt) |
| `4_imports_declared` | **PASS** | All 7 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C5

- **Stack**: `empty`
- **Verdict**: **SKIPPED**
- **Path**: `D:\CSE-C\C5`
- **Notes**: Empty folder (no files)

| Check | Status | Detail |
|---|---|---|

### C6-REALTIME ATTENDANCE WITH FACE RECOGNITION

- **Stack**: `python`
- **Verdict**: **REJECTED**
- **Path**: `D:\CSE-C\C6-REALTIME ATTENDANCE WITH FACE RECOGNITION`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **FAIL** | Third-party imports detected (cv2, flask, insightface, numpy, sklearn, ultralytics) but no requirements.txt or pyproject.toml |
| `4_imports_declared` | **FAIL** | Undeclared imports: cv2, flask, insightface, numpy, sklearn, ultralytics |
| `7_readme` | **PASS** | Found README.md.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

**Findings for `4_imports_declared`:**

- `{"import": "cv2"}`
- `{"import": "flask"}`
- `{"import": "insightface"}`
- `{"import": "numpy"}`
- `{"import": "sklearn"}`
- `{"import": "ultralytics"}`

**Reproduce these failures:**

```
python audit.py <root> --single "C6-REALTIME ATTENDANCE WITH FACE RECOGNITION"
```

### C7

- **Stack**: `empty`
- **Verdict**: **SKIPPED**
- **Path**: `D:\CSE-C\C7`
- **Notes**: Empty folder (no files)

| Check | Status | Detail |
|---|---|---|

### C8-Intelligent College Recommendation System

- **Stack**: `both`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C8-Intelligent College Recommendation System`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (Source_code/requirements.txt.txt) |
| `4_imports_declared` | **PASS** | All 4 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |

### C9-VOICE BASED VIRTUAL ASSISTANT

- **Stack**: `python`
- **Verdict**: **ACCEPTED**
- **Path**: `D:\CSE-C\C9-VOICE BASED VIRTUAL ASSISTANT`

| Check | Status | Detail |
|---|---|---|
| `1_abs_paths` | **PASS** | No absolute paths found |
| `2_external_refs` | **PASS** | No external references |
| `3_manifest` | **PASS** | Manifest present (requirements.txt) |
| `4_imports_declared` | **PASS** | All 9 third-party import(s) declared |
| `7_readme` | **PASS** | Found README.md |
| `7b_readme_quality` | **PASS** | README has installation and execution instructions |
