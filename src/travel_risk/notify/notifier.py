"""Delivery. Only this module sends anything, and only for approved reviews or digests.

Channels: email (Amazon SES), Slack incoming webhook (per organisation), and a log channel for
local runs without SES. Logs carry ids only, never names, addresses or message text.
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
    email_to: str | None = None
    subject: str = "Travel advisory update for your trip"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    error: str | None = None


class Notifier(Protocol):
    def deliver(self, d: Delivery) -> DeliveryResult: ...


class DefaultNotifier:
    def __init__(self, http: httpx.Client | None = None, ses=None) -> None:
        self.http = http or httpx.Client(timeout=10)
        self._ses = ses

    @property
    def ses(self):
        if self._ses is None:
            import boto3

            from travel_risk.config import get_settings

            self._ses = boto3.client("sesv2", region_name=get_settings().aws_region)
        return self._ses

    def deliver(self, d: Delivery) -> DeliveryResult:
        if d.channel == "email":
            return self._email(d)
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


    def _email(self, d: Delivery) -> DeliveryResult:
        from travel_risk.config import get_settings

        sender = get_settings().ses_from_email
        if not (sender and d.email_to):
            return DeliveryResult(False, "email not configured (TRA_SES_FROM_EMAIL / recipient)")
        try:
            self.ses.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [d.email_to]},
                Content={"Simple": {
                    "Subject": {"Data": d.subject},
                    "Body": {"Text": {"Data": d.message}},
                }},
            )
        except Exception as exc:  # botocore raises many types; record the class, not the text
            return DeliveryResult(False, f"ses: {exc.__class__.__name__}")
        return DeliveryResult(True)


def channel_for(notify_channel: str, slack_webhook_url: str | None) -> str:
    if notify_channel == "slack" and slack_webhook_url:
        return "slack"
    from travel_risk.config import get_settings

    if notify_channel == "email" and get_settings().ses_from_email:
        return "email"
    return "log"  # local runs without SES
