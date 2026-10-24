"""Student extraction adds public-content review without changing graph contracts."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    changed_paths,
    validate_candidate,
)
from shuxueshuo_server.graph_lesson.stage_one.runner import build_image_request
from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow_ledger import WorkflowStop
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalExtractionPrompt,
)

from .identity import (
    EXTRACTION_CONTRACT,
    PUBLIC_SCHEMA_PATH,
    candidate_schema,
    mathematical_candidate,
    public_structure_errors,
)

PUBLIC_PROMPT_PATH = contracts.ROOT / "internal/llm-prompts/search-stage-one-public.md"
REVIEW_CONTRACT = "search-problem-review/v1"


def review_schema():
    schema = contracts.review_schema()
    schema["properties"]["findings"]["items"]["properties"]["kind"]["enum"].append("wrong_public_content")
    return schema


def build_search_request(content, store):
    base = build_image_request(content, store)
    return replace(
        base,
        contract_version=EXTRACTION_CONTRACT,
        contract_schema=candidate_schema(),
        prompt=MultimodalExtractionPrompt(
            contracts.SYSTEM + "\n\n" + PUBLIC_PROMPT_PATH.read_text(encoding="utf-8"),
            json.dumps({"response_schema": candidate_schema(), "math_expression_catalog": contracts.expression_catalog()}, ensure_ascii=False),
            "对照完整题图，提取数学题意和可公开的完整题目内容。只返回指定 JSON。",
        ),
    )


class SearchStageOneContract(GraphStageOneContract):
    def validate_request(self, request, registry, mode):
        if registry or request.contract_version != EXTRACTION_CONTRACT or request.contract_schema != candidate_schema():
            raise WorkflowStop("workflow.unsupported_or_stale_contract")

    def schema(self):
        return candidate_schema()

    def frozen_files(self):
        files = super().frozen_files()
        for path in (PUBLIC_SCHEMA_PATH, PUBLIC_PROMPT_PATH, Path(__file__).with_name("identity.py"),
                     Path(__file__).with_name("stage_one.py"), __file__):
            path = Path(path)
            files[str(path.relative_to(contracts.ROOT))] = sha256(path.read_bytes()).hexdigest()
        return files

    def parse(self, raw, *, problem_id, source_hash, registry, store):
        try:
            candidate = strict_json(raw)
        except (ValueError, RecursionError) as exc:
            return {"contract": EXTRACTION_CONTRACT, "contract_valid": False,
                    "reports": {"json": {"ok": False, "issues": [str(exc)]}}}
        parsed = validate_candidate(mathematical_candidate(candidate))
        parsed.update(contract=EXTRACTION_CONTRACT, revision=revision(candidate),
                      binding={"problem_id": problem_id, "source_sha256": source_hash})
        errors = list(Draft202012Validator(candidate_schema()).iter_errors(candidate))
        issues = [{"path": "/" + "/".join(map(str, error.absolute_path)), "code": "schema.invalid", "message": error.message}
                  for error in errors[:32]]
        if not errors:
            issues.extend({"path": path, "code": "schema.invalid", "message": message}
                          for path, message in public_structure_errors(candidate))
        if issues:
            parsed["contract_valid"] = False
            parsed["reports"]["ir"]["ok"] = False
            parsed["reports"]["ir"].setdefault("issues", []).extend(issues)
        if store:
            store.put_bytes(kind="search_stage_one_raw", content=raw.encode("utf-8"), media_type="text/plain", suffix=".txt")
            store.put_json(kind="search_stage_one_validation", payload=parsed)
        return parsed

    def request_for(self, base, stage, candidate, registry, diagnostics=(), feedback=(), *, validation=None):
        outgoing = super().request_for(base, stage, candidate, registry, diagnostics, feedback, validation=validation)
        schema = review_schema() if stage == "review" else candidate_schema()
        payload = json.loads(outgoing.prompt.user_prefix)
        payload["response_schema"] = schema
        return replace(outgoing, contract_version=REVIEW_CONTRACT if stage == "review" else EXTRACTION_CONTRACT,
                       contract_schema=schema,
                       prompt=MultimodalExtractionPrompt(
                           outgoing.prompt.system + "\n\n" + PUBLIC_PROMPT_PATH.read_text(encoding="utf-8"),
                           json.dumps(payload, ensure_ascii=False), outgoing.prompt.user_suffix))

    def validate_review(self, raw, candidate):
        review = strict_json(raw)
        Draft202012Validator(review_schema()).validate(review)
        for finding in review["findings"]:
            path, kind = finding["path"], finding["kind"]
            public = path == "/public_content" or path.startswith("/public_content/")
            if public != (kind == "wrong_public_content"):
                raise ValueError("review.invalid_public_pointer")
            if not public and not (path == "/original_text" or path == "/root" or path.startswith("/root/")):
                raise ValueError("review.invalid_pointer")
            if kind == "wrong_transcription" and path != "/original_text":
                raise ValueError("review.invalid_transcription_pointer")
            pointer(candidate, path)
        return review

    def repair_diagnostics(self, current, proposed, diagnostics):
        mathematical = [item for item in diagnostics if not item["path"].startswith("/public_content")]
        errors = super().repair_diagnostics(mathematical_candidate(current), mathematical_candidate(proposed), mathematical)
        grants = [item["path"] for item in diagnostics
                  if item.get("action") == "repair" and item["path"].startswith("/public_content")]
        for path in changed_paths(current.get("public_content"), proposed.get("public_content"), "/public_content"):
            if not any(path == grant or path.startswith(grant + "/") for grant in grants):
                errors.append({"code": "repair.outside_authorized_path", "path": path,
                               "message": "仅可修改诊断明确授权的公开题目字段，不可顺带改变其他题意。"})
        return errors

    def result_fields(self, current):
        return {"output_contract": EXTRACTION_CONTRACT}
