"""本地资源路径与 Markdown 引用工具。"""

from __future__ import annotations

import os
import re
from typing import Iterable


def asset_rel_path(page_id: str, filename: str) -> str:
    """生成相对页面 Markdown 的资源路径（POSIX 风格）。"""
    safe = os.path.basename(filename).replace("\\", "/")
    return f"assets/{page_id}/{safe}"


def collect_local_refs_from_md(md: str) -> set[str]:
    """从 Markdown 中收集 ![](path) 与 [text](path) 的本地路径引用。"""
    refs: set[str] = set()
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md):
        refs.add(m.group(1).strip())
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", md):
        path = m.group(1).strip()
        if not path.startswith("http://") and not path.startswith("https://"):
            refs.add(path)
    return refs


def replace_local_paths(md: str, path_to_url: dict[str, str]) -> str:
    """将 Markdown 中的本地路径替换为 Dify 可访问 URL。"""
    if not path_to_url:
        return md

    def replacer(match: re.Match) -> str:
        prefix, path, suffix = match.group(1), match.group(2).strip(), match.group(3)
        if path in path_to_url:
            return f"{prefix}{path_to_url[path]}{suffix}"
        return match.group(0)

    # ![alt](path) 与 [text](path)
    pattern = r"(!?\[[^\]]*\]\()([^)]+)(\))"
    return re.sub(pattern, replacer, md)


def resolve_abs_path(md_dir: str, rel_path: str) -> str:
    return os.path.normpath(os.path.join(md_dir, rel_path))
