#!/usr/bin/env python3
"""Size and purity gate for the repository.

Rules (CONTRIBUTING.md):
  * a source file has at most MAX_FILE_LINES lines;
  * a function has at most MAX_FUNCTION_LINES lines (header to closing brace);
  * code under a `core` directory imports nothing from Android or JNI.

Exit codes: 0 clean, 1 violations found, 2 usage error.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 60
SOURCE_SUFFIXES = {".kt", ".kts", ".cpp", ".hpp", ".h", ".c", ".cc", ".py"}
SKIP_DIRS = {".git", "build", ".gradle", ".cxx", ".idea", "results", "node_modules", "__pycache__"}
CORE_FORBIDDEN = [
    (re.compile(r"#\s*include\s*[<\"](jni\.h|android/)"), "Android/JNI include in core"),
    (re.compile(r"__android_log"), "Android logging in core"),
    (re.compile(r"^\s*import\s+(android|androidx)\.", re.M), "Android import in core"),
]
CONTAINER_WORDS = {
    "cpp": re.compile(r"\b(namespace|class|struct|union|enum|extern)\b"),
    "kt": re.compile(r"\b(class|object|interface)\b"),
}
FUNCTION_HINT = {"cpp": re.compile(r"\("), "kt": re.compile(r"\bfun\b")}


@dataclass
class Violation:
    path: str
    line: int
    rule: str
    detail: str


def strip_comments_and_strings(text: str) -> str:
    """Blank out comments and string/char literals, keeping newlines so line numbers hold."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif text[i] in "\"'":
            j = _end_of_quoted(text, i)
        else:
            out.append(text[i])
            i += 1
            continue
        out.append(re.sub(r"[^\n]", " ", text[i:j]))
        i = j
    return "".join(out)


def _end_of_quoted(text: str, i: int) -> int:
    quote, j = text[i], i + 1
    while j < len(text) and text[j] != quote and text[j] != "\n":
        j += 2 if text[j] == "\\" else 1
    return min(j + 1, len(text))


def brace_functions(text: str, lang: str) -> list[tuple[int, int]]:
    """(start_line, n_lines) of every function body in C++ or Kotlin source."""
    code = strip_comments_and_strings(text)
    found: list[tuple[int, int]] = []
    _scan_block(code, 0, lang, found)
    return found


def _scan_block(code: str, pos: int, lang: str, found: list[tuple[int, int]]) -> int:
    """Scan from pos until the matching '}' of the enclosing block; return index after it."""
    header_start = pos
    while pos < len(code):
        ch = code[pos]
        if ch in ";}":
            if ch == "}":
                return pos + 1
            header_start = pos + 1
        elif ch == "{":
            header = code[header_start:pos]
            kind, offset = _classify(header, lang)
            if kind == "container":
                pos = _scan_block(code, pos + 1, lang, found)
            else:
                end = _matching_brace(code, pos)
                if kind == "function":
                    first = header_start + offset if offset is not None else _header_first_char(code, header_start, pos)
                    start_line = code.count("\n", 0, first) + 1
                    end_line = code.count("\n", 0, end) + 1
                    found.append((start_line, end_line - start_line + 1))
                pos = end + 1
            header_start = pos
            continue
        pos += 1
    return pos


KT_DECLARATION = re.compile(r"\b(fun|class|object|interface)\b")


def _classify(header: str, lang: str) -> tuple[str, int | None]:
    """(kind, offset of the declaration in header): container (scan inside), function
    (measure), data or other (skip)."""
    s = header.strip()
    if lang == "kt":
        # Kotlin has no semicolons, so a header can hold several declarations
        # (`data class E(...)` then `fun f() {`); the last declaration keyword owns the brace.
        last = None
        for last in KT_DECLARATION.finditer(header):
            pass
        if last is None:
            return ("data" if s.endswith("=") else "other"), None
        return ("function" if last.group(1) == "fun" else "container"), last.start()
    # `template<class T> T f(...)` has parentheses; namespace/class/struct headers do not.
    if "(" not in s and CONTAINER_WORDS["cpp"].search(s) is not None:
        return "container", None
    if s.endswith("="):
        return "data", None
    if FUNCTION_HINT[lang].search(s):
        return "function", None
    return "other", None


def _header_first_char(code: str, start: int, end: int) -> int:
    for k in range(start, end):
        if not code[k].isspace():
            return k
    return end


def _matching_brace(code: str, open_pos: int) -> int:
    depth = 0
    for k in range(open_pos, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(code) - 1


def python_functions(text: str) -> list[tuple[int, int]]:
    tree = ast.parse(text)
    return [
        (node.lineno, node.end_lineno - node.lineno + 1)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None
    ]


def check_file(path: Path, rel: str) -> list[Violation]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[Violation] = []
    n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if n_lines > MAX_FILE_LINES:
        out.append(Violation(rel, 1, "file-lines", f"{n_lines} > {MAX_FILE_LINES}"))
    suffix = path.suffix
    if suffix == ".py":
        functions = python_functions(text)
    elif suffix in {".kt", ".kts"}:
        functions = brace_functions(text, "kt")
    else:
        functions = brace_functions(text, "cpp")
    for line, length in functions:
        if length > MAX_FUNCTION_LINES:
            out.append(Violation(rel, line, "function-lines", f"{length} > {MAX_FUNCTION_LINES}"))
    if "core" in Path(rel).parts:
        for pattern, what in CORE_FORBIDDEN:
            for m in pattern.finditer(text):
                out.append(Violation(rel, text.count("\n", 0, m.start()) + 1, "core-purity", what))
    return out


def iter_sources(root: Path):
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p.startswith("fixtures") for p in rel_parts[:-1]):
            continue
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            yield path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="repository root to check")
    ap.add_argument("--json", action="store_true", help="print violations as JSON")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every file checked")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    violations: list[Violation] = []
    checked = 0
    for path in iter_sources(root):
        rel = path.relative_to(root).as_posix()
        if args.verbose:
            print(f"check {rel}", file=sys.stderr)
        violations += check_file(path, rel)
        checked += 1
    if args.json:
        print(json.dumps({"checked": checked, "violations": [asdict(v) for v in violations]}, indent=2))
    else:
        for v in violations:
            print(f"{v.path}:{v.line}: {v.rule}: {v.detail}")
        print(f"{checked} files checked, {len(violations)} violations", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
