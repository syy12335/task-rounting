from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
COLON_METRIC_RE = re.compile(rf"(?P<key>[A-Za-z0-9_./-]+):(?P<value>{_NUMBER_PATTERN})")
EQUAL_METRIC_RE = re.compile(rf"(?P<key>[A-Za-z0-9_./-]+)=(?P<value>{_NUMBER_PATTERN})")

STEP_METRIC_KEYS = (
    "actor/grad_norm",
    "actor/kl_loss",
    "actor/lr",
    "actor/pg_loss",
    "critic/advantages/mean",
    "critic/rewards/mean",
    "critic/score/max",
    "critic/score/mean",
    "critic/score/min",
    "perf/throughput",
    "response/aborted_ratio",
    "response_length/clip_ratio",
    "response_length/mean",
    "training/epoch",
    "training/global_step",
)


def parse_grpo_step_metrics(log_path: Path) -> list[dict[str, Any]]:
    """Parse verl console step lines into compact metrics rows."""
    resolved = Path(log_path).resolve()
    if not resolved.exists():
        return []

    rows_by_step: dict[int, dict[str, Any]] = {}
    for line_no, raw_line in enumerate(resolved.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = _strip_ansi(raw_line)
        if "critic/score/mean" not in line or ("step:" not in line and "step=" not in line):
            continue
        metrics = _parse_numeric_metrics(line)
        step_value = metrics.get("step") or metrics.get("training/global_step")
        if step_value is None:
            continue
        step = int(step_value)
        row: dict[str, Any] = {
            "step": step,
            "line_no": line_no,
        }
        for key in STEP_METRIC_KEYS:
            if key in metrics:
                row[key] = metrics[key]
        rows_by_step[step] = row
    return [rows_by_step[step] for step in sorted(rows_by_step)]


def summarize_grpo_step_metrics(step_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not step_metrics:
        return {
            "step_count": 0,
        }

    score_values = [float(row["critic/score/mean"]) for row in step_metrics if "critic/score/mean" in row]
    kl_values = [float(row["actor/kl_loss"]) for row in step_metrics if "actor/kl_loss" in row]
    clip_values = [float(row["response_length/clip_ratio"]) for row in step_metrics if "response_length/clip_ratio" in row]
    response_lengths = [float(row["response_length/mean"]) for row in step_metrics if "response_length/mean" in row]
    first = step_metrics[0]
    last = step_metrics[-1]

    summary: dict[str, Any] = {
        "step_count": len(step_metrics),
        "first_step": int(first.get("step", 0) or 0),
        "last_step": int(last.get("step", 0) or 0),
    }
    if score_values:
        summary.update(
            {
                "first_score_mean": round(score_values[0], 6),
                "last_score_mean": round(score_values[-1], 6),
                "best_score_mean": round(max(score_values), 6),
                "worst_score_mean": round(min(score_values), 6),
                "score_mean_delta": round(score_values[-1] - score_values[0], 6),
            }
        )
    if kl_values:
        summary.update(
            {
                "last_kl_loss": round(kl_values[-1], 6),
                "max_kl_loss": round(max(kl_values), 6),
            }
        )
    if clip_values:
        summary["max_response_length_clip_ratio"] = round(max(clip_values), 6)
    if response_lengths:
        summary.update(
            {
                "first_response_length_mean": round(response_lengths[0], 6),
                "last_response_length_mean": round(response_lengths[-1], 6),
            }
        )
    if "actor/lr" in last:
        summary["last_actor_lr"] = float(last["actor/lr"])
    if "actor/grad_norm" in last:
        summary["last_grad_norm"] = round(float(last["actor/grad_norm"]), 6)
    return summary


def summarize_grpo_reward_audit(audit_path: Path) -> dict[str, Any]:
    resolved = Path(audit_path).resolve()
    if not resolved.exists():
        return {
            "audit_path": str(resolved),
            "exists": False,
            "group_count": 0,
        }

    group_count = 0
    teacher_called_count = 0
    teacher_skipped_count = 0
    format_error_group_count = 0
    passed_distribution: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    candidate_count = 0
    candidate_passed_count = 0
    reward_scores: list[float] = []
    confidence_values: list[float] = []

    for line in resolved.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        group_count += 1
        passed_count = int(row.get("passed_count", 0) or 0)
        passed_distribution[str(passed_count)] += 1
        if bool(row.get("teacher_called", False)):
            teacher_called_count += 1
        if bool(row.get("teacher_skipped", False)):
            teacher_skipped_count += 1
        teacher_format_errors = row.get("teacher_format_errors", [])
        if isinstance(teacher_format_errors, list) and teacher_format_errors:
            format_error_group_count += 1
        confidence = row.get("teacher_confidence")
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))

        stage_counts = row.get("failure_counts_by_stage", {})
        if isinstance(stage_counts, dict):
            for stage, count in stage_counts.items():
                failure_counts[str(stage)] += int(count or 0)

        row_reward_scores: list[float] = []
        candidates = row.get("candidates", [])
        if isinstance(candidates, list):
            candidate_count += len(candidates)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if bool(candidate.get("hard_gate_passed", False)):
                    candidate_passed_count += 1
                score = candidate.get("reward_score")
                if isinstance(score, (int, float)):
                    row_reward_scores.append(float(score))
        scores_by_candidate = row.get("scores_by_candidate", {})
        if not row_reward_scores and isinstance(scores_by_candidate, dict):
            row_reward_scores.extend(float(score) for score in scores_by_candidate.values() if isinstance(score, (int, float)))
        reward_scores.extend(row_reward_scores)

    return {
        "audit_path": str(resolved),
        "exists": True,
        "group_count": group_count,
        "teacher_called_count": teacher_called_count,
        "teacher_skipped_count": teacher_skipped_count,
        "format_error_group_count": format_error_group_count,
        "passed_count_distribution": dict(sorted(passed_distribution.items(), key=lambda item: int(item[0]))),
        "failure_counts_by_stage": dict(sorted(failure_counts.items())),
        "candidate_count": candidate_count,
        "candidate_passed_count": candidate_passed_count,
        "candidate_pass_rate": round(candidate_passed_count / candidate_count, 6) if candidate_count else 0.0,
        "mean_candidate_reward_score": round(sum(reward_scores) / len(reward_scores), 6) if reward_scores else 0.0,
        "mean_teacher_confidence": round(sum(confidence_values) / len(confidence_values), 6) if confidence_values else 0.0,
    }


def find_latest_grpo_checkpoint(*, output_dir: Path, checkpoint_dir: Path | None = None) -> dict[str, Any]:
    resolved_output = Path(output_dir).resolve()
    resolved_checkpoint_dir = Path(checkpoint_dir).resolve() if checkpoint_dir is not None else (resolved_output / "checkpoints").resolve()
    result: dict[str, Any] = {
        "checkpoint_dir": str(resolved_checkpoint_dir),
        "exists": resolved_checkpoint_dir.exists(),
        "latest_step": None,
        "latest_checkpoint_path": "",
        "actor_checkpoint_path": "",
        "hf_model_path": "",
        "hf_model_exists": False,
    }
    if not resolved_checkpoint_dir.exists():
        result["reason"] = "checkpoint_dir_missing"
        return result

    step = _read_latest_checkpoint_step(resolved_checkpoint_dir)
    if step is None:
        step = _find_latest_global_step(resolved_checkpoint_dir)
    if step is None:
        result["reason"] = "global_step_checkpoint_missing"
        return result

    latest_checkpoint_path = resolved_checkpoint_dir / f"global_step_{step}"
    if not latest_checkpoint_path.exists():
        fallback_step = _find_latest_global_step(resolved_checkpoint_dir)
        if fallback_step is None:
            result["reason"] = "latest_checkpoint_path_missing"
            return result
        step = fallback_step
        latest_checkpoint_path = resolved_checkpoint_dir / f"global_step_{step}"

    actor_checkpoint_path = latest_checkpoint_path / "actor"
    hf_model_path = actor_checkpoint_path / "huggingface"
    hf_model_exists = _is_hf_model_dir(hf_model_path)
    result.update(
        {
            "latest_step": step,
            "latest_checkpoint_path": str(latest_checkpoint_path),
            "actor_checkpoint_path": str(actor_checkpoint_path),
            "hf_model_path": str(hf_model_path),
            "hf_model_exists": hf_model_exists,
        }
    )
    if not hf_model_exists:
        result["reason"] = "hf_model_missing"
    return result


def write_grpo_diagnostics(
    *,
    output_dir: Path,
    eval_output_dir: Path | None = None,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_output = Path(output_dir).resolve()
    diagnostics_dir = Path(eval_output_dir).resolve() if eval_output_dir is not None else resolved_output
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = resolved_output / "verl_stdout.log"
    audit_path = resolved_output / "reward_audit.jsonl"
    step_metrics = parse_grpo_step_metrics(stdout_log)
    step_summary = summarize_grpo_step_metrics(step_metrics)
    audit_summary = summarize_grpo_reward_audit(audit_path)
    checkpoint_summary = find_latest_grpo_checkpoint(output_dir=resolved_output, checkpoint_dir=checkpoint_dir)

    step_metrics_path = diagnostics_dir / "grpo_step_metrics.jsonl"
    reward_audit_summary_path = diagnostics_dir / "grpo_reward_audit_summary.json"
    diagnostics_path = diagnostics_dir / "grpo_diagnostics.json"

    step_metrics_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in step_metrics) + ("\n" if step_metrics else ""),
        encoding="utf-8",
    )
    reward_audit_summary_path.write_text(
        json.dumps(audit_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    diagnostics = {
        "output_dir": str(resolved_output),
        "stdout_log": str(stdout_log),
        "reward_audit_path": str(audit_path),
        "step_metrics_path": str(step_metrics_path),
        "reward_audit_summary_path": str(reward_audit_summary_path),
        "diagnostics_path": str(diagnostics_path),
        "summary": {
            "step_metrics": step_summary,
            "reward_audit": audit_summary,
            "checkpoint": checkpoint_summary,
        },
        "step_metrics": step_metrics,
    }
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return diagnostics


def _read_latest_checkpoint_step(checkpoint_dir: Path) -> int | None:
    marker = checkpoint_dir / "latest_checkpointed_iteration.txt"
    if not marker.exists():
        return None
    match = re.search(r"\d+", marker.read_text(encoding="utf-8", errors="replace"))
    return int(match.group(0)) if match else None


def _find_latest_global_step(checkpoint_dir: Path) -> int | None:
    steps: list[int] = []
    for child in checkpoint_dir.iterdir():
        if not child.is_dir():
            continue
        match = re.fullmatch(r"global_step_(\d+)", child.name)
        if match:
            steps.append(int(match.group(1)))
    return max(steps) if steps else None


def _is_hf_model_dir(path: Path) -> bool:
    if not path.is_dir() or not (path / "config.json").exists():
        return False
    model_files = (
        "model.safetensors",
        "pytorch_model.bin",
        "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
    )
    return any((path / name).exists() for name in model_files)


def render_grpo_training_chart_html(
    step_metrics: list[dict[str, Any]],
    audit_summary: dict[str, Any] | None = None,
    *,
    title: str = "GRPO Training Diagnostics",
) -> str:
    if not step_metrics:
        return _empty_card("暂无 GRPO step 指标。export_only 模式或 verl 日志不存在时这是正常的。")

    if not any("critic/score/mean" in row for row in step_metrics):
        return _empty_card("暂无 critic/score/mean 指标。")

    step_summary = summarize_grpo_step_metrics(step_metrics)
    audit_summary = audit_summary or {}
    summary_rows = [
        ("step_count", step_summary.get("step_count", 0)),
        ("score_mean", f"{step_summary.get('first_score_mean', 0):.6g} -> {step_summary.get('last_score_mean', 0):.6g}"),
        ("score_delta", step_summary.get("score_mean_delta", "")),
        ("best_score_mean", step_summary.get("best_score_mean", "")),
        ("last_kl_loss", step_summary.get("last_kl_loss", "")),
        ("last_response_length_mean", step_summary.get("last_response_length_mean", "")),
    ]
    if audit_summary:
        summary_rows.extend(
            [
                ("reward_audit_groups", audit_summary.get("group_count", 0)),
                ("candidate_pass_rate", f"{float(audit_summary.get('candidate_pass_rate', 0.0) or 0.0) * 100:.1f}%"),
                ("mean_candidate_reward_score", audit_summary.get("mean_candidate_reward_score", "")),
            ]
        )

    segments: list[str] = [
        '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
        'color:inherit;max-width:920px;">',
        f'<div style="font-weight:700;margin:0 0 8px 0;">{html.escape(title)}</div>',
        '<table style="border-collapse:collapse;font-size:14px;margin-bottom:12px;min-width:520px;">',
        '<thead><tr>'
        '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">Metric</th>'
        '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">Value</th>'
        '</tr></thead><tbody>',
    ]
    for index, (metric, value) in enumerate(summary_rows):
        background = "rgba(127,127,127,0.08)" if index % 2 else "transparent"
        segments.append(
            f'<tr style="background:{background};">'
            f'<td style="text-align:right;padding:6px 14px;">{html.escape(str(metric))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{html.escape(str(value))}</td>'
            '</tr>'
        )
    segments.extend(
        [
            '</tbody></table>',
            '<table style="border-collapse:collapse;font-size:14px;min-width:760px;">',
            '<thead><tr>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">Step</th>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">critic/score/mean</th>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">critic/rewards/mean</th>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">actor/kl_loss</th>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">response_length/mean</th>'
            '<th style="text-align:right;padding:6px 14px;border-bottom:1px solid #d0d7de;">perf/throughput</th>'
            '</tr></thead><tbody>',
        ]
    )
    for index, row in enumerate(step_metrics):
        background = "rgba(127,127,127,0.08)" if index % 2 else "transparent"
        segments.append(
            f'<tr style="background:{background};">'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("step"))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("critic/score/mean"))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("critic/rewards/mean"))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("actor/kl_loss"))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("response_length/mean"))}</td>'
            f'<td style="text-align:right;padding:6px 14px;">{_html_number(row.get("perf/throughput"))}</td>'
            '</tr>'
        )
    segments.append("</tbody></table></div>")
    return "".join(segments)


def _parse_numeric_metrics(line: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for regex in (COLON_METRIC_RE, EQUAL_METRIC_RE):
        for match in regex.finditer(line):
            metrics[match.group("key")] = float(match.group("value"))
    return metrics


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _html_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return html.escape(str(value))
    if isinstance(value, float):
        return html.escape(f"{value:.6g}")
    return html.escape(str(value))


def _empty_card(message: str) -> str:
    return (
        '<div style="padding:12px;border:1px solid #d0d7de;border-radius:12px;'
        'font-family:system-ui,sans-serif;background:#fff;color:#111827;">'
        f'{html.escape(message)}</div>'
    )
