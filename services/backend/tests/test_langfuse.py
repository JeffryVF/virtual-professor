"""Tests for Langfuse observability helpers.

Verifies that:
- Disabled mode (LANGFUSE_ENABLE=false) returns None without calling SDK
- Enabled mode creates traces/spans via the Langfuse SDK
- The @asynccontextmanager span pattern handles success and exceptions
"""

from contextlib import asynccontextmanager
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from core.config import Settings as FreshSettings


class TestMainLifespan:
    """Startup/shutdown wiring should work when Langfuse is enabled."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_and_flushes_langfuse(self):
        """GIVEN Langfuse is enabled
        WHEN the FastAPI lifespan runs
        THEN the client is initialized and flushed without raising NameError.
        """
        import main

        mock_conn = MagicMock()
        mock_conn.run_sync = AsyncMock()
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine.begin.return_value = mock_begin()

        with (
            patch("core.config.settings.langfuse_enable", True),
            patch.object(main, "engine", mock_engine),
            patch.object(main.langfuse_service, "init_langfuse") as mock_init,
            patch.object(main.langfuse_service, "flush_langfuse", new=AsyncMock()) as mock_flush,
        ):
            async with main.lifespan(main.app):
                pass

        mock_conn.run_sync.assert_awaited_once()
        mock_init.assert_called_once()
        mock_flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_wires_langfuse_callback_handler(self):
        """GIVEN Langfuse is enabled
        WHEN the FastAPI lifespan runs
        THEN LangfuseCallbackHandler is attached to LlamaIndex callback_manager.
        """
        import main

        mock_conn = MagicMock()
        mock_conn.run_sync = AsyncMock()
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine.begin.return_value = mock_begin()
        mock_handler = MagicMock()
        fake_langfuse_module = ModuleType("langfuse")
        fake_callback_module = ModuleType("langfuse.callback")
        fake_callback_module.LangfuseCallbackHandler = MagicMock(return_value=mock_handler)
        fake_langfuse_module.callback = fake_callback_module
        from llama_index.core import Settings as LlamaSettings

        with (
            patch("core.config.settings.langfuse_enable", True),
            patch.object(main, "engine", mock_engine),
            patch.object(main.langfuse_service, "init_langfuse"),
            patch.object(main.langfuse_service, "flush_langfuse", new=AsyncMock()),
            patch.dict(sys.modules, {"langfuse": fake_langfuse_module, "langfuse.callback": fake_callback_module}),
            patch.object(LlamaSettings.callback_manager, "add_handler") as mock_add_handler,
        ):
            async with main.lifespan(main.app):
                pass

        fake_callback_module.LangfuseCallbackHandler.assert_called_once()
        mock_add_handler.assert_called_once_with(mock_handler)


class TestDisabledMode:
    """All helpers must return None when LANGFUSE_ENABLE is False."""

    @pytest.mark.asyncio
    async def test_get_langfuse_returns_none_when_disabled(self):
        """GIVEN LANGFUSE_ENABLE=false
        WHEN get_langfuse() is called
        THEN it returns None.
        """
        with patch("core.config.settings.langfuse_enable", False):
            import services.langfuse as lf_module

            # Ensure the module doesn't have a client initialized
            lf_module._langfuse = None

            result = lf_module.get_langfuse()
            assert result is None

    @pytest.mark.asyncio
    async def test_create_trace_returns_none_when_disabled(self):
        """GIVEN LANGFUSE_ENABLE=false
        WHEN create_trace() is called
        THEN it returns None.
        """
        with patch("core.config.settings.langfuse_enable", False):
            import services.langfuse as lf_module

            lf_module._langfuse = None

            trace = await lf_module.create_trace("test-trace", {"key": "value"})
            assert trace is None

    @pytest.mark.asyncio
    async def test_create_span_yields_none_when_disabled(self):
        """GIVEN LANGFUSE_ENABLE=false
        WHEN create_span() is used as a context manager
        THEN it yields None.
        """
        with patch("core.config.settings.langfuse_enable", False):
            import services.langfuse as lf_module

            lf_module._langfuse = None

            async with lf_module.create_span(None, "test-span") as span:
                assert span is None

    @pytest.mark.asyncio
    async def test_create_span_yields_none_without_trace(self):
        """GIVEN a trace that is None (disabled)
        WHEN create_span(None, ...) is used
        THEN it yields None regardless of settings.
        """
        with patch("core.config.settings.langfuse_enable", False):
            import services.langfuse as lf_module

            lf_module._langfuse = None

            async with lf_module.create_span(None, "orphan-span") as span:
                assert span is None


class TestConfigurationDefaults:
    """Langfuse settings should resolve predictable defaults without env vars."""

    def test_defaults_without_env_vars(self, monkeypatch):
        """GIVEN no Langfuse env vars
        WHEN Settings initializes
        THEN Langfuse defaults match the documented configuration.
        """
        for env_name in (
            "LANGFUSE_ENABLE",
            "LANGFUSE_SECRET_KEY",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_HOST",
            "LANGFUSE_RELEASE",
        ):
            monkeypatch.delenv(env_name, raising=False)

        fresh_settings = FreshSettings()

        assert fresh_settings.langfuse_enable is False
        assert fresh_settings.langfuse_host == "https://cloud.langfuse.com"
        assert fresh_settings.langfuse_secret_key == ""
        assert fresh_settings.langfuse_public_key == ""
        assert fresh_settings.langfuse_release == "0.1.0"


class TestDeploymentManifest:
    """Docker Compose should declare the Langfuse stack."""

    def test_docker_compose_declares_langfuse_services(self):
        """GIVEN the repository docker-compose.yml
        WHEN inspected
        THEN it declares the Langfuse runtime services.
        """
        compose_file = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        compose_text = compose_file.read_text(encoding="utf-8")

        assert "langfuse:" in compose_text
        assert "langfuse-postgres:" in compose_text
        assert "langfuse-redis:" in compose_text


class TestEnabledMode:
    """Helpers must create real Langfuse SDK objects when enabled."""

    @pytest.mark.asyncio
    async def test_create_trace_creates_langfuse_trace(self):
        """GIVEN LANGFUSE_ENABLE=true and mocked Langfuse client
        WHEN create_trace() is called
        THEN it creates a trace via the Langfuse client.
        """
        mock_trace = MagicMock()
        mock_trace.id = "trace-1"
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace

        with (
            patch("core.config.settings.langfuse_enable", True),
            patch("services.langfuse._langfuse", mock_client),
        ):
            import services.langfuse as lf_module

            lf_module._langfuse = mock_client

            trace = await lf_module.create_trace("speak", {"session_id": "sess-1"})
            assert trace is mock_trace
            mock_client.trace.assert_called_once_with(
                name="speak",
                metadata={"session_id": "sess-1"},
            )

    @pytest.mark.asyncio
    async def test_create_span_yields_span_and_ends_on_success(self):
        """GIVEN a mock trace
        WHEN create_span() context manager exits normally
        THEN the span is yielded and .end() is called on exit.
        """
        mock_span = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.return_value = mock_span

        import services.langfuse as lf_module

        async with lf_module.create_span(mock_trace, "test-step") as span:
            assert span is mock_span
            mock_trace.span.assert_called_once_with(name="test-step")

        mock_span.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_span_ends_on_exception(self):
        """GIVEN a mock trace
        WHEN the context manager body raises an exception
        THEN span.end() is called and the exception propagates.
        """
        mock_span = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.return_value = mock_span

        import services.langfuse as lf_module

        with pytest.raises(ValueError, match="test error"):
            async with lf_module.create_span(mock_trace, "failing-step") as span:
                assert span is mock_span
                raise ValueError("test error")

        mock_span.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_trace_with_metadata(self):
        """GIVEN LANGFUSE_ENABLE=true
        WHEN create_trace is called with metadata
        THEN the trace includes professor_id, professor_name, etc.
        """
        mock_trace = MagicMock()
        mock_trace.id = "trace-2"
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace

        with (
            patch("core.config.settings.langfuse_enable", True),
            patch("services.langfuse._langfuse", mock_client),
        ):
            import services.langfuse as lf_module

            lf_module._langfuse = mock_client

            meta = {
                "professor_id": "prof-1",
                "professor_name": "Dr. Smith",
                "session_id": "sess-42",
                "student_id": "stud-7",
            }
            trace = await lf_module.create_trace("speak", meta)
            assert trace is mock_trace
            mock_client.trace.assert_called_once_with(name="speak", metadata=meta)
