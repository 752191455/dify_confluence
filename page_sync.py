"""单页 Confluence → Markdown（含本地资源路径）→ Dify 上传与 URL 回写。"""

from __future__ import annotations

import logging
import os
from typing import Any

from asset_paths import asset_rel_path
from dify_file_service import DifyFileService
from dify_uploader import DifyUploader
from markdown_builder import build_page_markdown

logger = logging.getLogger(__name__)


def safe_filename(title: str) -> str:
    return "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).rstrip()


def download_attachment_to_local(attachment, download_dir, confluence_client):
    filename, mime, content = confluence_client.download_attachment(attachment)
    safe_name = safe_filename(filename) or f"attachment_{attachment['id']}"
    ext = os.path.splitext(filename)[1]
    if ext and not safe_name.lower().endswith(ext.lower()):
        safe_name = safe_name + ext
    os.makedirs(download_dir, exist_ok=True)
    file_path = os.path.join(download_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path, safe_name, mime


def prepare_page_assets(page_id: str, attachments: list, space_temp: str, confluence) -> tuple[dict[str, str], dict[str, str]]:
    """
    下载页面附件到 assets/{page_id}/，返回：
    - asset_rel_paths: Confluence 附件名 -> Markdown 相对路径
    - asset_registry: Markdown 相对路径 -> 本地绝对路径
    """
    assets_dir = os.path.join(space_temp, "assets", page_id)
    os.makedirs(assets_dir, exist_ok=True)
    rel_paths: dict[str, str] = {}
    registry: dict[str, str] = {}

    for att in attachments:
        try:
            file_path, att_name, _mime = download_attachment_to_local(
                att, assets_dir, confluence
            )
            title = att.get("title") or att_name
            rel = asset_rel_path(page_id, title)
            rel_paths[title] = rel
            registry[rel] = file_path
            logger.info("    资源已落地: %s -> %s", title, rel)
        except Exception as e:
            logger.error("    资源下载失败 %s: %s", att.get("title", ""), e)

    return rel_paths, registry


def sync_page_to_dify(
    page: dict[str, Any],
    *,
    confluence,
    dify: DifyUploader,
    file_service: DifyFileService,
    space_temp: str,
    config: dict,
    desc: str = "",
) -> None:
    """同步单页：生成带本地路径的 MD → 上传资源换 URL → 回写并上传 MD。"""
    page_id = page["id"]
    title = page.get("title", f"page_{page_id}")
    conf_cfg = config.get("confluence", {})
    include_comments = conf_cfg.get("include_comments", True)
    include_labels = conf_cfg.get("include_labels", True)
    base_url = conf_cfg.get("base_url", "")

    if not page.get("body", {}).get("storage", {}).get("value"):
        page = confluence.get_page_by_id(page_id)

    attachments = confluence.get_attachments(page_id)
    asset_rel_paths, asset_registry = prepare_page_assets(
        page_id, attachments, space_temp, confluence
    )

    labels = confluence.get_page_labels(page_id) if include_labels else []
    contributors = confluence.get_page_contributors(page_id)
    author = confluence.get_page_creator(page)
    comments = confluence.get_comments(page_id) if include_comments else []

    md_content = build_page_markdown(
        page,
        labels=labels,
        contributors=contributors,
        comments=comments,
        author=author,
        base_url=base_url,
        asset_rel_paths=asset_rel_paths,
    )

    clean_title = safe_filename(title)
    page_filename = f"{clean_title}_{page_id}.md"
    page_path = os.path.join(space_temp, page_filename)
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    dify.upload_markdown_with_asset_urls(
        page_path,
        page_filename,
        conflu_id=f"page:{page_id}",
        file_service=file_service,
        asset_registry=asset_registry,
    )
    logger.info("    页面 Markdown 已上传（资源 URL 已回写）: %s", page_filename)
