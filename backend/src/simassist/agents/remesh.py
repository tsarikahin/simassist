"""Recognize self-contained mesh commands without inferring authorization."""

import re

from .context import RoutingContext
from .router import NUMBER, recent_mesh_intent


def explicit_mesh_request(message: str, context: RoutingContext) -> dict | None:
    """Accept only complete commands or chat-local parameter replies.

    Questions, negation, conditions, confirmations and compound requests remain
    with the agent. Missing bounds remain missing for backend clarification.
    """
    text = message.strip().lower().rstrip(".! ")
    if re.fullmatch(r"(?:please )?make it (?:finer|coarser)", text):
        return {}
    command = re.fullmatch(
        r"(?:please )?(?:remesh|mesh)(?: (?:it|the (?:active|selected|current) geometry))?"
        r"(?: (?:using|with))? (?P<sizes>.+)",
        text,
    )
    if command:
        text = command["sizes"]
    elif "stale_proposal" in context.issues or not (
        context.pending_remesh or recent_mesh_intent(context)
    ):
        return None
    text = re.sub(r"^(?:use|using)\s+", "", text)
    unit = r"(?P<{}>mm|cm|m|in)?"
    bounds = re.fullmatch(
        rf"min(?:imum|_size)?\s*[=:]?\s*(?P<min>{NUMBER})\s*{unit.format('min_unit')}"
        rf"\s*(?:,|and)?\s*max(?:imum|_size)?\s*[=:]?\s*(?P<max>{NUMBER})"
        rf"\s*{unit.format('max_unit')}",
        text,
    )
    if bounds is None:
        bounds = re.fullmatch(
            rf"(?P<min>{NUMBER})\s*{unit.format('min_unit')}\s*[-–—]\s*"
            rf"(?P<max>{NUMBER})\s*{unit.format('max_unit')}",
            text,
        )
    if bounds is None:
        return None
    return {
        "min_size": float(bounds["min"]),
        "max_size": float(bounds["max"]),
        "min_unit": bounds["min_unit"] or bounds["max_unit"],
        "max_unit": bounds["max_unit"] or bounds["min_unit"],
    }
