import os
import re
import sys
import html
import json
import time
from urllib.parse import unquote
from datetime import date, datetime

import requests
from ddgs import DDGS
import trafilatura
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai

BLOG_ID = "2163955447594716446"
SCOPES = ["https://www.googleapis.com/auth/blogger"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
BLOGGER_TOKEN_JSON = os.environ.get("BLOGGER_TOKEN_JSON")

TOPICS = [
    {
        "title": "Meemure Village News and Latest Updates",
        "query": "Meemure village Sri Lanka news latest",
        "label": "News",
        "fresh": True,
    },
    {
        "title": "Kandy News and Events",
        "query": "Kandy city Sri Lanka news today events",
        "label": "News",
        "fresh": True,
    },
    {
        "title": "How to Reach Meemure from Kandy",
        "query": "Meemure travel guide how to reach Lakegala Kandy road",
        "label": "Travel",
        "fresh": False,
    },
    {
        "title": "Meemure Weather and the Best Time to Visit",
        "query": "Meemure Knuckles weather rainfall best time to visit",
        "label": "Travel",
        "fresh": False,
    },
    {
        "title": "Meemure, Lakegala and the Village Culture",
        "query": "Meemure Lakegala legend history culture village",
        "label": "Cultural",
        "fresh": False,
    },
    {
        "title": "Kandy District Tourism and Transport Updates",
        "query": "Kandy district Sri Lanka tourism transport update",
        "label": "News",
        "fresh": True,
    },
    {
        "title": "Knuckles Mountain Range Hiking and Eco Tourism",
        "query": "Knuckles mountain range hiking eco tourism trail Sri Lanka",
        "label": "Travel",
        "fresh": False,
    },
]


def search_web(query, max_results=6, fresh=False):
    results = []
    try:
        with DDGS() as ddgs:
            kwargs = {"max_results": max_results, "region": "lk-en"}
            if fresh:
                kwargs["timelimit"] = "w"
            raw = list(ddgs.text(query, **kwargs))
            for r in raw:
                results.append({
                    "title": r.get("title", "").strip(),
                    "body": r.get("body", "").strip(),
                    "href": r.get("href", "").strip(),
                })
    except Exception as exc:
        print(f"[search] ddgs failed ({exc}); using HTML fallback")
        results = duckduckgo_html(query, max_results)
    results = [r for r in results if r.get("href")]
    return results


def duckduckgo_html(query, max_results=6):
    results = []
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query, "kl": "lk-en"},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
            timeout=20,
        )
        resp.raise_for_status()
        page = resp.text
        anchors = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:td|a|div)>', page, re.S)
        for i, (href, title_html) in enumerate(anchors[:max_results]):
            title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            body = ""
            if i < len(snippets):
                body = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
            results.append({"title": title, "body": body, "href": href})
    except Exception as exc:
        print(f"[search] HTML fallback failed: {exc}")
    return [r for r in results if r.get("href")]


def fetch_article_text(url, max_chars=4000):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_recall=False,
        )
        if text:
            return " ".join(text.split())[:max_chars]
    except Exception:
        pass
    return None


def build_context(results, max_full=3):
    parts = []
    for i, r in enumerate(results, 1):
        part = f"Document {i}:\nURL: {r['href']}\nTitle: {r['title']}\nSnippet: {r['body']}"
        if r.get("full_text"):
            part += f"\nFull text: {r['full_text']}"
        parts.append(part)
    return "\n\n".join(parts)


def build_prompt(topic, context, today):
    return f"""
You are a careful factual writer for "meemurevillage.lk", a Sri Lankan blog about Meemure Village and the Kandy district.

Write a daily blog post on the topic: "{topic}".
Today's date: {today}.

STRICT FACTUAL RULES (never break these):
1. Use ONLY the facts inside the source documents below. Ignore everything you know from training.
2. Do NOT invent, guess or imply any statistic, date, price, distance, name, person, event or number that is not present in the source documents.
3. If the sources do not cover a point, do not fill the gap from memory - simply skip that point.
4. Attribute each fact to a source: after every factual claim add an inline link such as <a href="URL">[Source]</a> pointing to the document that supports it.
5. If the original article states something as opinion, claim or announcement, write it as "according to <publication name>".
6. Never present speculation as fact. Never add warnings, forecasts or advice that are not in the documents.
7. End the article with an <h3>Sources</h3> section: an unordered list <ul> with ALL the source links used (list item per source: <a href="URL">Title</a>).

SOURCE DOCUMENTS:
{context}

FORMAT REQUIREMENTS:
- Reply with exactly two marker lines followed by the article:
TITLE: <a title of 8 to 12 words, do not use quotes>
CONTENT:
<article as clean HTML>
- Use only these HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em>, <a>. No <html>, <head>, <body>, <script> or <style>.
- Length: 400 to 700 words.
- Do not add any text, notes or explanation outside the TITLE: and CONTENT: markers.
"""


def generate_post(topic, context, today):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt(topic, context, today)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.4},
    )
    text = (response.text or "").strip()
    match = re.search(r"TITLE:\s*(.*?)\s*\nCONTENT:\s*(.*)", text, re.S)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def validate(content_html, results):
    if not content_html or len(content_html) < 500:
        return False
    source_urls = [r["href"] for r in results if r.get("href")]
    domains = []
    for url in source_urls:
        m = re.search(r"https?://([^/]+)", url)
        if m:
            domains.append(m.group(1))
    matched = sum(1 for d in domains if d in content_html)
    return matched >= 2


def publish_live(title, content_html, label):
    token_data = json.loads(BLOGGER_TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    service = build("blogger", "v3", credentials=creds)

    existing = service.posts().list(blogId=BLOG_ID, maxResults=25, fetchBodies=False).execute()
    for post in existing.get("items", []):
        if post.get("title") == title:
            print(f"[publish] duplicate title found (post {post['id']}) - skipping")
            return

    body = {
        "kind": "blogger#post",
        "title": title,
        "content": content_html,
        "labels": ["Automated", label],
    }
    result = service.posts().insert(
        blogId=BLOG_ID, body=body, isDraft=False
    ).execute()
    print(f"[publish] LIVE post created: {result.get('url')}")


def main():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY env var is missing")
        sys.exit(1)
    if not BLOGGER_TOKEN_JSON:
        print("ERROR: BLOGGER_TOKEN_JSON env var is missing")
        sys.exit(1)

    custom_topic = os.environ.get("CUSTOM_TOPIC", "").strip()
    if custom_topic:
        meta = {"title": f"Daily Update: {custom_topic}", "query": custom_topic, "label": "News", "fresh": True}
    else:
        meta = TOPICS[date.today().toordinal() % len(TOPICS)]

    print(f"[run] {datetime.now().isoformat()} topic={meta['title']} query={meta['query']}")

    results = search_web(meta["query"], fresh=meta["fresh"])
    if not results:
        print("[run] no search results found - skipping today to avoid publishing fake content")
        sys.exit(0)
    print(f"[run] {len(results)} search results")

    for r in results[:3]:
        r["full_text"] = fetch_article_text(r["href"])
        time.sleep(1)

    context = build_context(results)
    today = date.today().strftime("%B %d, %Y")

    title, content_html = None, None
    for attempt in (1, 2):
        title, content_html = generate_post(meta["title"], context, today)
        if title and content_html and validate(content_html, results):
            break
        print(f"[generate] attempt {attempt} failed validation, retrying")

    if not title or not content_html or not validate(content_html, results):
        print("[run] post could not pass factual validation twice - not publishing")
        sys.exit(1)

    publish_live(title, content_html, meta["label"])


if __name__ == "__main__":
    main()