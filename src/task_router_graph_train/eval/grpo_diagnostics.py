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

    score_points = [
        (int(row.get("step", 0) or 0), float(row["critic/score/mean"]))
        for row in step_metrics
        if "critic/score/mean" in row
    ]
    if not score_points:
        return _empty_card("暂无 critic/score/mean 指标。")

    step_summary = summarize_grpo_step_metrics(step_metrics)
    audit_summary = audit_summary or {}
    width = 720
    height = 280
    left = 56
    right = 24
    top = 26
    bottom = 40
    plot_width = width - left - right
    plot_height = height - top - bottom
    min_step = min(step for step, _score in score_points)
    max_step = max(step for step, _score in score_points)
    x_span = max(1, max_step - min_step)
    y_min = min(-1.0, min(score for _step, score in score_points))
    y_max = max(1.0, max(score for _step, score in score_points))
    y_span = max(0.001, y_max - y_min)

    def x_for(step: int) -> float:
        return left + ((step - min_step) / x_span) * plot_width

    def y_for(score: float) -> float:
        return top + ((y_max - score) / y_span) * plot_height

    score_polyline = " ".join(f"{x_for(step):.2f},{y_for(score):.2f}" for step, score in score_points)
    zero_y = y_for(0.0)
    y_ticks = [y_min, 0.0, y_max]

    cards = [
        ("steps", str(step_summary.get("step_count", 0))),
        ("score", f"{step_summary.get('first_score_mean', 0):.3f} -> {step_summary.get('last_score_mean', 0):.3f}"),
        ("best", f"{step_summary.get('best_score_mean', 0):.3f}"),
        ("clip", f"{float(step_summary.get('max_response_length_clip_ratio', 0.0)) * 100:.1f}%"),
    ]
    if audit_summary:
        cards.append(("audit", f"{int(audit_summary.get('group_count', 0) or 0)} groups"))
        cards.append(("pass", f"{float(audit_summary.get('candidate_pass_rate', 0.0) or 0.0) * 100:.1f}%"))

    segments: list[str] = [
        '<div style="font-family:system-ui,sans-serif;border:1px solid #d0d7de;border-radius:16px;'
        'padding:16px 18px;background:#fff;color:#111827;max-width:780px;">',
        f'<div style="font-size:18px;font-weight:700;margin-bottom:10px;">{html.escape(title)}</div>',
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">',
    ]
    for label, value in cards:
        segments.append(
            '<div style="border:1px solid #e5e7eb;border-radius:12px;padding:8px 10px;background:#f8fafc;min-width:82px;">'
            f'<div style="font-size:11px;color:#6b7280;text-transform:uppercase;">{html.escape(label)}</div>'
            f'<div style="font-size:15px;font-weight:700;">{html.escape(value)}</div>'
            '</div>'
        )
    segments.extend(
        [
            '</div>',
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="grpo score chart">',
            f'<rect x="0" y="0" width="{width}" height="{height}" rx="14" fill="#f8fafc"></rect>',
            f'<line x1="{left}" y1="{zero_y:.2f}" x2="{width - right}" y2="{zero_y:.2f}" stroke="#cbd5e1" stroke-dasharray="4 4"></line>',
        ]
    )
    for tick in y_ticks:
        y = y_for(tick)
        segments.extend(
            [
                f'<line x1="{left - 4}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e5e7eb"></line>',
                f'<text x="14" y="{y + 4:.2f}" font-size="11" fill="#6b7280">{tick:.1f}</text>',
            ]
        )
    segments.extend(
        [
            f'<polyline points="{score_polyline}" fill="none" stroke="#0f766e" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></polyline>',
        ]
    )
    for step, score in score_points:
        segments.append(f'<circle cx="{x_for(step):.2f}" cy="{y_for(score):.2f}" r="3.5" fill="#0f766e"></circle>')
    segments.extend(
        [
            f'<text x="{left}" y="{height - 14}" font-size="11" fill="#6b7280">step {min_step}</text>',
            f'<text x="{width - right - 54}" y="{height - 14}" font-size="11" fill="#6b7280">step {max_step}</text>',
            f'<text x="{left}" y="18" font-size="12" fill="#111827">critic/score/mean</text>',
            '</svg>',
            '</div>',
        ]
    )
    return "".join(segments)


def _parse_numeric_metrics(line: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for regex in (COLON_METRIC_RE, EQUAL_METRIC_RE):
        for match in regex.finditer(line):
            metrics[match.group("key")] = float(match.group("value"))
    return metrics


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _empty_card(message: str) -> str:
    return (
        '<div style="padding:12px;border:1px solid #d0d7de;border-radius:12px;'
        'font-family:system-ui,sans-serif;background:#fff;color:#111827;">'
        f'{html.escape(message)}</div>'
    )
