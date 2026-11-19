"""
Gipsy's knowledge pack: retrieval-augmented generation (RAG), from scratch.

The lessons live as Markdown files in gipsy_hub/knowledge/. Each "## " section
becomes one chunk. At start-up the hub asks Ollama's embedding model
(nomic-embed-text) to turn every chunk into a vector: a list of 768 numbers
where texts with similar meaning land close together. Vectors are cached in
knowledge/.index.json so this only happens again when a lesson changes.

When John asks something, the question is embedded the same way, we score
every chunk by cosine similarity, and the best few are pasted into the prompt
as reference notes. The model doesn't learn anything permanently. It reads
the notes like an open-book exam.

If the embedding model isn't installed, a simple keyword score is used
instead, so the pack still works (just less cleverly).

Add your own lessons: drop a .md file in knowledge/ and restart the hub.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("gipsy")

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an and are as at be but by can do does for from how i if in is it its me my of on or so "
    "that the their them then there these they this to was what when where which who why will "
    "with you your about should would could tell explain gipsy john hello hi hey thanks thank "
    "today good sounds ok okay yes yeah no please now just like get know want need sure great "
    "nice morning evening night let lets go going".split()
)


def words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


@dataclass
class Chunk:
    source: str
    title: str
    text: str
    vec: Optional[list[float]] = None
    terms: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.title}|{self.text}".encode()).hexdigest()


def split_markdown(name: str, md: str) -> list[Chunk]:
    """One chunk per '## ' section, with the file's '# ' title as context."""
    doc_title = name
    m = re.search(r"^# (.+)$", md, re.M)
    if m:
        doc_title = m.group(1).strip()
    parts = re.split(r"^## ", md, flags=re.M)
    chunks: list[Chunk] = []
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        body = body.strip()
        if body:
            title = f"{doc_title} > {head.strip()}"
            chunks.append(Chunk(name, title, body, terms=set(words(title + " " + body))))
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgePack:
    def __init__(self, folder: Path, ollama_url: str, embed_model: str = "nomic-embed-text") -> None:
        self.folder = folder
        self.ollama_url = ollama_url
        self.embed_model = embed_model
        self.chunks: list[Chunk] = []
        self.use_vectors = False
        self.load()

    # ------------------------------------------------------------ loading --

    def load(self) -> None:
        self.chunks = []
        for f in sorted(self.folder.glob("*.md")):
            if f.name.lower() == "readme.md":
                continue
            self.chunks += split_markdown(f.stem, f.read_text(encoding="utf-8"))
        n = len(self.chunks) or 1
        self.df: dict[str, int] = {}
        for c in self.chunks:
            for t in c.terms:
                self.df[t] = self.df.get(t, 0) + 1
        self.idf = {t: math.log(1 + n / d) for t, d in self.df.items()}
        log.info("Knowledge pack: %d sections from %s", len(self.chunks), self.folder)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as c:
            r = await c.post(f"{self.ollama_url}/api/embed", json={"model": self.embed_model, "input": texts})
            r.raise_for_status()
            return r.json()["embeddings"]

    async def build_index(self) -> None:
        """Embed every section (cached). Falls back to keywords on failure."""
        cache_path = self.folder / ".index.json"
        cache: dict[str, list[float]] = {}
        if cache_path.exists():
            try:
                saved = json.loads(cache_path.read_text(encoding="utf-8"))
                if saved.get("model") == self.embed_model:
                    cache = saved.get("vectors", {})
            except Exception:
                pass
        todo = [c for c in self.chunks if c.key not in cache]
        try:
            for i in range(0, len(todo), 16):
                batch = todo[i : i + 16]
                # nomic-embed-text wants these task prefixes.
                vecs = await self._embed([f"search_document: {c.title}\n{c.text}" for c in batch])
                for c, v in zip(batch, vecs):
                    cache[c.key] = v
        except Exception as e:
            log.warning(
                "Knowledge pack: no embeddings (%s). Using keyword search. Run 'ollama pull %s' for better results.",
                e, self.embed_model,
            )
            self.use_vectors = False
            return
        for c in self.chunks:
            c.vec = cache.get(c.key)
        keep = {c.key for c in self.chunks}
        cache_path.write_text(
            json.dumps({"model": self.embed_model, "vectors": {k: v for k, v in cache.items() if k in keep}}),
            encoding="utf-8",
        )
        self.use_vectors = all(c.vec for c in self.chunks)
        log.info("Knowledge pack: %d sections embedded with %s (%d new)", len(self.chunks), self.embed_model, len(todo))

    # ------------------------------------------------------------ search --

    def is_on_topic(self, text: str) -> bool:
        """True if the message names something a lesson is about (a word in a
        lesson title, like 'EMA', 'gold', 'yield' or 'TradingView')."""
        titles = {t for c in self.chunks for t in words(c.title.replace(">", " "))}
        for w in set(words(text)):
            if w in titles:
                return True
            # "candle" ~ "candlesticks", "crosses" ~ "crossovers"
            if len(w) >= 4 and any(t.startswith(w[:5]) for t in titles if len(t) >= 4):
                return True
        return False

    def keyword_scores(self, query: str) -> list[tuple[float, Chunk]]:
        q = set(words(query))
        if not q:
            return []
        total = sum(self.idf.get(t, 0) for t in q) or 1
        out = []
        for c in self.chunks:
            matched = q & c.terms
            if len(matched) < min(2, len(q)):
                continue  # one shared word (often a common one) isn't enough
            hit = sum(self.idf.get(t, 0) for t in matched)
            out.append((hit / total, c))
        return sorted(out, key=lambda x: -x[0])

    async def search(self, query: str, k: int = 3, min_score: Optional[float] = None) -> list[tuple[float, Chunk]]:
        if not self.chunks or not query.strip():
            return []
        if self.use_vectors:
            try:
                qv = (await self._embed([f"search_query: {query}"]))[0]
                scored = sorted(((cosine(qv, c.vec or []), c) for c in self.chunks), key=lambda x: -x[0])
                cut = 0.55 if min_score is None else min_score
                return [s for s in scored[:k] if s[0] >= cut]
            except Exception as e:
                log.info("Embedding the question failed (%s); using keywords", e)
        cut = 0.34 if min_score is None else min_score
        return [s for s in self.keyword_scores(query)[:k] if s[0] >= cut]

    @staticmethod
    def as_context(hits: list[tuple[float, Chunk]]) -> str:
        parts = [f"[{c.title}]\n{c.text}" for _, c in hits]
        return (
            "Reference notes from Gipsy's markets knowledge pack. Use them if they help answer "
            "John's latest message. Teach in your own words, simply, and keep it conversational.\n\n"
            + "\n\n---\n\n".join(parts)
        )
