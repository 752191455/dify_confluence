import requests
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class ConfluenceClient:
    def __init__(self, base_url, api_token):
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json"
        }

    def _get(self, path, params=None):
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        resp = requests.get(url, headers=self.headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get_raw(self, path, stream=False):
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        resp = requests.get(url, headers=self.headers, stream=stream, allow_redirects=True)
        resp.raise_for_status()
        return resp

    # ── 空间 ──
    def get_all_spaces(self):
        results = []
        start = 0
        while True:
            data = self._get('/rest/api/space', params={'start': start, 'limit': 100})
            results.extend(data['results'])
            if len(data['results']) < 100:
                break
            start += 100
        return results

    def get_space_description(self, space_key):
        data = self._get(f'/rest/api/space/{space_key}')
        desc = data.get('description', {})
        return desc.get('plain', {}).get('value', '') if desc else ''

    # ── 页面（Confluence 8.5+ 端点）──
    def get_pages_in_space(self, space_key):
        pages = []
        start = 0
        while True:
            data = self._get(f'/rest/api/space/{space_key}/content', params={
                'type': 'page',
                'start': start,
                'limit': 100,
                'expand': 'version'
            })
            page_results = data.get('results', [])
            pages.extend(page_results)
            if len(page_results) < 100:
                break
            start += 100
        return pages

    def get_child_pages(self, parent_id):
        results = []
        start = 0
        while True:
            data = self._get(f'/rest/api/content/{parent_id}/child/page',
                             params={'start': start, 'limit': 100, 'expand': 'version'})
            results.extend(data['results'])
            if len(data['results']) < 100:
                break
            start += 100
        return results

    def get_all_pages_recursive(self, space_key):
        all_pages = []
        top_pages = self.get_pages_in_space(space_key)
        def collect(page_list):
            for p in page_list:
                all_pages.append(p)
                children = self.get_child_pages(p['id'])
                if children:
                    collect(children)
        collect(top_pages)
        return all_pages

    # ── 页面内容 ──
    def get_page_view_html(self, page_id):
        data = self._get(f'/rest/api/content/{page_id}', params={
            'expand': 'body.view,version,space,history'
        })
        html = data.get('body', {}).get('view', {}).get('value', '')
        title = data.get('title', '')
        created = data.get('history', {}).get('createdDate', '')
        updated = data.get('version', {}).get('when', '')
        creator = data.get('history', {}).get('createdBy', {}).get('displayName', '')
        return html, title, created, updated, creator

    # ── 附件 ──
    def get_attachments(self, page_id):
        attachments = []
        start = 0
        while True:
            data = self._get(f'/rest/api/content/{page_id}/child/attachment',
                             params={'start': start, 'limit': 100})
            attachments.extend(data['results'])
            if len(data['results']) < 100:
                break
            start += 100
        return attachments

    def download_attachment(self, attachment):
        filename = attachment['title']
        mime = attachment.get('metadata', {}).get('mediaType', 'application/octet-stream')
        download_path = attachment['_links']['download']
        resp = self._get_raw(download_path)
        return filename, mime, resp.content

    # ── 评论 ──
    def get_page_comments(self, page_id):
        comments = []
        start = 0
        while True:
            data = self._get(f'/rest/api/content/{page_id}/child/comment',
                             params={'start': start, 'limit': 100,
                                     'expand': 'body.view,history'})
            for c in data['results']:
                author = c.get('history', {}).get('createdBy', {}).get('displayName', 'unknown')
                created = c.get('history', {}).get('createdDate', '')
                body = c.get('body', {}).get('view', {}).get('value', '')
                comments.append({'author': author, 'created': created, 'body': body})
            if len(data['results']) < 100:
                break
            start += 100
        return comments

    # ── 标签 ──
    def get_page_labels(self, page_id):
        data = self._get(f'/rest/api/content/{page_id}/label')
        return [lbl['name'] for lbl in data.get('results', [])]