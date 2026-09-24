"""从 config.yaml 读取本地工作目录（下载、同步、上传共用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_WORKSPACE = "./temp_confluence"


def get_workspace_dir(
    config: dict[str, Any],
    config_path: Path | str | None = None,
) -> Path:
    """
    解析 paths.workspace（唯一推荐配置项）。

    兼容旧配置：sync.local_temp_dir、upload.folder、download_attachments.download_root。
    """
    paths = config.get("paths") or {}
    raw = paths.get("workspace")
    if not raw:
        raw = (
            (config.get("sync") or {}).get("local_temp_dir")
            or (config.get("upload") or {}).get("folder")
            or (config.get("download_attachments") or {}).get("download_root")
            or (config.get("dify") or {}).get("local_images_dir")
            or DEFAULT_WORKSPACE
        )
    p = Path(str(raw).strip())
    if not p.is_absolute() and config_path is not None:
        base = Path(config_path).resolve().parent
        return (base / p).resolve()
    return p.resolve()
