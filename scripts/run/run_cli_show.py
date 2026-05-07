from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from task_router_graph.token_usage import (
    TOKEN_USAGE_BUCKETS,
    empty_token_usage_summary,
    merge_token_usage_summary,
)
try:
    from .run_common import (
        display_path,
        ensure_preferred_provider_and_log,
        flush_tracers,
        log,
        print_cli_line,
        persist_run_result,
        serialize_run_result,
        with_heartbeat,
    )
except ImportError:
    from run_common import (
        display_path,
        ensure_preferred_provider_and_log,
        flush_tracers,
        log,
        print_cli_line,
        persist_run_result,
        serialize_run_result,
        with_heartbeat,
    )


def _resolve_input(args: argparse.Namespace) -> str:
    if args.input is not None and str(args.input).strip():
        return str(args.input).strip()

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped

    raise ValueError("Please provide --input, or pipe input from stdin, or use --interactive.")


def _print_result(result: dict, *, show_environment: bool, show_raw: bool) -> None:
    if show_raw:
        print_cli_line(json.dumps(result, ensure_ascii=False, indent=2))
        return

    output = result.get("output", {}) if isinstance(result, dict) else {}
    print_cli_line(json.dumps(output, ensure_ascii=False, indent=2))

    if show_environment:
        environment = result.get("environment", {}) if isinstance(result, dict) else {}
        print_cli_line(json.dumps(environment, ensure_ascii=False, indent=2))


def _build_token_usage_text(
    result: dict,
    *,
    key: str = "token_usage",
    title: str = "=== Token Usage ===",
) -> str:
    if not isinstance(result, dict):
        return "[token_usage] invalid result payload"

    token_usage = result.get(key)
    if not isinstance(token_usage, dict):
        return f"[token_usage] missing {key} payload"

    lines = [
        title,
        f"total_tokens: {int(token_usage.get('total_tokens', 0) or 0)}",
        f"input_tokens: {int(token_usage.get('input_tokens', 0) or 0)}",
        f"output_tokens: {int(token_usage.get('output_tokens', 0) or 0)}",
        f"call_count: {int(token_usage.get('call_count', 0) or 0)}",
        f"calls_with_usage: {int(token_usage.get('calls_with_usage', 0) or 0)}",
        f"calls_without_usage: {int(token_usage.get('calls_without_usage', 0) or 0)}",
        f"is_complete: {bool(token_usage.get('is_complete', False))}",
    ]

    by_bucket = token_usage.get("by_bucket")
    if not isinstance(by_bucket, dict):
        lines.append("by_bucket: <missing>")
        return "\n".join(lines)

    lines.append("by_bucket:")
    for bucket in TOKEN_USAGE_BUCKETS:
        item = by_bucket.get(bucket, {})
        if not isinstance(item, dict):
            item = {}
        lines.append(
            (
                f"  {bucket}: "
                f"total={int(item.get('total_tokens', 0) or 0)} "
                f"input={int(item.get('input_tokens', 0) or 0)} "
                f"output={int(item.get('output_tokens', 0) or 0)} "
                f"calls={int(item.get('call_count', 0) or 0)} "
                f"missing={int(item.get('calls_without_usage', 0) or 0)} "
                f"complete={bool(item.get('is_complete', False))}"
            )
        )
    return "\n".join(lines)


def _print_token_usage(
    result: dict,
    *,
    key: str = "token_usage",
    title: str = "=== Token Usage ===",
) -> None:
    print_cli_line(_build_token_usage_text(result, key=key, title=title))


def _build_token_usage_brief_text(*, turn_usage: dict[str, Any], session_usage: dict[str, Any]) -> str:
    turn_total = int(turn_usage.get("total_tokens", 0) or 0)
    session_total = int(session_usage.get("total_tokens", 0) or 0)
    turn_complete = bool(turn_usage.get("is_complete", False))
    session_complete = bool(session_usage.get("is_complete", False))
    return (
        "TokenUsage(turn/session): "
        f"total={turn_total}/{session_total}, "
        f"complete={str(turn_complete).lower()}/{str(session_complete).lower()}"
    )


def _print_token_usage_brief(*, turn_usage: dict[str, Any], session_usage: dict[str, Any]) -> None:
    print_cli_line(_build_token_usage_brief_text(turn_usage=turn_usage, session_usage=session_usage))


def _build_environment_show_text(result: dict) -> str:
    try:
        from task_router_graph.schema import Environment
    except Exception as exc:
        return f"[show] failed to import schema: {exc}"

    if not isinstance(result, dict):
        return "[show] invalid result payload"

    environment_payload = result.get("environment")
    if not isinstance(environment_payload, dict):
        return "[show] missing environment payload"

    env = Environment.from_dict(environment_payload)
    return env.show_environment(show_trace=True)


def _print_show_track(result: dict) -> None:
    print_cli_line("\n=== Show Track ===")
    print_cli_line(_build_environment_show_text(result))


def _print_stream_event(event: dict[str, object]) -> None:
    if not isinstance(event, dict):
        return
    event_name = str(event.get("event", "")).strip()
    if event_name != "retry_reply":
        return
    reply = str(event.get("reply", "")).strip()
    if not reply:
        return
    print_cli_line(f"Assistant(progress)> {reply}")


def main() -> None:
    try:
        parser = argparse.ArgumentParser(description="CLI entrypoint with show(track) output for every turn.")
        parser.add_argument("--config", default="configs/graph.yaml", help="Path to graph config")
        parser.add_argument("--case-id", default="cli", help="Case ID for single-shot mode")
        parser.add_argument("--input", help="Single-shot user input text")
        parser.add_argument("--interactive", action="store_true", help="Interactive chat-like mode")
        parser.add_argument("--show-environment", action="store_true", help="Print environment payload after output")
        parser.add_argument("--raw", action="store_true", help="Print full result JSON instead of output only")
        args = parser.parse_args()

        if args.interactive and args.input is not None:
            parser.error("--interactive cannot be used together with --input")

        if (not args.interactive) and (args.input is None or not str(args.input).strip()) and sys.stdin.isatty():
            args.interactive = True
            log("No --input provided, switching to interactive mode.")

        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path
        config_path = config_path.resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {display_path(config_path)}")

        ensure_preferred_provider_and_log(config_path)

        try:
            from task_router_graph import TaskRouterGraph
        except Exception as exc:
            raise RuntimeError(
                "Failed to import TaskRouterGraph. Please install dependencies (pip install -r requirements.txt)."
            ) from exc

        log(f"Loading graph with config: {display_path(config_path)}")
        graph, _ = with_heartbeat(
            "Graph initialization",
            lambda: TaskRouterGraph(config_path=str(config_path)),
        )

        if args.interactive:
            print_cli_line("Interactive mode started. Type /exit to quit.")
            turn = 1
            interactive_environment = None
            session_token_usage = empty_token_usage_summary()
            last_turn_payload: dict[str, Any] | None = None
            while True:
                try:
                    user_input = input("\nYou> ").strip()
                except EOFError:
                    print("", flush=True)
                    break
                except KeyboardInterrupt:
                    print("", flush=True)
                    break

                if not user_input:
                    continue
                if user_input.lower() in {"/exit", "exit", "/quit", "quit"}:
                    break

                case_id = f"{args.case_id}_{turn}"
                log(f"Running turn={turn}, case_id={case_id}")
                result, _ = with_heartbeat(
                    f"Turn {turn}",
                    lambda: graph.run(
                        case_id=case_id,
                        user_input=user_input,
                        environment=interactive_environment,
                        on_event=_print_stream_event,
                    ),
                )
                interactive_environment = result.environment
                turn_token_usage = getattr(result, "token_usage", {})
                if not isinstance(turn_token_usage, dict):
                    turn_token_usage = empty_token_usage_summary()
                session_token_usage = merge_token_usage_summary(session_token_usage, turn_token_usage)
                persist_run_result(
                    result,
                    project_root=PROJECT_ROOT,
                    token_usage_session=session_token_usage,
                )
                payload = serialize_run_result(
                    result,
                    project_root=PROJECT_ROOT,
                    token_usage_session=session_token_usage,
                )
                last_turn_payload = payload

                output = payload.get("output", {}) if isinstance(payload, dict) else {}
                reply = str(output.get("reply", "")).strip()
                print_cli_line(f"Assistant> {reply}")
                _print_result(payload, show_environment=args.show_environment, show_raw=args.raw)
                if not args.raw:
                    _print_token_usage_brief(turn_usage=turn_token_usage, session_usage=session_token_usage)
                _print_show_track(payload)
                turn += 1
            if (not args.raw) and isinstance(last_turn_payload, dict):
                _print_token_usage(
                    last_turn_payload,
                    key="token_usage",
                    title="=== Token Usage Final (Last Turn) ===",
                )
                _print_token_usage(
                    last_turn_payload,
                    key="token_usage_session",
                    title="=== Token Usage Final (Session) ===",
                )
            return

        user_input = _resolve_input(args)
        log(f"Running single-shot input, case_id={args.case_id}")
        result, _ = with_heartbeat(
            "Single-shot run",
            lambda: graph.run(
                case_id=args.case_id,
                user_input=user_input,
                on_event=_print_stream_event,
            ),
        )
        persist_run_result(result, project_root=PROJECT_ROOT)
        payload = serialize_run_result(result, project_root=PROJECT_ROOT)
        _print_result(payload, show_environment=args.show_environment, show_raw=args.raw)
        if not args.raw:
            _print_token_usage(payload)
        _print_show_track(payload)
    finally:
        flush_tracers()


if __name__ == "__main__":
    main()
