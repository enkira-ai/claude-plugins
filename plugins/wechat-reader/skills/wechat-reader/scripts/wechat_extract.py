#!/usr/bin/env python3
"""Extract article content from WeChat (mp.weixin.qq.com) URLs.

Usage:
    python3 wechat_extract.py <url> [--json]

Bypasses WeChat's CAPTCHA by spoofing MicroMessenger User-Agent.
Extracts title, description, author, account name, and full article text.
"""

import sys
import re
import json
import subprocess

WECHAT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.50(0x18003233) NetType/WIFI Language/zh_CN"
)


def fetch_html(url: str) -> str:
    result = subprocess.run(
        ["curl", "-sL", "-A", WECHAT_UA, "--max-time", "15", url],
        capture_output=True, text=True
    )
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(f"curl failed (code {result.returncode}): {result.stderr}")
    return result.stdout


def extract_meta(html: str) -> dict:
    """Extract metadata from WeChat article HTML."""
    meta = {}
    patterns = {
        "title": r'var msg_title = "([^"]*)"',
        "description": r'var msg_desc = "([^"]*)"',
        "author": r'var author = "([^"]*)"',
        "account_name": r'var nickname = "([^"]*)"',
        "publish_time": r'var ct = "(\d+)"',
        "msg_cdn_url": r'var msg_cdn_url = "([^"]*)"',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, html)
        if m:
            val = m.group(1)
            if key == "publish_time":
                from datetime import datetime, timezone
                try:
                    val = datetime.fromtimestamp(int(val), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    pass
            meta[key] = val

    # Fallback: og:title / og:description
    if "title" not in meta:
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
        if m:
            meta["title"] = m.group(1)
    if "description" not in meta:
        m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
        if m:
            meta["description"] = m.group(1)

    return meta


def extract_content(html: str) -> str:
    """Extract article body text from js_content div."""
    m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div\s+class="ct_mpda_wrp")', html, re.DOTALL)
    if not m:
        # Fallback: broader match
        m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
    if not m:
        return ""

    raw = m.group(1)
    # Remove HTML tags, keeping line structure
    text = re.sub(r'<br\s*/?>', '\n', raw)
    text = re.sub(r'<p[^>]*>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<section[^>]*>', '\n', text)
    text = re.sub(r'</section>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: wechat_extract.py <url> [--json]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    as_json = "--json" in sys.argv

    if "mp.weixin.qq.com" not in url:
        print("Error: Not a WeChat article URL", file=sys.stderr)
        sys.exit(1)

    html = fetch_html(url)

    # Check for CAPTCHA page
    if '环境异常' in html and 'js_content' not in html:
        print("Error: WeChat returned CAPTCHA page. The IP may be rate-limited.", file=sys.stderr)
        sys.exit(2)

    meta = extract_meta(html)
    content = extract_content(html)

    if as_json:
        output = {**meta, "content": content}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if meta.get("title"):
            print(f"# {meta['title']}")
        if meta.get("account_name"):
            print(f"**公众号**: {meta['account_name']}")
        if meta.get("author"):
            print(f"**作者**: {meta['author']}")
        if meta.get("publish_time"):
            print(f"**发布时间**: {meta['publish_time']}")
        if meta.get("description"):
            print(f"**摘要**: {meta['description']}")
        print(f"\n---\n")
        print(content)


if __name__ == "__main__":
    main()
