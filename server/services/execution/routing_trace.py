"""Routing-only structured events; no full instructions or agent histories."""
from contextvars import ContextVar
import json
import logging

turn_id = ContextVar("routing_turn_id", default=None)


def emit(event, **fields):
    logging.getLogger("openpoke.server").info(
        "routing %s", json.dumps({"event": event, "turn_id": turn_id.get(), **fields}, ensure_ascii=False)
    )
