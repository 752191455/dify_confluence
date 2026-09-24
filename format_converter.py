import re
import base64
from bs4 import BeautifulSoup

class FormatConverter:
    SUPPORTED_ATTACHMENT_FORMATS = [
        "csv", "html", "xlsx", "properties", "vtt", "txt", "markdown",
        "pdf", "xls", "docx", "md", "mdx", "htm"
    ]

    def __init__(self, download_func, attachment_map):
        """
        download_func: 函数 (attachment_id) -> (bytes, mime_type)
        attachment_map: dict { filename_in_storage: (attachment_id, mime_type, title) }
        """
        self.download_func = download_func
        self.attachment_map = attachment_map  # 在组装前填充

    def storage_to_markdown(self, storage_html, page_id):
        """将 storage 格式转为 Markdown，嵌入图片和附件占位符"""
        soup = BeautifulSoup(storage_html, "lxml-xml")
        self._process_images(soup, page_id)
        self._process_attachments(soup)
        # 使用简单的 html2text 转换（或自己实现）
        from html2text import html2text
        html_str = str(soup)
        # 注意：某些嵌套可能需要预处理
        md = html2text(html_str, bodywidth=0)
        return md

    def _process_images(self, soup, page_id):
        """将 <ac:image> 替换为 base64 内嵌或占位 Markdown 图片"""
        for img in soup.find_all("ac:image"):
            ri = img.find("ri:attachment")
            if not ri:
                continue
            filename = ri.get("ri:filename")
            if filename in self.attachment_map:
                att_id, mime, title = self.attachment_map[filename]
                # 下载图片并转为 base64 内嵌（确保保留位置）
                try:
                    content, _ = self.download_func(att_id)
                    b64 = base64.b64encode(content).decode()
                    data_uri = f"data:{mime};base64,{b64}"
                    alt = title or filename
                    md_img = f"![{alt}]({data_uri})"
                    # 替换整个 ac:image 标签
                    img.replace_with(soup.new_string(md_img))
                except Exception:
                    img.replace_with(soup.new_string(f"[Image: {filename}]"))

    def _process_attachments(self, soup):
        """将附件链接转换为带文件名的引用"""
        for link in soup.find_all("ri:attachment"):
            filename = link.get("ri:filename")
            if filename in self.attachment_map:
                link.replace_with(soup.new_string(f"[Attachment: {filename}]"))
            else:
                link.replace_with(soup.new_string(f"[Attachment missing: {filename}]"))