"""One-time: Gemini listens to every voice sample and writes voice_tags.json (read it and fix tags that sound wrong).
Run: python generate_voice_tags.py   (~30 text requests; add --force to redo all)"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()
import voice_tags  # noqa: E402
import voices as V  # noqa: E402

tags = {} if "--force" in sys.argv else voice_tags.load()
todo = [v["name"] for v in V.VOICES if v["name"] not in tags]


def one(name):
    for _ in range(3):
        try:
            return name, voice_tags.tag_voice(name)
        except Exception as exc:
            err = exc
    print("FAILED", name, str(err)[:100])
    return name, None


with ThreadPoolExecutor(4) as pool:
    for name, t in pool.map(one, todo):
        if t:
            tags[name] = t
            print(voice_tags.line(name, t), flush=True)
json.dump(tags, open(voice_tags.TAGS_FILE, "w"), indent=1, ensure_ascii=False)
print(f"saved {len(tags)} tags to voice_tags.json")
