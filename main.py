"""Conditional quote reply.

A reply gets a ``Reply`` component attached only when the message being
answered is no longer the newest message in the chat: either newer
messages arrived while the bot was thinking, or the answer took longer
than the configured threshold.
"""

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Reply
from astrbot.api.star import Context, Star, register


@register(
    "astrbot_plugin_smart_quote",
    "dsh",
    "只在被回复的消息已经不是最新一条时，才给回复补上引用；最新一条不加引用。",
    "0.1.1",
)
class SmartQuote(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.conf = config or {}
        self._last_seen: dict[str, float] = {}

    def _opt(self, key, default):
        try:
            value = self.conf.get(key, default)
        except Exception:
            return default
        return default if value is None else value

    def _remember(self, event: AstrMessageEvent) -> None:
        try:
            self._last_seen[event.unified_msg_origin] = time.time()
            if len(self._last_seen) > 2000:
                cutoff = time.time() - 3600
                self._last_seen = {
                    k: v for k, v in self._last_seen.items() if v >= cutoff
                }
        except Exception:
            pass

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=200)
    async def remember_group(self, event: AstrMessageEvent):
        self._remember(event)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=200)
    async def remember_private(self, event: AstrMessageEvent):
        self._remember(event)

    @filter.on_decorating_result()
    async def quote_when_stale(self, event: AstrMessageEvent):
        if not bool(self._opt("enable", True)):
            return
        if bool(self._opt("group_only", True)) and event.is_private_chat():
            return

        result = event.get_result()
        chain = getattr(result, "chain", None)
        if not result or not chain:
            return
        if any(isinstance(comp, Reply) for comp in chain):
            return

        message_obj = getattr(event, "message_obj", None)
        message_id = getattr(message_obj, "message_id", None)
        if not message_id:
            return

        try:
            arrived = float(getattr(message_obj, "timestamp", 0) or 0)
        except (TypeError, ValueError):
            arrived = 0.0

        now = time.time()
        last = self._last_seen.get(event.unified_msg_origin, 0.0)
        newer_seen = bool(arrived) and last > arrived + 1.0
        waited = (now - arrived) if arrived else 0.0
        threshold = float(self._opt("quote_after_seconds", 6))

        if newer_seen or waited >= threshold:
            chain.insert(0, Reply(id=str(message_id)))
            logger.debug(
                "[smart_quote] quoted %s (newer_seen=%s, waited=%.1fs)",
                message_id,
                newer_seen,
                waited,
            )
