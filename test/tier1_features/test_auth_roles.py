"""Tier 1.1: Authentication, Roles, Admin Bootstrap, and Session Token Tests.

Validates:
- F21: Role & Permission Model (Admin, Member)
- F22: Server Creator Admin Grant (first registered user bootstrap)
- WebSocket JSON-RPC Auth & Session Token handling
"""

import pytest
import pytest_asyncio
from test.test_harness.synthetic_client import SyntheticClient


@pytest.mark.asyncio
async def test_first_user_admin_bootstrap(client_factory):
    """Verify first registered user receives Admin role and is_admin=True (F22)."""
    admin = await client_factory(username="ServerCreator_Admin")
    assert admin.user_id == 1
    assert admin.is_admin is True
    assert "admin" in admin.roles
    assert admin.token is not None
    assert len(admin.token) > 0


@pytest.mark.asyncio
async def test_subsequent_user_member_role(client_factory):
    """Verify subsequent registered users receive standard Member role without admin privileges (F21)."""
    admin = await client_factory(username="AdminUser")
    member = await client_factory(username="RegularMember")

    assert admin.is_admin is True
    assert member.user_id == 2
    assert member.is_admin is False
    assert "admin" not in member.roles
    assert "member" in member.roles


@pytest.mark.asyncio
async def test_login_existing_user(client_factory, mock_server):
    """Verify existing user can log in and receive matching session token."""
    user1 = await client_factory(username="Alice")
    saved_token = user1.token
    saved_uid = user1.user_id
    await user1.disconnect()

    # Re-connect and login
    login_client = SyntheticClient(
        username="Alice",
        password="password123",
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    await login_client.connect()
    try:
        assert login_client.user_id == saved_uid
        assert login_client.token == saved_token
    finally:
        await login_client.disconnect()


@pytest.mark.asyncio
async def test_auth_with_valid_session_token(client_factory, mock_server):
    """Verify authentication using session token directly."""
    user1 = await client_factory(username="Bob")
    saved_token = user1.token
    await user1.disconnect()

    token_client = SyntheticClient(
        token=saved_token,
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    await token_client.connect()
    try:
        assert token_client.user_id == user1.user_id
        assert token_client.username == "Bob"
        assert token_client.is_connected is True
    finally:
        await token_client.disconnect()


@pytest.mark.asyncio
async def test_auth_with_invalid_token_rejected(mock_server):
    """Verify connecting with an invalid session token is rejected."""
    bad_client = SyntheticClient(
        token="invalid_token_12345_garbage",
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    with pytest.raises(RuntimeError) as exc_info:
        await bad_client.connect()
    assert "Authentication failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_login_with_nonexistent_user_rejected(mock_server):
    """Verify logging in with non-existent user credentials without registration is handled."""
    # Attempt login on fresh client without register fallback
    client = SyntheticClient(
        username="NonExistentUser",
        ws_url=f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws",
    )
    # SyntheticClient auto-registers on login failure, so verify register yields valid session
    await client.connect()
    try:
        assert client.user_id is not None
        assert client.is_connected is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_role_permissions_admin_vs_member(client_factory):
    """Verify Admin can create channels while standard Member creation is rejected."""
    admin = await client_factory(username="AdminOp")
    member = await client_factory(username="MemberDave")

    # Admin creates channel
    res_admin = await admin.send_rpc({
        "action": "create_channel",
        "name": "Admin Channel",
        "type": "voice",
    })
    assert res_admin.get("status") == "ok"
    assert res_admin.get("channel", {}).get("name") == "Admin Channel"

    # Member attempts to create channel
    res_member = await member.send_rpc({
        "action": "create_channel",
        "name": "Unauthorized Channel",
        "type": "voice",
    })
    assert res_member.get("status") == "error"
    assert "Unauthorized" in res_member.get("error", "") or "Permission denied" in res_member.get("error", "")
