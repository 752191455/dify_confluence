import re
import html2text
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

def html_to_markdown(html_content):
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_tables = False
    h.ignore_emphasis = False
    h.mark_code = True
    h.unicode_snob = True
    h.wrap_links = False
    h.skip_internal_links = False
    md = h.handle(html_content)
    md = re.sub(r'\n{3,}', '\n\n', md).strip()
    return md

def replace_attachment_urls(html_content, filename_to_url):
    """
    将 HTML 中的附件引用（图片 src、链接 href）替换为 Dify 的文件预览 URL。
    filename_to_url: {原始文件名: Dify URL}
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    for img in soup.find_all('img'):
        src = img.get('src', '')
        if src:
            # 提取文件名（去除路径参数）
            filename = src.split('/')[-1].split('?')[0]
            if filename in filename_to_url:
                img['src'] = filename_to_url[filename]
                logger.debug(f"替换图片 {filename} -> {filename_to_url[filename]}")

    for a in soup.find_all('a'):
        href = a.get('href', '')
        if href:
            filename = href.split('/')[-1].split('?')[0]
            if filename in filename_to_url:
                a['href'] = filename_to_url[filename]
                logger.debug(f"替换链接 {filename} -> {filename_to_url[filename]}")

    return str(soup)

def build_final_markdown(html_body, title, author, created, updated, labels, comments_md_list):
    body_md = html_to_markdown(html_body)

    header = f'# {title}\n\n'
    if author:
        header += f'> Author: {author}\n'
    if created:
        header += f'> Created: {created}\n'
    if updated:
        header += f'> Updated: {updated}\n'
    if labels:
        header += f'> Labels: {", ".join(labels)}\n'
    header += '\n---\n\n'

    md = header + body_md

    if comments_md_list:
        md += '\n\n## Comments\n\n'
        for c in comments_md_list:
            md += f'> **{c["author"]}** ({c["created"]}):\n> {c["body"]}\n\n'
    return md