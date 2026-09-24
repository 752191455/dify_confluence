import requests
import json
import os
import logging

logger = logging.getLogger(__name__)

class DifyUploader:
    def __init__(self, api_base_url, api_key, dataset_id):
        self.api_base = api_base_url.rstrip('/')
        self.api_key = api_key
        self.dataset_id = dataset_id
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def upload_file(self, file_path, filename=None, mime_type="application/octet-stream"):
        """上传文件到 Dify 知识库，返回文档 ID"""
        if not filename:
            filename = os.path.basename(file_path)

        url = f"{self.api_base}/v1/datasets/{self.dataset_id}/document/create-by-file"
        data_payload = {
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"}
        }

        with open(file_path, 'rb') as f:
            files = {"file": (filename, f, mime_type)}
            data = {"data": (None, json.dumps(data_payload), "text/plain")}
            resp = requests.post(url, headers=self.headers, files=files, data=data)
        resp.raise_for_status()
        doc_id = resp.json()['document']['id']
        logger.info(f"✓ 上传成功: {filename} (doc_id={doc_id})")
        return doc_id

    def get_file_preview_url(self, doc_id):
        """
        获取文件的可预览 URL。
        优先尝试 API 返回字段，否则拼接标准预览地址。
        """
        url = f"{self.api_base}/v1/datasets/{self.dataset_id}/documents/{doc_id}"
        try:
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200:
                data = resp.json()
                for key in ['doc_url', 'url', 'download_url']:
                    if data.get(key):
                        return data[key]
        except Exception as e:
            logger.warning(f"获取文档详情失败: {e}")

        # 降级：Dify 标准文件预览路径
        return f"{self.api_base}/files/{doc_id}/file-preview"