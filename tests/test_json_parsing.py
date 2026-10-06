"""Tests for JSON parsing helpers (tolerates markdown fences)."""

import pytest

from omnimodel.extraction._utils import parse_json


class TestParseJson:
    @pytest.mark.parametrize("parser", [parse_json])
    def test_plain_json(self, parser):
        result = parser('{"company_name": "Acme"}')
        assert result == {"company_name": "Acme"}

    @pytest.mark.parametrize("parser", [parse_json])
    def test_markdown_fenced(self, parser):
        raw = '```json\n{"company_name": "Acme"}\n```'
        result = parser(raw)
        assert result == {"company_name": "Acme"}

    @pytest.mark.parametrize("parser", [parse_json])
    def test_markdown_fenced_no_lang(self, parser):
        raw = '```\n{"company_name": "Acme"}\n```'
        result = parser(raw)
        assert result == {"company_name": "Acme"}

    @pytest.mark.parametrize("parser", [parse_json])
    def test_invalid_json_returns_raw(self, parser):
        result = parser("not json at all")
        assert "_raw" in result
        assert result["_raw"] == "not json at all"

    @pytest.mark.parametrize("parser", [parse_json])
    def test_empty_string(self, parser):
        result = parser("")
        assert "_raw" in result

    @pytest.mark.parametrize("parser", [parse_json])
    def test_nested_json(self, parser):
        raw = '{"pricing": [{"plan": "Pro", "price": 49}]}'
        result = parser(raw)
        assert result["pricing"][0]["plan"] == "Pro"
