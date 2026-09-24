import os
import re
import time
import logging
import argparse
from pathlib import Path

import requests
import yaml

from workspace_paths import get_workspace_dir

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("download_attachments")


def load_config(path=None):
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _confluence_headers(config):
    conf = config.get("confluence") or {}
    api_token = conf.get("api_token", "")
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _download_settings(config, config_path=None):
    dl = config.get("download_attachments") or {}
    sync = config.get("sync") or {}
    base_url = (config.get("confluence") or {}).get("base_url", "").rstrip("/")
    spaces = dl.get("spaces") or sync.get("spaces") or []
    workspace = get_workspace_dir(config, config_path)
    return {
        "base_url": base_url,
        "headers": _confluence_headers(config),
        "download_root": str(workspace),
        "request_delay": float(
            dl.get("request_delay_seconds", sync.get("request_delay_seconds", 0.3))
        ),
        "spaces": spaces,
    }


def fetch_all_spaces(base_url, headers, request_delay):
    spaces = []
    url = f"{base_url}/rest/api/space"
    params = {"limit": 200}
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            logger.error("获取空间列表失败 (HTTP %s)", resp.status_code)
            break
        data = resp.json()
        for result in data.get("results", []):
            spaces.append(result["key"])
        next_link = data.get("_links", {}).get("next")
        if next_link:
            url = base_url + next_link if next_link.startswith("/") else next_link
            params = None
            time.sleep(request_delay)
        else:
            break
    return spaces


def fetch_all_pages(base_url, headers, space_key, request_delay):
    pages = []
    url = f"{base_url}/rest/api/space/{space_key}/content"
    params = {
        "type": "page",
        "limit": 50,
        "start": 0,
    }
    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            logger.error("获取页面列表失败 (HTTP %s)", resp.status_code)
            break
        data = resp.json()
        pages.extend(data.get("results", []))
        next_link = data.get("_links", {}).get("next")
        if next_link:
            url = base_url + next_link if next_link.startswith("/") else next_link
            params = None
            time.sleep(request_delay)
        else:
            break
    return pages


def fetch_attachments(base_url, headers, content_id, request_delay):
    attachments = []
    url = f"{base_url}/rest/api/content/{content_id}/child/attachment"
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            break
        data = resp.json()
        attachments.extend(data.get("results", []))
        next_link = data.get("_links", {}).get("next")
        if not next_link:
            break
        url = base_url + next_link if next_link.startswith("/") else next_link
        time.sleep(request_delay)
    return attachments


def fetch_all_comments(base_url, headers, page_id):
    comments = []
    url = f"{base_url}/rest/api/content/{page_id}/child/comment"
    params = {"expand": "body.storage", "limit": 100, "depth": "all"}
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        comments.extend(resp.json().get("results", []))
    return comments


def download_file(url, save_path, headers):
    try:
        resp = requests.get(
            url, headers=headers, allow_redirects=True, stream=True
        )
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        logger.warning("下载失败 HTTP %s: %s", resp.status_code, save_path)
    except Exception as e:
        logger.error("下载异常 %s: %s", save_path, e)
    return False


def process_page(page, space_key, settings):
    base_url = settings["base_url"]
    headers = settings["headers"]
    request_delay = settings["request_delay"]
    download_root = settings["download_root"]

    page_id = page["id"]
    page_title = page.get("title", "Untitled")
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", page_title)
    page_dir = os.path.join(download_root, space_key, f"{page_id}_{safe_title}")

    logger.info("  页面: %s (ID: %s)", page_title, page_id)

    page_attachments = fetch_attachments(
        base_url, headers, page_id, request_delay
    )
    if page_attachments:
        logger.info("    页面附件: %d 个", len(page_attachments))
        for att in page_attachments:
            fname = att["title"]
            download_url = (
                f"{base_url}/rest/api/content/{page_id}"
                f"/child/attachment/{att['id']}/download"
            )
            save_path = os.path.join(page_dir, "attachments", fname)
            ok = download_file(download_url, save_path, headers)
            logger.info("      %s %s", fname, "OK" if ok else "FAIL")
            time.sleep(request_delay)

    comments = fetch_all_comments(base_url, headers, page_id)
    if comments:
        logger.info("    评论: %d 条", len(comments))
        for comment in comments:
            comment_id = comment["id"]
            comment_attachments = fetch_attachments(
                base_url, headers, comment_id, request_delay
            )
            for att in comment_attachments:
                fname = att["title"]
                download_url = (
                    f"{base_url}/rest/api/content/{comment_id}"
                    f"/child/attachment/{att['id']}/download"
                )
                save_path = os.path.join(
                    page_dir, "comments_attachments", str(comment_id), fname
                )
                ok = download_file(download_url, save_path, headers)
                logger.info(
                    "      评论附件 %s (评论 %s) %s",
                    fname,
                    comment_id,
                    "OK" if ok else "FAIL",
                )
                time.sleep(request_delay)


def run_download_attachments(config, config_path=None):
    """下载 Confluence 空间附件（供 scheduler 或单次运行调用）。"""
    dl_cfg = config.get("download_attachments") or {}
    if dl_cfg.get("enabled") is False:
        logger.info("download_attachments 已禁用，跳过")
        return

    settings = _download_settings(config, config_path)
    if not settings["base_url"]:
        logger.error("confluence.base_url 未配置")
        return

    logger.info("开始下载 Confluence 附件 -> %s", settings["download_root"])

    target_spaces = settings["spaces"]
    if not target_spaces:
        logger.info("未指定空间，获取全部空间...")
        target_spaces = fetch_all_spaces(
            settings["base_url"],
            settings["headers"],
            settings["request_delay"],
        )
        logger.info("找到 %d 个空间", len(target_spaces))

    for space in target_spaces:
        logger.info("处理空间: %s", space)
        pages = fetch_all_pages(
            settings["base_url"],
            settings["headers"],
            space,
            settings["request_delay"],
        )
        logger.info("  找到 %d 个页面", len(pages))
        for page in pages:
            process_page(page, space, settings)

    logger.info("附件下载完成")


def main():
    parser = argparse.ArgumentParser(description="下载 Confluence 空间附件")
    parser.add_argument(
        "-c", "--config", default=str(DEFAULT_CONFIG_PATH), help="配置文件路径"
    )
    parser.add_argument(
        "--once", action="store_true", help="只运行一次（默认由 scheduler 定时调用）"
    )
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    run_download_attachments(config, config_path)


if __name__ == "__main__":
    main()
