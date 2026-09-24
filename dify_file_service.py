"""Dify 文件上传与预览 URL 生成。"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class DifyFileService:
    """通过 Knowledge Pipeline 上传文件并生成 Markdown 可引用的预览 URL。"""

    def __init__(self, api_base_url: str, api_key: str, files_base_url: str | None = None):
        self.api_base = api_base_url.rstrip("/")
        self.api_v1 = self.api_base if self.api_base.endswith("/v1") else f"{self.api_base}/v1"
        self.api_key = api_key
        self.files_base = (files_base_url or self._default_files_base()).rstrip("/")
        self.auth_headers = {"Authorization": f"Bearer {api_key}"}

    def _default_files_base(self) -> str:
        base = self.api_v1
        if base.endswith("/v1"):
            return base[:-3]
        return base

    def upload_pipeline_file(self, file_path: str, filename: str | None = None) -> dict[str, Any]:
        """
        POST /v1/datasets/pipeline/file-upload
        返回含 id 的文件记录（用于 /files/{id}/file-preview）。
        """
        name = filename or os.path.basename(file_path)
        url = f"{self.api_v1}/datasets/pipeline/file-upload"
        with open(file_path, "rb") as f:
            files = {"file": (name, f)}
            resp = requests.post(url, headers=self.auth_headers, files=files, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        logger.info("  ✓ Pipeline file uploaded: %s -> %s", name, data.get("id"))
        return data

    def build_file_preview_url(self, upload_file_id: str, absolute: bool = True) -> str:
        """
        生成 Dify 文件预览路径。
        索引时 Dify 会将 /files/{id}/file-preview 解析为可访问地址。
        """
        path = f"/files/{upload_file_id}/file-preview"
        if absolute and self.files_base:
            return urljoin(self.files_base + "/", path.lstrip("/"))
        return path

    def upload_and_get_url(self, file_path: str, filename: str | None = None, absolute: bool = True) -> str:
        record = self.upload_pipeline_file(file_path, filename)
        file_id = record.get("id")
        if not file_id:
            raise ValueError(f"pipeline file-upload missing id: {record}")
        return self.build_file_preview_url(file_id, absolute=absolute)
