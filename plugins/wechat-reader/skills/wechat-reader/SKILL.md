---
name: wechat-reader
description: Read and extract content from WeChat Official Account articles (mp.weixin.qq.com). Use when a user shares a WeChat article link, asks to read/summarize/analyze a WeChat post, or mentions 微信公众号 articles. Handles WeChat's anti-scraping protection by spoofing MicroMessenger User-Agent.
---

# WeChat Article Reader

Extract full text from WeChat Official Account articles (`mp.weixin.qq.com`).

## When a WeChat Link is Shared

Run the extraction script:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/wechat_extract.py "<URL>"
```

This returns the article title, author, account name, publish time, and full body text.

For JSON output (useful for further processing):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/wechat_extract.py "<URL>" --json
```

## How It Works

- Spoofs `MicroMessenger/8.0.50` User-Agent via curl — WeChat serves full HTML without CAPTCHA
- Extracts metadata from JavaScript variables (`msg_title`, `msg_desc`, `nickname`, `author`, `ct`)
- Parses article body from `id="js_content"` div, strips HTML tags

## Limitations

- If the server IP gets rate-limited, WeChat may still return a CAPTCHA page (exit code 2)
- Images in articles are not extracted (WeChat hotlink-protects them)
- Some articles may require WeChat login (rare, typically for paid/restricted content)

## After Extraction

- Summarize or analyze the article content as requested
- If the user asks for images, note they cannot be extracted due to WeChat's hotlink protection
