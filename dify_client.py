import requests
from urllib.parse import urljoin

class DifyClient:
    def __init__(self, base_url, dataset_id, api_key):
        self.base_url = base_url.rstrip('/')
        self.dataset_id = dataset_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def _request(self, method, path, **kwargs):
        url = urljoin(self.base_url, path)
        if "json" in kwargs:
            kwargs["headers"] = {**self.headers, "Content-Type": "application/json"}
        resp = requests.request(method, url, headers=self.headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def create_document_by_text(self, name, text, metadata=None):
        """上传文本创建文档，返回 document_id"""
        data = {
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"}
        }
        if metadata:
            data["metadata"] = metadata
        result = self._request("POST", f"datasets/{self.dataset_id}/documents", json=data)
        return result["document"]["id"]

    def update_document_by_text(self, document_id, name, text, metadata=None):
        """更新已有文档"""
        data = {"name": name, "text": text}
        if metadata:
            data["metadata"] = metadata
        self._request("PATCH", f"datasets/{self.dataset_id}/documents/{document_id}", json=data)

    def upload_file(self, file_path, file_name, mime_type):
        """上传文件（如图片、附件）作为独立文档"""
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, mime_type)}
            data = {"indexing_technique": "high_quality", "process_rule": {"mode": "automatic"}}
            # Dify 上传文件端点需使用 multipart
            resp = requests.post(
                f"{self.base_url}/datasets/{self.dataset_id}/document/create-by-file",
                headers={"Authorization": self.headers["Authorization"]},
                files=files,
                data={"data": json.dumps(data)}
            )
            resp.raise_for_status()
            return resp.json()["document"]["id"]

    def delete_document(self, document_id):
        self._request("DELETE", f"datasets/{self.dataset_id}/documents/{document_id}")