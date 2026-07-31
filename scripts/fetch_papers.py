#!/usr/bin/env python3
"""Fetch recent arXiv papers and build static-site data for GitHub Pages."""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS_PATH = ROOT / "config" / "keywords.txt"
DATA_PATH = ROOT / "data" / "papers.json"
SITE_DIR = ROOT / "site"
SITE_DATA_PATH = SITE_DIR / "papers_data.json"
DAILY_DIR = SITE_DIR / "daily"
FEED_PATH = SITE_DIR / "feed.xml"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class RunConfig:
    max_results: int
    days_lookback: int
    request_interval: float
    timezone_name: str

    @property
    def tz(self):
        return ZoneInfo(self.timezone_name)


def text(node: Optional[ET.Element]) -> str:
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def iso_date(value: str) -> str:
    return parse_dt(value).date().isoformat()


def arxiv_id_without_version(arxiv_id: str) -> str:
    if "v" in arxiv_id:
        head, tail = arxiv_id.rsplit("v", 1)
        if tail.isdigit():
            return head
    return arxiv_id


def read_queries() -> list[str]:
    if not KEYWORDS_PATH.exists():
        raise FileNotFoundError(f"Missing {KEYWORDS_PATH}")
    queries = []
    for line in KEYWORDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            queries.append(line)
    if not queries:
        raise ValueError("config/keywords.txt does not contain any active arXiv query")
    return queries


def load_existing() -> dict[str, dict]:
    if not DATA_PATH.exists():
        return {}
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    papers = payload.get("papers", [])
    return {str(p["arxiv_id"]): p for p in papers if p.get("arxiv_id")}


def build_arxiv_url(query: str, max_results: int) -> str:
    normalized_query = query.replace("+", " ")
    params = {
        "search_query": normalized_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API}?{urllib.parse.urlencode(params)}"


def fetch_query(query: str, config: RunConfig) -> list[dict]:
    url = build_arxiv_url(query, config.max_results)
    req = urllib.request.Request(url, headers={"User-Agent": "daily-paper-pages/1.0"})
    with urllib.request.urlopen(req, timeout=45) as res:
        body = res.read()

    root = ET.fromstring(body)
    papers = []
    for entry in root.findall("a:entry", ATOM_NS):
        full_id = text(entry.find("a:id", ATOM_NS)).split("/abs/")[-1]
        arxiv_id = arxiv_id_without_version(full_id)
        authors = [
            text(author.find("a:name", ATOM_NS))
            for author in entry.findall("a:author", ATOM_NS)
        ]
        categories = [
            cat.attrib.get("term", "")
            for cat in entry.findall("a:category", ATOM_NS)
            if cat.attrib.get("term")
        ]
        published_raw = text(entry.find("a:published", ATOM_NS))
        updated_raw = text(entry.find("a:updated", ATOM_NS))
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "versioned_id": full_id,
                "title": text(entry.find("a:title", ATOM_NS)),
                "authors": ", ".join(a for a in authors if a),
                "published_date": iso_date(published_raw),
                "updated_date": iso_date(updated_raw),
                "published_at": published_raw,
                "updated_at": updated_raw,
                "categories": ", ".join(categories),
                "abstract": text(entry.find("a:summary", ATOM_NS)),
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{full_id}",
                "source_query": query,
                "summary_cn": "",
                "affiliations": "",
            }
        )
    return papers


def merge_papers(existing: dict[str, dict], fetched: list[dict], config: RunConfig) -> tuple[list[dict], list[dict]]:
    now = datetime.now(config.tz)
    today = now.date().isoformat()
    cutoff = now.astimezone(timezone.utc) - timedelta(days=config.days_lookback)
    new_papers = []

    for paper in fetched:
        published = parse_dt(paper["published_at"])
        if published < cutoff:
            continue
        old = existing.get(paper["arxiv_id"])
        if old:
            merged = {**paper, **{k: v for k, v in old.items() if v not in ("", None)}}
            merged["last_seen_date"] = today
            existing[paper["arxiv_id"]] = merged
        else:
            paper["crawled_date"] = today
            paper["last_seen_date"] = today
            existing[paper["arxiv_id"]] = paper
            new_papers.append(paper)

    papers = sorted(
        existing.values(),
        key=lambda p: (p.get("published_date", ""), p.get("updated_date", ""), p.get("arxiv_id", "")),
        reverse=True,
    )
    return papers, new_papers


def llm_chat_completion(api_key: str, base_url: str, model: str, prompt: str) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是论文阅读助手。请用简洁、准确的中文介绍论文，不要夸大，不要编造摘要中没有的信息。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 260,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        payload = json.loads(res.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"].strip()


def fallback_chinese_intro(paper: dict) -> str:
    title = paper.get("title", paper.get("arxiv_id", "这篇论文"))
    cats = paper.get("categories", "")
    if cats:
        return f"这篇论文关注“{title}”，arXiv 分类为 {cats}。详细贡献请查看英文摘要和论文原文。"
    return f"这篇论文关注“{title}”。详细贡献请查看英文摘要和论文原文。"


def enrich_papers_with_chinese_intro(papers: list[dict]) -> None:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip()
    model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip()
    max_papers = int(os.getenv("LLM_MAX_PAPERS", "30"))

    targets = [p for p in papers if not p.get("summary_cn")][:max_papers]
    if not targets:
        return

    if not api_key:
        print("LLM_API_KEY is not set; skip Chinese intro generation.")
        return

    for index, paper in enumerate(targets, start=1):
        prompt = (
            "请根据下面的 arXiv 论文信息，生成中文简介。\n"
            "要求：\n"
            "1. 用 1-2 句话说明论文要解决什么问题、用了什么方法或有什么贡献。\n"
            "2. 保留必要英文术语，例如 Gaussian Splatting、panorama、3D editing。\n"
            "3. 不要超过 120 个中文字符。\n\n"
            f"标题：{paper.get('title', '')}\n"
            f"作者：{paper.get('authors', '')}\n"
            f"分类：{paper.get('categories', '')}\n"
            f"英文摘要：{paper.get('abstract', '')}\n"
        )
        try:
            paper["summary_cn"] = llm_chat_completion(api_key, base_url, model, prompt)
            print(f"Generated Chinese intro {index}/{len(targets)}: {paper.get('arxiv_id')}")
            time.sleep(0.5)
        except Exception as exc:
            paper["summary_cn"] = fallback_chinese_intro(paper)
            print(f"[WARN] Failed to generate Chinese intro for {paper.get('arxiv_id')}: {exc}")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_payload(papers: list[dict], new_papers: list[dict], config: RunConfig) -> dict:
    now = datetime.now(config.tz)
    crawled_dates = sorted({p.get("crawled_date", "") for p in papers if p.get("crawled_date")})
    published_dates = sorted({p.get("published_date", "") for p in papers if p.get("published_date")})
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": config.timezone_name,
        "count": len(papers),
        "new_count": len(new_papers),
        "crawled_date_min": crawled_dates[0] if crawled_dates else "",
        "crawled_date_max": crawled_dates[-1] if crawled_dates else "",
        "published_date_min": published_dates[0] if published_dates else "",
        "published_date_max": published_dates[-1] if published_dates else "",
        "papers": papers,
        "new_papers": new_papers,
    }


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_feed(payload: dict) -> None:
    generated = email.utils.format_datetime(datetime.now(timezone.utc))
    items = []
    for paper in payload["papers"][:50]:
        title = xml_escape(paper.get("title", paper.get("arxiv_id", "")))
        link = xml_escape(paper.get("abs_url", ""))
        desc = xml_escape(paper.get("abstract", ""))
        pub = paper.get("published_at") or paper.get("updated_at")
        pub_date = email.utils.format_datetime(parse_dt(pub).astimezone(timezone.utc)) if pub else generated
        items.append(
            f"<item><title>{title}</title><link>{link}</link><guid>{link}</guid>"
            f"<pubDate>{pub_date}</pubDate><description>{desc}</description></item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        '<title>Daily Papers</title><link>./</link>'
        '<description>Daily arXiv paper updates</description>'
        f"<lastBuildDate>{generated}</lastBuildDate>"
        + "".join(items)
        + "</channel></rss>\n"
    )
    FEED_PATH.write_text(feed, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=int(os.getenv("MAX_RESULTS", "50")))
    parser.add_argument("--days-lookback", type=int, default=int(os.getenv("DAYS_LOOKBACK", "3")))
    parser.add_argument("--request-interval", type=float, default=float(os.getenv("REQUEST_INTERVAL", "3")))
    parser.add_argument("--timezone", default=os.getenv("SITE_TIMEZONE", "Asia/Shanghai"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = RunConfig(
        max_results=args.max_results,
        days_lookback=args.days_lookback,
        request_interval=args.request_interval,
        timezone_name=args.timezone,
    )

    fetched: list[dict] = []
    for index, query in enumerate(read_queries()):
        if index:
            time.sleep(config.request_interval)
        fetched.extend(fetch_query(query, config))

    papers, new_papers = merge_papers(load_existing(), fetched, config)
    enrich_papers_with_chinese_intro(papers)
    payload = build_payload(papers, new_papers, config)
    write_json(DATA_PATH, {"papers": papers})
    write_json(SITE_DATA_PATH, payload)
    today = datetime.now(config.tz).date().isoformat()
    write_json(DAILY_DIR / f"{today}.json", {"date": today, "papers": new_papers})
    write_feed(payload)
    print(f"Fetched {len(fetched)} records, added {len(new_papers)} new papers, total {len(papers)}.")


if __name__ == "__main__":
    main()
