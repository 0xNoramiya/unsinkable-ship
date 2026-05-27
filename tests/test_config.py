from unsinkable.config import Settings


def _make(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_settings_derives_gateway_base_url():
    s = _make(tfy_api_key="fake", tfy_host="https://demo.truefoundry.cloud")
    assert s.gateway_base_url == "https://demo.truefoundry.cloud/api/llm"
    assert s.openai_base_url == "https://demo.truefoundry.cloud/api/llm/openai/v1"


def test_settings_respects_explicit_base_url():
    s = _make(
        tfy_api_key="fake",
        tfy_host="https://demo.truefoundry.cloud",
        tfy_gateway_base_url="https://custom.example.com/llm",
    )
    assert s.gateway_base_url == "https://custom.example.com/llm"
    assert s.openai_base_url == "https://custom.example.com/llm/openai/v1"
