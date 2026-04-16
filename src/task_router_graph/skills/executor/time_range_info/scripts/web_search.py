#!/usr/bin/env python3
from __future__ import annotations

"""time_range_info worker graph implementation (not the main orchestration graph.py)."""

import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

import yaml
from jsonschema import ValidationError, validate
from langgraph.graph import END, START, StateGraph

try:
    from defusedxml import ElementTree as SafeElementTree
except Exception:  # pragma: no cover
    from xml.etree import ElementTree as SafeElementTree


MAX_WEB_SEARCH_RESULTS = 5
MAX_WEB_SEARCH_QUERY_CHARS = 120
DEFAULT_POLICY_RELATIVE_PATH = "config/retrieval_policy.yaml"
GRAPH_CONFIG_RELATIVE_PATH = "configs/graph.yaml"

POLICY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["runtime", "retrieval", "grading", "prompts", "response"],
    "additionalProperties": False,
    "properties": {
        "runtime": {
            "type": "object",
            "required": ["max_iterations", "allow_rewrite", "rewrite_temperature", "max_docs_in_context"],
            "additionalProperties": False,
            "properties": {
                "max_iterations": {"type": "integer", "minimum": 1, "maximum": 8},
                "allow_rewrite": {"type": "boolean"},
                "rewrite_temperature": {"type": "number", "minimum": 0, "maximum": 1},
                "max_docs_in_context": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        "retrieval": {
            "type": "object",
            "required": [
                "engine",
                "http_timeout_sec",
                "max_http_bytes",
                "bootstrap_web_limit",
                "hybrid_web_limit",
                "hybrid_local_limit",
            ],
            "additionalProperties": False,
            "properties": {
                "engine": {"type": "string", "minLength": 1},
                "http_timeout_sec": {"type": "number", "exclusiveMinimum": 0},
                "max_http_bytes": {"type": "integer", "minimum": 1000},
                "bootstrap_web_limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "hybrid_web_limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "hybrid_local_limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        "grading": {
            "type": "object",
            "required": [
                "llm_min_confidence",
                "min_docs_for_answer",
                "min_dedup_ratio",
                "min_avg_snippet_chars",
            ],
            "additionalProperties": False,
            "properties": {
                "llm_min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "min_docs_for_answer": {"type": "integer", "minimum": 1, "maximum": 20},
                "min_dedup_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                "min_avg_snippet_chars": {"type": "integer", "minimum": 0, "maximum": 4000},
            },
        },
        "prompts": {
            "type": "object",
            "required": ["grading_system", "rewrite_system", "answer_system"],
            "additionalProperties": False,
            "properties": {
                "grading_system": {"type": "string", "minLength": 1},
                "rewrite_system": {"type": "string", "minLength": 1},
                "answer_system": {"type": "string", "minLength": 1},
            },
        },
        "response": {
            "type": "object",
            "required": ["agent_mode", "usage_note", "no_result_message"],
            "additionalProperties": False,
            "properties": {
                "agent_mode": {"type": "string", "minLength": 1},
                "usage_note": {"type": "string", "minLength": 1},
                "no_result_message": {"type": "string", "minLength": 1},
            },
        },
    },
}


class FlowState(TypedDict, total=False):
    input_payload: dict[str, Any]
    query: str
    limit: int
    current_query: str
    iteration: int
    query_history: list[str]
    bootstrap_docs: list[dict[str, Any]]
    semantic_chunks: list[dict[str, Any]]
    hybrid_docs: list[dict[str, Any]]
    selected_docs: list[dict[str, Any]]
    grade_decision: str
    grade_reason: str
    grade_confidence: float
    heuristic: dict[str, Any]
    task_status: str
    task_result: str


@dataclass(frozen=True)
class RetrievalPolicy:
    max_iterations: int
    allow_rewrite: bool
    rewrite_temperature: float
    max_docs_in_context: int
    retrieval_engine: str
    retrieval_http_timeout_sec: float
    retrieval_max_http_bytes: int
    bootstrap_web_limit: int
    hybrid_web_limit: int
    hybrid_local_limit: int
    llm_min_confidence: float
    min_docs_for_answer: int
    min_dedup_ratio: float
    min_avg_snippet_chars: int
    grading_system: str
    rewrite_system: str
    answer_system: str
    response_agent_mode: str
    response_usage_note: str
    no_result_message: str


@dataclass(frozen=True)
class ChatConfig:
    model: str
    base_url: str
    api_key: str
    timeout_sec: float
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    base_url: str
    api_key: str
    timeout_sec: float


@dataclass
class TimeRangeRagSubAgent:
    policy: RetrievalPolicy
    chat_cfg: ChatConfig
    embedding_cfg: EmbeddingConfig

    def run(self, *, input_payload: dict[str, Any]) -> dict[str, str]:
        workflow = _build_workflow(policy=self.policy, chat_cfg=self.chat_cfg, embedding_cfg=self.embedding_cfg)
        state = workflow.invoke({"input_payload": input_payload})
        status = str(state.get("task_status", "failed")).strip().lower()
        if status not in {"done", "failed"}:
            status = "failed"
        result = str(state.get("task_result", "")).strip() or "agentic rag sub-agent finished without result"
        return {"task_status": status, "task_result": result}


def _find_repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur] + list(cur.parents):
        candidate = parent / GRAPH_CONFIG_RELATIVE_PATH
        if candidate.exists() and candidate.is_file():
            return parent
    raise ValueError(f"failed to locate repo root by searching {GRAPH_CONFIG_RELATIVE_PATH}")


def _load_retrieval_policy() -> RetrievalPolicy:
    skill_dir = Path(__file__).resolve().parents[1]
    policy_path = skill_dir / DEFAULT_POLICY_RELATIVE_PATH
    if not policy_path.exists() or not policy_path.is_file():
        raise ValueError(f"retrieval policy not found: {policy_path}")

    try:
        payload = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to parse retrieval policy yaml: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("retrieval policy must be a mapping")

    try:
        validate(instance=payload, schema=POLICY_SCHEMA)
    except ValidationError as exc:
        raise ValueError(f"retrieval policy schema validation failed: {exc.message}") from exc

    runtime_cfg = payload["runtime"]
    retrieval_cfg = payload["retrieval"]
    grading_cfg = payload["grading"]
    prompts_cfg = payload["prompts"]
    response_cfg = payload["response"]

    return RetrievalPolicy(
        max_iterations=int(runtime_cfg["max_iterations"]),
        allow_rewrite=bool(runtime_cfg["allow_rewrite"]),
        rewrite_temperature=float(runtime_cfg["rewrite_temperature"]),
        max_docs_in_context=int(runtime_cfg["max_docs_in_context"]),
        retrieval_engine=str(retrieval_cfg["engine"]).strip(),
        retrieval_http_timeout_sec=float(retrieval_cfg["http_timeout_sec"]),
        retrieval_max_http_bytes=int(retrieval_cfg["max_http_bytes"]),
        bootstrap_web_limit=int(retrieval_cfg["bootstrap_web_limit"]),
        hybrid_web_limit=int(retrieval_cfg["hybrid_web_limit"]),
        hybrid_local_limit=int(retrieval_cfg["hybrid_local_limit"]),
        llm_min_confidence=float(grading_cfg["llm_min_confidence"]),
        min_docs_for_answer=int(grading_cfg["min_docs_for_answer"]),
        min_dedup_ratio=float(grading_cfg["min_dedup_ratio"]),
        min_avg_snippet_chars=int(grading_cfg["min_avg_snippet_chars"]),
        grading_system=str(prompts_cfg["grading_system"]).strip(),
        rewrite_system=str(prompts_cfg["rewrite_system"]).strip(),
        answer_system=str(prompts_cfg["answer_system"]).strip(),
        response_agent_mode=str(response_cfg["agent_mode"]).strip(),
        response_usage_note=str(response_cfg["usage_note"]).strip(),
        no_result_message=str(response_cfg["no_result_message"]).strip(),
    )


def _resolve_api_key(*, section_name: str, section_cfg: dict[str, Any], base_url: str) -> str:
    env_name = str(section_cfg.get("api_key_env", "")).strip()
    if env_name:
        value = str(os.getenv(env_name, "")).strip()
        if value:
            return value
    explicit = str(section_cfg.get("api_key", "")).strip()
    if explicit:
        return explicit
    host = ""
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        host = ""
    if host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return "EMPTY"
    raise ValueError(f"missing api key for config section '{section_name}'")


def _resolve_provider_section(root_cfg: dict[str, Any], *, section_name: str) -> dict[str, Any]:
    section = root_cfg.get(section_name)
    if not isinstance(section, dict):
        raise ValueError(f"missing config section '{section_name}'")

    providers = section.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError(f"config section '{section_name}.providers' must be a non-empty mapping")

    provider_env = str(section.get("provider_env", f"{section_name.upper()}_PROVIDER")).strip()
    default_provider = str(section.get("provider", "")).strip()
    selected_provider = str(os.getenv(provider_env, default_provider)).strip()
    if not selected_provider:
        raise ValueError(f"no provider selected for section '{section_name}'")

    provider_cfg = providers.get(selected_provider)
    if not isinstance(provider_cfg, dict):
        raise ValueError(f"unknown provider '{selected_provider}' in section '{section_name}'")

    return {
        "selected_provider": selected_provider,
        "provider_cfg": provider_cfg,
        "section_cfg": section,
    }


def _load_runtime_configs() -> tuple[ChatConfig, EmbeddingConfig]:
    repo_root = _find_repo_root()
    graph_cfg_path = repo_root / GRAPH_CONFIG_RELATIVE_PATH
    try:
        graph_cfg = yaml.safe_load(graph_cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to read graph config: {graph_cfg_path}: {exc}") from exc

    if not isinstance(graph_cfg, dict):
        raise ValueError("graph config must be a mapping")

    model_meta = _resolve_provider_section(graph_cfg, section_name="model")
    model_cfg = model_meta["provider_cfg"]
    model_root = model_meta["section_cfg"]
    model_name = str(model_cfg.get("name", "")).strip()
    model_base_url = str(model_cfg.get("base_url", "")).strip()
    if not model_name or not model_base_url:
        raise ValueError("model provider requires name and base_url")

    chat_cfg = ChatConfig(
        model=model_name,
        base_url=model_base_url,
        api_key=_resolve_api_key(section_name="model", section_cfg=model_cfg, base_url=model_base_url),
        timeout_sec=float(model_cfg.get("request_timeout_sec", model_root.get("request_timeout_sec", 90))),
        max_tokens=int(model_cfg.get("max_tokens", model_root.get("max_tokens", 1024))),
        temperature=float(model_root.get("temperature", model_cfg.get("temperature", 0))),
    )

    embedding_meta = _resolve_provider_section(graph_cfg, section_name="embedding")
    embedding_cfg = embedding_meta["provider_cfg"]
    embedding_name = str(embedding_cfg.get("name", "")).strip()
    embedding_base_url = str(embedding_cfg.get("base_url", "")).strip()
    if not embedding_name or not embedding_base_url:
        raise ValueError("embedding provider requires name and base_url")

    emb = EmbeddingConfig(
        model=embedding_name,
        base_url=embedding_base_url,
        api_key=_resolve_api_key(section_name="embedding", section_cfg=embedding_cfg, base_url=embedding_base_url),
        timeout_sec=float(embedding_cfg.get("request_timeout_sec", 60)),
    )

    return chat_cfg, emb


def _safe_http_get_text(*, url: str, timeout_sec: float, max_bytes: int) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "task-routing-pyskill-agentic-rag/2.0",
            "Accept": "application/rss+xml, application/xml, text/xml, text/plain, */*",
        },
    )
    with urlopen(request, timeout=timeout_sec) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="ignore")


def _openai_post_json(*, base_url: str, path: str, api_key: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="ignore")
    try:
        value = json.loads(text)
    except Exception as exc:
        raise ValueError(f"invalid json response from {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid response shape from {url}")
    return value


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text).strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _chat_json(*, chat_cfg: ChatConfig, system_prompt: str, user_payload: dict[str, Any], temperature: float | None = None) -> dict[str, Any]:
    body = {
        "model": chat_cfg.model,
        "temperature": chat_cfg.temperature if temperature is None else float(temperature),
        "max_tokens": chat_cfg.max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    resp = _openai_post_json(
        base_url=chat_cfg.base_url,
        path="/chat/completions",
        api_key=chat_cfg.api_key,
        payload=body,
        timeout_sec=chat_cfg.timeout_sec,
    )
    choices = resp.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = msg.get("content", "") if isinstance(msg, dict) else ""
    if isinstance(content, list):
        content = "\n".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
    return _extract_json_object(str(content))


def _embed_texts(*, embedding_cfg: EmbeddingConfig, texts: list[str]) -> list[list[float]]:
    cleaned = [str(item).strip() for item in texts if str(item).strip()]
    if not cleaned:
        return []
    body = {
        "model": embedding_cfg.model,
        "input": cleaned,
    }
    resp = _openai_post_json(
        base_url=embedding_cfg.base_url,
        path="/embeddings",
        api_key=embedding_cfg.api_key,
        payload=body,
        timeout_sec=embedding_cfg.timeout_sec,
    )
    data = resp.get("data")
    if not isinstance(data, list):
        return []

    output: list[list[float]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        emb = item.get("embedding")
        if not isinstance(emb, list):
            continue
        vec: list[float] = []
        for x in emb:
            try:
                vec.append(float(x))
            except Exception:
                vec.append(0.0)
        if vec:
            output.append(vec)
    return output


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for ai, bi in zip(a, b):
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _parse_bing_rss_results(*, xml_text: str, limit: int) -> list[dict[str, str]]:
    try:
        root = SafeElementTree.fromstring(xml_text)
    except Exception:
        return []

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in root.findall("./channel/item"):
        title = str(item.findtext("title") or "").strip()
        link = str(item.findtext("link") or "").strip()
        desc = str(item.findtext("description") or "").strip()
        if not link or link in seen_urls:
            continue
        seen_urls.add(link)
        results.append({"title": title, "url": link, "snippet": desc})
        if len(results) >= limit:
            break
    return results


def _search_web_docs(*, query: str, limit: int, policy: RetrievalPolicy) -> list[dict[str, Any]]:
    query_text = str(query).strip()
    if not query_text:
        return []
    rss_url = f"https://www.bing.com/search?q={quote_plus(query_text)}&format=rss"
    try:
        xml_text = _safe_http_get_text(
            url=rss_url,
            timeout_sec=policy.retrieval_http_timeout_sec,
            max_bytes=policy.retrieval_max_http_bytes,
        )
    except URLError:
        return []
    except Exception:
        return []

    results = _parse_bing_rss_results(xml_text=xml_text, limit=limit)
    out: list[dict[str, Any]] = []
    for item in results:
        out.append(
            {
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "snippet": str(item.get("snippet", "")).strip(),
                "source": "web",
                "retrieved_by_query": query_text,
            }
        )
    return out


def _doc_text(doc: dict[str, Any]) -> str:
    title = str(doc.get("title", "")).strip()
    snippet = str(doc.get("snippet", "")).strip()
    return f"{title}\n{snippet}".strip()


def _chunk_text(text: str, *, max_chars: int = 500, overlap: int = 80) -> list[str]:
    raw = str(text).strip()
    if not raw:
        return []
    if len(raw) <= max_chars:
        return [raw]
    out: list[str] = []
    step = max(1, max_chars - overlap)
    idx = 0
    while idx < len(raw):
        out.append(raw[idx : idx + max_chars])
        idx += step
    return out


def _build_semantic_chunks(*, docs: list[dict[str, Any]], embedding_cfg: EmbeddingConfig) -> list[dict[str, Any]]:
    base_chunks: list[dict[str, Any]] = []
    texts: list[str] = []

    for doc in docs:
        text = _doc_text(doc)
        if not text:
            continue
        for chunk in _chunk_text(text):
            base_chunks.append(
                {
                    "title": str(doc.get("title", "")).strip(),
                    "url": str(doc.get("url", "")).strip(),
                    "snippet": str(doc.get("snippet", "")).strip(),
                    "chunk": chunk,
                    "source": "local_semantic",
                }
            )
            texts.append(chunk)

    vectors = _embed_texts(embedding_cfg=embedding_cfg, texts=texts)
    if not vectors or len(vectors) != len(base_chunks):
        return []

    for idx, vec in enumerate(vectors):
        base_chunks[idx]["vector"] = vec
    return base_chunks


def _semantic_retrieve(*, query: str, semantic_chunks: list[dict[str, Any]], embedding_cfg: EmbeddingConfig, top_k: int) -> list[dict[str, Any]]:
    if not semantic_chunks:
        return []

    q_vectors = _embed_texts(embedding_cfg=embedding_cfg, texts=[query])
    if not q_vectors:
        return []
    q_vec = q_vectors[0]

    scored: list[dict[str, Any]] = []
    for item in semantic_chunks:
        vec = item.get("vector")
        if not isinstance(vec, list):
            continue
        score = _cosine(q_vec, [float(x) for x in vec])
        scored.append({"score": score, "doc": item})

    scored.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    out: list[dict[str, Any]] = []
    for item in scored[: max(1, top_k)]:
        doc = item.get("doc", {})
        if not isinstance(doc, dict):
            continue
        out.append(
            {
                "title": str(doc.get("title", "")).strip(),
                "url": str(doc.get("url", "")).strip(),
                "snippet": str(doc.get("snippet", "")).strip(),
                "source": "local_semantic",
                "retrieved_by_query": query,
                "semantic_score": round(float(item.get("score", 0.0)), 6),
            }
        )
    return out


def _dedupe_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in docs:
        url = str(doc.get("url", "")).strip()
        snippet = str(doc.get("snippet", "")).strip()
        key = (url, snippet)
        if not url and not snippet:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def _docs_for_llm(docs: list[dict[str, Any]], *, max_docs: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, doc in enumerate(docs[: max(1, max_docs)]):
        out.append(
            {
                "index": idx,
                "title": str(doc.get("title", "")).strip(),
                "url": str(doc.get("url", "")).strip(),
                "snippet": str(doc.get("snippet", "")).strip(),
                "source": str(doc.get("source", "")).strip(),
            }
        )
    return out


def _validate_input(state: FlowState) -> FlowState:
    payload = state.get("input_payload", {})
    if not isinstance(payload, dict):
        return {"task_status": "failed", "task_result": "input must be a json object"}

    query_value = str(payload.get("query", "")).strip()
    if not query_value:
        return {"task_status": "failed", "task_result": "query is empty"}
    if len(query_value) > MAX_WEB_SEARCH_QUERY_CHARS:
        return {
            "task_status": "failed",
            "task_result": f"query is too long (>{MAX_WEB_SEARCH_QUERY_CHARS})",
        }

    try:
        limit_value = int(payload.get("limit", 3))
    except Exception:
        limit_value = 3
    limit_value = max(1, min(MAX_WEB_SEARCH_RESULTS, limit_value))

    return {
        "query": query_value,
        "current_query": query_value,
        "limit": limit_value,
        "iteration": 1,
        "query_history": [query_value],
    }


def _bootstrap_retrieval(state: FlowState, *, policy: RetrievalPolicy) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}
    query = str(state.get("current_query", "")).strip()
    docs = _search_web_docs(query=query, limit=policy.bootstrap_web_limit, policy=policy)
    if not docs:
        return {"task_status": "failed", "task_result": "bootstrap retrieval returned no result"}
    return {"bootstrap_docs": _dedupe_docs(docs)}


def _build_local_semantic_index(state: FlowState, *, embedding_cfg: EmbeddingConfig) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}

    docs = state.get("bootstrap_docs", [])
    if not isinstance(docs, list) or not docs:
        return {"task_status": "failed", "task_result": "no bootstrap docs for semantic index"}

    chunks = _build_semantic_chunks(docs=docs, embedding_cfg=embedding_cfg)
    if not chunks:
        return {"task_status": "failed", "task_result": "failed to build local semantic index"}
    return {"semantic_chunks": chunks}


def _hybrid_retrieve(state: FlowState, *, policy: RetrievalPolicy, embedding_cfg: EmbeddingConfig) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}

    query = str(state.get("current_query", "")).strip()
    if not query:
        return {"task_status": "failed", "task_result": "current query is empty"}

    web_docs = _search_web_docs(query=query, limit=policy.hybrid_web_limit, policy=policy)
    semantic_chunks = state.get("semantic_chunks", [])
    local_docs = _semantic_retrieve(
        query=query,
        semantic_chunks=semantic_chunks if isinstance(semantic_chunks, list) else [],
        embedding_cfg=embedding_cfg,
        top_k=policy.hybrid_local_limit,
    )

    merged = _dedupe_docs(web_docs + local_docs)
    if not merged:
        return {"task_status": "failed", "task_result": "hybrid retrieval returned no result"}
    return {"hybrid_docs": merged}


def _llm_grade_relevance(state: FlowState, *, policy: RetrievalPolicy, chat_cfg: ChatConfig) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}

    query = str(state.get("query", "")).strip()
    current_query = str(state.get("current_query", "")).strip()
    docs = state.get("hybrid_docs", [])
    if not isinstance(docs, list) or not docs:
        return {"task_status": "failed", "task_result": "no docs for relevance grading"}

    doc_view = _docs_for_llm(docs, max_docs=policy.max_docs_in_context)
    payload = {
        "task": "Assess whether current evidence is sufficient to answer the user query.",
        "query": query,
        "current_query": current_query,
        "docs": doc_view,
        "output_schema": {
            "decision": "enough|insufficient",
            "confidence": "0~1",
            "reason": "short explanation",
            "selected_indices": "integer array",
        },
    }
    result = _chat_json(chat_cfg=chat_cfg, system_prompt=policy.grading_system, user_payload=payload)

    decision = str(result.get("decision", "insufficient")).strip().lower()
    if decision not in {"enough", "insufficient"}:
        decision = "insufficient"
    try:
        confidence = float(result.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(result.get("reason", "")).strip() or "llm grader returned empty reason"

    selected_indices: list[int] = []
    raw_indices = result.get("selected_indices", [])
    if isinstance(raw_indices, list):
        for item in raw_indices:
            try:
                idx = int(item)
            except Exception:
                continue
            if 0 <= idx < len(doc_view):
                selected_indices.append(idx)

    selected_docs: list[dict[str, Any]] = []
    if selected_indices:
        for idx in selected_indices:
            selected_docs.append(dict(docs[idx]))
    else:
        selected_docs = [dict(item) for item in docs[: max(1, min(policy.min_docs_for_answer, len(docs)))]]

    return {
        "grade_decision": decision,
        "grade_confidence": confidence,
        "grade_reason": reason,
        "selected_docs": selected_docs,
    }


def _heuristic_guardrail(state: FlowState, *, policy: RetrievalPolicy) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}

    docs = state.get("selected_docs", [])
    if not isinstance(docs, list):
        docs = []
    total = len(docs)
    unique_url = len({str(doc.get("url", "")).strip() for doc in docs if str(doc.get("url", "")).strip()})
    dedup_ratio = (unique_url / total) if total > 0 else 0.0

    snippets = [str(doc.get("snippet", "")).strip() for doc in docs if str(doc.get("snippet", "")).strip()]
    avg_snippet_chars = (sum(len(item) for item in snippets) / len(snippets)) if snippets else 0.0

    source_counts: dict[str, int] = {}
    for doc in docs:
        source = str(doc.get("source", "unknown")).strip() or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1

    llm_decision = str(state.get("grade_decision", "insufficient")).strip().lower()
    try:
        llm_conf = float(state.get("grade_confidence", 0.0))
    except Exception:
        llm_conf = 0.0

    pass_docs = total >= policy.min_docs_for_answer
    pass_dedup = dedup_ratio >= policy.min_dedup_ratio
    pass_snippet = avg_snippet_chars >= float(policy.min_avg_snippet_chars)
    pass_llm = llm_decision == "enough" and llm_conf >= policy.llm_min_confidence

    enough = bool(pass_docs and pass_dedup and pass_snippet and pass_llm)
    reason = str(state.get("grade_reason", "")).strip()
    if not enough:
        reason = reason or "heuristic guardrail rejected current evidence"

    return {
        "heuristic": {
            "total_docs": total,
            "unique_url": unique_url,
            "dedup_ratio": round(dedup_ratio, 4),
            "avg_snippet_chars": round(avg_snippet_chars, 2),
            "source_counts": source_counts,
            "pass_docs": pass_docs,
            "pass_dedup": pass_dedup,
            "pass_snippet": pass_snippet,
            "pass_llm": pass_llm,
        },
        "grade_decision": "enough" if enough else "insufficient",
        "grade_reason": reason,
    }


def _rewrite_query(state: FlowState, *, policy: RetrievalPolicy, chat_cfg: ChatConfig) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return {}

    query = str(state.get("query", "")).strip()
    current_query = str(state.get("current_query", "")).strip()
    reason = str(state.get("grade_reason", "")).strip()
    docs = state.get("hybrid_docs", [])
    doc_view = _docs_for_llm(docs if isinstance(docs, list) else [], max_docs=policy.max_docs_in_context)

    payload = {
        "task": "Rewrite retrieval query to improve evidence quality while keeping user intent unchanged.",
        "user_query": query,
        "current_query": current_query,
        "reason": reason,
        "docs": doc_view,
        "output_schema": {"rewritten_query": "string"},
    }
    result = _chat_json(
        chat_cfg=chat_cfg,
        system_prompt=policy.rewrite_system,
        user_payload=payload,
        temperature=policy.rewrite_temperature,
    )

    rewritten = str(result.get("rewritten_query", "")).strip()
    if not rewritten:
        rewritten = current_query
    if len(rewritten) > MAX_WEB_SEARCH_QUERY_CHARS:
        rewritten = rewritten[:MAX_WEB_SEARCH_QUERY_CHARS]

    history = list(state.get("query_history", []))
    if rewritten and rewritten not in history:
        history.append(rewritten)

    return {
        "current_query": rewritten,
        "query_history": history,
        "iteration": int(state.get("iteration", 1) or 1) + 1,
    }


def _synthesize_answer(state: FlowState, *, policy: RetrievalPolicy, chat_cfg: ChatConfig) -> FlowState:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return state

    query = str(state.get("query", "")).strip()
    decision = str(state.get("grade_decision", "insufficient")).strip().lower()
    docs = state.get("selected_docs", [])
    if not isinstance(docs, list) or not docs or decision != "enough":
        payload = {
            "query": query,
            "task_status": "failed",
            "reason": str(state.get("grade_reason", "")).strip() or policy.no_result_message,
            "heuristic": state.get("heuristic", {}),
            "query_history": state.get("query_history", []),
            "agent_mode": policy.response_agent_mode,
        }
        return {"task_status": "failed", "task_result": json.dumps(payload, ensure_ascii=False)}

    doc_view = _docs_for_llm(docs, max_docs=policy.max_docs_in_context)
    payload = {
        "task": "Produce a concise answer based only on evidence. If evidence conflicts, mention uncertainty.",
        "query": query,
        "docs": doc_view,
        "output_schema": {
            "answer": "string",
            "key_points": ["string"],
            "uncertainty": "string",
        },
    }
    ans = _chat_json(chat_cfg=chat_cfg, system_prompt=policy.answer_system, user_payload=payload)

    answer = str(ans.get("answer", "")).strip()
    if not answer:
        answer = policy.no_result_message

    key_points_raw = ans.get("key_points", [])
    key_points: list[str] = []
    if isinstance(key_points_raw, list):
        for item in key_points_raw:
            text = str(item).strip()
            if text:
                key_points.append(text)

    output: dict[str, Any] = {
        "query": query,
        "answer": answer,
        "key_points": key_points,
        "uncertainty": str(ans.get("uncertainty", "")).strip(),
        "evidence": doc_view,
        "query_history": state.get("query_history", []),
        "heuristic": state.get("heuristic", {}),
        "agent_mode": policy.response_agent_mode,
        "engine": policy.retrieval_engine,
        "usage_note": policy.response_usage_note,
    }

    return {
        "task_status": "done",
        "task_result": json.dumps(output, ensure_ascii=False),
    }


def _decide_next(state: FlowState, *, policy: RetrievalPolicy) -> str:
    if str(state.get("task_status", "")).strip().lower() == "failed":
        return "synthesize"

    decision = str(state.get("grade_decision", "insufficient")).strip().lower()
    iteration = int(state.get("iteration", 1) or 1)

    if decision == "enough":
        return "synthesize"
    if not policy.allow_rewrite:
        return "synthesize"
    if iteration >= policy.max_iterations:
        return "synthesize"
    return "rewrite"


def _build_workflow(*, policy: RetrievalPolicy, chat_cfg: ChatConfig, embedding_cfg: EmbeddingConfig) -> Any:
    builder = StateGraph(FlowState)
    builder.add_node("validate_input", _validate_input)
    builder.add_node("bootstrap_retrieval", lambda state: _bootstrap_retrieval(state, policy=policy))
    builder.add_node("build_local_semantic_index", lambda state: _build_local_semantic_index(state, embedding_cfg=embedding_cfg))
    builder.add_node("hybrid_retrieve", lambda state: _hybrid_retrieve(state, policy=policy, embedding_cfg=embedding_cfg))
    builder.add_node("llm_grade_relevance", lambda state: _llm_grade_relevance(state, policy=policy, chat_cfg=chat_cfg))
    builder.add_node("heuristic_guardrail", lambda state: _heuristic_guardrail(state, policy=policy))
    builder.add_node("rewrite_query", lambda state: _rewrite_query(state, policy=policy, chat_cfg=chat_cfg))
    builder.add_node("synthesize_answer", lambda state: _synthesize_answer(state, policy=policy, chat_cfg=chat_cfg))

    builder.add_edge(START, "validate_input")
    builder.add_edge("validate_input", "bootstrap_retrieval")
    builder.add_edge("bootstrap_retrieval", "build_local_semantic_index")
    builder.add_edge("build_local_semantic_index", "hybrid_retrieve")
    builder.add_edge("hybrid_retrieve", "llm_grade_relevance")
    builder.add_edge("llm_grade_relevance", "heuristic_guardrail")
    builder.add_conditional_edges(
        "heuristic_guardrail",
        lambda state: _decide_next(state, policy=policy),
        {
            "rewrite": "rewrite_query",
            "synthesize": "synthesize_answer",
        },
    )
    builder.add_edge("rewrite_query", "hybrid_retrieve")
    builder.add_edge("synthesize_answer", END)
    return builder.compile()


def _main() -> int:
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        print(json.dumps({"task_status": "failed", "task_result": "input is empty"}, ensure_ascii=False))
        return 0

    try:
        input_payload = json.loads(raw_input)
    except Exception as exc:
        print(
            json.dumps(
                {"task_status": "failed", "task_result": f"input is not valid json: {exc}"},
                ensure_ascii=False,
            )
        )
        return 0

    if not isinstance(input_payload, dict):
        print(json.dumps({"task_status": "failed", "task_result": "input must be a json object"}, ensure_ascii=False))
        return 0

    try:
        policy = _load_retrieval_policy()
    except Exception as exc:
        print(
            json.dumps(
                {"task_status": "failed", "task_result": f"retrieval policy error: {exc}"},
                ensure_ascii=False,
            )
        )
        return 0

    try:
        chat_cfg, embedding_cfg = _load_runtime_configs()
    except Exception as exc:
        print(
            json.dumps(
                {"task_status": "failed", "task_result": f"runtime config error: {exc}"},
                ensure_ascii=False,
            )
        )
        return 0

    sub_agent = TimeRangeRagSubAgent(policy=policy, chat_cfg=chat_cfg, embedding_cfg=embedding_cfg)
    payload = sub_agent.run(input_payload=input_payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
