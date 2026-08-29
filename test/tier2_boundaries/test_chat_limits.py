"""Tier 2.3: Chat Message Boundary Limits, Encoding, and Escaping Tests.

Validates:
- F04: Rich Text Input boundary conditions (4000-char max length)
- UTF-8 multi-byte encoding (emojis, CJK, RTL)
- Adversarial escaping (HTML script tags, SQL injection payloads)
"""

import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_maximum_chat_length_4000_chars(client_factory):
    """Verify exactly 4000 characters (maximum allowed message size) sends and arrives intact (F04)."""
    alice = await client_factory(username="AliceMaxChat")
    bob = await client_factory(username="BobMaxChat")

    max_payload = "A" * 4000
    res = await alice.send_chat_message(channel_id=201, content=max_payload)
    assert res.get("status") == "ok"

    evt = await bob.wait_for_event(
        "chat_message",
        lambda e: len(e.get("content", "")) == 4000,
        timeout=3.0,
    )
    assert len(evt.get("content")) == 4000
    assert evt.get("content") == max_payload


@pytest.mark.asyncio
async def test_oversized_chat_length_rejected(client_factory):
    """Verify messages exceeding 4000 characters (e.g. 4001 chars) are rejected."""
    alice = await client_factory(username="AliceOverflow")
    overflow_payload = "B" * 4001
    res = await alice.send_chat_message(channel_id=201, content=overflow_payload)
    assert res.get("status") == "error"
    assert "exceeds" in res.get("error", "").lower() or "limit" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_unicode_and_emoji_rich_text(client_factory):
    """Verify multi-byte UTF-8 emojis and complex international characters preserve fidelity."""
    alice = await client_factory(username="AliceUnicode")
    bob = await client_factory(username="BobUnicode")

    special_text = "🚀 Ultra-Low Latency Voice 🎧 | 🎮 48kHz Opus | 日本語テスト | العربية | 🔊 0.2ms SFU"
    await alice.send_chat_message(channel_id=201, content=special_text)

    evt = await bob.wait_for_event(
        "chat_message",
        lambda e: e.get("content") == special_text,
        timeout=3.0,
    )
    assert evt.get("content") == special_text


@pytest.mark.asyncio
async def test_adversarial_injection_payloads_preserved(client_factory):
    """Verify adversarial script and SQL injection strings are stored and delivered safely without execution."""
    alice = await client_factory(username="AliceSecurity")
    bob = await client_factory(username="BobSecurity")

    injections = [
        "<script>alert('xss')</script>",
        "'; DROP TABLE messages; --",
        "{{7*7}} ${999}",
        "SELECT * FROM users WHERE '1'='1'",
    ]

    for payload in injections:
        await alice.send_chat_message(channel_id=201, content=payload)
        evt = await bob.wait_for_event(
            "chat_message",
            lambda e: e.get("content") == payload,
            timeout=3.0,
        )
        assert evt.get("content") == payload
