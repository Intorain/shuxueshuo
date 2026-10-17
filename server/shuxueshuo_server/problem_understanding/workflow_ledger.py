"""Crash-safe at-most-once call reservations for the isolated workflow."""

import fcntl
import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from .identity import revision


class WorkflowStop(ValueError):
    pass


@dataclass(frozen=True)
class Budget:
    content: int = 3
    review: int = 3
    semantic: int = 6
    network: int = 12

    def __post_init__(self):
        for key, ceiling in (
            ("content", 3),
            ("review", 3),
            ("semantic", 6),
            ("network", 12),
        ):
            if not 1 <= getattr(self, key) <= ceiling:
                raise ValueError("workflow.invalid_budget")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()
        )
        f.flush()
        os.fsync(f.fileno())
        temp = f.name
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


_USAGE_FIELDS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "audio_tokens",
    "text_tokens",
    "image_tokens",
    "accepted_prediction_tokens",
    "rejected_prediction_tokens",
    "prompt_tokens_details",
    "completion_tokens_details",
    "input_tokens_details",
    "output_tokens_details",
}


def _safe_usage(value):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return None
    return {
        key: _safe_usage(item) if isinstance(item, Mapping) else item
        for key, item in value.items()
        if key in _USAGE_FIELDS
        and (
            isinstance(item, Mapping)
            or type(item) in (int, float)
            and math.isfinite(item)
            and item >= 0
        )
    }


def _safe_text(value, secrets):
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    for secret in secrets:
        value = value.replace(secret, "[redacted-credential]")
    value = re.sub(
        r"https?://[^\s<>\"']+", "[redacted-url]", value, flags=re.IGNORECASE
    )
    value = re.sub(
        r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
        "[redacted-credential]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:api[_-]?key|authorization|proxy-authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\b[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
        "[redacted-credential]",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted-credential]", value)


def _safe_content(value, secrets):
    if value is None or isinstance(value, str):
        return _safe_text(value, secrets)
    if isinstance(value, list):
        return [
            {
                key: _safe_text(item[key], secrets)
                for key in ("type", "text")
                if key in item
            }
            for item in value
            if isinstance(item, Mapping) and item.get("type") in ("text", "output_text")
        ]
    return None


def _safe_response_payload(value, secrets):
    """Persist model output and usage, never arbitrary SDK/request metadata."""
    if not isinstance(value, Mapping):
        return None
    result = {
        key: _safe_text(value[key], secrets)
        for key in ("id", "object", "model", "finish_reason")
        if key in value
    }
    if "usage" in value:
        result["usage"] = _safe_usage(value["usage"])
    for key in ("created", "received_output_characters"):
        if type(value.get(key)) is int:
            result[key] = value[key]
    if type(value.get("stream_terminated_at_json")) is bool:
        result["stream_terminated_at_json"] = value["stream_terminated_at_json"]
    for key in ("content", "reasoning_content", "reasoning"):
        if key in value:
            result[key] = _safe_content(value[key], secrets)
    if isinstance(value.get("choices"), list):
        choices = []
        for choice in value["choices"]:
            if not isinstance(choice, Mapping):
                continue
            saved = {}
            if type(choice.get("index")) is int:
                saved["index"] = choice["index"]
            if "finish_reason" in choice:
                saved["finish_reason"] = _safe_text(choice["finish_reason"], secrets)
            if "text" in choice:
                saved["text"] = _safe_content(choice["text"], secrets)
            for field in ("message", "delta"):
                if isinstance(choice.get(field), Mapping):
                    message = choice[field]
                    saved[field] = {
                        key: _safe_content(message[key], secrets)
                        for key in (
                            "role",
                            "content",
                            "reasoning_content",
                            "reasoning",
                            "refusal",
                        )
                        if key in message
                    }
            choices.append(saved)
        result["choices"] = choices
    return result


def _safe_provider_attempts(provider, provider_attempts):
    """Keep structured attempt evidence, including recovered transport failures."""
    secret = getattr(provider, "api_key", None)
    secrets = [secret] if isinstance(secret, str) and len(secret) >= 4 else []
    attempts = []
    for attempt in provider_attempts:
        item = attempt.to_payload() if hasattr(attempt, "to_payload") else attempt
        if not isinstance(item, Mapping):
            continue
        saved = {
            key: _safe_text(item[key], secrets)
            for key in ("status", "response_model", "finish_reason", "error_code")
            if key in item
        }
        for key in ("provider_attempt", "attempt", "latency_ms", "status_code"):
            if type(item.get(key)) is int:
                saved[key] = item[key]
        if type(item.get("visible_content")) is bool:
            saved["visible_content"] = item["visible_content"]
        if "usage" in item:
            saved["usage"] = _safe_usage(item["usage"])
        if "raw_payload" in item:
            saved["raw_payload"] = _safe_response_payload(item["raw_payload"], secrets)
        attempts.append(saved)
    return attempts


def failed_attempts_payload(provider):
    """Return available failed-call evidence using a narrow, explicit allowlist."""
    return {
        "schema_version": "problem-workflow-failed-attempts/v1",
        "attempts": _safe_provider_attempts(
            provider, getattr(provider, "last_provider_attempts", ())
        ),
    }


class Ledger:
    def __init__(self, directory, binding, budget):
        self.directory, self.binding, self.budget = Path(directory), binding, budget
        self.position, self.entries = 0, []

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / "workflow.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise WorkflowStop("workflow.concurrent_run") from exc
        try:
            self.path = self.directory / "ledger.json"
            identity = {"binding": self.binding, "budget": asdict(self.budget)}
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if data["identity"] != identity:
                    raise WorkflowStop("workflow.stale_binding")
                self.entries = data["calls"]
            else:
                self.flush()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def flush(self):
        save(
            self.path,
            {
                "identity": {"binding": self.binding, "budget": asdict(self.budget)},
                "calls": self.entries,
            },
        )

    def counts(self):
        return {
            "semantic_calls": len(self.entries),
            "content_calls": sum(e["stage"] != "review" for e in self.entries),
            "review_calls": sum(e["stage"] == "review" for e in self.entries),
            "network_attempts": sum(e.get("network_attempts", 0) for e in self.entries),
            "network_reserved": sum(e.get("network_attempts", 2) for e in self.entries),
            "file_api_calls": sum(e.get("file_api_calls", 0) for e in self.entries),
        }

    def complete(self, stage, request, base_revision, provider):
        prepared = provider.prepare_request(request)
        key = {
            "stage": stage,
            "request_hash": revision(prepared.redacted_payload()),
            "base_revision": base_revision,
        }
        position = self.position
        self.position += 1
        if position < len(self.entries):
            entry = self.entries[position]
            if any(entry[k] != v for k, v in key.items()):
                raise WorkflowStop("workflow.stale_response")
            if entry["status"] == "reserved":
                raise WorkflowStop("workflow.outcome_unknown")
            if entry["status"] == "failed":
                raise WorkflowStop(entry["error_code"])
            response = json.loads((self.directory / entry["response_file"]).read_text())
            if revision(response) != entry["response_hash"]:
                raise WorkflowStop("workflow.response_hash_mismatch")
            return response
        counts = self.counts()
        group = "review" if stage == "review" else "content"
        if (
            counts["semantic_calls"] >= self.budget.semantic
            or counts[group + "_calls"] >= getattr(self.budget, group)
            or counts["network_reserved"] + 2 > self.budget.network
        ):
            raise WorkflowStop("workflow.budget_exhausted")
        directory = self.directory / "calls" / f"{position + 1:02d}-{stage}"
        directory.mkdir(parents=True, exist_ok=True)
        save(directory / "request.json", prepared.redacted_payload())
        entry = {
            **key,
            "status": "reserved",
            "number": position + 1,
            "directory": str(directory.relative_to(self.directory)),
        }
        self.entries.append(entry)
        self.flush()  # Reservation is durable before any provider I/O.
        started = perf_counter()
        try:
            response = provider.complete(
                replace(prepared, transport_audit_directory=str(directory))
            )
            attempts = [
                a.to_payload() if hasattr(a, "to_payload") else a
                for a in response.provider_attempts
            ]
            if not 1 <= len(attempts) <= 2:
                raise WorkflowStop("workflow.provider_network_budget")
            metadata = dict(response.metadata_payload())
            if "provider_attempts" in metadata:
                # A successful retry can contain a prior exception string.
                # Apply the same allowlist as failed calls before persistence;
                # the model body and aggregate usage remain unchanged.
                metadata["provider_attempts"] = _safe_provider_attempts(
                    provider, attempts
                )
            saved = {
                "text": response.text,
                "finish_reason": response.finish_reason,
                "metadata": metadata,
                "raw_payload": dict(response.raw_payload),
                "network_attempts": len(attempts),
                "elapsed_seconds": round(perf_counter() - started, 3),
            }
            save(directory / "response.json", saved)
            entry.update(
                status="completed",
                response_file=str(
                    (directory / "response.json").relative_to(self.directory)
                ),
                response_hash=revision(saved),
                network_attempts=len(attempts),
                elapsed_seconds=saved["elapsed_seconds"],
                usage=saved["metadata"].get("usage"),
                file_api_calls=saved["metadata"].get("file_api_calls", 0),
            )
            self.flush()
            return saved
        except Exception as exc:
            # Provider failures can still have useful raw model responses.
            # Retain only structured allowlisted fields, never str(exc), SDK
            # objects, arbitrary headers or authenticated transport URLs.
            attempts = getattr(provider, "last_provider_attempts", ())
            evidence = failed_attempts_payload(provider)
            evidence_path = directory / "failed-attempts.json"
            save(evidence_path, evidence)
            entry.update(
                status="failed",
                error_code="workflow.provider_failed",
                error_type=type(exc).__name__,
                failed_attempts_file=str(evidence_path.relative_to(self.directory)),
                failed_attempts_hash=revision(evidence),
                elapsed_seconds=round(perf_counter() - started, 3),
                network_attempts=(
                    min(2, len(attempts))
                    if attempts
                    else 0
                    if getattr(provider, "last_completion_started", None) is False
                    else 2
                ),
                file_api_calls=sum(
                    e["api_calls"]
                    for e in getattr(provider, "last_file_operations", ())
                ),
            )
            self.flush()
            raise WorkflowStop(entry["error_code"]) from exc
