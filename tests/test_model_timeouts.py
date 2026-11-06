"""检查底层 SDK 客户端，避免只有 LangChain 字段改变而传输层仍用旧超时。"""
from unittest.mock import patch
import httpx
import pytest
from personal_superagent.models import build_model


@pytest.mark.parametrize('timeout', [30, 120])
def test_constructed_clients_use_actual_timeout(monkeypatch, timeout):
    monkeypatch.setenv('MODEL_API_KEY', 'test-only-not-real')
    monkeypatch.setenv('MODEL_NAME', 'test')
    model = build_model(demo=False, timeout=timeout, max_tokens=4096)
    try:
        assert model.request_timeout == timeout
        assert model.root_client.timeout == timeout
        assert model.root_client._client.timeout.as_dict() == httpx.Timeout(timeout).as_dict()
        assert model.root_async_client.timeout == timeout
        assert model.root_async_client._client.timeout.as_dict() == httpx.Timeout(timeout).as_dict()
        assert model.max_tokens == 4096
        assert model.root_client.max_retries == 0
    finally:
        model.root_client.close()
        import asyncio
        asyncio.run(model.root_async_client.close())


def test_research_initializes_timeout_in_factory():
    # 复用原生委派测试中的录制模型，检查实际研究入口向工厂传递了超时。
    from personal_superagent.modeling.research import run_research
    with patch('personal_superagent.models.build_model', side_effect=RuntimeError('factory reached')) as factory:
        with pytest.raises(RuntimeError, match='factory reached'):
            run_research({'max_calls': 8}, lambda *args: None)
    factory.assert_called_once_with(demo=False, timeout=120, max_tokens=4096)
