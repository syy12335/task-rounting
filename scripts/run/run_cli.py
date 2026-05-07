from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


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
        parser = argparse.ArgumentParser(description="CLI entrypoint for TaskRouterGraph without case files.")
        parser.add_argument("--config", default="configs/graph.yaml", help="Path to graph config")
        parser.add_argument("--case-id", default="cli", help="Case ID for single-shot mode")
        parser.add_argument("--input", help="Single-shot user input text")
        parser.add_argument("--interactive", action="store_true", help="Interactive chat-like mode")
        parser.add_argument("--show-environment", action="store_true", help="Print environment payload after output")
        parser.add_argument("--raw", action="store_true", help="Print full result JSON instead of output only")
        args = parser.parse_args()

        if args.interactive and args.input is not None:
            parser.error("--interactive cannot be used together with --input")

        # UX: when launched directly in a terminal with no --input, auto-enter interactive mode.
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
                persist_run_result(result, project_root=PROJECT_ROOT)
                payload = serialize_run_result(result, project_root=PROJECT_ROOT)

                output = payload.get("output", {}) if isinstance(payload, dict) else {}
                reply = str(output.get("reply", "")).strip()
                print_cli_line(f"Assistant> {reply}")
                _print_result(payload, show_environment=args.show_environment, show_raw=args.raw)
                turn += 1
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
    finally:
        flush_tracers()


if __name__ == "__main__":
    main()
