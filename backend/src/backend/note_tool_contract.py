"""Disambiguate declining a new note from requesting deletion."""
import re


def declined_new_note(text: str) -> bool:
    text = text.casefold().replace('’', "'")
    decline = re.search(
        r"\b(?:no need(?: for| to create| to make)?|don'?t(?: want| create| make)?|do not(?: want| create| make)?|avoid)\s+(?:a\s+)?(?:new|another|separate)\s+note\b",
        text,
    )
    explicit_delete = re.search(r'\b(?:delete|trash|remove|discard|erase)\b|\bget rid of\b', text)
    negated_delete = re.search(r"\b(?:don't|do not|never|not to|no need to)\s+(?:delete|trash|remove|discard|erase)\b", text)
    return bool(decline and (not explicit_delete or negated_delete))
