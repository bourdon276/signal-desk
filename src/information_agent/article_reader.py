"""Public article text extraction: fixed hosts, bounded downloads, no arbitrary redirects."""
import json
import re
from io import BytesIO
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from pypdf import PdfReader

from information_agent.ingest_common import download, safe_link
from information_agent.ingest_perfect_news import DETAIL_URL, share_news_id

SELECTORS = {
    "finance.eastmoney.com": "#ContentBody, #contentBody",
    "stock.eastmoney.com": "#ContentBody, #contentBody",
    "caifuhao.eastmoney.com": ".article-body .xeditor_content, .article-body",
    "www.stcn.com": ".detail-content-editor, .detail-content, .article-content, .content-detail",
    "stcn.com": ".detail-content-editor, .detail-content, .article-content, .content-detail",
    "www.dust2.com.br": ".news-item-content-container, .news-content, .article-content",
    "www.hltv.org": ".news-content",
    "hltv.org": ".news-content",
    "www.federalreserve.gov": "#article",
    "news.wmpvp.com": "article",
    "static.cninfo.com.cn": "pdf",
}


def clean_excerpt(text: str, title: str = "", watch_id: str = "") -> str:
    text = re.sub(r"^搜索摘录[（(][^）)]*[）)]\s*[：:]?\s*", "", text or "")
    text = re.sub(r"\$([^$]{1,80})\$", r"\1", text)
    # Discard site navigation instead of displaying it as an article summary.
    if "财经 焦点 股票" in text or "指数期指期权个股板块排行" in text:
        return ""  # The reader will extract the actual article, not this navigation fragment.
    if text.count("|") >= 4:
        return ""  # An incomplete table fragment is not a readable summary.
    return " ".join(text.split())[:500]


def extract_html(html: str, selector: str, source_url: str = "") -> tuple[str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(selector)
    if root is None:
        raise ValueError("article_body_missing")
    for node in root.select("script, style, nav, iframe, form, button, .advertisement, .ad, .share, .article-footer"):
        node.decompose()
    for image in root.find_all("img"):
        raw_url = image.get("data-src") or image.get("src") or ""
        image_url = urljoin(source_url, raw_url)
        parts = urlsplit(image_url)
        host = parts.hostname or ""
        approved_image = parts.scheme == "https" and not parts.username and not parts.password and any(
            host == domain or host.endswith("." + domain) for domain in (
                "dfcfw.com", "eastmoney.com", "wmpvp.com", "hltv.org", "dust2.com.br", "stcn.com",
                "federalreserve.gov", "wanmei.com", "pwesports.cn", "alicdn.com",
            )
        )
        marker = "\n\n[[阅讯图片|" + image_url + "]]\n\n" if approved_image else "【图片请在来源查看】"
        if image.find_parent(["p", "li"]):
            image.replace_with(marker)
        else:
            block = soup.new_tag("p")
            block.string = marker
            image.replace_with(block)
    for table in root.find_all("table"):
        rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False)]
                for row in table.find_all("tr")]
        rows = [row for row in rows if row]
        if not rows:
            table.decompose()
            continue
        header = rows[0]
        lines = [" / ".join(header)]
        lines.extend("；".join(f"{header[i] if i < len(header) else '数据'}：{value}"
                              for i, value in enumerate(row)) for row in rows[1:])
        block = soup.new_tag("p")
        block.string = "\n".join(lines)
        table.replace_with(block)
    blocks = []
    for node in root.find_all(["p", "h2", "h3", "li"]):
        if node.find_parent(["p", "li"]):
            continue
        text = node.get_text(" ", strip=True)
        footer = r"^(责任编辑[：:]|文章来源[：:]|郑重声明[：:]|举报|分享至|微信扫一扫|本文作者可以追加内容)"
        if text and not re.match(footer, text):
            blocks.append(text)
    if not blocks:
        blocks = [root.get_text("\n", strip=True)]
    body = "\n\n".join(blocks)
    if len(body) < 60 or len(body) > 200_000 or "财经 焦点 股票 新股" in body:
        raise ValueError("article_body_quality")
    return body, blocks


def read_full_article(client, url: str) -> dict:
    approved = safe_link(url, set(SELECTORS))
    if approved is None:
        raise ValueError("unsupported_source")
    host = urlsplit(approved).hostname
    if host == "news.wmpvp.com":
        news_id = share_news_id(approved)
        payload = json.loads(download(client, DETAIL_URL, params={"gameType": 2, "newsId": news_id}))
        news = payload.get("result", {}).get("news", {})
        if news.get("newsId") != news_id or news.get("gameType") != 2:
            raise ValueError("article_identity")
        html = news.get("content")
        if not isinstance(html, str):
            raise ValueError("article_body_missing")
        body, blocks = extract_html(f'<article>{html}</article>', "article", approved)
    elif host == "static.cninfo.com.cn":
        if not urlsplit(approved).path.lower().endswith(".pdf"):
            raise ValueError("unsupported_source")
        pdf = PdfReader(BytesIO(download(client, approved)))
        if len(pdf.pages) > 150:
            raise ValueError("article_too_large")
        blocks = [page.extract_text() or "" for page in pdf.pages]
        body = "\n\n".join(blocks)
        if len(body) < 60 or len(body) > 200_000:
            raise ValueError("article_body_quality")
    else:
        raw = download(client, approved)
        # Eastmoney currently serves UTF-8; explicit legacy encoding only when declared.
        encoding = "gb18030" if re.search(br'charset\s*=\s*["\']?gb(?:2312|k)', raw[:8000], re.I) else "utf-8"
        body, blocks = extract_html(raw.decode(encoding), SELECTORS[host], approved)
    return {"body": body, "blocks": blocks}


def article_excerpt(blocks: list[str], watch_id: str = "") -> str:
    blocks = [re.sub(r"\[\[阅讯图片\|[^\]]+\]\]", "", block).strip() for block in blocks]
    paragraphs = [block for block in blocks if len(block) > 25]
    intro = paragraphs[0] if paragraphs else ""
    marker = watch_id.rsplit(":", 1)[-1]
    relevant = next((block for block in paragraphs[1:] if marker.isdigit() and marker in block), "")
    if relevant:
        relevant = next((line for line in relevant.splitlines() if marker in line), relevant)
    return (intro[:300] + ("\n" + relevant[:180] if relevant else ""))[:500]
