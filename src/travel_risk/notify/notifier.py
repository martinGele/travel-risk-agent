"""Delivery. Only this module sends anything, and only for approved reviews or digests.

Channels: Slack incoming webhook (per organisation) and a log channel for local runs.
Email via Amazon SES arrives in week 5. Logs carry ids only, never names or message text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Delivery:
    notification_id: int
    channel: str
    message: str
    slack_webhook_url: str | None = None
    slack_user_id: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    error: str | None = None


class Notifier(Protocol):
    def deliver(self, d: Delivery) -> DeliveryResult: ...


class DefaultNotifier:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=10)

    def deliver(self, d: Delivery) -> DeliveryResult:
        if d.channel == "slack":
            if not d.slack_webhook_url:
                return DeliveryResult(False, "organisation has no Slack webhook configured")
            text = f"<@{d.slack_user_id}>\n{d.message}" if d.slack_user_id else d.message
            try:
                resp = self.http.post(d.slack_webhook_url, json={"text": text})
            except httpx.HTTPError as exc:
                return DeliveryResult(False, f"slack: {exc.__class__.__name__}")
            if resp.status_code != 200:
                return DeliveryResult(False, f"slack: HTTP {resp.status_code}")
            return DeliveryResult(True)
        if d.channel == "log":
            log.info("notification %s delivered to log channel", d.notification_id)
            return DeliveryResult(True)
        return DeliveryResult(False, f"channel {d.channel!r} not implemented yet")


def channel_for(notify_channel: str, slack_webhook_url: str | None) -> str:
    if notify_channel == "slack" and slack_webhook_url:
        return "slack"
    # Email lands in week 5; until then email organisations use the log channel.
    return "log"
