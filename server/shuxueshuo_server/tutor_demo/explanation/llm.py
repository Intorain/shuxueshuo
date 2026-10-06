"""Reuse provider configuration/transport; keep a separate interpretation contract."""

import hashlib
import json
from pathlib import Path

from ..llm import DeepSeekTutor
from .contracts import ExplanationProposal

ROOT = Path(__file__).parent
PROMPT = ROOT / "prompts/interpret.jinja"


class ExplanationInterpreter(DeepSeekTutor):
    proposal_type = ExplanationProposal
    max_tokens = 2400

    @property
    def prompt_version(self):
        return "interpret:" + hashlib.sha256(PROMPT.read_bytes()).hexdigest()[:10]

    def prompts(self, projection, request):
        return [
            {"role": "system", "content": PROMPT.read_text()},
            {"role": "user", "content": json.dumps(projection, ensure_ascii=False)},
        ]
