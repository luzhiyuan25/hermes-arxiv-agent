#!/usr/bin/env python3
"""Optionally send today's new papers to a Feishu/Lark custom bot webhook."""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_PATH = ROOT / "site" / "papers_data.json"


def markdown_for_papers(site_url: str, papers: list[dict]) -> str:
    max_items = int(os.getenv("FEISHU_MAX_PAPERS", "30"))
    lines = [f"**今日论文更新：{len(papers)} 篇**", ""]
    if site_url:
        lines.append(f"[打开阅读页]({site_url})")
        lines.append("")
    for paper in papers[:max_items]:
        title = paper.get("title") or paper.get("arxiv_id", "")
        abs_url = paper.get("abs_url", "")
        cats = paper.get("categories", "")
        intro = paper.get("summary_cn", "")
        lines.append(f"- [{title}]({abs_url})")
        if intro:
            lines.append(f"  简介：{intro}")
        if cats:
            lines.append(f"  分类：{cats}")
    if len(papers) > max_items:
        lines.append(f"- 还有 {len(papers) - max_items} 篇，请在阅读页查看。")
    return "\n".join(lines)


def main() -> None:
    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("FEISHU_WEBHOOK is not set; skip notification.")
        return

    payload = json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))
    new_papers = payload.get("new_papers", [])
    if not new_papers:
        print("No new papers; skip notification.")
        return

    site_url = os.getenv("SITE_URL", "").strip()
    body = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Daily Papers"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown_for_papers(site_url, new_papers),
                }
            ],
        },
    }
    secret = os.getenv("FEISHU_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64.b64encode(
            hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        body["timestamp"] = timestamp
        body["sign"] = sign

    req = urllib.request.Request(
        webhook,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        print(res.read().decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
