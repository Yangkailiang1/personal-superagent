import pytest

from personal_superagent.client.config import validate_url
from personal_superagent.client.files import describe_root, execute
from personal_superagent.client.ledger import Ledger


@pytest.fixture
def root(tmp_path):
    return {
        **describe_root(str(tmp_path)),
        "tools": ["list_files", "read_text", "write_text"],
    }


def test_real_read_write_and_no_overwrite(root):
    assert execute(root, "write_text", {"path": "hello.md", "content": "# 你好"})[
        "created"
    ]
    assert execute(root, "read_text", {"path": "hello.md"})["text"] == "# 你好"
    with pytest.raises(FileExistsError):
        execute(root, "write_text", {"path": "hello.md", "content": "overwrite"})
    assert execute(root, "read_text", {"path": "hello.md"})["text"] == "# 你好"


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", "sub/../../file", "..\\secret", "a\x00b"]
)
def test_traversal_rejected(root, path):
    with pytest.raises(ValueError):
        execute(root, "read_text", {"path": path})


def test_symlink_and_root_replacement_rejected(root, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "secret").write_text("hidden")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        execute(root, "read_text", {"path": "link/secret"})
    (tmp_path / "file-link").symlink_to(outside / "secret")
    with pytest.raises(OSError):
        execute(root, "read_text", {"path": "file-link"})
    tmp_path.rename(tmp_path.parent / (tmp_path.name + "-old"))
    tmp_path.mkdir()
    with pytest.raises(ValueError, match="替换"):
        execute(root, "list_files", {"path": "."})


def test_file_limits_and_local_tool_permission(root, tmp_path):
    (tmp_path / "large").write_bytes(b"x" * 65537)
    with pytest.raises(ValueError):
        execute(root, "read_text", {"path": "large"})
    root["tools"] = ["read_text"]
    with pytest.raises(ValueError):
        execute(root, "write_text", {"path": "file", "content": "denied"})


def test_ledger_crash_is_uncertain_never_replayed(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    operation = {
        "id": "one",
        "grant_id": "grant",
        "tool": "write_text",
        "arguments": {"path": "file", "content": "x"},
        "lease": "local-test",
    }
    assert ledger.begin(operation) is None
    assert ledger.begin(operation)[0] == "uncertain"
    ledger.complete(operation, "succeeded", {"created": True})
    assert ledger.begin(operation) == ("succeeded", {"created": True})
    with pytest.raises(ValueError):
        ledger.begin({**operation, "arguments": {"path": "other"}})


def test_client_requires_tls_except_loopback():
    assert validate_url("http://127.0.0.1:18002/") == "http://127.0.0.1:18002"
    with pytest.raises(ValueError):
        validate_url("http://public.example.com")
    with pytest.raises(ValueError):
        validate_url("https://user:password@example.com")


def test_credentials_directory_cannot_enter_remote_tool_scope(tmp_path, monkeypatch):
    from personal_superagent.client.agent import execute_operation

    config_dir = tmp_path / "client"
    config_dir.mkdir()
    root = {"id": "grant", **describe_root(str(tmp_path)), "tools": ["read_text"]}
    ledger = Ledger(config_dir / "ledger.sqlite3")
    monkeypatch.setattr(
        "personal_superagent.client.agent.request",
        lambda *a: pytest.fail("凭证目录不能发起云端执行校验"),
    )
    operation = {
        "id": "blocked",
        "grant_id": "grant",
        "tool": "read_text",
        "arguments": {"path": "client/client.json"},
        "lease": "test",
    }
    state, _ = execute_operation(
        {"roots": [root]}, "session", operation, ledger, client_dir=config_dir
    )
    assert state == "failed"
