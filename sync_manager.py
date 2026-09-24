import tempfile
import os
from datetime import datetime, timedelta
from confluence_client import ConfluenceClient
from content_extractor import ContentExtractor
from format_converter import FormatConverter
from dify_client import DifyClient
from state_db import SyncStateDB

class SyncManager:
    def __init__(self, config):
        self.confluence = ConfluenceClient(
            config["confluence"]["base_url"],
            config["confluence"]["email"],
            config["confluence"]["api_token"],
            config["sync"]["max_retries"],
            config["sync"]["retry_delay"]
        )
        self.dify = DifyClient(
            config["dify"]["base_url"],
            config["dify"]["dataset_id"],
            config["dify"]["api_key"]
        )
        self.state_db = SyncStateDB(config["state_db"])
        self.config = config
        self.extractor = ContentExtractor()
        self.last_sync_time = datetime.utcnow() - timedelta(days=7)  # 初始

    def run(self):
        """执行一次同步"""
        if self.config["sync"]["full_sync"]:
            pages = self._get_all_pages()
        else:
            pages = self._get_changed_pages_since(self.last_sync_time)
        
        for page in pages:
            try:
                self._sync_page(page)
            except Exception as e:
                print(f"Error syncing page {page['id']}: {e}")
        self.last_sync_time = datetime.utcnow()

    def _get_all_pages(self):
        spaces = self.config["confluence"]["space_keys"]
        if spaces:
            pages = []
            for sk in spaces:
                pages.extend(list(self.confluence.get_all_pages(space_key=sk)))
            return pages
        else:
            return list(self.confluence.get_all_pages())

    def _get_changed_pages_since(self, since_dt):
        since_str = since_dt.strftime("%Y-%m-%d %H:%M")
        cql = f"type=page AND lastModified >= '{since_str}'"
        return list(self.confluence.get_all_pages(cql=cql))

    def _sync_page(self, page_summary):
        """同步单个页面，模块化解耦调用"""
        page_id = page_summary["id"]
        full_page = self.confluence.get_page_by_id(page_id)
        meta = self.extractor.extract_page_meta(full_page)
        version = meta["version"]
        state = self.state_db.get_state(page_id)

        if state and state["version"] >= version:
            return  # 无更新

        # 1. 上传页面正文（含内嵌图片、附件占位符）
        self._upload_page_body(full_page, meta, state)

        # 2. 独立上传附件文件（Dify 支持的格式）
        if self.config["confluence"]["include_attachments"]:
            self._upload_attachments(full_page, page_id)

        # 3. 独立上传图片文件（可选，保留多模态检索）
        if self.config["confluence"]["include_images"]:
            self._upload_images_as_documents(full_page, page_id)

        # 4. 同步评论（嵌入文档末尾）
        if self.config["confluence"]["include_comments"]:
            self._upload_comments_inline(full_page, page_id, meta, state)

        # 5. 同步标签等元数据
        if self.config["confluence"]["include_labels"]:
            self._update_metadata(page_id, state)

        # 更新状态
        self.state_db.upsert_state(page_id, state["dify_doc_id"] if state else None, version)

    def _upload_page_body(self, full_page, meta, state):
        """处理并上传页面正文，含图片/附件占位符"""
        storage = self.extractor.extract_body_storage(full_page)
        # 构建附件映射表
        att_map = {}
        for att in self.confluence.get_attachments(meta["page_id"]):
            att_map[att["title"]] = (att["id"], att["mediaType"], att["title"])
        converter = FormatConverter(
            download_func=lambda aid: self.confluence.download_attachment(meta["page_id"], aid),
            attachment_map=att_map
        )
        md_content = converter.storage_to_markdown(storage, meta["page_id"])
        doc_name = f"{meta['title']} (PageID:{meta['page_id']})"
        if state and state["dify_doc_id"]:
            self.dify.update_document_by_text(state["dify_doc_id"], doc_name, md_content)
        else:
            new_id = self.dify.create_document_by_text(doc_name, md_content)
            self.state_db.upsert_state(meta["page_id"], new_id, meta["version"])

    def _upload_attachments(self, full_page, page_id):
        """上传附件到 Dify（独立文档），并在主文档中保留关系（已在正文占位）"""
        for att in self.confluence.get_attachments(page_id):
            filename = att["title"]
            ext = filename.split(".")[-1].lower()
            if ext not in FormatConverter.SUPPORTED_ATTACHMENT_FORMATS:
                continue  # 跳过不支持格式
            content, mime = self.confluence.download_attachment(page_id, att["id"])
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                att_id = self.dify.upload_file(tmp_path, filename, mime)
                # 可选：将附件 ID 记录到状态或元数据
            finally:
                os.unlink(tmp_path)

    def _upload_images_as_documents(self, full_page, page_id):
        """将图片独立上传为文档（支持多模态向量化）"""
        for att in self.confluence.get_attachments(page_id):
            mime = att["mediaType"]
            if mime.startswith("image/"):
                content, _ = self.confluence.download_attachment(page_id, att["id"])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                try:
                    self.dify.upload_file(tmp_path, att["title"], mime)
                finally:
                    os.unlink(tmp_path)

    def _upload_comments_inline(self, full_page, page_id, meta, state):
        """将评论内容追加到主文档末尾，保留位置关联"""
        comments = list(self.confluence.get_comments(page_id))
        if not comments:
            return
        comment_text = "\n\n## Comments\n"
        for c in comments:
            author = c.get("history", {}).get("createdBy", {}).get("displayName", "Unknown")
            body = self.extractor.extract_body_storage(c)
            # 简单清理 storage 标签
            soup = BeautifulSoup(body, "lxml-xml")
            clean_text = soup.get_text(separator=" ")
            comment_text += f"\n> **{author}**: {clean_text}\n"
        if state and state["dify_doc_id"]:
            # 获取当前文档内容，追加评论后更新
            # 简化：重新构建整个文档（包含正文+评论），较复杂
            # 这里只演示思路，实际可以单独更新文本段
            pass