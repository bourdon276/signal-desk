"""Bounded metadata reader for approved Eastmoney article URLs."""

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from information_agent.article_reader import SELECTORS, article_excerpt, extract_html
from information_agent.ingest_common import download, safe_link


def article_url(url: str) -> str:
    approved = safe_link(url, {"finance.eastmoney.com", "stock.eastmoney.com", "caifuhao.eastmoney.com"})
    if not approved or not re.fullmatch(r"/(?:a/\d{8}\d+\.html|news/\d{14,30})", urlsplit(approved).path):
        raise ValueError("article_url")
    return approved


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = []
        self.document_title = []
        self.in_document_title = False
        self.paragraphs = []
        self.in_title = False
        self.body_depth = 0
        self.in_paragraph = False
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h1":
            self.in_title = True
        if tag == "title":
            self.in_document_title = True
        if tag in {"script", "style"}:
            self.ignore += 1
        if tag == "div":
            if self.body_depth:
                self.body_depth += 1
            elif attrs.get("id") in {"ContentBody", "contentBody"}:
                self.body_depth = 1
        if tag == "p" and self.body_depth:
            self.in_paragraph = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_title = False
        if tag == "title":
            self.in_document_title = False
        if tag == "div" and self.body_depth:
            self.body_depth -= 1
        if tag == "p":
            self.in_paragraph = False
        if tag in {"script", "style"}:
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, text):
        if self.ignore:
            return
        if self.in_title:
            self.title.append(text)
        if self.in_document_title:
            self.document_title.append(text)
        if self.in_paragraph:
            self.paragraphs.append(text)


def read_article(client, url: str) -> dict:
    url = article_url(url)
    parser = ArticleParser()
    html = download(client, url).decode("utf-8")
    parser.feed(html)
    title = " ".join("".join(parser.title or parser.document_title).split())
    title = re.sub(r"\s*[_-]\s*东方财富网$", "", title)[:500]
    _, blocks = extract_html(html, SELECTORS[urlsplit(url).hostname], url)
    excerpt = article_excerpt(blocks)
    if not title or not excerpt:
        raise ValueError("article_metadata")
    date = re.search(r"/(?:a|news)/(\d{8})", urlsplit(url).path)[1]
    return {"title": title, "url": url, "content": excerpt,
            "published_date": datetime.strptime(date, "%Y%m%d").replace(
                tzinfo=ZoneInfo("Asia/Shanghai")
            ).isoformat()}
