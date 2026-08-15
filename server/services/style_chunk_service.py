"""Pure local text chunking for Style Engine analysis."""

import re


def _split_long_paragraph(paragraph, maximum):
    """Split an oversized paragraph at sentence boundaries when possible."""
    sentences = re.split(r"(?<=[。！？!?])", paragraph)
    if len(sentences) == 1:
        return [paragraph[i : i + maximum] for i in range(0, len(paragraph), maximum)]

    chunks, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > maximum:
            chunks.append(current.strip())
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_corpus_text(content, target=420, minimum=200, maximum=900):
    """Group natural paragraphs into the existing 200--900 character chunks."""
    raw_paragraphs = [
        item.strip() for item in re.split(r"\n\s*\n+", content or "") if item.strip()
    ]
    paragraphs = []
    for paragraph in raw_paragraphs:
        if len(paragraph) > maximum:
            paragraphs.extend(_split_long_paragraph(paragraph, maximum))
        else:
            paragraphs.append(paragraph)

    chunks, current, current_length = [], [], 0
    for paragraph in paragraphs:
        next_length = current_length + len(paragraph) + (2 if current else 0)
        if current and next_length > maximum:
            chunks.append("\n\n".join(current))
            current, current_length = [], 0
        current.append(paragraph)
        current_length += len(paragraph) + (2 if len(current) > 1 else 0)
        if current_length >= target:
            chunks.append("\n\n".join(current))
            current, current_length = [], 0
    if current:
        tail = "\n\n".join(current)
        if chunks and len(tail) < minimum and len(chunks[-1]) + len(tail) + 2 <= maximum:
            chunks[-1] += "\n\n" + tail
        else:
            chunks.append(tail)
    return [item for item in chunks if item.strip()]
