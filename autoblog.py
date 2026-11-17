import os
import re
import sys
import json
import time
from datetime import date, datetime
from urllib.parse import quote

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai

BLOG_ID = "2163955447594716446"
SCOPES = ["https://www.googleapis.com/auth/blogger"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
BLOGGER_TOKEN_JSON = os.environ.get("BLOGGER_TOKEN_JSON")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
IMAGE_DIR = "generated"

TOPICS = [
    {
        "title": "A Morning in Meemure Village",
        "angle": "the quiet rhythm of village life at dawn, mist on the fields, and everyday moments",
        "label": "Village Life",
    },
    {
        "title": "How to Reach Meemure from Kandy",
        "angle": "the journey from Kandy to Meemure, the changing roads, and what travelers should expect",
        "label": "Travel",
    },
    {
        "title": "Meemure Weather and the Best Time to Visit",
        "angle": "how the seasons feel in Meemure and the Knuckles, and when the village is most welcoming",
        "label": "Travel",
    },
    {
        "title": "Lakegala and the Spirit of Meemure",
        "angle": "the presence of Lakegala, local stories, and the cultural heart of the village",
        "label": "Cultural",
    },
    {
        "title": "Kandy to the Knuckles: A Day Trip Story",
        "angle": "a personal-feeling day trip from Kandy toward the Knuckles and Meemure",
        "label": "Travel",
    },
    {
        "title": "Village Food and Simple Traditions in Meemure",
        "angle": "home-cooked meals, local habits, and the warmth of Meemure traditions",
        "label": "Cultural",
    },
    {
        "title": "Hiking Around Meemure and the Knuckles Range",
        "angle": "trails, views, and the feeling of walking through the Knuckles landscape",
        "label": "Travel",
    },
]


def build_prompt(topic, angle, today):
    return f"""You are a local storyteller writing from Meemure, Sri Lanka. Write a blog post in your own words.

Topic: {topic}
Angle to explore: {angle}
Today's date (for context only, do not force it into the text): {today}

WRITING STYLE:
- Sound like a real person sharing lived experience and impressions, not an AI assistant or a brochure.
- Warm, clear, and natural tone with varied sentence lengths. Human rhythm, not robotic.
- Open with a vivid hook about the place/experience itself. No "Welcome to", no "In this post", no "Today we will".
- Never mention "blog", "article", "AI", "as an AI", website names, or meta commentary.
- Avoid clichés like "hidden gem", "tapestry", "delve", "in conclusion", "it's important to note".
- Write from a grounded, personal perspective, but do not invent specific statistics, exact prices, precise distances, named officials, or recent news events. Keep details general and experience-based.

CONTENT:
- Headline: natural and appealing, 6 to 10 words. No quotes, no emojis, no colons.
- Body: 450 to 700 words with helpful, engaging flow.
- Use only these HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em>. No links, no <html>/<head>/<body>, no scripts or styles.
- Structure with 2-3 short <h2> sections where it fits naturally.

Reply in exactly this format:
TITLE: <headline>
CONTENT:
<article html>
"""


def list_model_names(client):
    try:
        return [m.name.replace("models/", "") for m in client.models.list()]
    except Exception as exc:
        print(f"[models] could not list models: {str(exc)[:100]}")
        return []


def generate_post(topic_meta, today):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt(topic_meta["title"], topic_meta["angle"], today)
    available = list_model_names(client)
    candidates = [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
    models = [m for m in candidates if m and (not available or m in available)]
    if not models:
        models = [m for m in available if "flash" in m][:3]
    print(f"[generate] trying models: {models}")
    seen = set()
    for model in models:
        if not model or model in seen:
            continue
        seen.add(model)
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"temperature": 0.8},
                )
                text = (response.text or "").strip()
                match = re.search(r"TITLE:\s*(.*?)\s*\nCONTENT:\s*(.*)", text, re.S)
                if not match:
                    print(f"[generate] model={model} attempt={attempt} bad format")
                    continue
                title = match.group(1).strip().strip('"').strip("'")
                content = match.group(2).strip()
                if len(re.sub(r"<[^>]+>", "", content)) < 350:
                    print(f"[generate] model={model} attempt={attempt} content too short")
                    continue
                return title, content
            except Exception as exc:
                print(f"[generate] model={model} attempt={attempt} failed: {str(exc)[:120]}")
                time.sleep(5 * (attempt + 1))
    return None, None


def generate_ai_image(title, angle):
    prompt = (
        f"Editorial travel photograph for a story titled '{title}'. "
        f"Scene: {angle}. Setting: Meemure village and Knuckles mountain range, Sri Lanka. "
        "Photorealistic, natural light, vivid realistic colors, cinematic landscape composition, "
        "no text, no watermark, no logos, no captions, no close-up faces."
    )
    seed = date.today().toordinal() % 100000
    url = (
        f"{POLLINATIONS_URL}/{quote(prompt, safe='')}"
        f"?width=1024&height=576&seed={seed}&nologo=true"
    )
    try:
        response = requests.get(url, timeout=120)
        content_type = response.headers.get("content-type", "")
        if (
            response.status_code == 200
            and content_type.startswith("image/")
            and len(response.content) > 1000
        ):
            ext = "png" if "png" in content_type else "jpg"
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
            filename = f"{date.today().isoformat()}-{slug}.{ext}"
            os.makedirs(IMAGE_DIR, exist_ok=True)
            path = os.path.join(IMAGE_DIR, filename)
            with open(path, "wb") as handle:
                handle.write(response.content)
            repo = os.environ.get("GITHUB_REPOSITORY") or "dilanjanranmalinda/meemure-autoblog"
            branch = os.environ.get("GITHUB_REF_NAME") or "main"
            hosted_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{IMAGE_DIR}/{filename}"
            print(f"[image] Pollinations image saved: {path}")
            return hosted_url
        print(f"[image] Pollinations failed: status={response.status_code} type={content_type}")
    except Exception as exc:
        print(f"[image] Pollinations failed: {str(exc)[:160]}")
    return None


def find_stock_image(query, width=1200):
    if not PEXELS_API_KEY:
        return None
    queries = [query, "Meemure Sri Lanka mountains", "Sri Lanka landscape"]
    for q in queries:
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": q, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": PEXELS_API_KEY},
                timeout=20,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                continue
            src = photos[0].get("src", {})
            base = src.get("large2x") or src.get("large") or src.get("original")
            if not base:
                continue
            m = re.search(r"(https?://[^?]+)", base)
            if m:
                print(f"[image] stock photo found for '{q}'")
                return f"{m.group(1)}?auto=compress&cs=tinysrgb&w={width}"
        except Exception as exc:
            print(f"[image] stock query '{q}' failed: {str(exc)[:100]}")
    return None


def embed_image(content_html, image_src, alt):
    safe_alt = alt.replace('"', "&quot;")
    img_html = (
        '<div style="text-align:center;margin:10px 0 18px 0;">'
        f'<img src="{image_src}" alt="{safe_alt}" loading="lazy" '
        'style="max-width:100%;height:auto;border-radius:10px;" />'
        "</div>"
    )
    return img_html + content_html


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
        "labels": [label],
    }
    result = service.posts().insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
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
        meta = {
            "title": custom_topic,
            "angle": f"a personal, grounded perspective on {custom_topic} around Meemure and Kandy, Sri Lanka",
            "label": "Travel",
        }
    else:
        meta = TOPICS[date.today().toordinal() % len(TOPICS)]

    today = date.today().strftime("%B %d, %Y")
    print(f"[run] {datetime.now().isoformat()} topic={meta['title']}")

    title, content_html = generate_post(meta, today)
    if not title or not content_html:
        print("[run] failed to generate article")
        sys.exit(1)

    image_src = generate_ai_image(meta["title"], meta["angle"])
    if not image_src:
        print("[run] AI image unavailable - trying stock photo fallback")
        image_src = find_stock_image(f"{meta['title']} {meta['angle']} Sri Lanka")
    if image_src:
        content_html = embed_image(content_html, image_src, title)
    else:
        print("[run] publishing without image (no image source available)")

    publish_live(title, content_html, meta["label"])


if __name__ == "__main__":
    main()
