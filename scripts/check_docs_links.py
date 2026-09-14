#!/usr/bin/env python3
"""Check that every relative Markdown link in the repo resolves.

Covers both halves of a link: the file path, and the `#anchor` fragment
against the target file's headings. Broken cross-references are easy to
introduce when renaming a heading and cheap to catch here.

Usage: python3 scripts/check_docs_links.py
Exits non-zero (and lists offenders) if anything is broken.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", "cdk.out"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def slugify(heading: str) -> str:
    """Approximate GitHub's heading -> anchor conversion.

    Lowercase, drop backticks and punctuation, then replace each space with a
    hyphen. Note "each": "Custom domain + TLS" loses the "+" and keeps both
    surrounding spaces, giving "custom-domain--tls".
    """
    text = heading.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return text.replace(" ", "-")


def markdown_files() -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found.extend(
            os.path.join(dirpath, name) for name in filenames if name.endswith(".md")
        )
    return sorted(found)


def main() -> int:
    files = markdown_files()
    anchors = {}
    for path in files:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        anchors[os.path.realpath(path)] = {slugify(h) for _, h in HEADING_RE.findall(text)}

    problems: list[str] = []
    for path in files:
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()

        for target in LINK_RE.findall(text):
            target = target.strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue

            path_part, _, fragment = target.partition("#")
            if path_part:
                resolved = os.path.normpath(os.path.join(os.path.dirname(path), path_part))
                if not os.path.exists(resolved):
                    problems.append(f"{rel}: missing file -> {target}")
                    continue
            else:
                resolved = path  # same-document anchor

            real = os.path.realpath(resolved)
            if fragment and real in anchors and fragment not in anchors[real]:
                problems.append(f"{rel}: no such heading -> {target}")

    if problems:
        print(f"{len(problems)} broken link(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(f"All relative links and anchors resolve across {len(files)} Markdown files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
