import os
import json
import requests
import yaml
from pathlib import Path
import logging
from typing import Optional, Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 支持的图片扩展名
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}

def load_config(config_path: str = "config_image.yaml") -> dict:
    """加载 YAML 配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_state(state_file: str) -> dict:
    """加载已上传状态（文件名 -> doc_id 映射）"""
    if not os.path.exists(state_file):
        return {}
    with open(state_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_state(state: dict, state_file: str):
    """保存上传状态"""
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_mime_type(file_path: str) -> str:
    """根据扩展名获取 MIME 类型"""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml'
    }
    return mime_map.get(ext, 'application/octet-stream')

def upload_image(file_path: str, config: dict, state: Optional[dict] = None) -> Optional[str]:
    """
    上传单个图片到 Dify 知识库。
    :param file_path: 本地图片路径
    :param config: 完整配置字典
    :param state: 状态字典（用于去重），如果提供则按文件名去重
    :return: 文档ID，失败返回 None
    """
    dify_cfg = config['dify']
    api_url = f"{dify_cfg['api_base_url'].rstrip('/')}/v1/datasets/{dify_cfg['dataset_id']}/document/create-by-file"
    api_key = dify_cfg['api_key']
    headers = {"Authorization": f"Bearer {api_key}"}

    # 构建 process_rule
    process_rule = config.get('process_rule', {
        "indexing_technique": "high_quality",
        "mode": "automatic"
    })
    data_payload = {
        "indexing_technique": process_rule.get("indexing_technique", "high_quality"),
        "process_rule": process_rule.get("process_rule", {"mode": "automatic"})
    }

    filename = os.path.basename(file_path)
    mime_type = get_mime_type(file_path)

    # 去重检查
    if state is not None:
        if filename in state:
            logger.info(f"⏩ 文件已上传过，跳过: {filename} (doc_id={state[filename]})")
            return state[filename]

    try:
        with open(file_path, 'rb') as f:
            files = {"file": (filename, f, mime_type)}
            data = {"data": (None, json.dumps(data_payload), "text/plain")}
            resp = requests.post(api_url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            doc_id = resp.json()['document']['id']
            logger.info(f"✅ 上传成功: {filename} (doc_id={doc_id})")
            if state is not None:
                state[filename] = doc_id
            return doc_id
    except Exception as e:
        logger.error(f"❌ 上传失败 {filename}: {e}")
        return None

def collect_images(image_path: str, recursive: bool = True) -> List[str]:
    """
    收集图片文件列表。
    :param image_path: 文件或文件夹路径
    :param recursive: 是否递归子文件夹（仅对文件夹有效）
    :return: 绝对路径列表
    """
    path = Path(image_path)
    if path.is_file():
        # 单个文件
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            return [str(path.resolve())]
        else:
            logger.warning(f"不支持的文件类型: {path.name}")
            return []
    elif path.is_dir():
        # 文件夹
        pattern = "**/*" if recursive else "*"
        files = []
        for f in path.glob(pattern):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                files.append(str(f.resolve()))
        return files
    else:
        logger.error(f"路径不存在: {image_path}")
        return []

def main():
    config = load_config()
    upload_cfg = config.get('upload', {})
    image_path = upload_cfg.get('image_path')
    if not image_path:
        logger.error("请在 config.yaml 中指定 upload.image_path")
        return

    recursive = upload_cfg.get('recursive', True)
    keep_state = upload_cfg.get('keep_state', False)
    state_file = upload_cfg.get('state_file', 'uploaded_images.json')

    # 收集图片列表
    images = collect_images(image_path, recursive)
    if not images:
        logger.info("没有找到可上传的图片。")
        return

    logger.info(f"共找到 {len(images)} 张图片，开始上传...")

    # 加载状态（去重用）
    state = None
    if keep_state:
        state = load_state(state_file)

    success_count = 0
    for img in images:
        doc_id = upload_image(img, config, state)
        if doc_id:
            success_count += 1

    # 保存状态
    if keep_state and state is not None:
        save_state(state, state_file)

    logger.info(f"上传完成: 成功 {success_count}/{len(images)} 张")

if __name__ == "__main__":
    main()