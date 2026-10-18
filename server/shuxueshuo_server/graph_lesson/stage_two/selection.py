"""One text-only type selection, with exact-request recordings and bounded transport."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow_ledger import (
    failed_attempts_payload,
    save,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekTextProblemDomainProvider,
    MultimodalExtractionPrompt,
    MultimodalProviderResponse,
    ProviderSubAttempt,
)

from .fragments import _scope_ranges

CONTRACT = "graph-stage-two-selection/v1"
REPO = Path(__file__).resolve().parents[4]
PROMPT_PATH = REPO / "internal/llm-prompts/graph-stage-two-selection.md"
SCHEMA_PATH = REPO / "internal/schemas/graph-stage-two-selection-v1.schema.json"
_TARGET = re.compile(r"^/root(?:/children/\d+)*/goals/\d+$")
_STATES = {"supported", "conflict", "unknown"}


class SelectionError(ValueError):
    def __init__(self, code, path="", message=None):
        self.code, self.path = code, path
        super().__init__(message or code)


class _RecordedFailure(SelectionError):
    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(diagnostic["code"], diagnostic.get("path", ""))


def selection_schema():
    return json.loads(SCHEMA_PATH.read_text())


@dataclass(frozen=True)
class SelectionRequest:
    """The shared text transport's request protocol, without image evidence."""

    prompt: MultimodalExtractionPrompt
    contract_schema: dict
    model: str | None = None
    timeout: float = 120.0
    max_tokens: int = 4096
    contract_version: str = CONTRACT
    images: tuple = ()
    stream: bool = False
    thinking_mode: str = "disabled"
    reasoning_effort: str | None = None
    image_detail: str | None = None

    def thinking_payload(self):
        return {"thinking": {"type": self.thinking_mode}}

    def provider_messages(self):
        return [
            {"role": "system", "content": self.prompt.system},
            {"role": "user", "content": self.prompt.user_prefix},
        ]

    def redacted_payload(self):
        return {
            "contract": self.contract_version,
            "messages": self.provider_messages(),
            "contract_schema": self.contract_schema,
            "model": self.model,
            "response_format": {"type": "json_object"},
            "extra_body": self.thinking_payload(),
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "stream": self.stream,
        }


def _reports(type_reports, target_ref):
    supported, types, checks = [], set(), set()
    if not isinstance(type_reports, list):
        raise SelectionError("selection.invalid_report", "/types")
    for report in type_reports:
        type_id = report.get("type_id") if isinstance(report, dict) else None
        if not isinstance(type_id, str) or not type_id or type_id in types:
            raise SelectionError("selection.invalid_report", "/types/type_id")
        types.add(type_id)
        if report.get("status") not in _STATES or report.get("target_ref", target_ref) != target_ref:
            raise SelectionError("selection.invalid_report", "/types/status")
        branches, branch_ids = report.get("branches"), set()
        if not isinstance(branches, list) or not branches:
            raise SelectionError("selection.invalid_report", "/types/branches")
        for branch in branches:
            branch_id = branch.get("branch_id") if isinstance(branch, dict) else None
            if not isinstance(branch_id, str) or not branch_id or branch_id in branch_ids:
                raise SelectionError("selection.invalid_report", "/types/branches/branch_id")
            branch_ids.add(branch_id)
            if branch.get("status") not in _STATES or not isinstance(branch.get("checks"), list):
                raise SelectionError("selection.invalid_report", "/types/branches/checks")
            for check in branch["checks"]:
                check_id = check.get("check_id") if isinstance(check, dict) else None
                if not isinstance(check_id, str) or not check_id or check_id in checks:
                    raise SelectionError("selection.invalid_report", "/types/branches/checks/check_id")
                checks.add(check_id)
                if check.get("status") not in _STATES or check.get("target_ref", target_ref) != target_ref:
                    raise SelectionError("selection.invalid_report", "/types/branches/checks/status")
            if branch["status"] == "supported" and (
                not branch["checks"] or any(c["status"] != "supported" for c in branch["checks"])
            ):
                raise SelectionError("selection.inconsistent_report", "/types/branches")
        if report["status"] == "supported":
            if not any(b["status"] == "supported" for b in branches):
                raise SelectionError("selection.inconsistent_report", "/types")
            supported.append(deepcopy(report))
    if len(supported) < 2:
        raise SelectionError("selection.multiple_supported_required", "/types")
    return supported


def build_request(candidate, target_ref, type_reports):
    """Scope mathematical evidence; best-effort source clipping never blocks selection."""
    if not isinstance(target_ref, str) or not _TARGET.fullmatch(target_ref):
        raise SelectionError("selection.invalid_target", "/target_ref")
    try:
        goal = pointer(candidate, target_ref)
        scope_ref = target_ref.rsplit("/goals/", 1)[0]
        visible, current = [], "/root"
        parts = scope_ref[len(current):].split("/")[1:]
        for index in range(0, len(parts) + 1, 2):
            scope = pointer(candidate, current)
            visible.append({"scope": current, **{
                key: deepcopy(scope[key]) for key in ("label", "definitions", "facts") if key in scope
            }})
            if index < len(parts):
                current += f"/children/{parts[index + 1]}"
        if not isinstance(goal, dict) or not isinstance(candidate["original_text"], str):
            raise TypeError("invalid candidate")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SelectionError("selection.invalid_target", "/target_ref") from exc
    source_warning = None
    try:
        ranges = _scope_ranges(candidate, target_ref)
        if not ranges:
            raise ValueError("missing visible text")
        original_text = "\n".join(candidate["original_text"][start:end] for start, end in ranges)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        original_text = candidate["original_text"]
        source_warning = {
            "code": "selection.scope_text_fallback", "path": "/original_text",
            "reason": str(exc),
            "message": "未能按小问截取，已提供完整原文作为背景；只判断 target_ref 对应目标，"
                       "其条件与依据以 goal、visible_scopes、supported_types 为准。",
        }
    payload = {
        "contract": CONTRACT,
        "response_schema": selection_schema(),
        "candidate_revision": revision(candidate),
        "target_ref": target_ref,
        "original_text": original_text,
        "goal": deepcopy(goal),
        "visible_scopes": visible,
        "supported_types": _reports(type_reports, target_ref),
    }
    if source_warning is not None:
        payload["original_text_fallback"] = source_warning
    return SelectionRequest(
        MultimodalExtractionPrompt(PROMPT_PATH.read_text().strip(),
            json.dumps(payload, ensure_ascii=False, sort_keys=True), "", includes_images=False),
        selection_schema(),
    )


def validate_selection(text, target_ref, type_reports, *, finish_reason):
    if finish_reason != "stop":
        raise SelectionError("selection.invalid_finish_reason", "/finish_reason")
    try:
        value = strict_json(text)
    except (ValueError, TypeError, RecursionError) as exc:
        raise SelectionError("selection.invalid_json", "/response") from exc
    errors = list(Draft202012Validator(selection_schema()).iter_errors(value))
    if errors:
        raise SelectionError("selection.invalid_response", "/" + "/".join(map(str, errors[0].absolute_path)))
    if value["target_ref"] != target_ref:
        raise SelectionError("selection.target_mismatch", "/target_ref")
    reports = {r["type_id"]: r for r in _reports(type_reports, target_ref)}
    if value["primary_type_id"] not in reports:
        raise SelectionError("selection.unsupported_type", "/primary_type_id")
    branches = {b["branch_id"]: b for b in reports[value["primary_type_id"]]["branches"] if b["status"] == "supported"}
    if value["branch_id"] not in branches:
        raise SelectionError("selection.unsupported_branch", "/branch_id")
    allowed = {c["check_id"] for c in branches[value["branch_id"]]["checks"] if c["status"] == "supported"}
    if not set(value["check_ids"]) <= allowed:
        raise SelectionError("selection.invalid_check_reference", "/check_ids")
    return value


def live_provider_factory(provider_name="deepseek", *, model=None, timeout=120.0):
    """Return a lazy factory; deterministic paths never read keys or create clients."""
    def create():
        if os.getenv("RUN_LLM_INTEGRATION") != "1":
            raise SelectionError("selection.live_opt_in_required")
        if provider_name != "deepseek" or not 0 < timeout <= 300:
            raise SelectionError("selection.invalid_provider_configuration")
        from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig

        config = SolverRuntimeConfig.from_sources(llm_provider=provider_name)
        return DeepSeekTextProblemDomainProvider(
            api_key=config.deepseek_api_key or "", base_url=config.deepseek_base_url,
            model=model or config.llm_model or config.deepseek_model, request_timeout=timeout,
        )
    return create


class RecordedSelectionProvider:
    """Replay a completed recording only when the freshly prepared request matches."""

    is_replay = True

    @classmethod
    def from_run(cls, directory):
        """Route a run's independent recordings by their recorded target reference."""
        return _RecordedSelectionRouter(directory)

    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = strict_json((self.directory / "recording.json").read_text())
        self.request = strict_json((self.directory / "request.json").read_text())
        self.result = strict_json((self.directory / "selection-result.json").read_text())
        response_path = self.directory / "response.json"
        self.response = strict_json(response_path.read_text()) if response_path.exists() else None
        attempts_path = self.directory / "provider-attempts.json"
        self.attempts = strict_json(attempts_path.read_text()) if attempts_path.exists() else None
        if self.manifest.get("schema_version") != "graph-stage-two-selection-recording/v1" or (
            revision(self.request) != self.manifest.get("request_hash")
            or revision(self.result) != self.manifest.get("result_hash")
            or (revision(self.response) if self.response is not None else None) != self.manifest.get("response_hash")
            or (revision(self.attempts) if self.attempts is not None else None) != self.manifest.get("attempts_hash")
        ):
            raise SelectionError("selection.recording_integrity")
        if self.response is None and (self.result.get("ok") is not False or not self.result.get("diagnostics")):
            raise SelectionError("selection.recording_integrity")
        self.model = self.request["model"]
        self.request_timeout = self.request["timeout"]
        self.last_provider_attempts = ()
        self.last_completion_started = False
        self.calls = 0

    def prepare_request(self, request):
        return replace(request, model=self.model, timeout=self.request_timeout, stream=False)

    def historical_counts(self, request):
        return deepcopy(self.manifest.get("historical_counts", self.manifest["counts"]))

    def historical_attempts(self, request):
        if revision(request.redacted_payload()) != self.manifest["request_hash"]:
            raise SelectionError("selection.recording_request_mismatch")
        return deepcopy(self.attempts)

    def complete(self, request):
        if revision(request.redacted_payload()) != self.manifest["request_hash"]:
            raise SelectionError("selection.recording_request_mismatch")
        self.calls += 1
        if self.calls != 1:
            raise SelectionError("selection.recording_already_used")
        if self.response is None:
            raise _RecordedFailure(self.result["diagnostics"][0])
        metadata = self.response["metadata"]
        attempts = tuple(ProviderSubAttempt(**a) for a in self.response["provider_attempts"])
        return MultimodalProviderResponse(
            text=self.response["text"], raw_payload=self.response["raw_payload"],
            request_model=self.model, response_model=metadata.get("response_model"),
            usage=metadata.get("usage"), finish_reason=self.response["finish_reason"],
            provider_attempts=attempts, latency_ms=0, thinking_mode="disabled", reasoning_effort=None,
            contract_version=CONTRACT, provider_name="recorded",
        )


class _RecordedSelectionRouter:
    is_replay = True

    def __init__(self, directory):
        self.providers = {}
        for request_path in sorted((Path(directory) / "calls").glob("*/request.json")):
            provider = RecordedSelectionProvider(request_path.parent)
            payload = json.loads(provider.request["messages"][1]["content"])
            target = payload["target_ref"]
            if target in self.providers:
                raise SelectionError("selection.recording_duplicate_target")
            self.providers[target] = provider

    def _provider(self, request):
        target = json.loads(request.prompt.user_prefix)["target_ref"]
        if target not in self.providers:
            raise SelectionError("selection.recording_missing_target", target)
        return self.providers[target]

    def prepare_request(self, request):
        return self._provider(request).prepare_request(request)

    def complete(self, request):
        return self._provider(request).complete(request)

    def historical_counts(self, request):
        return self._provider(request).historical_counts(request)

    def historical_attempts(self, request):
        return self._provider(request).historical_attempts(request)


def select_primary(candidate, target_ref, type_reports, output: Path, provider=None):
    """Persist one immutable attempt; failures retain candidates without choosing one."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    llm = {"status": "failed", "mode": "provider", "semantic_calls": 0, "network_attempts": 0,
           "candidate_ids": [], "request_ref": None, "response_ref": None,
           "timeout_seconds": None, "max_network_attempts": 2, "validation": {"ok": False}}
    result = {"ok": False, "primary": None, "diagnostics": [], "llm": llm}
    request_payload, response_payload, attempts_payload, resolved = None, None, None, None
    try:
        request = build_request(candidate, target_ref, type_reports)
        source_warning = json.loads(request.prompt.user_prefix).get("original_text_fallback")
        if source_warning is not None:
            llm["input_warnings"] = [source_warning]
        llm["candidate_ids"] = [r["type_id"] for r in _reports(type_reports, target_ref)]
        # Keep the logical request even if credentials/client creation fails.
        request_payload = request.redacted_payload()
        save(output / "request.json", request_payload)
        llm.update(request_ref="request.json", request_hash=revision(request_payload), timeout_seconds=request.timeout)
        if provider is not None:
            resolved = provider() if callable(provider) and not hasattr(provider, "complete") else provider
            if not hasattr(resolved, "prepare_request") or not hasattr(resolved, "complete"):
                raise SelectionError("selection.invalid_provider")
            request = resolved.prepare_request(request)
            request = replace(request, model=getattr(resolved, "model", request.model))
        request_payload = request.redacted_payload()
        save(output / "request.json", request_payload)
        llm.update(request_ref="request.json", request_hash=revision(request_payload), timeout_seconds=request.timeout)
        if resolved is None:
            raise SelectionError("selection.provider_required")
        replay = bool(getattr(resolved, "is_replay", False))
        llm["mode"] = "recorded" if replay else "provider"
        llm["semantic_calls"] = 0 if replay else 1
        if replay:
            llm["historical_counts"] = resolved.historical_counts(request)
            attempts_payload = resolved.historical_attempts(request)
            if attempts_payload is not None:
                save(output / "provider-attempts.json", attempts_payload)
                llm["historical_attempts_ref"] = "provider-attempts.json"
        response = resolved.complete(request)
        # The response retains complete provider-authored choices. Exception
        # strings are excluded from the separately persisted failed attempts.
        response_payload = {
            "text": response.text, "finish_reason": response.finish_reason,
            "raw_payload": dict(response.raw_payload),
            "metadata": {k: v for k, v in response.metadata_payload().items() if k != "provider_attempts"},
            "provider_attempts": [a.to_payload() for a in response.provider_attempts],
        }
        # Attempt errors may contain URLs/credentials; retain only the shared allowlist.
        for item in response_payload["provider_attempts"]:
            item.pop("error_message", None)
        save(output / "response.json", response_payload)
        llm["response_ref"] = "response.json"
        if not replay:
            llm["network_attempts"] = len(response.provider_attempts)
        if not 1 <= len(response.provider_attempts) <= 2:
            raise SelectionError("selection.network_budget")
        selected = validate_selection(response.text, target_ref, type_reports, finish_reason=response.finish_reason)
        result.update(ok=True, primary=selected["primary_type_id"])
        llm.update(status="succeeded", selection=selected, validation={"ok": True})
    except Exception as exc:  # noqa: BLE001 - each goal retains its own failed selection
        code = exc.code if isinstance(exc, SelectionError) else "selection.provider_failed"
        diagnostic = deepcopy(exc.diagnostic) if isinstance(exc, _RecordedFailure) else {
            "code": code, "path": getattr(exc, "path", ""), "error_type": type(exc).__name__}
        result["diagnostics"].append(diagnostic)
        llm["validation"] = {"ok": False, "diagnostics": [diagnostic]}
        if resolved is not None and not getattr(resolved, "is_replay", False):
            attempts_payload = failed_attempts_payload(resolved)
            save(output / "provider-attempts.json", attempts_payload)
            llm["attempts_ref"] = "provider-attempts.json"
            llm["network_attempts"] = len(attempts_payload["attempts"]) or int(bool(getattr(resolved, "last_completion_started", False)))
    llm["elapsed_seconds"] = round(perf_counter() - started, 6)
    llm["new_semantic_calls"] = llm["semantic_calls"]
    llm["new_network_attempts"] = llm["network_attempts"]
    save(output / "selection-result.json", result)
    save(output / "recording.json", {
        "schema_version": "graph-stage-two-selection-recording/v1",
        "request_hash": revision(request_payload) if request_payload is not None else None,
        "response_hash": revision(response_payload) if response_payload is not None else None,
        **({"attempts_hash": revision(attempts_payload)} if attempts_payload is not None else {}),
        "result_hash": revision(result),
        "counts": {k: llm[k] for k in ("semantic_calls", "network_attempts")},
        **({"historical_counts": llm["historical_counts"]} if "historical_counts" in llm else {}),
        "mode": llm["mode"],
    })
    return result
