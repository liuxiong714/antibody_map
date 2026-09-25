import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json

from conftest import fake_llm_stream as _stream_mock

from app.core.extraction.json_parser import LLMJSONParseError
from app.core.llm_extractor import LLMExtractor


class TestLLMExtractor:
    def test_model_config_resolution(self):
        extractor = LLMExtractor(model="deepseek-chat")
        assert extractor.model == "deepseek-chat"

    @pytest.mark.asyncio
    @patch("app.core.extraction.llm_client.AsyncOpenAI")
    async def test_extract_with_mock_response(self, mock_openai):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _stream_mock(json.dumps({
            "data_points": [{
                "disease_name": "麻疹",
                "province": "广东省",
                "sample_size": 1245,
                "positivity_rate": 87.3,
                "detection_method": "ELISA",
                "antibody_type": "IgG",
            }]
        }))
        mock_openai.return_value = mock_client

        extractor = LLMExtractor(model="deepseek-chat")
        result = await extractor.extract("测试文本", language="zh", title="测试标题")

        assert len(result) == 1
        assert result[0]["disease_name"] == "measles"
        assert result[0]["province"] == "广东"
        assert result[0]["sample_size"] == 1245
        assert result[0]["positivity_rate"] == 87.3

    @pytest.mark.asyncio
    @patch("app.core.extraction.llm_client.AsyncOpenAI")
    async def test_extract_with_invalid_json(self, mock_openai):
        mock_client = AsyncMock()
        usage = MagicMock(prompt_tokens=10, completion_tokens=2, total_tokens=12)
        mock_client.chat.completions.create.return_value = _stream_mock(
            "not valid json", usage=usage
        )
        mock_openai.return_value = mock_client

        extractor = LLMExtractor(model="deepseek-chat")
        with pytest.raises(LLMJSONParseError):
            _ = await extractor.extract("测试文本", language="zh")

    @pytest.mark.asyncio
    @patch("app.core.extraction.llm_client.AsyncOpenAI")
    async def test_extract_with_json_code_block(self, mock_openai):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _stream_mock(
            "```json\n{\"data_points\": [{\"disease_name\": \"麻疹\"}]}\n```"
        )
        mock_openai.return_value = mock_client

        extractor = LLMExtractor(model="deepseek-chat")
        result = await extractor.extract("测试文本", language="zh")

        assert len(result) == 1
        assert result[0]["disease_name"] == "measles"

    @pytest.mark.asyncio
    @patch("app.core.extraction.llm_client.AsyncOpenAI")
    async def test_extract_with_missing_key_fields(self, mock_openai):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _stream_mock(json.dumps({
            "data_points": [{
                "disease_name": "麻疹",
                "province": "广东",
            }]
        }))
        mock_openai.return_value = mock_client

        extractor = LLMExtractor(model="deepseek-chat")
        result = await extractor.extract("测试文本", language="zh")

        assert len(result) == 1
        assert result[0]["positivity_rate"] is None
        assert result[0]["gmc_value"] is None

    def test_has_key_fields_with_positivity_rate(self):
        extractor = LLMExtractor()
        points = [{"positivity_rate": 87.3}]
        assert extractor._has_key_fields(points) is True

    def test_has_key_fields_with_gmc_value(self):
        extractor = LLMExtractor()
        points = [{"gmc_value": 120.5}]
        assert extractor._has_key_fields(points) is True

    def test_has_key_fields_without_key_fields(self):
        extractor = LLMExtractor()
        points = [{"disease_name": "麻疹"}]
        assert extractor._has_key_fields(points) is False

    def test_has_key_fields_empty(self):
        extractor = LLMExtractor()
        assert extractor._has_key_fields([]) is False