from __future__ import annotations

import io
import os
import re
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPTS_ROOT = PROJECT_ROOT / "scripts" / "run"
if str(RUN_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(RUN_SCRIPTS_ROOT))


import run_common


def _write_provider_config(path: Path) -> None:
    path.write_text(
        """
model:
  provider: sglang
  provider_env: MODEL_PROVIDER
  providers:
    aliyun:
      name: qwen-flash
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    sglang:
      name: qwen3-4b
      base_url: http://127.0.0.1:30000/v1
""".strip(),
        encoding="utf-8",
    )


class _FakeStdout(io.StringIO):
    def __init__(self, *, is_tty: bool) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_with_heartbeat_renders_wait_indicator_and_wraps(monkeypatch) -> None:
    fake_stdout = _FakeStdout(is_tty=True)
    monkeypatch.setattr(run_common, "WAIT_INDICATOR_INTERVAL_SEC", 0.005)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_ACTIVE", False)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_WIDTH", 0)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    result, elapsed = run_common.with_heartbeat("demo task", lambda: time.sleep(0.05) or "done")

    assert result == "done"
    assert elapsed > 0
    output = fake_stdout.getvalue()
    frames = re.findall(r"\r等待中\.{0,6}", output)
    assert "\r等待中" in frames
    assert "\r等待中." in frames
    assert "\r等待中.." in frames
    assert "\r等待中..." in frames
    assert "\r等待中...." in frames
    assert "\r等待中....." in frames
    assert "\r等待中......" in frames

    wrap_start = frames.index("\r等待中......")
    assert "\r等待中" in frames[wrap_start + 1 :]
    assert "demo task finished in" in output


def test_with_heartbeat_logs_failure_and_stops_indicator(monkeypatch) -> None:
    fake_stdout = _FakeStdout(is_tty=True)
    monkeypatch.setattr(run_common, "WAIT_INDICATOR_INTERVAL_SEC", 0.005)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_ACTIVE", False)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_WIDTH", 0)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    def _boom() -> None:
        time.sleep(0.02)
        raise RuntimeError("boom")

    try:
        run_common.with_heartbeat("broken task", _boom)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    output = fake_stdout.getvalue()
    assert "\r等待中" in output
    assert "broken task failed after" in output
    assert "finished in" not in output


def test_with_heartbeat_degrades_without_tty(monkeypatch) -> None:
    fake_stdout = _FakeStdout(is_tty=False)
    monkeypatch.setattr(run_common, "WAIT_INDICATOR_INTERVAL_SEC", 0.005)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_ACTIVE", False)
    monkeypatch.setattr(run_common, "_WAIT_INDICATOR_WIDTH", 0)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    result, _ = run_common.with_heartbeat("plain task", lambda: time.sleep(0.02) or 7)

    assert result == 7
    output = fake_stdout.getvalue()
    assert "\r等待中" not in output
    assert "plain task finished in" in output


def test_ensure_preferred_provider_defaults_to_sglang_after_auto_start(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "graph.yaml"
    _write_provider_config(config_path)
    availability = iter([False, True])

    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(run_common, "SGLANG_AUTO_START", True)
    monkeypatch.setattr(run_common, "_is_sglang_available", lambda _providers: next(availability))
    monkeypatch.setattr(run_common, "_start_sglang_service", lambda: (True, "sglang started"))

    provider, model_name, provider_env = run_common.ensure_preferred_provider_and_log(config_path)

    assert provider == "sglang"
    assert model_name == "qwen3-4b"
    assert provider_env == "MODEL_PROVIDER"
    assert os.environ["MODEL_PROVIDER"] == "sglang"


def test_ensure_preferred_provider_falls_back_without_auto_start(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "graph.yaml"
    _write_provider_config(config_path)
    start_calls = 0

    def _start() -> tuple[bool, str]:
        nonlocal start_calls
        start_calls += 1
        return True, "should not be called"

    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(run_common, "SGLANG_AUTO_START", False)
    monkeypatch.setattr(run_common, "_is_sglang_available", lambda _providers: False)
    monkeypatch.setattr(run_common, "_start_sglang_service", _start)

    provider, model_name, provider_env = run_common.ensure_preferred_provider_and_log(config_path)

    assert provider == "aliyun"
    assert model_name == "qwen-flash"
    assert provider_env == "MODEL_PROVIDER"
    assert start_calls == 0
    assert os.environ["MODEL_PROVIDER"] == "aliyun"


def test_ensure_preferred_provider_falls_back_to_aliyun_when_sglang_cannot_start(
    monkeypatch, tmp_path
) -> None:
    config_path = tmp_path / "graph.yaml"
    _write_provider_config(config_path)

    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(run_common, "SGLANG_AUTO_START", True)
    monkeypatch.setattr(run_common, "_is_sglang_available", lambda _providers: False)
    monkeypatch.setattr(run_common, "_start_sglang_service", lambda: (False, "sglang failed"))

    provider, model_name, provider_env = run_common.ensure_preferred_provider_and_log(config_path)

    assert provider == "aliyun"
    assert model_name == "qwen-flash"
    assert provider_env == "MODEL_PROVIDER"
    assert os.environ["MODEL_PROVIDER"] == "aliyun"
