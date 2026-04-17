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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

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
IMPORT_TO_PACKAGE_ALIASES: dict[str, str | list[str]] = {
    # Imaging
    "pil": "pillow",
    "cv2": ["opencv-python", "opencv-contrib-python", "opencv-python-headless"],
    "skimage": "scikit-image",
    # ML / AI
    "sklearn": "scikit-learn",
    "whisper": "openai-whisper",
    "langchain_community": "langchain-community",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "sentence_transformers": "sentence-transformers",
    "xgboost": "xgboost",
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
    # Database
    "mysql": ["mysql-connector-python", "mysqlclient", "pymysql"],
    "psycopg2": ["psycopg2", "psycopg2-binary"],
    "pymongo": "pymongo",
    "bson": "pymongo",
    # Web
    "jwt": "pyjwt",
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
    # Google
    "google": ["google-api-python-client", "google-generativeai",
               "google-cloud-storage", "google-auth", "googleapis-common-protos",
               "google-cloud-bigquery", "google-cloud-firestore"],
    "googleapiclient": "google-api-python-client",
    # Crypto / security
    "crypto": "pycryptodome",
    "Crypto": "pycryptodome",
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
    # Audio / speech / video
    "speech_recognition": "speechrecognition",
    "gtts": "gtts",
    "pydub": "pydub",
    "moviepy": "moviepy",
    # Search / web scraping
    "ddgs": "duckduckgo-search",
    "playwright": "playwright",
    "selenium": "selenium",
    # Networking / API
    "dns": "dnspython",
    "magic": "python-magic",
    "gi": "pygobject",
    "telegram": "python-telegram-bot",
    "tweepy": "tweepy",
    "instaloader": "instaloader",
    "discord": "discord.py",
    # Misc
    "dotenv": "python-dotenv",
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
}

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
    "7b_readme_quality",
]

# Python entry-point discovery priority (top-level first, then tree walk)
PY_ENTRY_TOP_LEVEL = ["main.py", "app.py", "run.py"]

# Node entry-point fallback priority (after npm start script and main field)
NODE_ENTRY_FALLBACK = ["index.js", "server.js", "app.js"]

# Targeted error substrings (Check 6) -- these mean "not self-contained"
PY_TARGETED_ERRORS = ["ModuleNotFoundError", "ImportError", "SyntaxError"]
NODE_TARGETED_ERRORS = ["Cannot find module", "MODULE_NOT_FOUND", "SyntaxError"]

# Timeouts (seconds)
VENV_CREATE_TIMEOUT = 120
PIP_INSTALL_TIMEOUT = 180
NPM_INSTALL_TIMEOUT = 300
RUN_TIMEOUT = 15


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
    notes: list = field(default_factory=list)
    logs: dict = field(default_factory=dict)

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

def _should_exclude_dir(name: str) -> bool:
    low = name.lower()
    if low in EXCLUDE_DIRS_LOWER:
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
            except Exception:
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
        except Exception:
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
    except Exception:
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
    except Exception:
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
            has_py = any(f.endswith(".py") for f in os.listdir(sub))
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
    except Exception:
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
    except Exception:
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
            except Exception:
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
            transitive_covered |= {c.lower() for c in children}
    missing = []
    for imp in third_party:
        if imp.lower() in transitive_covered:
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

    clone_re = re.compile(
        r"git\s+clone\s+(https?://\S+)", re.IGNORECASE,
    )
    clone_match = clone_re.search(text)
    if clone_match:
        findings.append(
            f"README tells user to 'git clone' from {clone_match.group(1).rstrip('`')} "
            f"— useless for a hard-drive submission"
        )

    github_hits = sum(1 for p in GITHUB_STYLE_SIGNALS if p.search(text))
    is_github_style = github_hits >= GITHUB_STYLE_THRESHOLD

    has_install = any(kw in text_lower for kw in INSTALL_KEYWORDS)
    has_run = any(kw in text_lower for kw in RUN_KEYWORDS)

    if is_github_style:
        findings.append(
            f"GitHub-style README ({github_hits} signals: badges, "
            f"contributing/license sections, fork/PR language)"
        )

    if not has_install:
        findings.append("No installation instructions found")
    if not has_run:
        findings.append("No execution/run instructions found")

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
    else:
        c3, c4 = check_manifest_and_imports_node(proj)
    r.add(c3)
    r.add(c4)
    c7, c7b = check_readme(proj)
    r.add(c7)
    r.add(c7b)
    return r


def compute_verdict(r: ProjectResult) -> str:
    if r.verdict:
        return r.verdict
    for c in r.checks.values():
        if not c.passed:
            return "REJECTED"
    return "ACCEPTED"


# ============================================================
# Report writers (incremental)
# ============================================================

def write_csv(results: list[ProjectResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "project_name", "stack", "verdict",
            "check1_abs_paths", "check2_external_refs",
            "check3_manifest", "check4_imports_declared",
            "check5_install", "check6_runs", "check7_readme", "check7b_readme_quality",
            "failure_summary",
        ])
        for r in results:
            row = [r.name, r.stack, r.verdict]
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
            row.append("; ".join(parts))
            w.writerow(row)


def _finding_to_line(f: dict) -> str:
    try:
        return json.dumps(f, ensure_ascii=False)
    except Exception:
        return str(f)


def write_md(results: list[ProjectResult], path: Path, env: dict) -> None:
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
    accepted = sum(1 for r in results if r.verdict == "ACCEPTED")
    skipped = sum(1 for r in results if r.verdict == "SKIPPED")
    rejected = len(results) - accepted - skipped
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **ACCEPTED**: {accepted}/{len(results)}")
    lines.append(f"- **REJECTED**: {rejected}/{len(results)}")
    if skipped:
        lines.append(f"- **SKIPPED**: {skipped}/{len(results)} (empty folders)")
    lines.append("")
    breakdown: dict[str, int] = {}
    for r in results:
        if r.verdict != "REJECTED":
            continue
        for k, c in r.checks.items():
            if not c.passed:
                breakdown[k] = breakdown.get(k, 0) + 1
    if breakdown:
        lines.append("## Rejection Reasons Breakdown")
        lines.append("")
        for k in sorted(breakdown.keys()):
            lines.append(f"- `{k}`: {breakdown[k]} project(s)")
        lines.append("")
    lines.append("## Per-Project Details")
    lines.append("")
    for r in results:
        lines.append(f"### {r.name}")
        lines.append("")
        lines.append(f"- **Stack**: `{r.stack}`")
        lines.append(f"- **Verdict**: **{r.verdict}**")
        lines.append(f"- **Path**: `{r.path}`")
        if r.notes:
            lines.append(f"- **Notes**: {'; '.join(r.notes)}")
        lines.append("")
        lines.append("| Check | Status | Detail |")
        lines.append("|---|---|---|")
        for key in sorted(r.checks.keys()):
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
# Console progress printer
# ============================================================

def print_progress(r: ProjectResult) -> None:
    for key in sorted(r.checks.keys()):
        c = r.checks[key]
        if c.na:
            color, mark = Fore.CYAN, "N/A "
        elif c.passed:
            color, mark = Fore.GREEN, "PASS"
        else:
            color, mark = Fore.RED, "FAIL"
        print(f"  {color}[{mark}]{Style.RESET_ALL} {key}: {c.detail}")
    if r.verdict == "SKIPPED":
        vcolor = Fore.YELLOW
    elif r.verdict == "ACCEPTED":
        vcolor = Fore.GREEN
    else:
        vcolor = Fore.RED
    print(f"  {vcolor}VERDICT: {r.verdict}{Style.RESET_ALL}")


def project_short_code(name: str) -> str:
    m = re.match(r"^(C\d+)", name)
    if m:
        return m.group(1)
    return name.replace(" ", "_")


# ============================================================
# CLI / main
# ============================================================

def main() -> int:
    p = argparse.ArgumentParser(
        description="Self-contained verification tool for student mini-projects.",
    )
    p.add_argument("root", type=Path,
                   help="Root directory containing project subfolders")
    p.add_argument("--single", type=str, default=None,
                   help="Audit only one project by folder name")
    p.add_argument("--resume", action="store_true",
                   help="Skip projects already in existing report")
    p.add_argument("--only-static", action="store_true",
                   help="Skip install/run checks (quick preview)")
    p.add_argument("--report-dir", type=Path, default=Path.cwd(),
                   help="Where to write report files (default: cwd)")
    args = p.parse_args()

    colorama_init(autoreset=True)
    env = verify_environment()
    print(f"{Fore.CYAN}Python {env['python']} | "
          f"node {env.get('node_version') or 'MISSING'} | "
          f"npm {env.get('npm_version') or 'MISSING'}{Style.RESET_ALL}")
    if not env.get("node_ok") or not env.get("npm_ok"):
        print(f"{Fore.YELLOW}WARNING: node or npm not on PATH -- Node projects "
              f"will fail dynamic checks{Style.RESET_ALL}")

    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"{Fore.RED}ERROR: root dir does not exist: {root}{Style.RESET_ALL}")
        return 2

    all_projects = sorted(
        [x for x in root.iterdir() if x.is_dir() and x.name not in EXCLUDE_DIRS]
    )
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
    args.report_dir.mkdir(parents=True, exist_ok=True)

    done_names: set[str] = set()
    if args.resume and report_csv.exists():
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

    counts = {"python": 0, "node": 0, "both": 0, "flutter": 0, "unknown": 0}
    for x in all_projects:
        counts[detect_stack(x)] += 1
    parts = [f"{counts['python']} Python", f"{counts['node']} Node"]
    if counts['flutter']:
        parts.append(f"{counts['flutter']} Flutter")
    if counts['both']:
        parts.append(f"{counts['both']} Both")
    parts.append(f"{counts['unknown']} Unknown")
    print(f"{Fore.CYAN}Found {len(all_projects)} project folders "
          f"({' / '.join(parts)}). Starting audit...{Style.RESET_ALL}\n")

    results: list[ProjectResult] = []
    to_audit = [x for x in all_projects if x.name not in done_names]
    for i, proj in enumerate(to_audit, start=1):
        print(f"{Fore.YELLOW}[{i}/{len(to_audit)}] {proj.name} "
              f"({detect_stack(proj)}){Style.RESET_ALL}")
        try:
            r = audit_static(proj)
            if not args.only_static and not r.verdict:
                # Dynamic checks (5, 6) will be added in the next step
                pass
            r.verdict = compute_verdict(r)
            print_progress(r)
            results.append(r)
            write_csv(results, report_csv)
            write_md(results, report_md, env)
        except Exception as e:
            r = ProjectResult(name=proj.name, path=proj, stack="unknown")
            r.verdict = "REJECTED"
            r.notes.append(f"audit harness error: {e!r}")
            results.append(r)
            print(f"  {Fore.RED}REJECTED (harness error: {e!r}){Style.RESET_ALL}")
            write_csv(results, report_csv)
            write_md(results, report_md, env)
        print()
        if i < len(to_audit):
            time.sleep(2)

    accepted = sum(1 for r in results if r.verdict == "ACCEPTED")
    skipped = sum(1 for r in results if r.verdict == "SKIPPED")
    rejected = len(results) - accepted - skipped
    print(f"{Fore.CYAN}=== Audit complete ==={Style.RESET_ALL}")
    print(f"{Fore.GREEN}ACCEPTED: {accepted}{Style.RESET_ALL}")
    print(f"{Fore.RED}REJECTED: {rejected}{Style.RESET_ALL}")
    if skipped:
        print(f"{Fore.YELLOW}SKIPPED: {skipped} (empty folders){Style.RESET_ALL}")
    print("")
    print(f"{Fore.CYAN}Unified project status list:{Style.RESET_ALL}")
    # Sort results by team number for numeric order
    sorted_results = sorted(results, key=lambda r: int(re.match(r'C(\d+)', r.name).group(1)))
    for r in sorted_results:
        code = project_short_code(r.name)
        status = "NOT_SUBMITTED" if r.verdict == "SKIPPED" else r.verdict
        print(f"{code}-{status}")
    print(f"\nReports:\n  {report_md}\n  {report_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
