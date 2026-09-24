"""将 Confluence 页面/空间内容组装为完整 Markdown 文档（含元数据、评论、空间描述）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from html2text import html2text

from content_handler import process_storage_to_html


def _format_timestamp(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return iso_str


def _storage_to_plain_text(storage_xml: str) -> str:
    if not storage_xml:
        return ""
    soup = BeautifulSoup(storage_xml, "xml")
    return soup.get_text(separator="\n", strip=True)


def _html_to_markdown(html_doc: str) -> str:
    md = html2text(html_doc, bodywidth=0)
    # 去掉 html2text 自动生成的顶层标题（正文里已有 h1）
    return md.strip()


def extract_page_timestamps(page_data: dict[str, Any]) -> dict[str, str]:
    history = page_data.get("history") or {}
    version = page_data.get("version") or {}
    created_by = history.get("createdBy") or {}
    modified_by = version.get("by") or {}
    return {
        "created_at": _format_timestamp(history.get("createdDate")),
        "modified_at": _format_timestamp(version.get("when")),
        "created_by": created_by.get("displayName") or created_by.get("username") or "",
        "last_modified_by": modified_by.get("displayName") or modified_by.get("username") or "",
        "version": str(version.get("number", "")),
    }


def build_metadata_section(
    page_data: dict[str, Any],
    labels: list[str],
    contributors: list[str],
    base_url: str = "",
) -> str:
    """生成页面元数据 Markdown 块。"""
    ts = extract_page_timestamps(page_data)
    title = page_data.get("title", "")
    page_id = page_data.get("id", "")
    space_key = (page_data.get("space") or {}).get("key", "")
    webui = (page_data.get("_links") or {}).get("webui", "")
    source_url = f"{base_url.rstrip('/')}{webui}" if base_url and webui else webui

    lines = [
        "## 文档元数据",
        "",
        f"| 字段 | 值 |",
        f"|------|-----|",
        f"| 标题 | {title} |",
        f"| 页面 ID | {page_id} |",
        f"| 空间 | {space_key} |",
        f"| 创建时间 | {ts['created_at']} |",
        f"| 修改时间 | {ts['modified_at']} |",
        f"| 创建人 | {ts['created_by']} |",
        f"| 最后修改人 | {ts['last_modified_by']} |",
        f"| 版本号 | {ts['version']} |",
    ]
    if labels:
        lines.append(f"| 标签 | {', '.join(labels)} |")
    if contributors:
        lines.append(f"| 贡献者 | {', '.join(contributors)} |")
    if source_url:
        lines.append(f"| 原文链接 | {source_url} |")
    lines.append("")
    return "\n".join(lines)


def build_comments_section(comments: list[dict[str, Any]]) -> str:
    if not comments:
        return ""
    lines = ["\n---\n\n## 评论\n"]
    for idx, comment in enumerate(comments, 1):
        history = comment.get("history") or {}
        author = (history.get("createdBy") or {}).get("displayName", "Unknown")
        when = _format_timestamp(history.get("createdDate"))
        body_storage = (comment.get("body") or {}).get("storage", {}).get("value", "")
        body_md = _storage_to_plain_text(body_storage)
        lines.append(f"\n### 评论 {idx}\n")
        lines.append(f"- **作者**: {author}")
        if when:
            lines.append(f"- **时间**: {when}")
        lines.append(f"\n{body_md}\n")
    return "\n".join(lines)


def build_page_markdown(
    page_data: dict[str, Any],
    *,
    labels: list[str] | None = None,
    contributors: list[str] | None = None,
    comments: list[dict[str, Any]] | None = None,
    author: str = "",
    base_url: str = "",
    asset_rel_paths: dict[str, str] | None = None,
) -> str:
    """
    将单页 Confluence 内容转为完整 Markdown：元数据 + 正文 + 评论。
    空间描述请使用 build_space_description_markdown 单独生成文档。
    """
    title = page_data.get("title", "Untitled")
    storage = (page_data.get("body") or {}).get("storage", {}).get("value", "")
    labels = labels or []
    contributors = contributors or []
    comments = comments or []

    html_doc = process_storage_to_html(
        storage,
        title,
        author=author,
        labels=labels,
        asset_rel_paths=asset_rel_paths,
    )
    body_md = _html_to_markdown(html_doc)

    parts = [
        f"# {title}\n",
        build_metadata_section(page_data, labels, contributors, base_url),
        "---\n",
        "## 正文\n",
        body_md,
    ]

    if comments:
        parts.append(build_comments_section(comments))

    return "\n".join(parts).strip() + "\n"


def build_space_description_markdown(
    space_key: str,
    description: str,
    space_name: str = "",
) -> str:
    """空间描述独立 Markdown 文档。"""
    name = space_name or space_key
    return (
        f"# 空间描述: {name}\n\n"
        f"## 文档元数据\n\n"
        f"| 字段 | 值 |\n"
        f"|------|-----|\n"
        f"| 空间 Key | {space_key} |\n"
        f"| 空间名称 | {name} |\n\n"
        f"---\n\n"
        f"## 描述内容\n\n"
        f"{description.strip()}\n"
    )
