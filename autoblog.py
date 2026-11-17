import os
import re
import sys
import json
import time
import base64
from datetime import date, datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai
from google.genai import types

BLOG_ID = "2163955447594716446"
SCOPES = ["https://www.googleapis.com/auth/blogger"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
IMAGE_MODEL = os.environ.get("IMAGE_MODEL") or "imagen-3.0-generate-002"
BLOGGER_TOKEN_JSON = os.environ.get("BLOGGER_TOKEN_JSON")

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


def generate_image(topic_title, angle):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        f"Photorealistic, high-quality travel photograph illustrating: {topic_title}. "
        f"Scene details: {angle}. Location feel: Meemure village and Knuckles mountain range, Sri Lanka. "
        "Natural lighting, vivid but realistic colors, cinematic composition, no text, no watermark, no logos, no people faces in close-up."
    )

    available = list_model_names(client)
    first_choices = [IMAGE_MODEL, "imagen-3.0-generate-002", "imagen-3.0-fast-generate-001"]
    image_models = [m for m in first_choices if m and (not available or m in available)]
    image_models += [m for m in available if "imagen" in m or "image-generation" in m]
    print(f"[image] trying models: {image_models}")
    seen = set()
    for model in image_models:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            result = client.models.generate_images(
                model=model,
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1),
            )
            if result and getattr(result, "generated_images", None):
                img = result.generated_images[0]
                image_obj = getattr(img, "image", None)
                data = getattr(image_obj, "image_bytes", None) if image_obj else None
                if not data and image_obj is not None:
                    b64 = getattr(image_obj, "data", None)
                    if b64:
                        data = base64.b64decode(b64) if isinstance(b64, str) else b64
                if data:
                    b64out = base64.b64encode(data).decode("ascii")
                    print(f"[image] generated with {model}")
                    return f"data:image/png;base64,{b64out}"
        except Exception as exc:
            print(f"[image] model={model} failed: {str(exc)[:140]}")

    fallback_models = [m for m in available if "image" in m] + [
        "gemini-2.0-flash-preview-image-generation",
        "gemini-2.0-flash-exp-image-generation",
    ]
    seen = set()

    for model in fallback_models:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
            )
            for cand in getattr(response, "candidates", []) or []:
                content = getattr(cand, "content", None)
                for part in getattr(content, "parts", []) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        data = inline.data
                        if isinstance(data, str):
                            b64out = data
                        else:
                            b64out = base64.b64encode(data).decode("ascii")
                        mime = getattr(inline, "mime_type", None) or "image/png"
                        print(f"[image] generated with {model}")
                        return f"data:{mime};base64,{b64out}"
        except Exception as exc:
            print(f"[image] model={model} failed: {str(exc)[:140]}")

    print("[image] could not generate AI image")
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

    image_src = generate_image(meta["title"], meta["angle"])
    if image_src:
        content_html = embed_image(content_html, image_src, title)
    else:
        print("[run] publishing without image (image generation unavailable)")

    publish_live(title, content_html, meta["label"])


if __name__ == "__main__":
    main()
