"""`unsinkable wire` codemod — rewrite OpenAI/Anthropic SDK imports in a
project so they point at the unsinkable shim instead. Uses libcst to preserve
formatting and comments.

Handles:
  from openai    import OpenAI [as X], AsyncOpenAI [as Y]
  from anthropic import Anthropic [as X], AsyncAnthropic [as Y]
  import openai             (warned; not rewritten — too brittle to be safe)
  import anthropic          (warned; not rewritten)
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst

REWRITE_MAP: dict[str, dict[str, str]] = {
    "openai": {"OpenAI": "OpenAI", "AsyncOpenAI": "AsyncOpenAI"},
    "anthropic": {"Anthropic": "Anthropic", "AsyncAnthropic": "AsyncAnthropic"},
}
TARGET_PACKAGE = "unsinkable"


@dataclass
class FileResult:
    path: Path
    rewritten: bool = False
    diff: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class _RewriteImports(cst.CSTTransformer):
    def __init__(self) -> None:
        self.rewritten_modules: set[str] = set()
        self.warnings: list[str] = []

    def leave_ImportFrom(
        self, original: cst.ImportFrom, updated: cst.ImportFrom
    ) -> cst.ImportFrom:
        if updated.module is None:
            return updated
        module_name = _dotted_name(updated.module)
        if module_name not in REWRITE_MAP:
            return updated
        allowed = REWRITE_MAP[module_name]
        # Verify every alias is one we know how to rewrite; if not, skip the line
        # rather than silently dropping unknown symbols.
        if isinstance(updated.names, cst.ImportStar):
            self.warnings.append(
                f"`from {module_name} import *` cannot be safely rewritten — skipped"
            )
            return updated
        unknown = [a.name.value for a in updated.names if a.name.value not in allowed]
        if unknown:
            self.warnings.append(
                f"`from {module_name} import {', '.join(unknown)}` — unknown symbol(s); "
                f"skipped this import"
            )
            return updated
        self.rewritten_modules.add(module_name)
        return updated.with_changes(module=cst.parse_expression(TARGET_PACKAGE))

    def leave_Import(self, original: cst.Import, updated: cst.Import) -> cst.Import:
        for alias in updated.names:
            mod = _dotted_name(alias.name)
            if mod in REWRITE_MAP:
                self.warnings.append(
                    f"`import {mod}` left unchanged — use `from {mod} import OpenAI` "
                    f"form to enable codemod, or rewrite manually."
                )
        return updated


def _dotted_name(node: cst.BaseExpression) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr.value}"
    return ""


def rewrite_source(source: str) -> tuple[str, list[str]]:
    """Return (new_source, warnings). Identity-stable if no rewrites apply."""
    module = cst.parse_module(source)
    transformer = _RewriteImports()
    new_module = module.visit(transformer)
    return new_module.code, transformer.warnings


def _make_diff(path: Path, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
    ))


def wire_path(target: Path, dry_run: bool = False) -> list[FileResult]:
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    results: list[FileResult] = []
    for path in files:
        # Skip the unsinkable package itself, virtualenvs, build dirs, dotdirs.
        s = str(path)
        if any(part.startswith(".") for part in path.parts) or any(
            seg in s for seg in ("/.venv/", "/venv/", "/site-packages/", "/build/", "/dist/", "/unsinkable/")
        ):
            continue
        try:
            before = path.read_text(encoding="utf-8")
            after, warnings = rewrite_source(before)
        except (UnicodeDecodeError, cst.ParserSyntaxError) as exc:
            results.append(FileResult(path=path, error=f"{type(exc).__name__}: {exc}"))
            continue
        if after == before:
            if warnings:
                results.append(FileResult(path=path, warnings=warnings))
            continue
        diff = _make_diff(path, before, after)
        if not dry_run:
            path.write_text(after, encoding="utf-8")
        results.append(FileResult(path=path, rewritten=True, diff=diff, warnings=warnings))
    return results
