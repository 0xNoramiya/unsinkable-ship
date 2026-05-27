"""McpBackend constructors and kind dispatch."""

from unsinkable.mcp import McpBackend


def test_stdio_factory():
    b = McpBackend.stdio("primary", "python", ["server.py"], env={"K": "v"})
    assert b.kind == "stdio"
    assert b.command == "python"
    assert b.args == ["server.py"]
    assert b.env == {"K": "v"}
    assert b.url == ""


def test_http_factory():
    b = McpBackend.http(
        "tf-virtual",
        "https://llm-gateway.truefoundry.com/mcp-server/grp/v1/server",
        headers={"Authorization": "Bearer tfy_xxx"},
    )
    assert b.kind == "http"
    assert b.url.startswith("https://llm-gateway.truefoundry.com/")
    assert b.headers == {"Authorization": "Bearer tfy_xxx"}
    assert b.command == ""


def test_default_kind_is_stdio():
    b = McpBackend(name="x", command="echo")
    assert b.kind == "stdio"


def test_explicit_http_kind_without_factory():
    b = McpBackend(name="x", kind="http", url="https://example/server")
    assert b.kind == "http"
