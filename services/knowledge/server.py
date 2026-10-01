from __future__ import annotations

import json
import re
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
ARTICLES = json.loads((ROOT / "data" / "knowledge.json").read_text())["articles"]
app = FastAPI(title="Bookly Knowledge API", version="0.1.0")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=5)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "knowledge", "articles": len(ARTICLES)}


@app.post("/v1/search")
async def search(request: SearchRequest) -> dict:
    q = tokens(request.query)
    ranked = []
    for article in ARTICLES:
        haystack = tokens(f"{article['title']} {article['content']}")
        score = len(q & haystack)
        if score:
            ranked.append((score, article))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return {"results": [{"article_id": a["article_id"], "title": a["title"], "content": a["content"], "score": score} for score, a in ranked[: request.limit]]}
