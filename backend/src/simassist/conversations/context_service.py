"""Reconstruct role-aware MAF 1.26 Message inputs from durable chat state."""

import json
import logging
from dataclasses import dataclass

from agent_framework import Message

from .budget import ContextBudget, estimate
from .summary import PREFIX, summarize

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    messages: list[Message]
    tokens: int
    turns: int
    watermark: int
    summary_status: str


def complete_turns(messages):
    turns = []
    pending = []
    for message in messages:
        if message["role"] == "user":
            pending = [message]
        elif message["role"] == "assistant" and pending:
            pending.append(message)
            turns.append(pending)
            pending = []
    return turns


class ConversationContextService:
    def __init__(self, store, budget=None):
        self.store = store
        self.budget = budget or ContextBudget.from_env()

    def build(self, project_id, chat_id, current, instructions, schemas):
        budget = self.budget
        base = (
            estimate(instructions) + estimate(json.dumps(schemas)) + estimate(current)
        )
        if base > budget.available:
            raise ValueError(
                "Request and tool definitions exceed the safe context window. "
                "Shorten the request or increase SIMASSIST_CONTEXT_WINDOW_TOKENS "
                "to match your loaded model."
            )
        summary = self.store.summary(project_id, chat_id) if chat_id else None
        watermark = summary["watermark"] if summary else 0
        turns = (
            complete_turns(self.store.context_messages(project_id, chat_id))
            if chat_id
            else []
        )
        turns = [t for t in turns if t[-1]["id"] > watermark]
        text = PREFIX + summary["content"] if summary else ""
        # Reserve summary space only when it fits alongside the current request.
        summary_limit = min(budget.summary, max(0, budget.available - base))

        if text and estimate(text) > summary_limit:
            text = ""
        summary_cost = estimate(text) if text else 0
        pressure = (
            base + summary_cost + sum(estimate(m["content"]) for t in turns for m in t)
            > budget.available
        )
        reserve = summary_limit if budget.auto_summary and pressure else summary_cost
        used = base + summary_cost
        recent = []
        for turn in reversed(turns):
            cost = sum(estimate(m["content"]) for m in turn)
            if used + cost > budget.available - (reserve - summary_cost):
                break
            recent.insert(0, turn)
            used += cost
        dropped = turns[: len(turns) - len(recent)]
        status = "skipped"
        if dropped and budget.auto_summary and summary_limit >= estimate(PREFIX + "[]"):
            try:
                content = summarize(
                    summary["content"] if summary else None,
                    [m for t in dropped for m in t],
                    summary_limit,
                )
                new_watermark = dropped[-1][-1]["id"]
                self.store.save_summary(project_id, chat_id, new_watermark, content)
                watermark = new_watermark
                used -= estimate(text) if text else 0
                text = PREFIX + content
                used += estimate(text)
                status = "updated"
            except Exception:  # noqa: BLE001 - optional memory must never fail a valid turn
                status = "failed"
                logger.warning(
                    "Conversation summary failed; using bounded recent history"
                )
        messages = [Message("user", [text])] if text else []
        messages.extend(Message(m["role"], [m["content"]]) for t in recent for m in t)
        messages.append(Message("user", [current]))
        return ConversationContext(messages, used, len(recent), watermark, status)
