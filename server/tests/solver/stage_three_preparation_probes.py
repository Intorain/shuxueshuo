"""Importable probes executed by the real supervised preparation process."""

import builtins
import os
import time
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_three.preparation import dispatch


def probe(payload):
    config = payload.get("hook_data", {})
    if payload["operation"] == config.get("phase") and (
        not config.get("target_ref") or payload.get("target_ref") == config["target_ref"]
    ):
        if config.get("pid_file"):
            Path(config["pid_file"]).write_text(str(os.getpid()))
        if config.get("sleep"):
            time.sleep(config["sleep"])
        if config.get("error"):
            raise getattr(builtins, config["error"])(config.get("message", "injected goal failure"))
    return dispatch(payload)


def hooks(phase, *, target_ref=None, error=None, message="injected goal failure", **data):
    return {"preparation_dispatch": probe,
            "preparation_data": {"phase": phase, "target_ref": target_ref, "error": error, "message": message, **data}}
