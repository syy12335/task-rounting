from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

T = TypeVar("T")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAIT_INDICATOR_LABEL = "等待中"
WAIT_INDICATOR_INTERVAL_SEC = 1.0
WAIT_INDICATOR_MAX_DOTS = 6
_OUTPUT_LOCK = threading.RLock()
_WAIT_INDICATOR_ACTIVE = False
_WAIT_INDICATOR_WIDTH = 0


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


SGLANG_PROBE_TOTAL_WAIT_SEC = _read_float_env("SGLANG_PROBE_TOTAL_WAIT_SEC", 2.0)
SGLANG_PROBE_INTERVAL_SEC = _read_float_env("SGLANG_PROBE_INTERVAL_SEC", 0.5)
SGLANG_AUTO_START = _read_bool_env("SGLANG_AUTO_START", False)
SGLANG_AUTO_START_READY_TIMEOUT_SEC = _read_float_env("SGLANG_AUTO_START_READY_TIMEOUT_SEC", 30.0)
SGLANG_START_TIMEOUT_SEC = _read_float_env(
    "SGLANG_START_TIMEOUT_SEC",
    SGLANG_AUTO_START_READY_TIMEOUT_SEC + 5.0,
)


def flush_tracers() -> None:
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
    except Exception:
        return

    try:
        wait_for_all_tracers()
    except Exception:
        return


def log(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _OUTPUT_LOCK:
        clear_wait_line()
        print(f"[{ts}] {message}", flush=True)


def clear_wait_line() -> None:
    global _WAIT_INDICATOR_ACTIVE, _WAIT_INDICATOR_WIDTH
    if not _WAIT_INDICATOR_ACTIVE:
        return
    if not sys.stdout.isatty():
        _WAIT_INDICATOR_ACTIVE = False
        _WAIT_INDICATOR_WIDTH = 0
        return
    blank = " " * max(0, _WAIT_INDICATOR_WIDTH)
    sys.stdout.write(f"\r{blank}\r")
    sys.stdout.flush()
    _WAIT_INDICATOR_ACTIVE = False
    _WAIT_INDICATOR_WIDTH = 0


def print_cli_line(message: str = "") -> None:
    with _OUTPUT_LOCK:
        clear_wait_line()
        print(message, flush=True)


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def display_path(path: Path | str, *, project_root: Path = PROJECT_ROOT) -> str:
    target = Path(str(path)).resolve()
    root = project_root.resolve()
    try:
        return target.relative_to(root).as_posix()
    except Exception:
        return os.path.relpath(str(target), str(root))


def resolve_run_dir(*, project_root: Path, run_id: str) -> Path:
    normalized = str(run_id).strip()
    if not normalized:
        raise ValueError("run_id is required to resolve run directory")
    return project_root / "var" / "runs" / f"run_{normalized}"


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def persist_run_result(
    result: Any,
    *,
    project_root: Path,
    token_usage_session: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    from task_router_graph.token_usage import empty_token_usage_summary
    from task_router_graph.utils import write_json

    run_id = str(getattr(result, "run_id", "")).strip()
    if not run_id:
        raise ValueError("GraphRunResult.run_id is required")

    run_dir = resolve_run_dir(project_root=project_root, run_id=run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    environment = getattr(result, "environment", None)
    output = getattr(result, "output", None)
    if environment is None or output is None:
        raise ValueError("GraphRunResult must include environment and output")

    environment_payload = environment.to_dict(include_trace=True)
    environment_payload["case_id"] = str(getattr(output, "case_id", "")).strip()
    write_json(run_dir / "environment.json", environment_payload)

    output_payload = output.to_dict()
    output_payload["run_dir"] = str(run_dir.relative_to(project_root))
    token_usage = getattr(result, "token_usage", {})
    if not isinstance(token_usage, dict):
        token_usage = empty_token_usage_summary()
    result_payload = {
        "run_id": run_id,
        "case_id": str(output_payload.get("case_id", "")).strip(),
        "output": output_payload,
        "token_usage": token_usage,
    }
    if isinstance(token_usage_session, dict):
        result_payload["token_usage_session"] = token_usage_session
    write_json(
        run_dir / "result.json",
        result_payload,
    )

    archive_records_raw = getattr(result, "archive_records", [])
    archive_records: list[dict[str, Any]] = []
    if isinstance(archive_records_raw, list):
        for item in archive_records_raw:
            if isinstance(item, dict):
                archive_records.append(item)
    append_jsonl(run_dir / "environment_archive.jsonl", archive_records)
    return run_dir, environment_payload


def serialize_run_result(
    result: Any,
    *,
    project_root: Path,
    token_usage_session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from task_router_graph.schema import to_dict
    from task_router_graph.token_usage import empty_token_usage_summary

    run_dir = resolve_run_dir(project_root=project_root, run_id=str(getattr(result, "run_id", "")))
    output_payload = to_dict(getattr(result, "output"))
    output_payload["run_dir"] = str(run_dir.relative_to(project_root))
    environment_payload = getattr(result, "environment").to_dict(include_trace=True)
    environment_payload["case_id"] = str(output_payload.get("case_id", "")).strip()
    token_usage = getattr(result, "token_usage", {})
    if not isinstance(token_usage, dict):
        token_usage = empty_token_usage_summary()
    payload = {
        "environment": environment_payload,
        "output": output_payload,
        "token_usage": token_usage,
    }
    if isinstance(token_usage_session, dict):
        payload["token_usage_session"] = token_usage_session
    return payload


def with_heartbeat(task_name: str, fn: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    stop_event = threading.Event()
    indicator_enabled = sys.stdout.isatty()

    def _heartbeat() -> None:
        global _WAIT_INDICATOR_ACTIVE, _WAIT_INDICATOR_WIDTH
        dots = 0
        while True:
            frame = WAIT_INDICATOR_LABEL + ("." * dots)
            frame_width = _display_width(frame)
            with _OUTPUT_LOCK:
                if not indicator_enabled:
                    continue
                padding = " " * max(0, _WAIT_INDICATOR_WIDTH - frame_width)
                _WAIT_INDICATOR_ACTIVE = True
                _WAIT_INDICATOR_WIDTH = frame_width
                sys.stdout.write(f"\r{frame}{padding}")
                sys.stdout.flush()
            if stop_event.wait(WAIT_INDICATOR_INTERVAL_SEC):
                break
            dots = 0 if dots >= WAIT_INDICATOR_MAX_DOTS else dots + 1

    heartbeat_thread = None
    if indicator_enabled:
        heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
        heartbeat_thread.start()

    try:
        result = fn()
    except Exception:
        elapsed = time.perf_counter() - start
        log(f"{task_name} failed after {elapsed:.1f}s")
        raise
    finally:
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=0.2)
        with _OUTPUT_LOCK:
            clear_wait_line()

    elapsed = time.perf_counter() - start
    log(f"{task_name} finished in {elapsed:.1f}s")
    return result, elapsed


def _resolve_config_path(config_path: str | Path) -> Path:
    path = Path(str(config_path).strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _load_model_cfg(config_path: str | Path) -> tuple[dict[str, Any], str]:
    path = _resolve_config_path(config_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config must be a yaml mapping")

    model_cfg = payload.get("model")
    if not isinstance(model_cfg, dict):
        raise ValueError("config.model must be a mapping")

    provider_env = str(model_cfg.get("provider_env", "MODEL_PROVIDER")).strip() or "MODEL_PROVIDER"
    return model_cfg, provider_env


def _resolve_provider_api_key(provider_cfg: dict[str, Any]) -> str:
    api_key_env = str(provider_cfg.get("api_key_env", "")).strip()
    if api_key_env:
        env_val = os.getenv(api_key_env, "").strip()
        if env_val:
            return env_val

    explicit = str(provider_cfg.get("api_key", "")).strip()
    if explicit:
        return explicit

    return "EMPTY"


def _probe_http(base_url: str, api_key: str, timeout_sec: float = 1.5) -> bool:
    probe_url = f"{base_url.rstrip('/')}/models"
    req = Request(probe_url, headers={"Authorization": f"Bearer {api_key or 'EMPTY'}"})
    try:
        with urlopen(req, timeout=timeout_sec):
            return True
    except HTTPError:
        # 401/404 等也表示服务已启动并可达。
        return True
    except URLError:
        return False
    except Exception:
        return False


def _is_sglang_available(providers: dict[str, Any]) -> bool:
    sglang_cfg = providers.get("sglang")
    if not isinstance(sglang_cfg, dict):
        return False

    base_url = str(sglang_cfg.get("base_url", "")).strip()
    if not base_url:
        return False

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip()
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    api_key = _resolve_provider_api_key(sglang_cfg)
    deadline = time.monotonic() + max(0.0, SGLANG_PROBE_TOTAL_WAIT_SEC)

    while True:
        socket_ok = False
        try:
            with socket.create_connection((host, port), timeout=1.0):
                socket_ok = True
        except OSError:
            socket_ok = False

        if socket_ok and _probe_http(base_url=base_url, api_key=api_key):
            return True

        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.1, SGLANG_PROBE_INTERVAL_SEC))


def _last_non_empty_line(text: str) -> str:
    for line in reversed(str(text).splitlines()):
        line = line.strip()
        if line:
            return line
    return ""


def _start_sglang_service() -> tuple[bool, str]:
    script_path = PROJECT_ROOT / "scripts" / "sglang" / "start.sh"
    if not script_path.exists():
        return False, f"start script missing: {display_path(script_path)}"

    timeout_sec = max(1.0, SGLANG_START_TIMEOUT_SEC)
    env = os.environ.copy()
    env.setdefault("SGLANG_READY_TIMEOUT_SEC", f"{max(1.0, SGLANG_AUTO_START_READY_TIMEOUT_SEC):g}")
    env.setdefault("SGLANG_READY_INTERVAL_SEC", "1")
    try:
        completed = subprocess.run(
            [str(script_path)],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        last_line = _last_non_empty_line(output)
        detail = f"; last output: {last_line}" if last_line else ""
        return False, f"start timed out after {timeout_sec:.0f}s{detail}"
    except Exception as exc:
        return False, f"start failed: {exc}"

    output = completed.stdout or ""
    last_line = _last_non_empty_line(output)
    if completed.returncode == 0:
        return True, last_line or "start script succeeded"
    return False, last_line or f"start script exited with code {completed.returncode}"


def _fallback_provider(providers: dict[str, Any]) -> tuple[str | None, str]:
    if "aliyun" in providers:
        return "aliyun", "aliyun"
    non_sglang = [str(name) for name in providers.keys() if str(name) != "sglang"]
    if non_sglang:
        return non_sglang[0], non_sglang[0]
    return None, ""


def ensure_preferred_provider_and_log(config_path: str | Path) -> tuple[str, str, str]:
    model_cfg, provider_env = _load_model_cfg(config_path)
    providers = model_cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("model.providers must be a non-empty mapping")

    default_provider = str(model_cfg.get("provider", "")).strip()
    env_provider = os.getenv(provider_env, "").strip()

    preferred = "sglang" if "sglang" in providers else (default_provider or next(iter(providers.keys())))
    selected = env_provider or preferred

    reason = "env override" if env_provider else "default to sglang"

    if selected not in providers:
        selected = preferred
        reason = f"invalid env provider, fallback to {selected}"

    if selected == "sglang" and not _is_sglang_available(providers):
        start_detail = ""
        if SGLANG_AUTO_START:
            log("SGLang is not ready; trying to start local SGLang before provider fallback.")
            started, start_detail = _start_sglang_service()
            if started and _is_sglang_available(providers):
                reason = f"{reason}, auto-started sglang"
            else:
                fallback, fallback_label = _fallback_provider(providers)
                if fallback is not None:
                    selected = fallback
                    reason = (
                        f"sglang unavailable after auto-start ({start_detail or 'not ready'}), "
                        f"fallback to {fallback_label}"
                    )
                else:
                    reason = (
                        f"sglang unavailable after auto-start ({start_detail or 'not ready'}), "
                        "no fallback provider"
                    )
        else:
            fallback, fallback_label = _fallback_provider(providers)
            if fallback is not None:
                selected = fallback
                reason = f"sglang unavailable, fallback to {fallback_label}"
            else:
                reason = "sglang unavailable, no fallback provider"

    os.environ[provider_env] = selected

    provider_cfg = providers.get(selected)
    model_name = ""
    if isinstance(provider_cfg, dict):
        model_name = str(provider_cfg.get("name", "")).strip()

    log(
        "Provider selected before startup: "
        f"provider={selected}, model={model_name or '-'}, env={provider_env}, reason={reason}"
    )

    return selected, model_name, provider_env
