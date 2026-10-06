"""One call produces the selected derivation, its state and subsequent choices."""

import hashlib
import json
import logging
from pathlib import Path

from ..llm import DeepSeekTutor, ModelResponseInvalid
from .generated_contracts import GeneratedTurn
from .json_format import decode_model_json

PROMPT = Path(__file__).parent / "prompts/generate.jinja"
logger = logging.getLogger(__name__)


class ExplanationGenerator(DeepSeekTutor):
    proposal_type = GeneratedTurn
    max_tokens = 6000
    # BudgetedTutor reserves quota separately for each actual provider call.
    format_attempts = 2

    def decode_response(self, content):
        try:
            payload, repairs = decode_model_json(content)
            result = self.proposal_type.model_validate(payload)
        except (ValueError, TypeError) as exc:
            logger.warning("explanation output format rejected: %s", type(exc).__name__)
            raise ModelResponseInvalid("模型推导格式修复后仍未通过校验") from exc
        if repairs:
            logger.info("explanation JSON syntax repaired: %s", ", ".join(repairs))
        return result

    @property
    def prompt_version(self):
        return "generate:" + hashlib.sha256(PROMPT.read_bytes()).hexdigest()[:10]

    def prompts(self, projection):
        return [
            {"role": "system", "content": PROMPT.read_text() + "\nJSON Schema:\n" +
             json.dumps(GeneratedTurn.model_json_schema(), ensure_ascii=False)},
            {"role": "user", "content": json.dumps(projection, ensure_ascii=False)},
        ]
