from __future__ import annotations

import json
import re
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
ARTICLES = json.loads((ROOT / "data" / "knowledge.json").read_text())["articles"]

TOKEN_NORMALIZATION = {
    "deliveries": "delivery",
    "returns": "return",
    "refunds": "refund",
    "orders": "order",
    "payments": "payment",
    "discounts": "discount",
    "codes": "code",
    "items": "item",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "book", "bookly", "but", "by",
    "can", "do", "does", "for", "from", "how", "i", "in", "is", "it", "me",
    "my", "of", "on", "or", "please", "the", "to", "what", "when", "where",
    "which", "with", "you", "your",
}
app = FastAPI(title="Bookly Knowledge API", version="0.1.0")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=5)


def tokens(text: str) -> set[str]:
    normalized = {
        TOKEN_NORMALIZATION.get(token, token)
        for token in re.findall(r"[a-z0-9]+", text.lower())
    }
    return {token for token in normalized if token not in STOPWORDS}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "knowledge", "articles": len(ARTICLES)}


@app.post("/v1/search")
async def search(request: SearchRequest) -> dict:
    q = tokens(request.query)
    ranked = []
    for article in ARTICLES:
        title_tokens = tokens(article["title"])
        content_tokens = tokens(article["content"])
        title_overlap = len(q & title_tokens)
        body_overlap = len(q & content_tokens)
        score = (title_overlap * 3) + body_overlap
        if score:
            ranked.append((score, title_overlap, article))
    ranked.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
    return {
        "results": [
            {
                "article_id": article["article_id"],
                "title": article["title"],
                "content": article["content"],
                "score": score,
            }
            for score, _title_overlap, article in ranked[: request.limit]
        ]
    }
