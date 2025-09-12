import logging
import math
import re
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Try to use tiktoken for better token estimates; fall back to simple whitespace heuristic.
try:
    import tiktoken  # type: ignore

    def _get_tokenizer(encoding_name: str = "cl100k_base"):
        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception:
            return tiktoken.encoding_for_model("gpt-4") if hasattr(tiktoken, "encoding_for_model") else tiktoken.get_encoding("cl100k_base")

    _TIKTOKEN_AVAILABLE = True
except Exception:
    _TIKTOKEN_AVAILABLE = False


@dataclass
class Chunk:
    id: str
    text: str
    tokens: int
    metadata: Dict[str, Any]


def _simple_tokenize(text: str) -> List[str]:
    # naive tokenization: split on whitespace/punctuation to approximate tokens
    toks = re.findall(r"\w+|[^\s\w]", text, flags=re.UNICODE)
    return toks


def estimate_tokens(text: str, tokenizer: Optional[Any] = None) -> int:
    """
    Estimate token count for a text. If a tiktoken-like tokenizer is provided (or available),
    it will be used. Otherwise fall back to a simple whitespace/punctuation heuristic.
    """
    if tokenizer is None and _TIKTOKEN_AVAILABLE:
        try:
            tokenizer = _get_tokenizer()
        except Exception:
            tokenizer = None

    if tokenizer is not None:
        try:
            # tiktoken encoders expose encode method
            if hasattr(tokenizer, "encode"):
                return len(tokenizer.encode(text))
            # some tokenizers use encode_ordinary / encode_single_token
            enc = getattr(tokenizer, "encode", None)
            if enc:
                return len(enc(text))
        except Exception:
            logger.debug("tokenizer.encode failed, falling back to simple tokenize", exc_info=True)

    # fallback heuristic: count words/punctuation as tokens
    return max(1, len(_simple_tokenize(text)))


def _split_on_sentence_boundaries(text: str) -> List[str]:
    # naive sentence splitter, keeps punctuation
    parts = re.split(r'(?<=[\.\?\!])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_text(
    text: str,
    max_tokens: int = 512,
    overlap: int = 64,
    min_tokens: int = 8,
    tokenizer: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Chunk]:
    """
    Chunk `text` into token-bounded pieces.
    - max_tokens: target max tokens per chunk
    - overlap: number of tokens to overlap between consecutive chunks
    - min_tokens: minimum acceptable tokens for a chunk (small tail will be merged)
    - tokenizer: optional tiktoken-like encoding object
    Returns list of Chunk dataclasses preserving provided metadata.
    """
    if not text:
        return []

    tokenizer_obj = tokenizer
    if tokenizer_obj is None and _TIKTOKEN_AVAILABLE:
        try:
            tokenizer_obj = _get_tokenizer()
        except Exception:
            tokenizer_obj = None

    # First try splitting by sentence boundaries to create coherent chunks
    sentences = _split_on_sentence_boundaries(text)
    if not sentences:
        sentences = [text]

    chunks: List[Chunk] = []
    current_tokens = 0
    current_text_parts: List[str] = []
    current_token_counts: List[int] = []

    for sent in sentences:
        tok_count = estimate_tokens(sent, tokenizer=tokenizer_obj)
        # if single sentence exceeds max_tokens, hard-split by words/tokens
        if tok_count >= max_tokens:
            # split the sentence into token-sized windows
            words = sent.split()
            approx_tokens_per_word = 1  # fallback assumption
            # build sliding windows of words to approximate tokens
            i = 0
            n = len(words)
            while i < n:
                window_words = []
                window_tok = 0
                while i < n and window_tok < max_tokens:
                    window_words.append(words[i])
                    window_tok += approx_tokens_per_word
                    i += 1
                window_text = " ".join(window_words)
                window_tok = estimate_tokens(window_text, tokenizer=tokenizer_obj)
                chunk = Chunk(id=str(uuid.uuid4()), text=window_text, tokens=window_tok, metadata=dict(metadata or {}))
                chunks.append(chunk)
            continue

        # normal accumulation
        if current_tokens + tok_count <= max_tokens or not current_text_parts:
            current_text_parts.append(sent)
            current_token_counts.append(tok_count)
            current_tokens += tok_count
        else:
            # flush current chunk
            chunk_text_str = " ".join(current_text_parts).strip()
            chunk = Chunk(id=str(uuid.uuid4()), text=chunk_text_str, tokens=current_tokens, metadata=dict(metadata or {}))
            chunks.append(chunk)

            # prepare new chunk, optionally include overlap from previous chunk
            # build overlap text from tail sentences until overlap token count satisfied
            overlap_text_parts = []
            overlap_tokens = 0
            for prev_sent, prev_tok in zip(reversed(current_text_parts), reversed(current_token_counts)):
                if overlap_tokens >= overlap:
                    break
                overlap_text_parts.insert(0, prev_sent)
                overlap_tokens += prev_tok
            # start next chunk with overlap + current sentence
            current_text_parts = overlap_text_parts + [sent]
            current_token_counts = [estimate_tokens(s, tokenizer=tokenizer_obj) for s in current_text_parts]
            current_tokens = sum(current_token_counts)

    # flush tail
    if current_text_parts:
        tail_text = " ".join(current_text_parts).strip()
        tail_tokens = current_tokens
        # if tail is too small and there is a previous chunk, merge into previous
        if chunks and tail_tokens < min_tokens:
            prev = chunks[-1]
            merged_text = (prev.text + "\n" + tail_text).strip()
            merged_tokens = estimate_tokens(merged_text, tokenizer=tokenizer_obj)
            chunks[-1] = Chunk(id=prev.id, text=merged_text, tokens=merged_tokens, metadata=prev.metadata)
        else:
            chunks.append(Chunk(id=str(uuid.uuid4()), text=tail_text, tokens=tail_tokens, metadata=dict(metadata or {})))

    return chunks


def chunk_documents(
    docs: Iterable[Dict[str, Any]],
    text_key: str = "text",
    metadata_key: str = "metadata",
    **chunk_opts,
) -> List[Dict[str, Any]]:
    """
    Given an iterable of documents (dicts), produce flattened chunk dicts suitable
    for embedding/upsert. Each returned dict contains:
      - id: unique chunk id
      - text: chunk text
      - tokens: estimated token count
      - metadata: merged metadata including source doc id / index / original metadata
    chunk_opts are forwarded to chunk_text (max_tokens, overlap, etc).
    """
    out: List[Dict[str, Any]] = []
    for idx, doc in enumerate(docs):
        src_text = str(doc.get(text_key, "") or "")
        src_meta = dict(doc.get(metadata_key, {}) or {})
        # include source pointers
        src_meta.setdefault("source_index", idx)
        if "id" in doc:
            src_meta.setdefault("source_id", doc.get("id"))
        chunks = chunk_text(src_text, metadata=src_meta, **chunk_opts)
        for c in chunks:
            out.append({"id": c.id, "text": c.text, "tokens": c.tokens, "metadata": c.metadata})
    return out


def merge_small_chunks(chunks: List[Dict[str, Any]], min_tokens: int = 32) -> List[Dict[str, Any]]:
    """
    Merge adjacent small chunks (dict shape with 'text' and 'tokens') until each chunk >= min_tokens.
    Returns new list of chunk dicts. Preserves order.
    """
    if not chunks:
        return []
    merged: List[Dict[str, Any]] = []
    buffer_text = ""
    buffer_tokens = 0
    buffer_meta: Dict[str, Any] = {}

    def _flush():
        nonlocal buffer_text, buffer_tokens, buffer_meta
        if buffer_text:
            merged.append({"id": str(uuid.uuid4()), "text": buffer_text.strip(), "tokens": buffer_tokens, "metadata": dict(buffer_meta or {})})
        buffer_text = ""
        buffer_tokens = 0
        buffer_meta = {}

    for ch in chunks:
        t = ch.get("text", "")
        tok = int(ch.get("tokens", estimate_tokens(t)))
        meta = ch.get("metadata", {}) or {}
        if not buffer_text:
            buffer_text = t
            buffer_tokens = tok
            buffer_meta = dict(meta)
        else:
            # if buffer is already large enough, flush and start new
            if buffer_tokens >= min_tokens:
                _flush()
                buffer_text = t
                buffer_tokens = tok
                buffer_meta = dict(meta)
            else:
                # merge into buffer
                buffer_text = buffer_text + "\n" + t
                buffer_tokens += tok
                # merge metadata shallowly
                buffer_meta.update(meta)
    # flush remainder
    _flush()
    return merged
