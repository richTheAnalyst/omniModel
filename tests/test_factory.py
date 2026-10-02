"""Tests for the extraction backend factory."""

import pytest

from omnimodel.config import Config
from omnimodel.extraction.factory import (
    available_backends,
    extract_signals,
    get_extractor,
)


class TestBackendResolution:
    def test_ollama_default(self):
        config = Config(
            openrouter_api_key="",
            anthropic_api_key="",
            extraction_backend="ollama",
        )
        # Patch the module-level config temporarily
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert get_extractor().__module__ == "omnimodel.extraction.ollama_extractor"
        finally:
            factory_mod.config = original

    def test_openrouter_default(self):
        config = Config(
            openrouter_api_key="sk-test",
            anthropic_api_key="",
            extraction_backend="openrouter",
        )
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert get_extractor().__module__ == "omnimodel.extraction.openrouter_extractor"
        finally:
            factory_mod.config = original

    def test_claude_default(self):
        config = Config(
            openrouter_api_key="",
            anthropic_api_key="sk-ant-test",
            extraction_backend="claude",
        )
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert get_extractor().__module__ == "omnimodel.extraction.claude_extractor"
        finally:
            factory_mod.config = original

    def test_explicit_backend_override(self):
        config = Config(
            openrouter_api_key="",
            anthropic_api_key="",
            extraction_backend="ollama",
        )
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert get_extractor("openrouter").__module__ == "omnimodel.extraction.openrouter_extractor"
            assert get_extractor("claude").__module__ == "omnimodel.extraction.claude_extractor"
        finally:
            factory_mod.config = original

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError):
            get_extractor("nonexistent")

    def test_available_backends_no_keys(self):
        config = Config(
            openrouter_api_key="",
            anthropic_api_key="",
            extraction_backend="ollama",
        )
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert available_backends() == ["ollama"]
        finally:
            factory_mod.config = original

    def test_available_backends_with_keys(self):
        config = Config(
            openrouter_api_key="sk-test",
            anthropic_api_key="sk-ant-test",
            extraction_backend="ollama",
        )
        import omnimodel.extraction.factory as factory_mod

        original = factory_mod.config
        factory_mod.config = config
        try:
            assert available_backends() == ["ollama", "openrouter", "claude"]
        finally:
            factory_mod.config = original