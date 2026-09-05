"""Deterministic replies for turns that carry no new request."""

import re
import unicodedata
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

_CLOSURE = re.compile(
    r"(?:(?:ah+|oh|yeah|yep|right) )?"
    r"(?:ok(?:ay)?|alright|all right|sure|got it|i (?:see|understand)|understood|"
    r"(?:(?:that|this) )?makes sense|fair enough)"
    r"(?: (?:now|then))?"
)
_APPROVAL = re.compile(
    r"(?:very )?(?:nice|cool|great|awesome|good|perfect|lovely|neat)"
    r"(?: (?:thanks|thank you))?"
)
_GRATITUDE = re.compile(
    r"(?:thanks|thank you)"
    r"(?: (?:kitty|that helps|this helps|that is helpful|this is helpful|"
    r"that was helpful|this was helpful))?"
)

_REPLIES = {
    "closure": ("mhm.", "yeah.", "all right."),
    "approval": ("glad you think so.", "good.", "nice."),
    "gratitude": ("you're welcome.", "any time.", "of course."),
}

EVENT_MARKER = "acknowledgement"


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w\s']+", " ", text).split())


def _kind(text: str) -> str | None:
    if "?" in text:
        return None
    normalised = _normalise(text)
    if _GRATITUDE.fullmatch(normalised):
        return "gratitude"
    if _APPROVAL.fullmatch(normalised):
        return "approval"
    if _CLOSURE.fullmatch(normalised):
        return "closure"
    return None


def acknowledgement_reply(messages: Sequence[BaseMessage]) -> str | None:
    """Return a vetted closer only when the latest turn is purely social."""
    if not messages or not isinstance(messages[-1], HumanMessage):
        return None
    if not (kind := _kind(str(messages[-1].text))):
        return None

    recent = {
        _normalise(str(message.text))
        for message in messages[-12:]
        if isinstance(message, AIMessage)
    }
    replies = _REPLIES[kind]
    return next((reply for reply in replies if _normalise(reply) not in recent), replies[0])
