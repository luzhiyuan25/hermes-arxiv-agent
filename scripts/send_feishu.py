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


def choose_papers_to_send(payload: dict) -> list[dict]:
    new_papers = payload.get("new_papers", [])
    if new_papers:
        return new_papers

    crawled_date = payload.get("crawled_date_max", "")
    if not crawled_date:
        return []
    return [
        paper
        for paper in payload.get("papers", [])
        if paper.get("crawled_date") == crawled_date
    ]


def validate_feishu_response(raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    code = payload.get("code", payload.get("StatusCode", payload.get("status_code", 0)))
    if code not in (0, "0", None):
        message = payload.get("msg") or payload.get("message") or payload.get("StatusMessage") or raw
        raise RuntimeError(f"Feishu webhook rejected the message: code={code}, message={message}")


def main() -> None:
    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("FEISHU_WEBHOOK is not set; skip notification.")
        return

    payload = json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))
    papers_to_send = choose_papers_to_send(payload)
    if not papers_to_send:
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
                    "content": markdown_for_papers(site_url, papers_to_send),
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
        raw = res.read().decode("utf-8", errors="replace")
        validate_feishu_response(raw)
        print(raw)


if __name__ == "__main__":
    main()
