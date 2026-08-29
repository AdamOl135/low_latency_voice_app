"""Pytest Configuration and Shared Fixtures for Low-Latency Voice App E2E Tests."""

import asyncio
import os
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Callable, List
from test.test_harness.mock_server import MockServer
from test.test_harness.synthetic_client import SyntheticClient


@pytest.fixture(scope="session")
def event_loop():
    """Create session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_server() -> AsyncGenerator[MockServer, None]:
    """Start an isolated mock backend server on dynamic ports."""
    server = MockServer(host="127.0.0.1", ws_port=0, udp_port=0)
    await server.start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def client_factory(mock_server: MockServer) -> AsyncGenerator[Callable[..., SyntheticClient], None]:
    """Factory fixture to spawn and connect SyntheticClients."""
    created_clients: List[SyntheticClient] = []

    async def _make_client(
        username: str = "TestUser",
        password: str = "pass123",
        token: str = None,
    ) -> SyntheticClient:
        ws_url = os.getenv("VOICE_WS_URL", f"ws://127.0.0.1:{mock_server.actual_ws_port}/ws")
        udp_port = int(os.getenv("VOICE_UDP_PORT", str(mock_server.actual_udp_port)))
        udp_host = os.getenv("VOICE_UDP_HOST", "127.0.0.1")

        client = SyntheticClient(
            username=username,
            password=password,
            token=token,
            ws_url=ws_url,
            udp_host=udp_host,
            udp_port=udp_port,
        )
        await client.connect()
        created_clients.append(client)
        return client

    yield _make_client

    # Teardown all created clients
    for c in created_clients:
        try:
            await c.disconnect()
        except Exception:
            pass
