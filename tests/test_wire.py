"""Codemod that rewrites OpenAI/Anthropic SDK imports to unsinkable."""

from pathlib import Path

import pytest

from unsinkable.wire import rewrite_source, wire_path


def test_rewrites_openai_import():
    src = "from openai import OpenAI\n"
    out, _ = rewrite_source(src)
    assert out == "from unsinkable import OpenAI\n"


def test_rewrites_both_classes_in_one_line():
    src = "from openai import OpenAI, AsyncOpenAI\n"
    out, _ = rewrite_source(src)
    assert out == "from unsinkable import OpenAI, AsyncOpenAI\n"


def test_preserves_alias():
    src = "from openai import OpenAI as Client\n"
    out, _ = rewrite_source(src)
    assert out == "from unsinkable import OpenAI as Client\n"


def test_rewrites_anthropic_import():
    src = "from anthropic import Anthropic, AsyncAnthropic\n"
    out, _ = rewrite_source(src)
    assert out == "from unsinkable import Anthropic, AsyncAnthropic\n"


def test_passes_through_unrelated_imports():
    src = "import json\nfrom collections import deque\n"
    out, warnings = rewrite_source(src)
    assert out == src
    assert warnings == []


def test_unknown_symbol_skips_line_and_warns():
    src = "from openai import OpenAI, ChatCompletion\n"
    out, warnings = rewrite_source(src)
    # We refuse to silently drop ChatCompletion; entire line preserved
    assert out == src
    assert any("ChatCompletion" in w for w in warnings)


def test_bare_import_warns_but_unchanged():
    src = "import openai\nclient = openai.OpenAI()\n"
    out, warnings = rewrite_source(src)
    assert out == src
    assert any("unchanged" in w for w in warnings)


def test_import_star_warns_unchanged():
    src = "from openai import *\n"
    out, warnings = rewrite_source(src)
    assert out == src
    assert any("import *" in w for w in warnings)


def test_wire_path_directory_dry_run(tmp_path):
    f1 = tmp_path / "a.py"
    f1.write_text("from openai import OpenAI\n")
    f2 = tmp_path / "b.py"
    f2.write_text("from anthropic import Anthropic\n")
    f3 = tmp_path / "c.py"
    f3.write_text("import json\n")

    results = wire_path(tmp_path, dry_run=True)
    rewritten = {str(r.path): r for r in results if r.rewritten}
    assert str(f1) in rewritten
    assert str(f2) in rewritten
    assert str(f3) not in rewritten
    # Dry-run leaves the file unchanged
    assert f1.read_text() == "from openai import OpenAI\n"


def test_wire_path_applies_in_default_mode(tmp_path):
    f1 = tmp_path / "a.py"
    f1.write_text("from openai import OpenAI\n")
    wire_path(tmp_path, dry_run=False)
    assert f1.read_text() == "from unsinkable import OpenAI\n"


def test_wire_path_skips_venv_dirs(tmp_path):
    venv = tmp_path / ".venv" / "site"
    venv.mkdir(parents=True)
    inside = venv / "openai_client.py"
    inside.write_text("from openai import OpenAI\n")
    results = wire_path(tmp_path, dry_run=False)
    assert all(str(inside) != str(r.path) for r in results)
    assert inside.read_text() == "from openai import OpenAI\n"
