"""Encrypted, advisor-owned AI chat history."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from folioman_app.models.base import TimeStampedModel
from folioman_app.security.chat import decrypt_chat_text, encrypt_chat_text


class AgentChatSession(TimeStampedModel):
    owned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_chat_sessions",
    )
    investor = models.ForeignKey(
        "Investor",
        on_delete=models.CASCADE,
        related_name="agent_chat_sessions",
    )
    title_encrypted = models.BinaryField()

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [models.Index(fields=("owned_by", "investor", "-updated_at"))]

    def set_title(self, title: str) -> None:
        self.title_encrypted = encrypt_chat_text(title)

    def get_title(self) -> str:
        return decrypt_chat_text(self.title_encrypted)


class AgentChatMessage(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    session = models.ForeignKey(
        AgentChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content_encrypted = models.BinaryField()
    provider = models.CharField(max_length=16, default="local")
    model = models.CharField(max_length=255, blank=True)
    data_as_of = models.DateField(null=True, blank=True)
    pii_redactions = models.PositiveIntegerField(default=0)
    external_transmission = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("session", "created_at"))]

    def set_content(self, content: str) -> None:
        self.content_encrypted = encrypt_chat_text(content)

    def get_content(self) -> str:
        return decrypt_chat_text(self.content_encrypted)
