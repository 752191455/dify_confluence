"""从 config.yaml 读取 Dify 知识库支持的文件扩展名（upload.extensions）。"""

from __future__ import annotations

from typing import Any


def parse_upload_extensions(raw: dict[str, Any]) -> tuple[set[str], set[str]]:
    """
    解析 upload.extensions 配置。
    返回 (带点扩展名集合, 不带点扩展名集合)，例如 ({'.pdf'}, {'pdf'})。
    """
    upload = raw.get("upload") or {}
    if upload.get("upload_all_extensions"):
        return set(), set()

    ext_list = upload.get("extensions") or []
    if not ext_list:
        raise ValueError(
            "config.yaml 中 upload.extensions 未配置，请设置 Dify 知识库支持的文件扩展名"
        )

    dot_exts = {
        (str(e) if str(e).startswith(".") else f".{e}").lower() for e in ext_list
    }
    name_exts = {e.lstrip(".") for e in dot_exts}
    return dot_exts, name_exts


def extension_names_from_list(ext_list) -> set[str]:
    return {str(f).lower().lstrip(".") for f in (ext_list or [])}


def is_allowed_extension(filename: str, name_exts: set[str]) -> bool:
    if not name_exts:
        return True
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[-1].lower() in name_exts
