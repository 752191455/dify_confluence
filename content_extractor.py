from bs4 import BeautifulSoup  # 解析 storage 格式的 XHTML

class ContentExtractor:
    @staticmethod
    def extract_body_storage(page_data):
        """返回 storage 格式的 XHTML 字符串"""
        return page_data.get("body", {}).get("storage", {}).get("value", "")

    @staticmethod
    def extract_page_meta(page_data):
        """提取标题、空间、版本等"""
        return {
            "title": page_data.get("title"),
            "page_id": page_data.get("id"),
            "version": page_data.get("version", {}).get("number"),
            "space_key": page_data.get("space", {}).get("key"),
            "url": page_data.get("_links", {}).get("webui", ""),
        }

    @staticmethod
    def extract_images_from_storage(storage_html):
        """从 storage 格式中提取所有 <ac:image> 的附件引用"""
        soup = BeautifulSoup(storage_html, "lxml-xml")
        images = []
        for img in soup.find_all("ac:image"):
            ri = img.find("ri:attachment")
            if ri:
                images.append({
                    "attachment_id": ri.get("ri:filename"),  # 实际是文件名
                    "alt": img.find("ac:alt") or "",
                })
        return images

    @staticmethod
    def extract_attachment_links(storage_html):
        """提取 <ri:attachment> 链接"""
        soup = BeautifulSoup(storage_html, "lxml-xml")
        links = []
        for link in soup.find_all("ri:attachment"):
            links.append(link.get("ri:filename"))
        return links