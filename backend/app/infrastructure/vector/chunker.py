from __future__ import annotations
import logging
import uuid

logger = logging.getLogger(__name__)
from . import embedding_encoder

def _fallback_chunk_offsets(text: str, tokenizer, model_limit: int) -> list[tuple[int, int]]:
    """Support slow tokenizers using exact token counts, never a character guess."""
    def count(start: int, end: int) -> int:
        return len(tokenizer(
            embedding_encoder._embedding_input(text[start:end], "passage"),
            add_special_tokens=True, truncation=False,
        )["input_ids"])

    offsets: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        while start < length and text[start].isspace():
            start += 1
        if start >= length:
            break
        low, high = start + 1, min(start + model_limit * 8, length)
        if count(start, low) > model_limit:
            raise embedding_encoder.EmbeddingUnavailableError("One memory character exceeds the embedding token budget")
        while low < high:
            middle = (low + high + 1) // 2
            if count(start, middle) <= model_limit:
                low = middle
            else:
                high = middle - 1
        end = low
        offsets.append((start, end))
        if end >= length:
            break
        start = max(end - min(64, (end - start) // 4), start + 1)
    return offsets

def _memory_chunk_offsets(text: str, *, max_tokens: int = 440, overlap_tokens: int = 64) -> list[tuple[int, int]]:
    """Initialize first, then chunk against the configured model's real window."""
    active_encoder = embedding_encoder._get_encoder()
    tokenizer = getattr(active_encoder, "tokenizer", None)
    if tokenizer is None:
        raise embedding_encoder.EmbeddingUnavailableError("Embedding model has no tokenizer for bounded memory chunking")
    model_limit = getattr(active_encoder, "max_seq_length", 512)
    if not isinstance(model_limit, int):
        model_limit = 512
    if model_limit <= 16:
        raise embedding_encoder.EmbeddingUnavailableError("Embedding model token window is too small for passage input")
    max_tokens = min(max(int(max_tokens), 1), model_limit - 16)
    overlap_tokens = min(max(int(overlap_tokens), 0), max_tokens // 4)
    try:
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        token_offsets = [
            (int(start), int(end))
            for start, end in encoded.get("offset_mapping", [])
            if int(end) > int(start)
        ]
    except Exception:
        logger.info("Tokenizer offsets unavailable; using exact token-count chunking")
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    if not token_offsets:
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    chunks: list[tuple[int, int]] = []
    token_start = 0
    while token_start < len(token_offsets):
        token_end = min(token_start + max_tokens, len(token_offsets))
        chunks.append((token_offsets[token_start][0], token_offsets[token_end - 1][1]))
        if token_end >= len(token_offsets):
            break
        token_start = max(token_end - overlap_tokens, token_start + 1)
    chunks[0] = (0, chunks[0][1])
    chunks[-1] = (chunks[-1][0], len(text))
    # Tokenization at a new chunk boundary can differ from the full-document
    # tokenization. Check the actual passage prefix and special tokens too.
    if any(
        len(tokenizer(
            embedding_encoder._embedding_input(text[start:end], "passage"),
            add_special_tokens=True, truncation=False,
        )["input_ids"]) > model_limit
        for start, end in chunks
    ):
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    return chunks

def _chunk_point_id(event_id: str, chunk_index: int) -> str:
    if chunk_index == 0:
        return event_id
    try:
        namespace = uuid.UUID(event_id)
    except (ValueError, TypeError, AttributeError):
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, event_id)
    return str(uuid.uuid5(namespace, f"chunk:{chunk_index}"))
