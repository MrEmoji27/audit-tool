#!/usr/bin/env python3
"""audit.py -- self-contained verification for student mini-projects.

Audits each project in a root directory against a 7-point rubric and
produces an incremental Markdown + CSV report. Binary verdict per project:
ACCEPTED or REJECTED.

Windows-native. Python 3.11+. Stdlib + colorama only.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("audit")

# Set to True via --strict; makes file-read failures visible as check findings
AUDIT_STRICT: bool = False

try:
    from colorama import Fore, Style, init as colorama_init
except ImportError:
    class _Dummy:
        def __getattr__(self, _):
            return ""
    Fore = Style = _Dummy()

    def colorama_init(**_):
        pass


# ============================================================
# Config / constants
# ============================================================

EXCLUDE_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".next", ".svelte-kit", "coverage",
    ".pytest_cache", ".mypy_cache", ".tox", "env",
    "staticfiles", "static", "vendor", "bower_components",
    "docs", "doc",
    "ios", "android", ".dart_tool", "macos", "linux", "windows",
    "ephemeral", ".symlinks",
    ".ipynb_checkpoints",
}

EXCLUDE_DIRS_LOWER = {d.lower() for d in EXCLUDE_DIRS}

EXCLUDE_DIR_KEYWORDS = {
    "video", "execution", "documentation", "software", "softwares",
    "demo", "screenshots", "recordings", "installer",
    "hf_cache", "model_cache", "release",
}

MAX_FILE_SIZE = 512 * 1024  # 512 KB — skip minified / vendored files

CODE_CONFIG_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".ini", ".cfg", ".toml",
    ".html", ".css", ".scss", ".dart",
}

JS_EXTS = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}

# Windows drive paths: guarded against URL schemes (http:, file:) by excluding a
# preceding letter. Unix paths: guarded against relative paths like `../Users/`
# or `./home/` by excluding preceding letter, digit, `.`, `/`, `\`.
ABS_PATH_PATTERNS = [
    (re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"), "Windows drive path"),
    (re.compile(r"(?<![A-Za-z0-9./\\])/home/"), "Unix /home/ path"),
    (re.compile(r"(?<![A-Za-z0-9./\\])/Users/"), "Unix /Users/ path"),
    (re.compile(r"(?<![A-Za-z0-9./\\])/mnt/"), "Unix /mnt/ path"),
    (re.compile(r"(?<![A-Za-z0-9./\\])/root/"), "Unix /root/ path"),
]

README_PREFIX_LOWER = "readme"

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster",
    "console", "constants", "crypto", "dgram", "diagnostics_channel",
    "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl",
    "stream", "string_decoder", "sys", "timers", "tls",
    "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib",
    "fs/promises", "stream/promises", "stream/web",
    "timers/promises", "dns/promises", "readline/promises",
}

JS_STRING_RE = re.compile(
    r"""(?P<quote>['"`])(?P<body>(?:\\.|(?!(?P=quote)).)*)(?P=quote)""",
    re.DOTALL,
)

JS_IMPORT_RE = re.compile(
    r"""
    (?:
      import\s+(?:type\s+)?(?:[^'"()]*?\sfrom\s+)?['"]([^'"]+)['"]
      |
      require\s*\(\s*['"]([^'"]+)['"]\s*\)
      |
      import\s*\(\s*['"]([^'"]+)['"]\s*\)
    )
    """,
    re.VERBOSE,
)

DOTDOT_RE = re.compile(r"\.\.[\\/]")

# Leave headroom under Windows 260-char MAX_PATH
PATH_LENGTH_LIMIT = 240

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Common Python import -> PyPI package aliases (avoids false positives on Check 4)
# Values can be a single string or a list of possible package names.
# ALL KEYS MUST BE LOWERCASE — the lookup at check time does imp.lower().
IMPORT_TO_PACKAGE_ALIASES: dict[str, str | list[str]] = {
    # Imaging
    "pil": "pillow",
    "image": "pillow",
    "cv2": ["opencv-python", "opencv-contrib-python", "opencv-python-headless"],
    "skimage": "scikit-image",
    "wand": "wand",
    "fitz": "pymupdf",
    # ML / AI
    "sklearn": "scikit-learn",
    "whisper": "openai-whisper",
    "langchain_community": "langchain-community",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "sentence_transformers": "sentence-transformers",
    "huggingface_hub": "huggingface-hub",
    "xgboost": "xgboost",
    "tf_keras": "tf-keras",
    "absl": "absl-py",
    # Data / parsing
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "rapidfuzz": "rapidfuzz",
    "ruamel": "ruamel.yaml",
    # Database
    "mysql": ["mysql-connector-python", "mysqlclient", "pymysql"],
    "mysqldb": "mysqlclient",
    "psycopg2": ["psycopg2", "psycopg2-binary"],
    "psycopg": "psycopg",
    "pymongo": "pymongo",
    "bson": "pymongo",
    # Web
    "jwt": "pyjwt",
    "jose": "python-jose",
    "flask_cors": "flask-cors",
    "flask_sqlalchemy": "flask-sqlalchemy",
    "flask_login": "flask-login",
    "flask_mail": "flask-mail",
    "flask_migrate": "flask-migrate",
    "flask_wtf": "flask-wtf",
    "flask_restful": "flask-restful",
    "flask_socketio": "flask-socketio",
    "flask_bcrypt": "flask-bcrypt",
    "flask_session": "flask-session",
    "flask_sock": "flask-sock",
    "rest_framework": "djangorestframework",
    "corsheaders": "django-cors-headers",
    "requests_oauthlib": "requests-oauthlib",
    # Google
    "google": ["google-api-python-client", "google-generativeai",
               "google-cloud-storage", "google-auth", "googleapis-common-protos",
               "google-cloud-bigquery", "google-cloud-firestore"],
    "googleapiclient": "google-api-python-client",
    # Crypto / security
    "crypto": "pycryptodome",
    "cryptodome": "pycryptodomex",
    "openssl": "pyopenssl",
    "nacl": "pynacl",
    "bcrypt": "bcrypt",
    "passlib": "passlib",
    # System / hardware
    "serial": "pyserial",
    "usb": "pyusb",
    "win32com": "pywin32",
    "win32api": "pywin32",
    "win32gui": "pywin32",
    "pythoncom": "pywin32",
    "comtypes": "comtypes",
    "pyttsx3": "pyttsx3",
    "pyautogui": "pyautogui",
    "pyaudio": "pyaudio",
    "wx": "wxpython",
    "pkg_resources": "setuptools",
    # Audio / speech / video
    "speech_recognition": "speechrecognition",
    "gtts": "gtts",
    "pydub": "pydub",
    "moviepy": "moviepy",
    "playsound": "playsound",
    # Search / web scraping
    "ddgs": "duckduckgo-search",
    "playwright": "playwright",
    "selenium": "selenium",
    # Networking / API / gRPC
    "dns": "dnspython",
    "magic": "python-magic",
    "gi": "pygobject",
    "telegram": "python-telegram-bot",
    "tweepy": "tweepy",
    "instaloader": "instaloader",
    "discord": "discord.py",
    "grpc": "grpcio",
    "grpc_tools": "grpcio-tools",
    # Misc utilities
    "colorama": "colorama",
    "tqdm": "tqdm",
    "rich": "rich",
    "click": "click",
    "typer": "typer",
    "pydantic": "pydantic",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "starlette": "starlette",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "websockets": "websockets",
    "socketio": "python-socketio",
    "celery": "celery",
    "redis": "redis",
    "boto3": "boto3",
    "stripe": "stripe",
    "razorpay": "razorpay",
    "twilio": "twilio",
    "levenshtein": "python-levenshtein",
    "apscheduler": "apscheduler",
}
# Normalise to lowercase — lookup is always imp.lower() so keys must match
IMPORT_TO_PACKAGE_ALIASES = {k.lower(): v for k, v in IMPORT_TO_PACKAGE_ALIASES.items()}

# Packages that are well-known transitive dependencies of another package.
# If the parent is declared, the child import is considered covered.
TRANSITIVE_DEPS: dict[str, set[str]] = {
    # Web frameworks
    "flask": {"werkzeug", "jinja2", "click", "markupsafe", "itsdangerous", "blinker"},
    "django": {"asgiref", "sqlparse", "pytz"},
    "fastapi": {"starlette", "pydantic", "anyio", "httptools", "uvloop"},
    "uvicorn": {"click", "h11", "httptools"},
    "djangorestframework": {"django"},
    "flask-sqlalchemy": {"sqlalchemy"},
    "flask-login": {"werkzeug"},
    "flask-wtf": {"wtforms"},
    "flask-migrate": {"alembic"},
    # ML / AI
    "torch": {"numpy"},
    "tensorflow": {"numpy", "keras", "h5py", "absl", "tensorboard"},
    "tf-keras": {"keras"},
    "transformers": {"numpy", "requests", "tqdm", "filelock", "tokenizers",
                     "safetensors", "huggingface-hub"},
    "scikit-learn": {"numpy", "scipy", "joblib", "threadpoolctl"},
    "xgboost": {"numpy", "scipy"},
    "lightgbm": {"numpy", "scipy"},
    "keras": {"numpy"},
    "openai": {"httpx", "pydantic", "tqdm"},
    "langchain": {"pydantic", "requests", "numpy", "aiohttp", "tenacity"},
    # Data
    "pandas": {"numpy", "pytz", "dateutil"},
    "matplotlib": {"numpy", "pyparsing", "cycler", "kiwisolver", "PIL"},
    "seaborn": {"numpy", "matplotlib", "pandas"},
    "scipy": {"numpy"},
    "plotly": {"tenacity"},
    # Computer vision
    "deepface": {"numpy", "opencv-python", "PIL", "keras"},
    "mediapipe": {"numpy"},
    "ultralytics": {"numpy", "opencv-python", "PIL", "torch", "tqdm", "matplotlib"},
    "insightface": {"numpy", "opencv-python"},
    # Audio / speech
    "openai-whisper": {"numpy", "torch", "tqdm"},
    "pyttsx3": {"comtypes", "pywin32"},
    # Web scraping
    "requests": {"urllib3", "certifi", "charset-normalizer", "idna"},
    "beautifulsoup4": {"soupsieve"},
    "selenium": {"urllib3", "certifi"},
    # Database
    "sqlalchemy": {"greenlet"},
    "pymongo": {"bson", "gridfs"},
    # Misc
    "boto3": {"botocore", "s3transfer", "jmespath"},
    "celery": {"kombu", "billiard", "vine"},
    "pydantic": {"annotated-types", "typing-extensions"},
    "rich": {"pygments", "markdown-it-py"},
}

ALL_CHECK_KEYS = [
    "1_abs_paths", "2_external_refs", "3_manifest",
    "4_imports_declared", "5_install", "6_runs", "7_readme",
    "7b_readme_quality", "8_tests", "9_env_example",
]

# Points awarded per check (N/A and absent checks count as full marks)
# 8_tests is N/A when no test files exist, so projects without tests are not penalised
# 9_env_example is N/A when no env var usage is detected
CHECK_WEIGHTS: dict[str, int] = {
    "1_abs_paths":        15,
    "2_external_refs":    15,
    "3_manifest":         15,
    "4_imports_declared": 15,
    "5_install":          10,
    "6_runs":             10,
    "7_readme":            5,
    "7b_readme_quality":   5,
    "8_tests":            10,
    "9_env_example":       5,
}
TOTAL_WEIGHT: int = sum(CHECK_WEIGHTS.values())  # 105

_RUBRIC_CHECK_KEYS = frozenset(ALL_CHECK_KEYS)
assert CHECK_WEIGHTS.keys() == _RUBRIC_CHECK_KEYS, (
    f"rubric drift: weights={sorted(CHECK_WEIGHTS)}, expected={sorted(_RUBRIC_CHECK_KEYS)}"
)
assert TOTAL_WEIGHT == 105, f"CHECK_WEIGHTS sum is {TOTAL_WEIGHT}, expected 105"

# Python entry-point discovery priority (top-level first, then tree walk)
PY_ENTRY_TOP_LEVEL = ["main.py", "app.py", "run.py"]

# Node entry-point fallback priority (after npm start script and main field)
NODE_ENTRY_FALLBACK = ["index.js", "server.js", "app.js"]

# Targeted error substrings (Check 6) -- these mean "not self-contained"
PY_TARGETED_ERRORS = ["ModuleNotFoundError", "ImportError", "SyntaxError"]
NODE_TARGETED_ERRORS = ["Cannot find module", "MODULE_NOT_FOUND", "SyntaxError"]

# Environment variable usage patterns (Check 9)
ENV_USAGE_PY_RE = re.compile(
    r'os\.environ\[|os\.getenv\s*\(|load_dotenv\s*\(|dotenv\.load\s*\('
)
ENV_USAGE_JS_RE = re.compile(r'process\.env\.')
ENV_EXAMPLE_NAMES = frozenset({'.env.example', '.env.sample', '.env.template', '.env.default'})

# Extraction regexes — pull the actual variable name out of each usage (Check 9 detail reporting)
ENV_VARNAME_PY_RE = re.compile(
    r'(?:os\.environ\.get|os\.getenv)\s*\(\s*["\'](\w+)["\']'
    r'|os\.environ\s*\[\s*["\'](\w+)["\']\s*\]'
)
ENV_VARNAME_JS_RE = re.compile(r'process\.env\.([A-Z_][A-Z0-9_]*)')

# Minimum README content thresholds (Check 7b)
README_MIN_CHARS = 150
README_MIN_LINES = 5

# Timeouts (seconds)
# PIP_INSTALL_TIMEOUT is intentionally large: student projects often include
# heavy ML deps (torch, tensorflow, transformers) that need >3 min on a cold cache.
VENV_CREATE_TIMEOUT = 120
PIP_INSTALL_TIMEOUT = 600
NPM_INSTALL_TIMEOUT = 300
RUN_TIMEOUT = 15
TEST_RUNNER_TIMEOUT = 120

# Temp-dir root: set AUDIT_TMP to a short path (e.g. C:\T) to avoid Windows
# MAX_PATH issues when venv + node_modules nesting exceeds 260 chars.
_AUDIT_TMP_ROOT: str | None = os.environ.get("AUDIT_TMP")


# ============================================================
# Data model
# ============================================================

@dataclass
class CheckResult:
    key: str
    passed: bool
    na: bool = False
    detail: str = ""
    findings: list = field(default_factory=list)
    # Raw subprocess output — populated by check_install / check_runs for the logs block
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)

    @property
    def status(self) -> str:
        if self.na:
            return "N/A"
        return "PASS" if self.passed else "FAIL"


@dataclass
class ProjectResult:
    name: str
    path: Path
    stack: str
    checks: dict = field(default_factory=dict)
    verdict: str = ""
    score: int = 0
    notes: list = field(default_factory=list)
    logs: dict = field(default_factory=dict)
    duplicate_of: str = ""
    duplicate_info: dict = field(default_factory=dict)
    max_score: int = TOTAL_WEIGHT  # denominator; 75 when --only-static skips dynamic checks

    def add(self, c: CheckResult) -> None:
        self.checks[c.key] = c


# ============================================================
# Environment verification
# ============================================================

def verify_environment() -> dict:
    info: dict = {}
    if sys.version_info < (3, 11):
        print(f"{Fore.RED}ERROR: Python 3.11+ required "
              f"(have {sys.version.split()[0]}){Style.RESET_ALL}")
        sys.exit(2)
    info["python"] = sys.version.split()[0]
    try:
        r = subprocess.run(
            ["node", "--version"], capture_output=True, text=True,
            timeout=5, creationflags=CREATE_NO_WINDOW,
        )
        info["node_ok"] = (r.returncode == 0)
        info["node_version"] = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        info["node_ok"] = False
        info["node_version"] = ""
    try:
        r = subprocess.run(
            "npm --version", capture_output=True, text=True,
            timeout=5, shell=True, creationflags=CREATE_NO_WINDOW,
        )
        info["npm_ok"] = (r.returncode == 0)
        info["npm_version"] = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        info["npm_ok"] = False
        info["npm_version"] = ""
    return info


# ============================================================
# File iteration / stack detection
# ============================================================

VENV_MARKER_FILES = {"pyvenv.cfg", "activate", "activate.bat"}

_CHECKPOINT_RE = re.compile(r'^checkpoint-\d+$', re.IGNORECASE)

def _should_exclude_dir(name: str) -> bool:
    low = name.lower()
    if low in EXCLUDE_DIRS_LOWER:
        return True
    if _CHECKPOINT_RE.match(name):
        return True
    for kw in EXCLUDE_DIR_KEYWORDS:
        if kw in low:
            return True
    return False


def _is_venv_dir(d: Path) -> bool:
    return (d / "pyvenv.cfg").exists()


def iter_project_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not _should_exclude_dir(d)
            and not _is_venv_dir(Path(dirpath) / d)
        ]
        for f in filenames:
            yield Path(dirpath) / f


_SINGLE_PROJECT_MANIFESTS = {"requirements.txt", "pyproject.toml", "package.json", "pubspec.yaml"}
_SINGLE_PROJECT_SUFFIXES  = {".py", ".ipynb", ".js", ".ts", ".mjs", ".cjs"}


def _is_single_project_dir(p: Path) -> bool:
    """Return True if *p* looks like a single project (has manifest or source files at top level)."""
    try:
        for entry in p.iterdir():
            if entry.is_file():
                if entry.name.lower() in _SINGLE_PROJECT_MANIFESTS:
                    return True
                if entry.suffix.lower() in _SINGLE_PROJECT_SUFFIXES:
                    return True
    except OSError:
        return False
    return False


def detect_stack(proj: Path) -> str:
    has_pkg = has_req = has_pyproj = has_py = has_pubspec = False
    for f in iter_project_files(proj):
        name = f.name.lower()
        if name == "package.json":
            has_pkg = True
        elif name in ("requirements.txt", "requirements.txt.txt"):
            has_req = True
        elif name == "pyproject.toml":
            has_pyproj = True
        elif name == "pubspec.yaml":
            has_pubspec = True
        elif f.suffix in (".py", ".ipynb"):
            has_py = True
    if has_pubspec:
        return "flutter"
    is_py = has_req or has_pyproj or has_py
    is_node = has_pkg
    if is_py and is_node:
        return "both"
    if is_py:
        return "python"
    if is_node:
        return "node"
    return "unknown"


# ============================================================
# Check 1: absolute paths
# ============================================================

def _scan_lines_for_abs_paths(
    lines: list[str], rel_path: str, findings: list[dict],
) -> None:
    for lineno, line in enumerate(lines, start=1):
        for pat, label in ABS_PATH_PATTERNS:
            if pat.search(line):
                findings.append({
                    "file": rel_path,
                    "line": lineno,
                    "pattern": label,
                    "content": line.strip()[:200],
                })
                break


def check_abs_paths(proj: Path) -> CheckResult:
    findings = []
    for f in iter_project_files(proj):
        ext = f.suffix.lower()
        rel = str(f.relative_to(proj)).replace("\\", "/")
        if ext == ".ipynb":
            try:
                if f.stat().st_size > MAX_FILE_SIZE * 4:
                    continue
                data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Skipping notebook %s: %s", f, e)
                if AUDIT_STRICT:
                    findings.append({"file": str(rel), "issue": f"unreadable: {e}"})
                continue
            for cell in data.get("cells", []):
                if cell.get("cell_type") != "code":
                    continue
                source = cell.get("source", [])
                if isinstance(source, list):
                    code_lines = [l.rstrip("\n") for l in source]
                else:
                    code_lines = source.split("\n")
                _scan_lines_for_abs_paths(code_lines, rel, findings)
            continue
        if ext not in CODE_CONFIG_EXTS:
            continue
        try:
            if f.stat().st_size > MAX_FILE_SIZE:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.debug("Skipping unreadable file %s: %s", f, e)
            if AUDIT_STRICT:
                findings.append({"file": str(rel), "issue": f"unreadable: {e}"})
            continue
        _scan_lines_for_abs_paths(text.splitlines(), rel, findings)
    if findings:
        return CheckResult(
            "1_abs_paths", False,
            detail=f"{len(findings)} absolute path occurrence(s) found",
            findings=findings,
        )
    return CheckResult("1_abs_paths", True, detail="No absolute paths found")


# ============================================================
# Check 2: external file references
# ============================================================

def extract_py_strings(py_file: Path) -> list[tuple[int, str]]:
    try:
        if py_file.stat().st_size > MAX_FILE_SIZE:
            return []
        src = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(py_file))
    except OSError as e:
        logger.debug("Cannot read %s: %s", py_file, e)
        return []
    except SyntaxError as e:
        logger.debug("Syntax error in %s: %s", py_file, e)
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def extract_js_strings(js_file: Path) -> list[tuple[int, str]]:
    try:
        if js_file.stat().st_size > MAX_FILE_SIZE:
            return []
        text = js_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.debug("Cannot read %s: %s", js_file, e)
        return []
    out: list[tuple[int, str]] = []
    for m in JS_STRING_RE.finditer(text):
        body = m.group("body") or ""
        lineno = text.count("\n", 0, m.start()) + 1
        out.append((lineno, body))
    return out


def path_escapes(file_dir: Path, path_literal: str, project_root: Path) -> bool:
    try:
        norm = path_literal.replace("\\", "/")
        if "://" in norm:
            return False
        candidate = (file_dir / norm).resolve()
        root_resolved = project_root.resolve()
        try:
            candidate.relative_to(root_resolved)
            return False
        except ValueError:
            return True
    except Exception:
        return False


def check_external_refs(proj: Path) -> CheckResult:
    findings = []
    proj_resolved = proj.resolve()
    for f in iter_project_files(proj):
        ext = f.suffix.lower()
        if ext == ".py":
            strings = extract_py_strings(f)
        elif ext in JS_EXTS:
            strings = extract_js_strings(f)
        else:
            continue
        for lineno, s in strings:
            if not s or len(s) > 500:
                continue
            if not DOTDOT_RE.search(s):
                continue
            if any(c in s for c in "\n\r\t\0"):
                continue
            if path_escapes(f.parent, s, proj_resolved):
                findings.append({
                    "file": str(f.relative_to(proj)).replace("\\", "/"),
                    "line": lineno,
                    "literal": s[:200],
                })
    if findings:
        return CheckResult(
            "2_external_refs", False,
            detail=f"{len(findings)} external reference(s) escape project root",
            findings=findings,
        )
    return CheckResult("2_external_refs", True, detail="No external references")


# ============================================================
# Python manifest + import analysis
# ============================================================

def parse_requirements_txt(req: Path) -> set[str]:
    deps: set[str] = set()
    try:
        text = req.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return deps
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)", line)
        if m:
            deps.add(m.group(1).lower().replace("_", "-"))
    return deps


def parse_pyproject_toml(pp: Path) -> set[str]:
    deps: set[str] = set()
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return deps
    project = data.get("project") or {}
    for d in project.get("dependencies") or []:
        m = re.match(r"([A-Za-z0-9_.\-]+)", d)
        if m:
            deps.add(m.group(1).lower().replace("_", "-"))
    for grp in (project.get("optional-dependencies") or {}).values():
        for d in grp:
            m = re.match(r"([A-Za-z0-9_.\-]+)", d)
            if m:
                deps.add(m.group(1).lower().replace("_", "-"))
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name in (poetry.get("dependencies") or {}).keys():
        if name.lower() != "python":
            deps.add(name.lower().replace("_", "-"))
    for name in (poetry.get("dev-dependencies") or {}).keys():
        deps.add(name.lower().replace("_", "-"))
    return deps


def get_py_declared_deps(proj: Path) -> tuple[set[str], list[str]]:
    deps: set[str] = set()
    manifest_paths: list[str] = []
    for f in iter_project_files(proj):
        name = f.name.lower()
        rel = str(f.relative_to(proj)).replace("\\", "/")
        if name in ("requirements.txt", "requirements.txt.txt"):
            deps |= parse_requirements_txt(f)
            manifest_paths.append(rel)
        elif name == "pyproject.toml":
            deps |= parse_pyproject_toml(f)
            manifest_paths.append(rel)
    return deps, manifest_paths


def get_py_local_modules(proj: Path) -> set[str]:
    locals_: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(proj):
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]
        for f in filenames:
            if f.endswith(".py"):
                locals_.add(f[:-3])
        for d in dirnames:
            sub = Path(dirpath) / d
            has_init = (sub / "__init__.py").exists()
            try:
                has_py = any(f.endswith(".py") for f in os.listdir(sub))
            except OSError:
                has_py = False
            if has_init or has_py:
                locals_.add(d)
    return locals_


def _ignored_third_party_import(full_name: str) -> bool:
    """Ignore imports that are environment-specific and not required in manifests."""
    if full_name.startswith("google.colab"):
        return True
    return False


def _extract_imports_from_source(src: str, filename: str = "<string>") -> set[str]:
    imports: set[str] = set()
    try:
        tree = ast.parse(src, filename=filename)
    except SyntaxError as e:
        logger.debug("Syntax error parsing imports from %s: %s", filename, e)
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                full_name = alias.name
                if _ignored_third_party_import(full_name):
                    continue
                imports.add(full_name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if (node.level or 0) > 0:
                continue
            if node.module:
                full_name = node.module
                if _ignored_third_party_import(full_name):
                    continue
                imports.add(full_name.split(".")[0])
    return imports


def _collect_notebook_imports(nb_file: Path) -> set[str]:
    try:
        if nb_file.stat().st_size > MAX_FILE_SIZE * 4:
            return set()
        data = json.loads(nb_file.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Cannot parse notebook %s: %s", nb_file, e)
        return set()
    imports: set[str] = set()
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            code = "".join(source)
        else:
            code = source
        imports |= _extract_imports_from_source(code, str(nb_file))
    return imports


def collect_py_imports(proj: Path) -> set[str]:
    imports: set[str] = set()
    for f in iter_project_files(proj):
        if f.suffix == ".py":
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logger.debug("Skipping unreadable source %s: %s", f, e)
                continue
            imports |= _extract_imports_from_source(src, str(f))
        elif f.suffix == ".ipynb":
            imports |= _collect_notebook_imports(f)
    return imports


def norm_pkg(name: str) -> str:
    return name.lower().replace("_", "-")


def check_manifest_and_imports_py(proj: Path) -> tuple[CheckResult, CheckResult]:
    imports = collect_py_imports(proj)
    locals_ = get_py_local_modules(proj)
    stdlib = set(sys.stdlib_module_names)
    third_party = sorted(i for i in imports if i not in stdlib and i not in locals_)
    deps, manifest_paths = get_py_declared_deps(proj)

    if not third_party:
        if manifest_paths:
            c3 = CheckResult(
                "3_manifest", True,
                detail=f"Manifest present ({', '.join(manifest_paths)}); no third-party imports",
            )
        else:
            c3 = CheckResult(
                "3_manifest", True, na=True,
                detail="No third-party imports; manifest not required (stdlib-only)",
            )
        c4 = CheckResult(
            "4_imports_declared", True, na=True,
            detail="No third-party imports to declare",
        )
        return c3, c4

    if not manifest_paths:
        c3 = CheckResult(
            "3_manifest", False,
            detail=(
                f"Third-party imports detected ({', '.join(third_party)}) "
                f"but no requirements.txt or pyproject.toml"
            ),
        )
    else:
        c3 = CheckResult(
            "3_manifest", True,
            detail=f"Manifest present ({', '.join(manifest_paths)})",
        )

    normalized_deps = {norm_pkg(d) for d in deps}
    # Build set of imports covered by transitive dependencies
    transitive_covered: set[str] = set()
    for parent_pkg, children in TRANSITIVE_DEPS.items():
        if norm_pkg(parent_pkg) in normalized_deps:
            transitive_covered |= {norm_pkg(c) for c in children}
    missing = []
    for imp in third_party:
        if norm_pkg(imp) in transitive_covered:
            continue
        candidates = {norm_pkg(imp)}
        alias = IMPORT_TO_PACKAGE_ALIASES.get(imp.lower())
        if alias:
            if isinstance(alias, list):
                candidates.update(norm_pkg(a) for a in alias)
            else:
                candidates.add(norm_pkg(alias))
        if not candidates & normalized_deps:
            missing.append(imp)
    if missing:
        c4 = CheckResult(
            "4_imports_declared", False,
            detail=f"Undeclared imports: {', '.join(missing)}",
            findings=[{"import": m} for m in missing],
        )
    else:
        c4 = CheckResult(
            "4_imports_declared", True,
            detail=f"All {len(third_party)} third-party import(s) declared",
        )
    return c3, c4


# ============================================================
# Node manifest + import analysis
# ============================================================

def node_package_name(spec: str) -> Optional[str]:
    if not spec:
        return None
    if spec.startswith((".", "/")):
        return None
    if spec.startswith("node:"):
        return None
    if spec.startswith("@"):
        parts = spec.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return None
    return spec.split("/")[0]


def _find_package_json(proj: Path) -> Optional[Path]:
    root_pkg = proj / "package.json"
    if root_pkg.exists():
        return root_pkg
    for f in iter_project_files(proj):
        if f.name.lower() == "package.json":
            return f
    return None


def check_manifest_and_imports_node(proj: Path) -> tuple[CheckResult, CheckResult]:
    pkg_path = _find_package_json(proj)
    if pkg_path is None:
        return (
            CheckResult("3_manifest", False, detail="package.json missing"),
            CheckResult("4_imports_declared", False, detail="No manifest to check against"),
        )
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        return (
            CheckResult("3_manifest", False, detail=f"package.json invalid JSON: {e}"),
            CheckResult("4_imports_declared", False, detail="No manifest to check against"),
        )
    declared: dict = {}
    declared.update(data.get("dependencies") or {})
    declared.update(data.get("devDependencies") or {})
    declared_names = set(declared.keys())

    specs: set[str] = set()
    for f in iter_project_files(proj):
        if f.suffix.lower() not in JS_EXTS:
            continue
        try:
            if f.stat().st_size > MAX_FILE_SIZE:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in JS_IMPORT_RE.finditer(text):
            spec = m.group(1) or m.group(2) or m.group(3)
            if spec:
                specs.add(spec)

    needed: set[str] = set()
    for s in specs:
        name = node_package_name(s)
        if name is None:
            continue
        if name in NODE_BUILTINS:
            continue
        needed.add(name)

    if not declared_names:
        c3 = CheckResult(
            "3_manifest", False,
            detail="package.json has no dependencies or devDependencies",
        )
    else:
        c3 = CheckResult(
            "3_manifest", True,
            detail=f"package.json declares {len(declared_names)} dep(s)",
        )

    if not needed:
        c4 = CheckResult(
            "4_imports_declared", True, na=True,
            detail="No external imports to declare",
        )
    else:
        missing = [n for n in sorted(needed) if n not in declared_names]
        if missing:
            c4 = CheckResult(
                "4_imports_declared", False,
                detail=f"Undeclared imports: {', '.join(missing)}",
                findings=[{"import": m} for m in missing],
            )
        else:
            c4 = CheckResult(
                "4_imports_declared", True,
                detail=f"All {len(needed)} external import(s) declared",
            )
    return c3, c4


# ============================================================
# Check 7: README present + quality
# ============================================================

# Patterns that signal a GitHub-style README not suited for submission
GITHUB_STYLE_SIGNALS = [
    re.compile(r"img\.shields\.io/", re.IGNORECASE),
    re.compile(r"badges\.\w+\.io/", re.IGNORECASE),
    re.compile(r"#{1,3}\s*.{0,5}contributing", re.IGNORECASE),
    re.compile(r"#{1,3}\s*.{0,5}license\b", re.IGNORECASE),
    re.compile(r"#{1,3}\s*.{0,5}acknowledgements?\b", re.IGNORECASE),
    re.compile(r"pull\s+request", re.IGNORECASE),
    re.compile(r"open\s+an?\s+issue", re.IGNORECASE),
    re.compile(r"fork\s+(this|the)\s+(repo|repository)", re.IGNORECASE),
    re.compile(r"git\s+clone\s+https?://github\.com/", re.IGNORECASE),
]
GITHUB_STYLE_THRESHOLD = 3

INSTALL_KEYWORDS = [
    "install", "setup", "set up", "set-up", "pip install", "npm install",
    "requirements", "dependencies", "prerequisites", "setup.bat",
    "getting started",
]

RUN_KEYWORDS = [
    "run", "execute", "start", "launch", "open", "python ", "node ",
    "flask run", "npm start", "uvicorn", "localhost", "127.0.0.1",
    "start.bat", "how to use", "usage", "steps to execute",
]


GITHUB_URL_RE = re.compile(
    r'https://github\.com/([\w.-]+)/([\w.-]+)', re.IGNORECASE,
)
GITHUB_CHECK_TIMEOUT = 5  # seconds per URL


def _verify_github_url(url: str) -> tuple[bool, str]:
    """HEAD-request a GitHub URL. Returns (reachable, detail).
    Network failures are non-fatal — returns (True, reason) so offline graders aren't penalised."""
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "audit-tool/1.0"},
        )
        with urllib.request.urlopen(req, timeout=GITHUB_CHECK_TIMEOUT) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"HTTP 404 — repo not found or private"
        return True, f"HTTP {e.code} (non-404, treated as reachable)"
    except Exception as e:
        logger.debug("GitHub URL check failed for %s: %s", url, e)
        return True, f"network check skipped"


def _find_readme(proj: Path) -> Optional[Path]:
    try:
        for item in proj.iterdir():
            if item.is_file() and item.name.lower().startswith(README_PREFIX_LOWER):
                return item
    except Exception:
        pass
    return None


def check_readme(proj: Path) -> tuple[CheckResult, CheckResult]:
    readme = _find_readme(proj)
    if readme is None:
        return (
            CheckResult("7_readme", False, detail="No README at project root"),
            CheckResult("7b_readme_quality", False, detail="No README to evaluate"),
        )

    c7 = CheckResult("7_readme", True, detail=f"Found {readme.name}")

    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return c7, CheckResult(
            "7b_readme_quality", False, detail=f"Could not read README: {e}",
        )

    text_lower = text.lower()
    findings: list[str] = []

    # Minimum content threshold — reject obvious one-liner stubs
    stripped = text.strip()
    meaningful_lines = [l for l in stripped.splitlines() if l.strip()]
    if len(stripped) < README_MIN_CHARS or len(meaningful_lines) < README_MIN_LINES:
        findings.append(
            f"README is too short ({len(stripped)} chars, {len(meaningful_lines)} lines) "
            f"— appears to be a placeholder (min {README_MIN_CHARS} chars / {README_MIN_LINES} lines)"
        )

    # Any git remote operation is invalid in a hard-drive submission
    GIT_REMOTE_RE = re.compile(
        r"git\s+clone\b|git\s+pull\b|git\s+fetch\b", re.IGNORECASE,
    )
    git_match = GIT_REMOTE_RE.search(text)
    if git_match:
        findings.append(
            f"README contains '{git_match.group(0).strip()}' — "
            f"git commands are invalid for a self-contained submission"
        )

    # Check GitHub URLs — informational only, does not affect verdict
    for gh_match in GITHUB_URL_RE.finditer(text):
        url = gh_match.group(0).rstrip(".,)'\"")
        reachable, detail = _verify_github_url(url)
        logger.debug("GitHub URL %s: %s (%s)", "OK" if reachable else "unreachable", url, detail)

    github_hits = sum(1 for p in GITHUB_STYLE_SIGNALS if p.search(text))
    is_github_style = github_hits >= GITHUB_STYLE_THRESHOLD
    if is_github_style:
        findings.append(
            f"GitHub-style README ({github_hits} signals: badges, "
            f"contributing/license sections, fork/PR language)"
        )

    has_install = any(kw in text_lower for kw in INSTALL_KEYWORDS)
    has_run = any(kw in text_lower for kw in RUN_KEYWORDS)

    if not has_install:
        findings.append("No installation instructions found (expected: pip install / npm install / setup steps)")
    if not has_run:
        findings.append("No execution instructions found (expected: python main.py / npm start / uvicorn ...)")

    if findings:
        return c7, CheckResult(
            "7b_readme_quality", False,
            detail="; ".join(findings),
            findings=[{"issue": f} for f in findings],
        )

    return c7, CheckResult(
        "7b_readme_quality", True,
        detail="README has installation and execution instructions",
    )


# ============================================================
# Check 9: .env.example present when env vars are used
# ============================================================

def check_env_example(proj: Path) -> CheckResult:
    """PASS if no env var usage detected, or if .env.example/.env.sample exists alongside usage."""
    key = "9_env_example"
    uses_env = False
    for f in iter_project_files(proj):
        ext = f.suffix.lower()
        if ext in {".py", ".ipynb"}:
            pat = ENV_USAGE_PY_RE
        elif ext in {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}:
            pat = ENV_USAGE_JS_RE
        else:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pat.search(text):
            uses_env = True
            break

    if not uses_env:
        return CheckResult(key, True, na=True, detail="No environment variable usage detected")

    for entry in proj.iterdir():
        if entry.is_file() and entry.name.lower() in ENV_EXAMPLE_NAMES:
            return CheckResult(key, True, detail=f"Found {entry.name}")

    # Second pass: collect variable names and exact locations for the report
    var_names: dict[str, None] = {}  # insertion-ordered deduplicated set
    location_findings: list[dict] = []
    for f in iter_project_files(proj):
        ext = f.suffix.lower()
        if ext in {".py", ".ipynb"}:
            name_re = ENV_VARNAME_PY_RE
        elif ext in {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}:
            name_re = ENV_VARNAME_JS_RE
        else:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(f.relative_to(proj)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in name_re.finditer(line):
                groups = [g for g in m.groups() if g is not None]
                varname = groups[0] if groups else None
                if varname:
                    var_names[varname] = None
                    if len(location_findings) < 20:
                        location_findings.append({"file": rel, "line": lineno, "var": varname})

    findings: list[dict] = []
    if var_names:
        findings.append({
            "action": f"Create .env.example with {len(var_names)} variable(s): {', '.join(var_names)}"
        })
    else:
        findings.append({"action": "Create .env.example listing all required environment variable names"})
    findings.extend(location_findings)
    if len(location_findings) == 20:
        findings.append({"note": "Only first 20 usages shown above"})

    var_list = list(var_names)
    if var_list:
        preview = ", ".join(var_list[:5]) + ("…" if len(var_list) > 5 else "")
        detail = f"No .env.example — {len(var_list)} env var(s) used: {preview}"
    else:
        detail = "Env vars used (os.environ/load_dotenv/process.env) but no .env.example found"

    return CheckResult(key, False, detail=detail, findings=findings)


# ============================================================
# Unpinned dependency helper (informational, part of Check 3)
# ============================================================

def _check_unpinned_deps(proj: Path) -> list[str]:
    """Return list of dependency names in requirements.txt that have no version specifier."""
    unpinned: list[str] = []
    for f in iter_project_files(proj):
        if f.name.lower() not in ("requirements.txt", "requirements.txt.txt"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if not re.search(r"[=<>!~]", line):
                m = re.match(r"([A-Za-z0-9_.\-]+)", line)
                if m:
                    unpinned.append(m.group(1))
    return unpinned


# ============================================================
# Project fingerprint and similarity (duplicate detection)
# ============================================================

_CODE_EXTS = frozenset({".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"})
_PY_COMMENT_RE  = re.compile(r'\s*#.*$',  re.MULTILINE)
_JS_COMMENT_RE  = re.compile(r'\s*//.*$', re.MULTILINE)
_SIM_CONTENT_CAP = 50_000   # chars — bounds SequenceMatcher runtime on huge files
NEAR_DUPE_THRESHOLD = 0.75  # pairwise similarity required to flag as near-duplicate


def _normalize_source(text: str, ext: str) -> str:
    """Strip comments and whitespace so trivial edits don't hide clones."""
    if ext in {'.py', '.ipynb'}:
        text = _PY_COMMENT_RE.sub('', text)
    elif ext in {'.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs'}:
        text = _JS_COMMENT_RE.sub('', text)
    lines = [l.strip().lower() for l in text.splitlines()]
    return '\n'.join(l for l in lines if l)


def _get_normalized_files(proj: Path) -> dict[str, str]:
    """Return {rel_path: normalized_content} for every source file in the project."""
    result: dict[str, str] = {}
    for f in iter_project_files(proj):
        if f.suffix.lower() not in _CODE_EXTS:
            continue
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        rel = str(f.relative_to(proj)).replace('\\', '/')
        result[rel] = _normalize_source(text, f.suffix.lower())
    return result


def _fingerprint_from_norm(norm: dict[str, str]) -> str:
    """SHA-256 of sorted normalized file contents. Returns 16-char hex prefix."""
    h = hashlib.sha256()
    for rel in sorted(norm):
        h.update(norm[rel].encode('utf-8'))
    return h.hexdigest()[:16]


def fingerprint_project(proj: Path) -> str:
    """Public entry-point kept for compatibility — uses normalized content."""
    return _fingerprint_from_norm(_get_normalized_files(proj))


def compute_file_similarity(norm_a: dict[str, str], norm_b: dict[str, str]) -> dict:
    """
    Compare two projects' normalized file sets file-by-file.

    Returns a dict with:
      similarity      — overall 0.0–1.0 score (matched weight / union file count)
      identical_files — files present in both with byte-identical normalized content
      similar_files   — files present in both with ≥ 50% SequenceMatcher ratio
      unique_self     — files only in norm_a
      unique_orig     — files only in norm_b
    """
    keys_a, keys_b = set(norm_a), set(norm_b)
    common = keys_a & keys_b
    total  = len(keys_a | keys_b)

    identical_files: list[str] = []
    similar_files: list[dict]  = []

    for rel in sorted(common):
        ca, cb = norm_a[rel], norm_b[rel]
        if ca == cb:
            identical_files.append(rel)
        else:
            ratio = SequenceMatcher(
                None, ca[:_SIM_CONTENT_CAP], cb[:_SIM_CONTENT_CAP], autojunk=False
            ).ratio()
            if ratio >= 0.5:
                similar_files.append({"file": rel, "similarity": round(ratio, 3)})

    matched   = len(identical_files) + sum(f["similarity"] for f in similar_files)
    similarity = round(matched / total, 3) if total else 0.0

    return {
        "similarity":      similarity,
        "identical_files": identical_files,
        "similar_files":   sorted(similar_files, key=lambda x: x["similarity"], reverse=True),
        "unique_self":     sorted(keys_a - keys_b),
        "unique_orig":     sorted(keys_b - keys_a),
    }


# ============================================================
# Flutter manifest check
# ============================================================

def check_flutter_manifest(proj: Path) -> CheckResult:
    for f in iter_project_files(proj):
        if f.name.lower() == "pubspec.yaml":
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if "dependencies:" in text:
                    rel = str(f.relative_to(proj)).replace("\\", "/")
                    return CheckResult(
                        "3_manifest", True,
                        detail=f"pubspec.yaml present ({rel})",
                    )
                return CheckResult(
                    "3_manifest", False,
                    detail="pubspec.yaml has no dependencies section",
                )
            except Exception as e:
                return CheckResult("3_manifest", False, detail=f"pubspec.yaml unreadable: {e}")
    return CheckResult("3_manifest", False, detail="pubspec.yaml missing")


# ============================================================
# Dynamic checks (5 & 6) — install + run
# ============================================================

# Binary/large file extensions to skip when copying to temp for dynamic checks
_COPY_SKIP_EXTS = {
    ".bin", ".safetensors", ".pt", ".pth", ".ckpt", ".h5", ".pb",
    ".npy", ".npz", ".pkl", ".pickle", ".parquet", ".arrow",
    ".mp4", ".avi", ".mov", ".mkv", ".mp3", ".wav",
    ".zip", ".tar", ".gz", ".7z",
}
_COPY_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MB


def _copytree_ignore(src: str, names: list[str]) -> list[str]:
    ignored = []
    src_path = Path(src)
    for n in names:
        p = src_path / n
        if p.is_dir():
            if n.startswith(".") or _should_exclude_dir(n) or _is_venv_dir(p):
                ignored.append(n)
        elif p.is_file():
            if p.suffix.lower() in _COPY_SKIP_EXTS:
                ignored.append(n)
            elif p.stat().st_size > _COPY_SIZE_LIMIT:
                ignored.append(n)
        else:
            # symlink to missing target, junction, device — skip to be safe
            ignored.append(n)
    return ignored


def _has_main_guard(text: str) -> bool:
    """Return True if *text* has a real top-level `if __name__ == '__main__':` guard.

    Uses ast.parse to avoid matching the pattern in comments or docstrings.
    Falls back to a simple substring check only when the file can't be parsed.
    """
    if len(text) > MAX_FILE_SIZE:
        return "__name__" in text and "__main__" in text
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "__name__" in text and "__main__" in text
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            return True
    return False


def _find_entry_point(proj_copy: Path, stack: str) -> Path | None:
    if stack in ("python", "both"):
        for name in PY_ENTRY_TOP_LEVEL:
            candidate = proj_copy / name
            if candidate.exists():
                return candidate
        for f in sorted(proj_copy.rglob("*.py")):
            if any(p in _SKIP_PARTS for p in f.relative_to(proj_copy).parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if _has_main_guard(text):
                    return f
            except Exception:
                pass
    elif stack == "node":
        pkg = proj_copy / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
                start_script = (data.get("scripts") or {}).get("start")
                if start_script:
                    return pkg  # sentinel: npm start
                main_rel = data.get("main")
                if main_rel:
                    candidate = proj_copy / main_rel
                    if candidate.exists():
                        return candidate
            except Exception:
                pass
        for name in NODE_ENTRY_FALLBACK:
            candidate = proj_copy / name
            if candidate.exists():
                return candidate
    return None


def _last_lines(text: str, n: int = 20) -> str:
    """Return the last *n* non-empty lines of *text* as a single string."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def check_install(proj: Path, stack: str) -> tuple[CheckResult, Path | None]:
    """Check 5: copy project to temp dir, create venv/node_modules, install deps."""
    key = "5_install"
    tmp: Path | None = None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="audit_", dir=_AUDIT_TMP_ROOT))
        dst = tmp / proj.name
        shutil.copytree(proj, dst, ignore=_copytree_ignore)

        if stack in ("python", "both"):
            venv_dir = tmp / ".venv"
            rv = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                capture_output=True, text=True,
                timeout=VENV_CREATE_TIMEOUT, creationflags=CREATE_NO_WINDOW,
            )
            if rv.returncode != 0:
                detail = f"venv creation failed: {rv.stderr[:300].strip()}"
                return CheckResult(key, False, detail=detail,
                                   stdout=rv.stdout, stderr=rv.stderr), tmp
            if sys.platform == "win32":
                pip_exe = venv_dir / "Scripts" / "pip.exe"
            else:
                pip_exe = venv_dir / "bin" / "pip"

            # Walk subdirectories to find manifest (same as Check 3)
            req_file = next(
                (f for f in dst.rglob("requirements.txt")
                 if not any(p in _SKIP_PARTS for p in f.relative_to(dst).parts)),
                None,
            )
            pyproj_file = next(
                (f for f in dst.rglob("pyproject.toml")
                 if not any(p in _SKIP_PARTS for p in f.relative_to(dst).parts)),
                None,
            )
            if req_file is not None:
                install_cmd = [str(pip_exe), "install", "-r", str(req_file),
                               "--quiet", "--no-warn-script-location"]
            elif pyproj_file is not None:
                install_cmd = [str(pip_exe), "install", str(pyproj_file.parent),
                               "--quiet", "--no-warn-script-location"]
            else:
                return CheckResult(key, True, na=True,
                                   detail="No Python manifest; nothing to install"), tmp

            ri = subprocess.run(
                install_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=PIP_INSTALL_TIMEOUT, creationflags=CREATE_NO_WINDOW, cwd=str(dst),
            )
            if ri.returncode != 0:
                tail = _last_lines(ri.stderr or ri.stdout)
                return CheckResult(key, False, detail="pip install failed",
                                   findings=[tail] if tail else [],
                                   stdout=ri.stdout, stderr=ri.stderr), tmp

            # For "both" stacks also install Node deps if package.json is present
            if stack == "both":
                pkg_json = next(
                    (f for f in dst.rglob("package.json")
                     if not any(p in _SKIP_PARTS for p in f.relative_to(dst).parts)),
                    None,
                )
                if pkg_json is not None:
                    npm_prefix = ["cmd", "/c", "npm"] if sys.platform == "win32" else ["npm"]
                    for extra in [["ci", "--quiet"], ["install", "--quiet"]]:
                        rn = subprocess.run(
                            npm_prefix + extra, capture_output=True, text=True,
                            timeout=NPM_INSTALL_TIMEOUT, creationflags=CREATE_NO_WINDOW,
                            cwd=str(pkg_json.parent),
                        )
                        if rn.returncode == 0:
                            break
                    # Non-fatal: Node install failure doesn't block Python verdict
            return CheckResult(key, True, detail="pip install succeeded",
                               stdout=ri.stdout, stderr=ri.stderr), tmp

        elif stack == "node":
            # On Windows npm is a .cmd batch file — must be invoked via cmd /c
            if sys.platform == "win32":
                npm_prefix = ["cmd", "/c", "npm"]
            else:
                npm_prefix = ["npm"]
            last_rn: subprocess.CompletedProcess | None = None
            for extra in [["ci", "--quiet"], ["install", "--quiet"]]:
                last_rn = subprocess.run(
                    npm_prefix + extra, capture_output=True, text=True,
                    timeout=NPM_INSTALL_TIMEOUT, creationflags=CREATE_NO_WINDOW, cwd=str(dst),
                )
                if last_rn.returncode == 0:
                    cmd_used = "npm ci" if "ci" in extra else "npm install"
                    return CheckResult(key, True, detail=f"{cmd_used} succeeded",
                                       stdout=last_rn.stdout, stderr=last_rn.stderr), tmp
            tail = _last_lines((last_rn.stderr if last_rn else "") or "")
            return CheckResult(key, False, detail="npm install failed",
                               findings=[tail] if tail else [],
                               stdout=last_rn.stdout if last_rn else "",
                               stderr=last_rn.stderr if last_rn else ""), tmp

        else:
            return CheckResult(key, True, na=True,
                               detail=f"Stack '{stack}' not checked for install"), tmp

    except subprocess.TimeoutExpired as exc:
        # Partial output may still be available on the exception object
        partial_out = getattr(exc, "stdout", "") or ""
        partial_err = getattr(exc, "stderr", "") or ""
        tail = _last_lines(partial_err or partial_out)
        return CheckResult(key, False,
                           detail=f"Install timed out after {PIP_INSTALL_TIMEOUT}s",
                           findings=[tail] if tail else [],
                           stdout=partial_out, stderr=partial_err), tmp
    except FileNotFoundError as exc:
        return CheckResult(key, False,
                           detail=f"Executable not found: {exc.filename}"), tmp
    except OSError as exc:
        return CheckResult(key, False,
                           detail=f"OS error during install: {exc.strerror} ({exc.filename})"), tmp
    except Exception as exc:
        import traceback as _tb
        logger.exception("check_install unexpected error for %s", proj.name)
        return CheckResult(key, False,
                           detail=f"Install error: {type(exc).__name__}: {exc}",
                           findings=[_tb.format_exc()[-800:]]), tmp


def check_runs(proj: Path, stack: str, tmp_dir: Path | None) -> CheckResult:
    """Check 6: run entry point; PASS if no ImportError/ModuleNotFoundError within timeout."""
    key = "6_runs"
    if tmp_dir is None:
        return CheckResult(key, True, na=True, detail="Skipped — install did not produce a temp dir")

    proj_copy = tmp_dir / proj.name
    if not proj_copy.exists():
        return CheckResult(key, False, detail="Temp copy missing — copytree may have failed")

    try:
        venv_dir = tmp_dir / ".venv"

        if stack in ("python", "both"):
            if venv_dir.exists():
                if sys.platform == "win32":
                    python_exe = venv_dir / "Scripts" / "python.exe"
                else:
                    python_exe = venv_dir / "bin" / "python"
                using_host = False
            else:
                python_exe = Path(sys.executable)
                using_host = True

            entry = _find_entry_point(proj_copy, "python")
            if entry is None:
                return CheckResult(key, True, na=True, detail="No runnable entry point found")

            rr = subprocess.run(
                [str(python_exe), str(entry)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=RUN_TIMEOUT, creationflags=CREATE_NO_WINDOW, cwd=str(proj_copy),
            )
            combined = rr.stdout + rr.stderr
            note = " (using host Python — no venv)" if using_host else ""
            for err_str in PY_TARGETED_ERRORS:
                if err_str in combined:
                    snippet = next((ln for ln in combined.splitlines() if err_str in ln), "")
                    return CheckResult(key, False,
                                       detail=f"{err_str} detected{note}",
                                       findings=[snippet[:300]],
                                       stdout=rr.stdout, stderr=rr.stderr)
            return CheckResult(key, True,
                               detail=f"Ran without import errors{note}",
                               stdout=rr.stdout, stderr=rr.stderr)

        elif stack == "node":
            entry = _find_entry_point(proj_copy, "node")
            if entry is None:
                return CheckResult(key, True, na=True, detail="No runnable entry point found")

            npm_prefix = ["cmd", "/c", "npm"] if sys.platform == "win32" else ["npm"]
            if entry.name == "package.json":
                # Sentinel from _find_entry_point: package.json has a start script
                cmd = npm_prefix + ["start"]
            else:
                cmd = ["node", str(entry)]

            rr = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=RUN_TIMEOUT, creationflags=CREATE_NO_WINDOW, cwd=str(proj_copy),
            )
            combined = rr.stdout + rr.stderr
            for err_str in NODE_TARGETED_ERRORS:
                if err_str in combined:
                    snippet = next((ln for ln in combined.splitlines() if err_str in ln), "")
                    return CheckResult(key, False, detail=f"'{err_str}' detected",
                                       findings=[snippet[:300]],
                                       stdout=rr.stdout, stderr=rr.stderr)
            return CheckResult(key, True, detail="Ran without module errors",
                               stdout=rr.stdout, stderr=rr.stderr)

        else:
            return CheckResult(key, True, na=True, detail=f"Stack '{stack}' not checked for runs")

    except subprocess.TimeoutExpired:
        # App ran for the full timeout without printing module errors → treat as pass
        return CheckResult(key, True,
                           detail=f"App ran for {RUN_TIMEOUT}s without import errors (server-style app)")
    except FileNotFoundError as exc:
        return CheckResult(key, False,
                           detail=f"Executable not found: {exc.filename}")
    except OSError as exc:
        return CheckResult(key, False,
                           detail=f"OS error during run: {exc.strerror} ({exc.filename})")
    except Exception as exc:
        import traceback as _tb
        logger.exception("check_runs unexpected error for %s", proj.name)
        return CheckResult(key, False,
                           detail=f"Run error: {type(exc).__name__}: {exc}",
                           findings=[_tb.format_exc()[-800:]])


# ============================================================
# Check 8: test suite
# ============================================================

_SKIP_PARTS = {".venv", "venv", "env", "node_modules", "__pycache__", ".git"}


def _find_test_files(proj_copy: Path, stack: str) -> list[Path]:
    found: list[Path] = []
    if stack in ("python", "both"):
        for f in proj_copy.rglob("*.py"):
            if any(p in _SKIP_PARTS for p in f.relative_to(proj_copy).parts):
                continue
            name = f.name.lower()
            if name.startswith("test_") or name.endswith("_test.py"):
                found.append(f)
    elif stack == "node":
        for pat in ("**/*.test.js", "**/*.spec.js", "**/*.test.ts", "**/*.spec.ts",
                    "**/__tests__/*.js", "**/__tests__/*.ts"):
            for f in proj_copy.glob(pat):
                if any(p in _SKIP_PARTS for p in f.relative_to(proj_copy).parts):
                    continue
                found.append(f)
    return found


def check_tests(proj: Path, stack: str, tmp_dir: Path | None) -> CheckResult:
    """Check 8: discover and run the project's own test suite."""
    key = "8_tests"
    if tmp_dir is None:
        return CheckResult(key, True, na=True, detail="Skipped — no install workspace")

    proj_copy = tmp_dir / proj.name
    if not proj_copy.exists():
        return CheckResult(key, True, na=True, detail="Temp copy missing")

    test_files = _find_test_files(proj_copy, stack)
    if not test_files:
        return CheckResult(key, True, na=True,
                           detail="No test files found (test_*.py / *_test.py / *.test.js)")

    logger.debug("Found %d test file(s) in %s: %s", len(test_files), proj.name,
                 [str(f.relative_to(proj_copy)) for f in test_files])

    try:
        venv_dir = tmp_dir / ".venv"

        if stack in ("python", "both"):
            if venv_dir.exists():
                if sys.platform == "win32":
                    python_exe = venv_dir / "Scripts" / "python.exe"
                    pip_exe    = venv_dir / "Scripts" / "pip.exe"
                else:
                    python_exe = venv_dir / "bin" / "python"
                    pip_exe    = venv_dir / "bin" / "pip"
            else:
                python_exe = Path(sys.executable)
                pip_exe = None
                logger.warning(
                    "%s: no venv found for check_tests — using host Python (%s); "
                    "result may be unreliable if project has undeclared dependencies",
                    proj.name, python_exe,
                )

            # Ensure pytest is available in the venv
            if pip_exe and pip_exe.exists():
                subprocess.run(
                    [str(pip_exe), "install", "pytest", "--quiet", "--no-warn-script-location"],
                    capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW,
                )

            rr = subprocess.run(
                [str(python_exe), "-m", "pytest", str(proj_copy),
                 "--tb=line", "-q", "--no-header"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TEST_RUNNER_TIMEOUT, creationflags=CREATE_NO_WINDOW,
                cwd=str(proj_copy),
            )

            combined = rr.stdout + rr.stderr

            # pytest exit codes: 0=pass, 1=failures, 2=collection error, 5=no tests collected
            if rr.returncode == 5:
                return CheckResult(key, True, na=True, detail="pytest collected no tests")
            if rr.returncode == 2:
                err_lines = [ln for ln in combined.splitlines() if "ERROR" in ln or "error" in ln.lower()][:5]
                return CheckResult(key, False,
                                   detail="pytest collection error (bad import or conftest)",
                                   findings=err_lines)

            # Parse summary line: "3 passed, 1 failed in 0.12s"
            passed = failed = errored = 0
            for line in reversed(combined.splitlines()):
                pm = re.search(r"(\d+) passed", line)
                fm = re.search(r"(\d+) failed", line)
                em = re.search(r"(\d+) error", line)
                if pm or fm or em:
                    passed  = int(pm.group(1)) if pm else 0
                    failed  = int(fm.group(1)) if fm else 0
                    errored = int(em.group(1)) if em else 0
                    break

            host_note = " (host Python — no isolated venv)" if pip_exe is None else ""
            if rr.returncode == 0:
                return CheckResult(key, True,
                                   detail=f"{passed} test(s) passed{host_note}",
                                   findings=[])
            else:
                total = passed + failed + errored
                detail = []
                if failed:
                    detail.append(f"{failed} failed")
                if errored:
                    detail.append(f"{errored} error(s)")
                if passed and total:
                    detail.append(f"{passed}/{total} passed")
                failing_lines = [
                    ln for ln in combined.splitlines()
                    if "FAILED" in ln or "ERROR" in ln or "AssertionError" in ln
                ][:8]
                fail_detail = (", ".join(detail) or "test suite failed") + host_note
                return CheckResult(key, False,
                                   detail=fail_detail,
                                   findings=failing_lines)

        elif stack == "node":
            # Require an explicit test script in package.json
            pkg = proj_copy / "package.json"
            has_test_script = False
            if pkg.exists():
                try:
                    data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
                    script = (data.get("scripts") or {}).get("test", "")
                    has_test_script = bool(script and "no test" not in script.lower())
                except (OSError, json.JSONDecodeError):
                    pass

            if not has_test_script:
                return CheckResult(key, True, na=True,
                                   detail=f"{len(test_files)} test file(s) found but no npm test script")

            npm_prefix = ["cmd", "/c", "npm"] if sys.platform == "win32" else ["npm"]
            rr = subprocess.run(
                npm_prefix + ["test"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TEST_RUNNER_TIMEOUT, creationflags=CREATE_NO_WINDOW,
                cwd=str(proj_copy),
            )
            if rr.returncode == 0:
                return CheckResult(key, True, detail="npm test passed")
            snippet = (rr.stdout + rr.stderr)[-600:].strip().splitlines()[:8]
            return CheckResult(key, False, detail="npm test failed", findings=snippet)

        else:
            return CheckResult(key, True, na=True,
                               detail=f"Stack '{stack}' not supported for test runner")

    except subprocess.TimeoutExpired:
        return CheckResult(key, False,
                           detail=f"Test suite timed out (>{TEST_RUNNER_TIMEOUT}s)")
    except Exception as e:
        return CheckResult(key, False, detail=f"Test runner error: {e!r}")


# ============================================================
# Static orchestration
# ============================================================

def is_empty_project(proj: Path) -> bool:
    for dirpath, dirnames, filenames in os.walk(proj):
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]
        if filenames:
            return False
    return True


def audit_static(proj: Path) -> ProjectResult:
    if is_empty_project(proj):
        r = ProjectResult(name=proj.name, path=proj, stack="empty")
        r.verdict = "SKIPPED"
        r.notes.append("Empty folder (no files)")
        return r

    stack = detect_stack(proj)
    r = ProjectResult(name=proj.name, path=proj, stack=stack)

    resolved = str(proj.resolve())
    if len(resolved) > PATH_LENGTH_LIMIT:
        r.add(CheckResult(
            "0_path_length", False,
            detail=f"Path too long ({len(resolved)} chars; limit {PATH_LENGTH_LIMIT})",
        ))
        r.verdict = "REJECTED"
        r.notes.append("Path too long (Windows MAX_PATH guard)")
        return r

    if stack == "unknown":
        r.add(CheckResult(
            "0_stack", False,
            detail="No Python or Node manifest/code detected",
        ))
        r.verdict = "REJECTED"
        r.notes.append("No Python or Node manifest/code detected")
        return r

    r.add(check_abs_paths(proj))
    r.add(check_external_refs(proj))
    if stack == "flutter":
        c3 = check_flutter_manifest(proj)
        c4 = CheckResult(
            "4_imports_declared", True, na=True,
            detail="Dart import analysis not supported; manifest checked",
        )
    elif stack in ("python", "both"):
        c3, c4 = check_manifest_and_imports_py(proj)
        unpinned = _check_unpinned_deps(proj)
        if unpinned and c3.passed:
            c3.findings.append({
                "issue": f"Unpinned dependencies (no version specifier): {', '.join(unpinned)}"
            })
    else:
        c3, c4 = check_manifest_and_imports_node(proj)
    r.add(c3)
    r.add(c4)
    c7, c7b = check_readme(proj)
    r.add(c7)
    r.add(c7b)
    r.add(check_env_example(proj))
    return r


def compute_verdict(r: ProjectResult) -> str:
    if r.verdict:
        return r.verdict
    for c in r.checks.values():
        if not c.na and not c.passed:
            return "REJECTED"
    return "ACCEPTED"


def compute_score(r: ProjectResult) -> int:
    """Compute and store r.score and r.max_score. Returns the score.

    Checks skipped via --only-static are excluded from both numerator and
    denominator so the reported fraction (e.g. 60/75) is always meaningful.
    All other absent or N/A checks count as full marks.
    """
    if r.verdict == "SKIPPED":
        r.max_score = 0
        return 0
    # Early-exit rejections (0_stack, 0_path_length) — no rubric checks ran
    if any(k.startswith("0_") for k in r.checks):
        r.max_score = 0
        return 0
    earned = 0
    applicable = 0
    for key, weight in CHECK_WEIGHTS.items():
        c = r.checks.get(key)
        if c is not None and c.na and "only-static" in c.detail:
            continue  # excluded from score entirely — not applicable to this run mode
        applicable += weight
        if c is None or c.na or c.passed:
            earned += weight
    r.max_score = applicable
    return earned


# ============================================================
# Report writers (incremental)
# ============================================================

def write_csv(results: list[ProjectResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        check_headers = [f"check{k}" for k in ALL_CHECK_KEYS]
        w.writerow(["project_name", "stack", "verdict", "score"] + check_headers + ["duplicate_of", "failure_summary"])
        for r in results:
            row = [r.name, r.stack, r.verdict, r.score]
            for key in ALL_CHECK_KEYS:
                c = r.checks.get(key)
                row.append(c.status if c else "N/A")
            parts = []
            for k in sorted(r.checks.keys()):
                c = r.checks[k]
                if not c.passed:
                    parts.append(f"{k}: {c.detail}")
            if r.notes:
                parts.extend(r.notes)
            row.append(r.duplicate_of)
            row.append("; ".join(parts))
            w.writerow(row)


def _finding_to_line(f: dict) -> str:
    try:
        return json.dumps(f, ensure_ascii=False)
    except Exception:
        return str(f)


def write_md(results: list[ProjectResult], path: Path, env: dict, seq_info: list[dict] | None = None) -> None:
    lines: list[str] = []
    lines.append("# Audit Report")
    lines.append("")
    lines.append(f"Generated: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append("")
    lines.append(
        f"Auditor environment: Python `{env.get('python', '?')}`, "
        f"Node `{env.get('node_version') or 'not installed'}`, "
        f"npm `{env.get('npm_version') or 'not installed'}`."
    )
    lines.append("")
    accepted = sum(1 for r in results if r.verdict.startswith("ACCEPTED"))
    skipped = sum(1 for r in results if r.verdict == "SKIPPED")
    rejected = len(results) - accepted - skipped
    scored = [r for r in results if r.verdict != "SKIPPED"]
    avg_score = (sum(r.score for r in scored) / len(scored)) if scored else 0
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **ACCEPTED**: {accepted}/{len(results)}")
    lines.append(f"- **REJECTED**: {rejected}/{len(results)}")
    if skipped:
        lines.append(f"- **SKIPPED**: {skipped}/{len(results)} (empty folders)")
    lines.append(f"- **Average score**: {avg_score:.1f} / {TOTAL_WEIGHT}")
    if scored:
        lines.append(f"- **Highest**: {max(r.score for r in scored)} "
                     f"| **Lowest**: {min(r.score for r in scored)}")
    lines.append("")

    # Score distribution buckets (percentage-based so they stay correct as TOTAL_WEIGHT changes)
    def _pct(s: int) -> int:
        return round(s / TOTAL_WEIGHT * 100)

    buckets = [
        ("100 (perfect)", lambda s: _pct(s) >= 100),
        ("80–99 (good)",  lambda s: 80 <= _pct(s) <= 99),
        ("60–79 (partial)", lambda s: 60 <= _pct(s) <= 79),
        ("40–59 (weak)",  lambda s: 40 <= _pct(s) <= 59),
        ("0–39 (poor)",   lambda s: _pct(s) <= 39),
    ]
    lines.append("### Score Distribution")
    lines.append("")
    lines.append("| Band | Count |")
    lines.append("|------|-------|")
    for label, pred in buckets:
        count = sum(1 for r in scored if pred(r.score))
        lines.append(f"| {label} | {count} |")
    lines.append("")

    # Leaderboard table (sorted by score desc)
    lines.append("### Score Leaderboard")
    lines.append("")
    lines.append(f"| # | Project | Score | Verdict |")
    lines.append(f"|---|---------|-------|---------|")
    for rank, r in enumerate(sorted(scored, key=lambda x: x.score, reverse=True), 1):
        filled = round(r.score / TOTAL_WEIGHT * 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"| {rank} | {r.name} | {r.score}/{TOTAL_WEIGHT} `{bar}` | {r.verdict} |")
    lines.append("")

    if seq_info:
        lines.append("### Folder Sequence")
        lines.append("")
        for idx, pat in enumerate(seq_info, 1):
            prefix, suffix = pat["prefix"], pat["suffix"]
            lo, hi = pat["range"]
            label = f"Pattern {idx}" if len(seq_info) > 1 else "Pattern detected"
            lines.append(f"- **{label}**: `{prefix}<N>{suffix}`  "
                         f"range {lo}–{hi}  ({pat['matched_count']} found / {hi - lo + 1} expected)")
            if pat["missing_names"]:
                lines.append(f"  - **Missing ({len(pat['missing_names'])})**: "
                             + ", ".join(f"`{n}`" for n in pat["missing_names"]))
            else:
                lines.append("  - **Missing**: none — sequence complete")
            if pat.get("other_names"):
                lines.append(f"  - **Outside pattern**: "
                             + ", ".join(f"`{n}`" for n in pat["other_names"]))
        lines.append("")

    # Build rejection breakdown: check_key → list of (project_name, detail, first_finding)
    breakdown: dict[str, list[tuple[str, str, str]]] = {}
    for r in results:
        if r.verdict != "REJECTED":
            continue
        for k, c in r.checks.items():
            if not c.passed and not c.na:
                first_finding = str(c.findings[0])[:120] if c.findings else ""
                breakdown.setdefault(k, []).append((r.name, c.detail, first_finding))
    if breakdown:
        lines.append("## Rejection Reasons Breakdown")
        lines.append("")
        for k in sorted(breakdown.keys(), key=lambda x: (-len(breakdown[x]), x)):
            entries = breakdown[k]
            lines.append(f"### `{k}` — {len(entries)} project(s) rejected")
            lines.append("")
            cap = 5
            for proj_name, detail, finding in entries[:cap]:
                # GitHub anchors: lowercase, spaces→hyphens, strip everything else non-alphanumeric
                anchor = re.sub(r"[^a-z0-9-]", "", proj_name.lower().replace(" ", "-").replace("_", "-"))
                reason = detail
                if finding:
                    reason += f" — `{finding}`"
                lines.append(f"- **[{proj_name}](#{anchor})**: {reason}")
            if len(entries) > cap:
                lines.append(f"- *…and {len(entries) - cap} more (see per-project details below)*")
            lines.append("")
    lines.append("## Per-Project Details")
    lines.append("")
    for r in results:
        lines.append(f"### {r.name}")
        lines.append("")
        lines.append(f"- **Stack**: `{r.stack}`")
        lines.append(f"- **Verdict**: **{r.verdict}**")
        lines.append(f"- **Score**: {r.score}/{TOTAL_WEIGHT}")
        lines.append(f"- **Path**: `{r.path}`")
        if r.duplicate_of:
            di   = r.duplicate_info
            kind = di.get("kind", "exact")
            sim  = di.get("similarity", 1.0)
            pct  = f"{sim:.0%}"
            if kind == "exact":
                lines.append(f"- **⚠ Duplicate of**: `{r.duplicate_of}` — **exact clone** ({pct} normalized match)")
            else:
                lines.append(f"- **⚠ Near-duplicate of**: `{r.duplicate_of}` — **{pct} similar**")
        if r.notes:
            lines.append(f"- **Notes**: {'; '.join(r.notes)}")
        lines.append("")

        # Detailed duplicate similarity breakdown
        if r.duplicate_of and r.duplicate_info:
            di      = r.duplicate_info
            kind    = di.get("kind", "exact")
            sim     = di.get("similarity", 1.0)
            id_fs   = di.get("identical_files", [])
            sim_fs  = di.get("similar_files", [])
            u_self  = di.get("unique_self", [])
            u_orig  = di.get("unique_orig", [])
            title   = "Exact clone" if kind == "exact" else "Near-duplicate"
            lines.append(f"**{title} analysis ({sim:.0%} overall match after normalization):**")
            lines.append("")
            lines.append("| Category | Files |")
            lines.append("|----------|-------|")
            lines.append(f"| Identical (100%) | {len(id_fs)} |")
            lines.append(f"| Similar (50–99%) | {len(sim_fs)} |")
            lines.append(f"| Unique to this project | {len(u_self)} |")
            lines.append(f"| Unique to original | {len(u_orig)} |")
            lines.append("")
            # File-level table (cap at 20 rows to avoid bloat)
            rows: list[tuple[str, str, str]] = []
            for f in id_fs:
                rows.append((f"`{f}`", "identical", "100%"))
            for entry in sim_fs:
                rows.append((f"`{entry['file']}`", "similar", f"{entry['similarity']:.0%}"))
            for f in u_self:
                rows.append((f"`{f}`", "unique to this project", "—"))
            for f in u_orig:
                rows.append((f"`{f}`", "unique to original", "—"))
            if rows:
                lines.append("| File | Status | Similarity |")
                lines.append("|------|--------|-----------|")
                for file_cell, status, sim_cell in rows[:20]:
                    lines.append(f"| {file_cell} | {status} | {sim_cell} |")
                if len(rows) > 20:
                    lines.append(f"| … | *{len(rows) - 20} more files not shown* | |")
                lines.append("")

        # Pre-flight guard failures (0_stack, 0_path_length) are not scored rubric
        # checks — render them separately so they're not confused with the 10 checks.
        preflight = {k: c for k, c in r.checks.items() if k.startswith("0_")}
        if preflight:
            lines.append("**Pre-flight failure (not part of the rubric):**")
            lines.append("")
            for k, c in sorted(preflight.items()):
                lines.append(f"- `{k}`: {c.detail}")
            lines.append("")
        lines.append("| Check | Status | Detail |")
        lines.append("|---|---|---|")
        for key in sorted(k for k in r.checks.keys() if not k.startswith("0_")):
            c = r.checks[key]
            lines.append(f"| `{key}` | **{c.status}** | {c.detail} |")
        lines.append("")
        for key in sorted(r.checks.keys()):
            c = r.checks[key]
            if not c.findings:
                continue
            lines.append(f"**Findings for `{key}`:**")
            lines.append("")
            for f in c.findings[:50]:
                lines.append(f"- `{_finding_to_line(f)}`")
            if len(c.findings) > 50:
                lines.append(f"- ...and {len(c.findings) - 50} more")
            lines.append("")
        fails = [(k, c) for k, c in r.checks.items() if not c.passed]
        if fails:
            lines.append("**Reproduce these failures:**")
            lines.append("")
            lines.append("```")
            single_arg = f'"{r.name}"' if " " in r.name else r.name
            lines.append(f"python audit.py <root> --single {single_arg}")
            lines.append("```")
            lines.append("")
        for stage, payload in r.logs.items():
            lines.append(f"**Logs -- {stage}:**")
            lines.append("")
            lines.append("```")
            lines.append(payload.get("cmd", ""))
            lines.append("--- stdout ---")
            lines.append((payload.get("stdout") or "")[:4000])
            lines.append("--- stderr ---")
            lines.append((payload.get("stderr") or "")[:4000])
            lines.append("```")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# TUI helpers
# ============================================================

_ANSI_ESC = re.compile(r'\x1b\[[0-9;]*m')


def _vlen(s: str) -> int:
    """Visible length of a string — strips ANSI escape codes."""
    return len(_ANSI_ESC.sub("", s))


def _tw() -> int:
    try:
        return min(os.get_terminal_size().columns, 100)
    except OSError:
        return 80


def _score_bar(score: int, total: int = 100, width: int = 10) -> str:
    filled = round(score / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def format_score(r: "ProjectResult") -> str:
    if not r.max_score:
        return "0/—"
    return f"{r.score}/{r.max_score}"


def _hline(width: int, left: str = "├", right: str = "┤", fill: str = "─") -> str:
    return left + fill * (width - 2) + right


def _row(content: str, width: int, left: str = "│", right: str = "│") -> str:
    """Pad content to fill a fixed-width box row, ANSI-safe."""
    inner = width - 2
    visible = _vlen(content)
    pad = max(0, inner - visible)
    # Truncate by visible chars if too long (strip trailing ANSI before cut)
    if visible > inner:
        plain = _ANSI_ESC.sub("", content)
        content = plain[:inner - 1] + "…"
        pad = 0
    return left + content + " " * pad + right


def _center(text: str, width: int, left: str = "│", right: str = "│") -> str:
    inner = width - 2
    visible = _vlen(text)
    pad = max(0, inner - visible)
    lp = pad // 2
    rp = pad - lp
    return left + " " * lp + text + " " * rp + right


# ============================================================
# Console progress printer (per-project box)
# ============================================================

_CHECK_LABELS: dict[str, str] = {
    "0_stack":            "stack",
    "0_path_length":      "path",
    "1_abs_paths":        "abs paths",
    "2_external_refs":    "ext refs",
    "3_manifest":         "manifest",
    "4_imports_declared": "imports",
    "5_install":          "install",
    "6_runs":             "runs",
    "7_readme":           "readme",
    "7b_readme_quality":  "readme quality",
    "8_tests":            "tests",
    "9_env_example":      "env example",
}


def print_progress(r: ProjectResult) -> None:
    W = _tw()
    verdict_color = (Fore.YELLOW if r.verdict == "SKIPPED"
                     else Fore.GREEN if r.verdict.startswith("ACCEPTED")
                     else Fore.RED)

    for key in sorted(r.checks.keys()):
        c = r.checks[key]
        if c.na:
            icon, color = "○", Fore.CYAN + Style.DIM
        elif c.passed:
            icon, color = "✓", Fore.GREEN
        else:
            icon, color = "✗", Fore.RED + Style.BRIGHT
        label = _CHECK_LABELS.get(key, key).ljust(15)
        content = f"  {color}{icon}{Style.RESET_ALL}  {label}  {c.detail}"
        print(_row(content, W))

    print(_hline(W, "├", "┤"))
    tag = f"{verdict_color}{Style.BRIGHT} {r.verdict} {Style.RESET_ALL}"
    if r.verdict == "SKIPPED":
        content = f"  {verdict_color}{Style.BRIGHT} SKIPPED {Style.RESET_ALL}"
    elif r.max_score == 0:
        content = f"  {tag}   0/—"
    else:
        bar = _score_bar(r.score, r.max_score)
        content = f"  {tag}   {r.score:>3}/{r.max_score}   {bar}"
    print(_row(content, W))
    print("└" + "─" * (W - 2) + "┘")


# ============================================================
# Sequence gap detection
# ============================================================

# Non-digit-only prefix so the FIRST run of digits is the sequence number.
# Old regex (.*?) backtracks to grab the LAST digit run, fragmenting folders
# like 'C10-NLP-2024' into prefix='C10-NLP-', num='2024'.
_SEQ_RE = re.compile(r'^(\D*?)(\d+)(.*)$')

# Minimum members for a bucket to be reported as a pattern (avoids noise).
_SEQ_MIN_MEMBERS = 3


def _seq_suffix_key(suffix: str) -> str:
    """Normalise a folder suffix for sequence grouping.

    Folders like 'C7' (suffix '') and 'C1-SMART TITLE' (suffix '-SMART TITLE')
    are part of the same numbered sequence — only the separator character matters
    for grouping, not the descriptive text that follows it.
    """
    return "" if (not suffix or suffix[0] in ('-', '_', ' ')) else suffix


def detect_sequence_gaps(names: list[str]) -> list[dict]:
    """
    Detect sequential folder naming patterns (e.g. A01, C-01, Team02) among
    *names* and return a list of pattern dicts — one per detected pattern.

    Handles:
    - Mixed padding: C01 + C7 + C08 treated as one sequence, missing names
      zero-padded to match the dominant width.
    - Folders with titles containing digits: C10-NLP-2024 → prefix='C', num=10,
      not fragmented to prefix='C10-NLP-', num=2024.
    - Case/whitespace variation in prefix: 'A', 'a', 'A ' all group together.
    - Multiple independent patterns (e.g. A01-A10 AND C01-C10 coexist).

    Returns an empty list if no pattern has at least _SEQ_MIN_MEMBERS members.
    """
    # Map normalized (prefix_casefold, suffix_key) → list of (num_int, num_str, raw_name, raw_prefix)
    groups: dict[tuple[str, str], list[tuple[int, str, str, str]]] = {}
    unmatched: list[str] = []
    for name in names:
        m = _SEQ_RE.match(name)
        if m:
            raw_prefix, num_str, suffix = m.group(1), m.group(2), m.group(3)
            norm_key = (raw_prefix.strip().casefold(), _seq_suffix_key(suffix))
            groups.setdefault(norm_key, []).append((int(num_str), num_str, name, raw_prefix))
        else:
            unmatched.append(name)

    patterns: list[dict] = []
    matched_names: set[str] = set()

    # Sort by size desc so largest patterns are reported first
    for norm_key, entries in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(entries) < _SEQ_MIN_MEMBERS:
            continue

        nums = sorted(e[0] for e in entries)
        num_strs = {e[0]: e[1] for e in entries}

        min_num, max_num = nums[0], nums[-1]
        missing_nums = sorted(set(range(min_num, max_num + 1)) - set(nums))

        # Zero-pad missing names only if existing folders use leading zeros
        is_zero_padded = any(s.startswith("0") for s in num_strs.values())
        pad_width = max(len(s) for s in num_strs.values()) if is_zero_padded else 0

        # Use most frequent raw prefix for display (handles case/whitespace variants).
        # Display suffix comes directly from the stable bucket norm_key — deterministic
        # regardless of the order entries were inserted.
        display_prefix = Counter(e[3] for e in entries).most_common(1)[0][0]
        display_suffix = norm_key[1]  # already the _seq_suffix_key-normalised suffix

        missing_names = [
            f"{display_prefix}{str(n).zfill(pad_width) if is_zero_padded else str(n)}{display_suffix}"
            for n in missing_nums
        ]

        for e in entries:
            matched_names.add(e[2])

        patterns.append({
            "prefix": display_prefix,
            "suffix": display_suffix,
            "matched_count": len(entries),
            "range": (min_num, max_num),
            "missing_nums": missing_nums,
            "missing_names": missing_names,
        })

    # Names that didn't match ANY reported pattern go into other_names on the first pattern
    all_other = [n for n in names if n not in matched_names]
    if patterns:
        patterns[0]["other_names"] = all_other
        for p in patterns[1:]:
            p["other_names"] = []
    return patterns


# ============================================================
# CLI / main
# ============================================================

def _configure_logging(verbose: bool, log_file: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def main() -> int:
    global AUDIT_STRICT
    p = argparse.ArgumentParser(
        description="Self-contained verification tool for student mini-projects.",
    )
    p.add_argument("root", type=Path, nargs="?", default=None,
                   help="Root directory containing project subfolders "
                        "(default: cwd, auto-detected as root-of-projects or single project)")
    p.add_argument("--single", type=str, default=None,
                   help="Audit only one project by folder name")
    p.add_argument("--resume", action="store_true",
                   help="Skip projects already in existing report")
    p.add_argument("--only-static", action="store_true",
                   help="Skip install/run checks (quick preview)")
    p.add_argument("--strict", action="store_true",
                   help="Treat unreadable files as check findings instead of silently skipping")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Emit debug-level logging to stderr")
    p.add_argument("--log-file", type=Path, default=None, metavar="FILE",
                   help="Write all log output to FILE in addition to stderr")
    p.add_argument("--report-dir", type=Path, default=Path.cwd(),
                   help="Where to write report files (default: cwd)")
    args = p.parse_args()

    _configure_logging(args.verbose, args.log_file)
    AUDIT_STRICT = args.strict
    if AUDIT_STRICT:
        logger.warning("Strict mode enabled — unreadable files will appear as findings")

    colorama_init(autoreset=True)
    # Ensure UTF-8 output so box-drawing characters render on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = verify_environment()
    W = _tw()
    node_v = env.get('node_version') or f"{Fore.RED}MISSING{Style.RESET_ALL}"
    npm_v  = env.get('npm_version')  or f"{Fore.RED}MISSING{Style.RESET_ALL}"
    title = f"  {Style.BRIGHT}AUDIT TOOL{Style.RESET_ALL}  "
    title_pad = W - 2 - _vlen(title)
    lp = title_pad // 2
    rp = title_pad - lp
    print("╔" + "═" * lp + title + "═" * rp + "╗")
    print(_row(f"  Python {env['python']}   node {node_v}   npm {npm_v}", W, left="║", right="║"))
    if not env.get("node_ok") or not env.get("npm_ok"):
        print(_row(f"  {Fore.YELLOW}⚠  node/npm missing — Node projects will fail dynamic checks{Style.RESET_ALL}", W, left="║", right="║"))
    print("╚" + "═" * (W - 2) + "╝")
    print()

    if args.root is None:
        cwd = Path.cwd().resolve()
        if _is_single_project_dir(cwd):
            root = cwd.parent
            all_projects = [cwd]
            print(f"{Fore.CYAN}  Single-project mode: auditing  {cwd.name}{Style.RESET_ALL}\n")
        else:
            root = cwd
            all_projects = sorted(
                [x for x in root.iterdir()
                 if x.is_dir()
                 and not x.name.startswith(".")
                 and x.name not in EXCLUDE_DIRS]
            )
    else:
        root = args.root.resolve()
        if not root.is_dir():
            print(f"{Fore.RED}ERROR: root dir does not exist: {root}{Style.RESET_ALL}")
            return 2
        all_projects = sorted(
            [x for x in root.iterdir()
             if x.is_dir()
             and not x.name.startswith(".")
             and x.name not in EXCLUDE_DIRS]
        )

    seq_info = detect_sequence_gaps([x.name for x in all_projects])

    if args.single:
        all_projects = [x for x in all_projects if x.name == args.single]
        if not all_projects:
            print(f"{Fore.RED}ERROR: no project named {args.single}{Style.RESET_ALL}")
            return 2
    if not all_projects:
        print(f"{Fore.RED}ERROR: no project folders found in {root}{Style.RESET_ALL}")
        return 2

    report_md = args.report_dir / "audit_report.md"
    report_csv = args.report_dir / "audit_report.csv"
    flags_file = args.report_dir / "audit_flags.json"
    args.report_dir.mkdir(parents=True, exist_ok=True)

    current_flags = {"only_static": args.only_static, "strict": args.strict}

    done_names: set[str] = set()
    if args.resume and report_csv.exists():
        # Warn if flags differ from the previous run
        try:
            prev_flags = json.loads(flags_file.read_text(encoding="utf-8"))
            mismatches = [k for k in current_flags if current_flags[k] != prev_flags.get(k)]
            if mismatches:
                print(f"{Fore.YELLOW}⚠  --resume: flags differ from previous run "
                      f"({', '.join(mismatches)}) — skipped projects were audited with different settings"
                      f"{Style.RESET_ALL}")
        except Exception:
            pass
        try:
            with report_csv.open(encoding="utf-8") as fh:
                rd = csv.reader(fh)
                next(rd, None)
                for row in rd:
                    if row:
                        done_names.add(row[0])
            print(f"{Fore.CYAN}Resume: skipping {len(done_names)} "
                  f"already-reported project(s){Style.RESET_ALL}")
        except Exception:
            pass

    # Persist flags for future --resume comparisons
    try:
        flags_file.write_text(json.dumps(current_flags, indent=2), encoding="utf-8")
    except Exception:
        pass

    counts = {"python": 0, "node": 0, "both": 0, "flutter": 0, "unknown": 0}
    for x in all_projects:
        counts[detect_stack(x)] += 1
    parts = []
    if counts['python']:  parts.append(f"{counts['python']} Python")
    if counts['node']:    parts.append(f"{counts['node']} Node")
    if counts['flutter']: parts.append(f"{counts['flutter']} Flutter")
    if counts['both']:    parts.append(f"{counts['both']} Both")
    if counts['unknown']: parts.append(f"{counts['unknown']} Unknown")
    n = len(all_projects)
    noun = "project" if n == 1 else "projects"
    breakdown = f"  ·  {' / '.join(parts)}" if parts else ""
    print(f"  {Fore.CYAN}{Style.BRIGHT}{n}{Style.RESET_ALL}{Fore.CYAN} {noun} found{Style.RESET_ALL}{breakdown}")
    print()

    results: list[ProjectResult] = []
    to_audit = [x for x in all_projects if x.name not in done_names]
    W = _tw()
    for i, proj in enumerate(to_audit, start=1):
        stack_label = detect_stack(proj)
        counter = f"[{i}/{len(to_audit)}]"
        header_plain = f" {counter}  {proj.name}  ·  {stack_label} "
        header_colored = f" {Style.DIM}{counter}{Style.RESET_ALL}  {Style.BRIGHT}{proj.name}{Style.RESET_ALL}  {Style.DIM}·  {stack_label}{Style.RESET_ALL} "
        pad = max(0, (W - 2) - len(header_plain))
        lp = pad // 2
        rp = pad - lp
        print("┌" + "─" * lp + header_colored + "─" * rp + "┐")
        tmp_dir: Path | None = None
        try:
            r = audit_static(proj)
            if not args.only_static and not r.verdict:
                print(_row(f"  {Fore.CYAN}installing…{Style.RESET_ALL}", W))
                c5, tmp_dir = check_install(proj, r.stack)
                r.add(c5)
                r.logs["check5"] = {
                    "cmd": "pip/npm install",
                    "stdout": c5.stdout,
                    "stderr": c5.stderr or "\n".join(str(f) for f in c5.findings),
                }
                print(_row(f"  {Fore.CYAN}running entry point…{Style.RESET_ALL}", W))
                c6 = check_runs(proj, r.stack, tmp_dir)
                r.add(c6)
                r.logs["check6"] = {
                    "cmd": "python/node <entry>",
                    "stdout": c6.stdout,
                    "stderr": c6.stderr or "\n".join(str(f) for f in c6.findings),
                }
                print(_row(f"  {Fore.CYAN}running tests…{Style.RESET_ALL}", W))
                c8 = check_tests(proj, r.stack, tmp_dir)
                r.add(c8)
                r.logs["check8"] = {"cmd": "pytest / npm test", "stdout": "", "stderr": "\n".join(
                    f if isinstance(f, str) else str(f) for f in c8.findings
                )}
            elif args.only_static and not r.verdict:
                # Register explicit N/A entries so the report is transparent about
                # which checks were skipped and the score display is not misleading.
                for _key in ("5_install", "6_runs", "8_tests"):
                    r.add(CheckResult(_key, True, na=True, detail="Skipped (--only-static)"))
                r.notes.append("Dynamic checks skipped (--only-static); score is out of 75 applicable points")
            r.verdict = compute_verdict(r)
            r.score = compute_score(r)
            print_progress(r)
            results.append(r)
            write_csv(results, report_csv)
            write_md(results, report_md, env, seq_info)
        except Exception as e:
            r = ProjectResult(name=proj.name, path=proj, stack="unknown")
            r.verdict = "REJECTED"
            r.score = 0
            r.notes.append(f"audit harness error: {e!r}")
            results.append(r)
            print(_row(f"  {Fore.RED}✗ harness error: {e!r}{Style.RESET_ALL}", W))
            print("└" + "─" * (W - 2) + "┘")
            write_csv(results, report_csv)
            write_md(results, report_md, env, seq_info)
        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        print()

    # ── Duplicate detection ────────────────────────────────────
    # Build normalized file cache once for every non-skipped project
    _norm_cache: dict[str, dict[str, str]] = {
        r.name: _get_normalized_files(r.path)
        for r in results if r.verdict != "SKIPPED"
    }

    # Phase 1 — exact clones: same normalized fingerprint
    # Projects with zero recognized source files are excluded — they'd all share
    # the same empty-input hash and produce false positives.
    _seen_fps: dict[str, str] = {}
    _unique_projects: list[ProjectResult] = []   # first-seen for each fingerprint
    for r in results:
        if r.verdict == "SKIPPED":
            continue
        if not _norm_cache[r.name]:   # no recognized source files — skip
            continue
        fp = _fingerprint_from_norm(_norm_cache[r.name])
        if fp in _seen_fps:
            orig_name = _seen_fps[fp]
            info = compute_file_similarity(_norm_cache[orig_name], _norm_cache[r.name])
            r.duplicate_of   = orig_name
            r.duplicate_info = {"kind": "exact", **info}
        else:
            _seen_fps[fp] = r.name
            _unique_projects.append(r)

    # Phase 2 — near-duplicates: pairwise SequenceMatcher among unique projects
    _seen_unique: list[ProjectResult] = []
    for r in _unique_projects:
        if not _norm_cache[r.name]:   # guard (already excluded above, but be explicit)
            _seen_unique.append(r)
            continue
        best_sim, best_orig, best_info = 0.0, None, {}
        for prev in _seen_unique:
            info = compute_file_similarity(_norm_cache[prev.name], _norm_cache[r.name])
            if info["similarity"] > best_sim:
                best_sim, best_orig, best_info = info["similarity"], prev, info
        if best_orig and best_sim >= NEAR_DUPE_THRESHOLD:
            r.duplicate_of   = best_orig.name
            r.duplicate_info = {"kind": "near", **best_info}
        else:
            _seen_unique.append(r)

    # Rewrite reports with duplicate_of populated
    write_csv(results, report_csv)
    write_md(results, report_md, env, seq_info)

    accepted = sum(1 for r in results if r.verdict.startswith("ACCEPTED"))
    skipped  = sum(1 for r in results if r.verdict == "SKIPPED")
    rejected = len(results) - accepted - skipped
    scored_results = [r for r in results if r.verdict != "SKIPPED"]
    avg_score = (sum(r.score for r in scored_results) / len(scored_results)) if scored_results else 0
    avg_pct = (
        sum((r.score / r.max_score) for r in scored_results if r.max_score) / len(scored_results) * 100
        if scored_results else 0
    )

    def _sort_key(r: ProjectResult) -> tuple:
        m = _SEQ_RE.match(r.name)
        return (0, m.group(1), int(m.group(2))) if m else (1, r.name, 0)
    sorted_results = sorted(results, key=_sort_key)

    W = _tw()

    def row(text: str = "") -> None:
        print(_row(f"  {text}", W, left="║", right="║"))

    def section(title: str) -> None:
        label = f" {Style.BRIGHT}{title}{Style.RESET_ALL} "
        label_plain = f" {title} "
        inner = W - 2
        fill = "─" * (inner - len(label_plain) - 1)
        print("╟─" + label + fill + "╢")

    # ── header ────────────────────────────────────────────────
    title = f"  {Style.BRIGHT}AUDIT COMPLETE{Style.RESET_ALL}  "
    title_pad = W - 2 - _vlen(title)
    lp = title_pad // 2
    rp = title_pad - lp
    print("╔" + "═" * lp + title + "═" * rp + "╗")
    row()

    total = len(results)
    noun = "project" if total == 1 else "projects"
    acc_str  = f"{Fore.GREEN}{Style.BRIGHT}{accepted}{Style.RESET_ALL}{Fore.GREEN} accepted{Style.RESET_ALL}"
    rej_str  = f"{Fore.RED}{Style.BRIGHT}{rejected}{Style.RESET_ALL}{Fore.RED} rejected{Style.RESET_ALL}"
    skp_str  = f"    {Fore.YELLOW}{skipped} skipped{Style.RESET_ALL}" if skipped else ""
    row(f"{Style.BRIGHT}{total}{Style.RESET_ALL} {noun}    {acc_str}    {rej_str}{skp_str}")

    if scored_results:
        hi = max(r.score for r in scored_results)
        lo = min(r.score for r in scored_results)
        hi_name = next(r.name for r in scored_results if r.score == hi)
        lo_name = next(r.name for r in scored_results if r.score == lo)
        avg_col = (Fore.GREEN if avg_pct >= 80
                   else Fore.YELLOW if avg_pct >= 60
                   else Fore.RED)
        if any(r.max_score != TOTAL_WEIGHT for r in scored_results):
            avg_label = f"avg {avg_col}{avg_score:.1f}{Style.RESET_ALL} pts ({avg_pct:.0f}%)"
        else:
            avg_label = f"avg {avg_col}{avg_score:.1f}{Style.RESET_ALL}/{TOTAL_WEIGHT}"
        hi_score = format_score(next(r for r in scored_results if r.score == hi))
        lo_score = format_score(next(r for r in scored_results if r.score == lo))
        row(f"{avg_label}"
            f"   ·   high {Fore.GREEN}{hi_score}{Style.RESET_ALL} ({hi_name})"
            f"   ·   low {Fore.RED}{lo_score}{Style.RESET_ALL} ({lo_name})")
    row()

    # ── score distribution ────────────────────────────────────
    section("SCORE DISTRIBUTION")
    def _pct_c(s: int, max_score: int) -> int:
        return round(s / max_score * 100) if max_score else 0

    buckets = [
        ("100    perfect", Fore.GREEN + Style.BRIGHT, lambda s, m: _pct_c(s, m) >= 100),
        ("80–99  good   ", Fore.GREEN,                lambda s, m: 80 <= _pct_c(s, m) <= 99),
        ("60–79  partial", Fore.YELLOW,               lambda s, m: 60 <= _pct_c(s, m) <= 79),
        ("40–59  weak   ", Fore.RED,                  lambda s, m: 40 <= _pct_c(s, m) <= 59),
        (" 0–39  poor   ", Fore.RED + Style.BRIGHT,   lambda s, m: _pct_c(s, m) <= 39),
    ]
    counts_list = [(lbl, col, sum(1 for r in scored_results if fn(r.score, r.max_score))) for lbl, col, fn in buckets]
    max_count = max((c for _, _, c in counts_list), default=1) or 1
    for label, color, count in counts_list:
        if count == 0:
            dim = Style.DIM
            bar = "░" * 16
            row(f"{dim}{label}  {bar}  0{Style.RESET_ALL}")
        else:
            bar_w = round(count / max_count * 16)
            bar = f"{color}{'█' * bar_w}{Style.RESET_ALL}{'░' * (16 - bar_w)}"
            row(f"{color}{label}{Style.RESET_ALL}  {bar}  {Style.BRIGHT}{count}{Style.RESET_ALL}")
    row()

    # ── rejection reasons ─────────────────────────────────────
    breakdown: dict[str, int] = {}
    for r in results:
        if r.verdict != "REJECTED":
            continue
        for k, c in r.checks.items():
            if not c.na and not c.passed:
                breakdown[k] = breakdown.get(k, 0) + 1
    if breakdown:
        section("REJECTION REASONS")
        max_b = max(breakdown.values())
        for k in sorted(breakdown.keys(), key=lambda x: (-breakdown[x], x)):
            cnt = breakdown[k]
            friendly = _CHECK_LABELS.get(k, k)
            bar_w = round(cnt / max_b * 12)
            bar = f"{Fore.RED}{'█' * bar_w}{Style.RESET_ALL}{'░' * (12 - bar_w)}"
            row(f"{friendly:<16}  {bar}  {Style.BRIGHT}{cnt}{Style.RESET_ALL}")
        row()

    # ── sequence gaps ─────────────────────────────────────────
    if seq_info:
        section("SEQUENCE")
        for idx, pat in enumerate(seq_info, 1):
            prefix, suffix = pat["prefix"], pat["suffix"]
            lo, hi = pat["range"]
            pat_label = f"{prefix}<N>{suffix}"
            pat_num = f"[{idx}] " if len(seq_info) > 1 else ""
            row(f"{pat_num}Pattern  {Style.BRIGHT}{pat_label}{Style.RESET_ALL}   "
                f"range {lo}–{hi}   "
                f"{Fore.CYAN}{pat['matched_count']} found{Style.RESET_ALL} / "
                f"{hi - lo + 1} expected")
            if pat["missing_names"]:
                miss_color = Fore.YELLOW + Style.BRIGHT
                _cap = 12
                names_m = pat["missing_names"]
                miss_list = "  ".join(names_m[:_cap])
                tail = f"  + {len(names_m) - _cap} more" if len(names_m) > _cap else ""
                row(f"{miss_color}Missing ({len(names_m)}){Style.RESET_ALL}:  {miss_list}{tail}")
            else:
                row(f"{Fore.GREEN}Sequence complete — no missing folders{Style.RESET_ALL}")
            if pat.get("other_names"):
                _cap = 8
                names_o = pat["other_names"]
                others = "  ".join(names_o[:_cap])
                tail = f"  + {len(names_o) - _cap} more" if len(names_o) > _cap else ""
                row(f"{Style.DIM}Outside pattern:  {others}{tail}{Style.RESET_ALL}")
        row()

    # ── duplicates ────────────────────────────────────────────
    dupes = [(r.name, r.duplicate_of, r.duplicate_info) for r in sorted_results if r.duplicate_of]
    if dupes:
        section("DUPLICATES")
        for name, orig, di in dupes:
            kind = di.get("kind", "exact")
            sim  = di.get("similarity", 1.0)
            tag  = "exact clone" if kind == "exact" else f"near-duplicate  {sim:.0%}"
            row(f"{Fore.YELLOW}{Style.BRIGHT}{name}{Style.RESET_ALL}"
                f"  {Style.DIM}→{Style.RESET_ALL}  {orig}"
                f"  {Style.DIM}({tag}){Style.RESET_ALL}")
        row()

    # ── results list ──────────────────────────────────────────
    section("RESULTS")
    name_w = min(28, max((len(r.name) for r in sorted_results), default=12))
    for r in sorted_results:
        name = r.name[:name_w]
        if r.verdict.startswith("ACCEPTED"):
            vcolor, tag = Fore.GREEN, r.verdict
        elif r.verdict == "SKIPPED":
            vcolor, tag = Fore.YELLOW, "SKIPPED "
        else:
            vcolor, tag = Fore.RED, "REJECTED"
        if r.verdict == "SKIPPED":
            score_part = ""
        elif r.max_score == 0:
            score_part = f"  {'0':>3}/—"
        else:
            bar = _score_bar(r.score, r.max_score)
            score_part = f"  {r.score:>3}/{r.max_score}  {bar}"
        dupe_tag = f"  {Fore.YELLOW}⚑ dupe{Style.RESET_ALL}" if r.duplicate_of else ""
        row(f"{name:<{name_w}}   {vcolor}{Style.BRIGHT}{tag}{Style.RESET_ALL}{score_part}{dupe_tag}")
    row()

    # ── reports ───────────────────────────────────────────────
    section("REPORTS")
    row(f"{Style.DIM}›{Style.RESET_ALL} {report_md}")
    row(f"{Style.DIM}›{Style.RESET_ALL} {report_csv}")
    row()
    print("╚" + "═" * (W - 2) + "╝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
