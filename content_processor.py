import json
import logging
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Dify ETL 支持的文件格式（用户指定保留原格式的）
PRESERVE_FORMATS = {
    "csv", "html", "xlsx", "properties", "vtt", "txt",
    "markdown", "pdf", "xls", "docx", "md", "mdx", "htm",
}

# MIME 类型映射
MIME_TO_EXT = {
    "text/csv": ".csv",
    "text/html": ".html",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/vtt": ".vtt",
    "application/octet-stream": "",
}


def process_html_view(html_view, page_title, metadata=None):
    """
    处理 Confluence HTML 视图内容
    移除无关标签（script, style），保留正文结构
    返回格式化的文本内容（保留原格式标记）
    """
    soup = BeautifulSoup(html_view, "html.parser")
    # 移除无关标签
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # 构建带元数据的内容
    header = f"# {page_title}\n\n"
    if metadata:
        header += f"> 空间: {metadata.get('space_key', '')}\n"
        header += f"> 版本: {metadata.get('version', '')}\n"
        header += f"> 作者: {metadata.get('author', '')}\n"
        header += f"> 标签: {', '.join(metadata.get('labels', []))}\n\n"
    header += "---\n\n"

    body = soup.get_text(separator="\n", strip=True)
    return header + body


def process_storage_format(storage_xml, page_title, metadata=None):
    """
    处理 Confluence Storage Format（XML）
    处理宏（Macros）：提取代码块、表格等实际内容，跳过纯导航宏
    """
    soup = BeautifulSoup(storage_xml, "xml")

    # 处理代码块宏
    for macro in soup.find_all("ac:structured-macro"):
        macro_name = macro.get("ac:name", "")

        if macro_name == "code":
            # 代码块：提取代码内容
            body = macro.find("ac:plain-text-body")
            lang = macro.find("ac:parameter", {"ac:name": "language"})
            lang_text = lang.text if lang else ""
            if body:
                new_tag = soup.new_tag("pre")
                code_tag = soup.new_tag("code")
                code_tag.string = body.text
                new_tag.append(code_tag)
                macro.replace_with(new_tag)

        elif macro_name in ("toc", "children", "pagetree", "include"):
            # 目录/导航类宏：仅保留占位说明
            placeholder = soup.new_tag("p")
            placeholder.string = f"[Confluence Macro: {macro_name}]"
            macro.replace_with(placeholder)

        elif macro_name in ("jira", "jiraissues"):
            # Jira 宏：保留配置信息作为结构化备注
            config_params = {}
            for param in macro.find_all("ac:parameter"):
                config_params[param.get("ac:name", "")] = param.text if param.text else ""
            placeholder = soup.new_tag("p")
            placeholder.string = f"[Embedded Jira Issues - Config: {json.dumps(config_params)}]"
            macro.replace_with(placeholder)

    # 处理图片标签
    for img in soup.find_all("ac:image"):
        ri = img.find("ri:attachment")
        if ri:
            filename = ri.get("ri:filename", "image")
            new_img = soup.new_tag("img", src=f"[ATTACHMENT:{filename}]")
            img.replace_with(new_img)

    text = soup.get_text(separator="\n", strip=True)
    header = f"# {page_title}\n\n"
    if metadata:
        header += f"> 作者: {metadata.get('author', '')} | 标签: {', '.join(metadata.get('labels', []))}\n\n"
    return header + text


def classify_and_handle_attachment(file_name, mime_type, content_bytes, page_title):
    """
    分类处理附件：根据扩展名和 MIME 类型判断是否为保留原格式的文件。
    - 如果附件是图片，标记需要向量化
    - 如果附件是 CSV/XLSX/DOCX/PDF 等保留原格式的文件，标记并准备上传
    - 其他类型按文本处理
    返回: dict {type, file_name, content, mime_type, need_vectorize, title}
    """
    import os
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")

    # 图片处理：PNG、JPEG、GIF、SVG、WebP、BMP
    IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp"}
    if ext in IMAGE_EXTS or (mime_type and mime_type.startswith("image/")):
        return {
            "type": "image",
            "file_name": file_name,
            "content": content_bytes,
            "mime_type": mime_type,
            "need_vectorize": True,
            "title": f"{page_title} - {file_name}",
        }

    # 保留原格式的文件
    if ext in PRESERVE_FORMATS:
        return {
            "type": "preserve_format",
            "file_name": file_name,
            "content": content_bytes,
            "mime_type": mime_type,
            "need_vectorize": ext in ("pdf",),  # PDF 也需要向量化
            "title": f"{page_title} - {file_name}",
            "ext": ext,
        }

    # 默认按文本处理
    return {
        "type": "text",
        "file_name": file_name,
        "content": content_bytes,
        "mime_type": mime_type,
        "need_vectorize": False,
        "title": f"{page_title} - {file_name}",
    }


def build_page_metadata(page_data, labels, users):
    """组装页面元数据"""
    return {
        "space_key": page_data.get("space_key", ""),
        "version": page_data.get("version", 1),
        "author": users[0]["display_name"] if users else "unknown",
        "labels": [lbl["name"] for lbl in labels],
        "contributors": [u["display_name"] for u in users],
    }