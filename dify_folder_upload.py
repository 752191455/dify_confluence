#!/usr/bin/env python3
"""
递归上传文件夹及子文件夹内所有文件到 Dify 知识库（create-by-file API）。

用法:
  python3 dify_folder_upload.py
  python3 dify_folder_upload.py /path/to/folder
  python3 dify_folder_upload.py -c

配置优先级: 命令行参数 > 环境变量 > YAML 文件
环境变量: DIFY_BASE_URL, DIFY_DATASET_ID, DIFY_API_KEY, DIFY_UPLOAD_FOLDER（覆盖 paths.workspace）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent


def _import_yaml():
    try:
        import yaml

        return yaml
    except ImportError:
        pass
    for venv_name in (".venv", "venv"):
        site = SCRIPT_DIR / "confluence_dify_sync" / venv_name
        if not site.is_dir():
            continue
        for pattern in ("lib/python*/site-packages",):
            for sp in site.glob(pattern):
                if str(sp) not in sys.path:
                    sys.path.insert(0, str(sp))
        try:
            import yaml

            return yaml
        except ImportError:
            continue
    return None


yaml = _import_yaml()
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"

SKIP_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__"}
RETRY_STATUS = {429, 502, 503, 504}

from kb_extensions import parse_upload_extensions
from workspace_paths import get_workspace_dir


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    if yaml is None:
        print(
            "错误: 需要 PyYAML。请运行: pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)
    if not config_path.is_file():
        print(f"错误: 配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_process_data(dify_raw: dict[str, Any]) -> dict[str, Any]:
    rule_raw = dify_raw.get("process_rule") or {}
    pre_rules = rule_raw.get("pre_processing_rules") or [
        {"id": "remove_extra_spaces", "enabled": True},
        {"id": "remove_urls_emails", "enabled": True},
    ]
    seg = rule_raw.get("segmentation") or {
        "separator": "###",
        "max_tokens": 500,
    }
    return {
        "indexing_technique": str(
            dify_raw.get("indexing_technique", "high_quality")
        ),
        "process_rule": {
            "rules": {
                "pre_processing_rules": pre_rules,
                "segmentation": seg,
            },
            "mode": str(rule_raw.get("mode", "custom")),
        },
    }


class UploadConfig:
    def __init__(self, raw: dict[str, Any], config_path: Path) -> None:
        dify = raw.get("dify") or {}
        upload = raw.get("upload") or {}

        self.config_path = config_path
        self.base_url = (
            os.environ.get("DIFY_BASE_URL")
            or str(dify.get("base_url", "http://localhost/v1"))
        ).rstrip("/")
        self.api_key = os.environ.get("DIFY_API_KEY") or str(
            dify.get("api_key", "")
        )
        self.dataset_id = os.environ.get("DIFY_DATASET_ID") or str(
            dify.get("dataset_id", "")
        )
        self.process_data = build_process_data(dify)
        self.upload_delay = float(
            dify.get("upload_delay_seconds", upload.get("upload_delay_seconds", 1.0))
        )
        self.max_retries = int(
            dify.get("upload_retry_attempts", upload.get("upload_retry_attempts", 5))
        )

        # extensions 从 config.yaml upload.extensions 统一读取
        ext_list = upload.get("extensions")
        upload_all = bool(upload.get("upload_all_extensions", False))
        if ext_list:
            self.extensions = {
                (e if str(e).startswith(".") else f".{e}").lower()
                for e in ext_list
            }
        elif upload_all:
            self.extensions = set()
        else:
            self.extensions, _ = parse_upload_extensions(raw)

        skip = upload.get("skip_dirs")
        self.skip_dirs = set(skip) if skip else set(SKIP_DIR_NAMES)

        folder_raw = os.environ.get("DIFY_UPLOAD_FOLDER")
        if folder_raw:
            p = Path(str(folder_raw).strip())
            if not p.is_absolute():
                p = (config_path.parent / p).resolve()
            else:
                p = p.resolve()
            self.folder = p
        else:
            self.folder = get_workspace_dir(raw, config_path)

    def validate(self, folder_override: Path | None = None) -> Path:
        missing = []
        if not self.api_key:
            missing.append("dify.api_key / DIFY_API_KEY")
        if not self.dataset_id:
            missing.append("dify.dataset_id / DIFY_DATASET_ID")
        root = folder_override or self.folder
        if root is None:
            missing.append("paths.workspace / DIFY_UPLOAD_FOLDER / 命令行目录参数")
        if missing:
            print(
                f"错误: 缺少必填配置 ({', '.join(missing)})\n"
                f"请编辑: {self.config_path}",
                file=sys.stderr,
            )
            sys.exit(1)

        assert root is not None
        if not root.is_dir():
            print(f"错误: 目录不存在: {root}", file=sys.stderr)
            sys.exit(1)
        return root

    @property
    def upload_url(self) -> str:
        return (
            f"{self.base_url}/v1/datasets/{self.dataset_id}"
            "/document/create-by-file"
        )


def load_config(config_path: Path | None = None) -> UploadConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    raw = load_yaml_config(path.resolve())
    cfg = UploadConfig(raw, path.resolve())
    cfg.validate()
    return cfg


def iter_files(root: Path, extensions: set[str], skip_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in skip_dirs and not d.startswith(".")
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if extensions and p.suffix.lower() not in extensions:
                continue
            files.append(p)
    return sorted(files)


def _encode_multipart(
    fields: list[tuple[str, str, str | None]],
    files: list[tuple[str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----difyUpload{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value, content_type in fields:
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n'.encode())
        if content_type:
            lines.append(f"Content-Type: {content_type}\r\n".encode())
        lines.append(b"\r\n")
        lines.append(value.encode("utf-8"))
        lines.append(b"\r\n")

    for name, filename, content in files:
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        lines.append(b"Content-Type: application/octet-stream\r\n\r\n")
        lines.append(content)
        lines.append(b"\r\n")

    lines.append(f"--{boundary}--\r\n".encode())
    return b"".join(lines), boundary


def upload_file(
    cfg: UploadConfig,
    file_path: Path,
    doc_name: str | None = None,
) -> dict:
    payload = dict(cfg.process_data)
    if doc_name:
        payload["name"] = doc_name

    data_json = json.dumps(payload, ensure_ascii=False)
    file_bytes = file_path.read_bytes()

    body, boundary = _encode_multipart(
        fields=[("data", data_json, "text/plain")],
        files=[("file", file_path.name, file_bytes)],
    )

    req = Request(
        cfg.upload_url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    try:
        with urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        hint = ""
        if e.code == 400:
            ext = file_path.suffix.lower()
            if ext and cfg.extensions and ext not in cfg.extensions:
                hint = (
                    f" (Dify 不支持 {ext}，配置允许: "
                    f"{', '.join(sorted(cfg.extensions))})"
                )
            elif not detail.strip() or '"message":""' in detail:
                hint = (
                    " (常见原因: 文件类型不支持或 process_rule 参数无效)"
                )
        raise RuntimeError(f"HTTP {e.code}: {detail[:800]}{hint}") from e


def upload_with_retry(
    cfg: UploadConfig,
    file_path: Path,
    doc_name: str | None,
) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            return upload_file(cfg, file_path, doc_name)
        except (RuntimeError, URLError, TimeoutError) as e:
            last_err = e
            msg = str(e)
            retryable = any(f"HTTP {code}" in msg for code in RETRY_STATUS)
            if not retryable or attempt == cfg.max_retries:
                raise
            wait = min(2**attempt, 60)
            print(f"  重试 {attempt}/{cfg.max_retries} ({wait}s): {e}")
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def run_folder_upload(
    config_path: Path | None = None,
    folder: Path | None = None,
    *,
    cfg: UploadConfig | None = None,
    dry_run: bool = False,
    respect_enabled: bool = True,
) -> int:
    """批量上传文件夹到 Dify（供 scheduler 或单次运行调用）。"""
    path = (config_path or DEFAULT_CONFIG_PATH).resolve()
    if cfg is None:
        raw = load_yaml_config(path)
        if respect_enabled and (raw.get("folder_upload") or {}).get("enabled") is False:
            print("folder_upload 已禁用，跳过")
            return 0
        cfg = UploadConfig(raw, path)

    root = cfg.validate(folder.resolve() if folder else None)

    files = iter_files(root, cfg.extensions, cfg.skip_dirs)
    if not files:
        print("未找到可上传文件。")
        return 0

    print(f"配置: {cfg.config_path}")
    print(f"目录: {root}")
    print(f"目标: {cfg.upload_url}")
    if cfg.extensions:
        print(f"扩展名过滤: {', '.join(sorted(cfg.extensions))}")
    else:
        print("扩展名过滤: 无（上传全部，易遇 400）")
    print(f"共 {len(files)} 个文件\n")

    if dry_run:
        for p in files:
            print(p)
        return 0

    ok, fail = 0, 0
    for i, file_path in enumerate(files, 1):
        rel = file_path.relative_to(root)
        doc_name = str(rel)
        print(f"[{i}/{len(files)}] {rel} ... ", end="", flush=True)
        try:
            result = upload_with_retry(cfg, file_path, doc_name)
            doc = result.get("document") or result
            doc_id = doc.get("id", "?")
            print(f"OK (id={doc_id})")
            ok += 1
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1
        if cfg.upload_delay > 0 and i < len(files):
            time.sleep(cfg.upload_delay)

    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="批量上传文件夹到 Dify 知识库")
    parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=None,
        help="要上传的根目录（可省略，使用 YAML 中 paths.workspace）",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"YAML 配置文件 (默认: {DEFAULT_CONFIG_PATH.name})",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="覆盖 YAML/环境变量中的 Dify API 地址",
    )
    parser.add_argument(
        "--dataset-id",
        default=None,
        help="覆盖 YAML/环境变量中的 dataset ID",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="覆盖 YAML/环境变量中的 API Key",
    )
    parser.add_argument(
        "--ext",
        nargs="*",
        default=None,
        help="覆盖 YAML，只上传指定扩展名，如: --ext .txt .md",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="覆盖 YAML 中的上传间隔秒数",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出文件，不上传",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.base_url:
        cfg.base_url = args.base_url.rstrip("/")
    if args.dataset_id:
        cfg.dataset_id = args.dataset_id
    if args.api_key:
        cfg.api_key = args.api_key
    if args.ext is not None:
        cfg.extensions = {
            (e if e.startswith(".") else f".{e}").lower() for e in args.ext
        }
    if args.delay is not None:
        cfg.upload_delay = args.delay

    folder_override = args.folder.resolve() if args.folder else None
    return run_folder_upload(
        args.config,
        folder_override,
        cfg=cfg,
        dry_run=args.dry_run,
        respect_enabled=False,
    )


if __name__ == "__main__":
    sys.exit(main())
