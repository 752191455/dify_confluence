import yaml
import schedule
import time
import logging
import re
import os
from confluence_client import ConfluenceClient
from content_handler import replace_attachment_urls, build_final_markdown, html_to_markdown
from dify_uploader import DifyUploader
from state_manager import StateManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('sync')

def load_config(path='config.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def safe_filename(title):
    return re.sub(r'[\\/*?:"<>|]', '_', title)

def download_attachment_to_local(att, download_dir, confluence):
    orig_filename = att['title']
    mime = att.get('metadata', {}).get('mediaType', 'application/octet-stream')
    content = confluence.download_attachment(att)[2]
    safe_name = safe_filename(orig_filename)
    if not safe_name:
        safe_name = f"att_{att['id']}"
    local_path = os.path.join(download_dir, safe_name)
    with open(local_path, 'wb') as f:
        f.write(content)
    return orig_filename, local_path, mime

def sync_space(confluence, dify, space_key, config, state_manager):
    logger.info(f"🚀 开始同步空间: {space_key}")

    base_temp = config['sync'].get('local_temp_dir', './temp_confluence')
    space_temp = os.path.join(base_temp, safe_filename(space_key))
    os.makedirs(space_temp, exist_ok=True)

    # 空间描述
    desc = confluence.get_space_description(space_key)
    if desc:
        desc_path = os.path.join(space_temp, f"{safe_filename(space_key)}_description.md")
        with open(desc_path, 'w', encoding='utf-8') as f:
            f.write(f'# {space_key} Description\n\n{desc}')
        dify.upload_file(desc_path, mime_type='text/markdown')
        logger.info(f"  空间描述已上传")

    pages = confluence.get_all_pages_recursive(space_key)
    logger.info(f"  共 {len(pages)} 个页面")

    for page in pages:
        page_id = page['id']
        html_body, title, created, updated, creator = confluence.get_page_view_html(page_id)
        if not html_body:
            logger.warning(f"  页面 {title} 无内容，跳过")
            continue

        logger.info(f"  📄 处理页面: {title} (id={page_id})")

        page_dir = os.path.join(space_temp, f"{page_id}_{safe_filename(title)}")
        att_dir = os.path.join(page_dir, "attachments")
        os.makedirs(att_dir, exist_ok=True)

        try:
            # 处理附件
            attachments = confluence.get_attachments(page_id)
            filename_to_url = {}

            if attachments:
                logger.info(f"    处理 {len(attachments)} 个附件...")
                for att in attachments:
                    try:
                        orig_name, local_path, mime = download_attachment_to_local(att, att_dir, confluence)
                        # 上传并获取 URL
                        doc_id = dify.upload_file(local_path, filename=orig_name, mime_type=mime)
                        file_url = dify.get_file_preview_url(doc_id)
                        if file_url:
                            filename_to_url[orig_name] = file_url
                            logger.info(f"    附件已上传: {orig_name} -> {file_url}")
                    except Exception as e:
                        logger.error(f"    附件处理失败 {att.get('title', '')}: {e}")

            # 替换正文 HTML 中的附件引用
            if filename_to_url:
                html_body = replace_attachment_urls(html_body, filename_to_url)

            # 处理评论（同样替换附件引用）
            comments_raw = confluence.get_page_comments(page_id)
            comments_md = []
            for c in comments_raw:
                if filename_to_url:
                    c['body'] = replace_attachment_urls(c['body'], filename_to_url)
                comment_md = html_to_markdown(c['body'])
                comments_md.append({
                    'author': c['author'],
                    'created': c['created'],
                    'body': comment_md.strip()
                })

            # 获取标签
            labels = confluence.get_page_labels(page_id)

            # 生成最终 Markdown
            final_md = build_final_markdown(html_body, title, creator, created, updated, labels, comments_md)

            # 保存 Markdown 文件
            md_filename = f"{safe_filename(title)}.md"
            md_path = os.path.join(page_dir, md_filename)
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(final_md)

            # 上传 Markdown 到 Dify
            dify.upload_file(md_path, filename=md_filename, mime_type='text/markdown')
            logger.info(f"    ✅ 页面已同步: {title}")

        except Exception as e:
            logger.error(f"  页面处理失败 {title}: {e}")
            continue

    logger.info(f"✅ 空间 {space_key} 同步完成\n")

def run_sync(config):
    confluence = ConfluenceClient(
        config['confluence']['base_url'],
        config['confluence']['api_token']
    )
    dify = DifyUploader(
        config['dify']['api_base_url'],
        config['dify']['api_key'],
        config['dify']['dataset_id']
    )
    state_manager = StateManager()

    spaces = config['sync'].get('spaces', [])
    if not spaces:
        all_spaces = confluence.get_all_spaces()
        spaces = [s['key'] for s in all_spaces]
        logger.info(f"未指定空间，将同步 {len(spaces)} 个空间")

    for space_key in spaces:
        try:
            sync_space(confluence, dify, space_key, config, state_manager)
        except Exception as e:
            logger.error(f"空间 {space_key} 同步失败: {e}")

def main():
    config = load_config()
    interval = config['sync']['interval_minutes']
    logger.info(f"⏰ 定时同步间隔: {interval} 分钟")
    run_sync(config)
    schedule.every(interval).minutes.do(run_sync, config)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == '__main__':
    main()