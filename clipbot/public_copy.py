"""Keep editorial assessment private at every public-text boundary."""
from __future__ import annotations

import re

from .config import Settings
from .models import Candidate


class UnsafePublicCopy(ValueError):
    """A clip must wait rather than publish internal notes or legacy fallback text."""


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if not key.startswith('_') and key != 'style':
                yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def check_public_text(c: Candidate, value, settings: Settings) -> None:
    """Block diagnostic language and substantial verbatim overlap with private notes.

    The main protection is source separation, not a claim to detect every paraphrase.
    This catches stale/manual text and accidental reintroduction of review fallbacks.
    """
    width = settings.copywriter.private_overlap_words
    # A final reviewer watches the public render and can quote its hook verbatim.
    # Feeding those observations back into this guard would invalidate its own pass.
    private = list(_strings({k: v for k, v in c.verdict.items() if k != 'final_review'})) + [c.visual or '']
    forbidden = set()
    for note in private:
        words = _words(note)
        forbidden.update(tuple(words[i:i + width]) for i in range(len(words) - width + 1))
    # Independently observed source dialogue is public evidence even when a judge
    # happens to quote it too. This exemption never allows diagnostic patterns.
    dialogue = _words(' '.join(w.text for w in c.words) if c.words else re.sub(r'\[[\d.]+-[\d.]+\]', '', c.transcript or ''))
    forbidden.difference_update(tuple(dialogue[i:i + width]) for i in range(len(dialogue) - width + 1))
    for text in _strings(value):
        for pattern in settings.copywriter.private_text_patterns:
            try:
                found = re.search(pattern, text, re.IGNORECASE)
            except re.error as exc:
                raise UnsafePublicCopy('An internal-text protection pattern is invalid.') from exc
            if found:
                raise UnsafePublicCopy('Public copy contains editorial or diagnostic language; rewrite it from the video.')
        words = _words(text)
        if any(tuple(words[i:i + width]) in forbidden for i in range(len(words) - width + 1)):
            raise UnsafePublicCopy('Public copy repeats internal review notes; rewrite it from the video.')


def require_public_copy(c: Candidate, settings: Settings, target: str) -> dict:
    if c.post_copy.get('_source') != 'video':
        raise UnsafePublicCopy('Fresh public copy is required; internal judge captions cannot be used for posting.')
    copy = c.post_copy.get(target)
    if not isinstance(copy, dict):
        raise UnsafePublicCopy(f'Public {target} copy is missing; no review-note fallback is allowed.')
    required = 'title' if target in ('youtube', 'facebook') else 'message' if target == 'discord' else 'caption'
    if not str(copy.get(required, '')).strip():
        raise UnsafePublicCopy(f'Public {target} {required} is empty.')
    check_public_text(c, {target: copy, 'hook': c.post_copy.get('hook', '')}, settings)
    return copy
