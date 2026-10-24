"""Measure an existing real sidecar using only standard-library HTTP and procfs."""

import argparse
import http.client
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

BASE_URL = "http://127.0.0.1:8080"
CLIENT_LATENCY_BUDGET = 120
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SAMPLE_INTERVAL = 0.1
MEMORY_GAUGES = ("vm_rss_bytes", "vm_hwm_bytes", "memory_current_bytes", "memory_peak_bytes")


def read_text(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def parse_counter(value):
    if value is None:
        return None
    try:
        number = int(value.strip())
        return number if number >= 0 else None
    except ValueError:
        return None


def parse_counters(value):
    if value is None:
        return None
    counters = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) == 2:
            number = parse_counter(fields[1])
            if number is not None:
                counters[fields[0]] = number
    return counters or None


def parse_process_status(value):
    result = {"vm_rss_bytes": None, "vm_hwm_bytes": None}
    for line in (value or "").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] in {"VmRSS:", "VmHWM:"} and fields[2] == "kB":
            number = parse_counter(fields[1])
            key = "vm_rss_bytes" if fields[0] == "VmRSS:" else "vm_hwm_bytes"
            result[key] = number * 1024 if number is not None else None
    return result


def memory_snapshot(proc_status="/proc/1/status", cgroup="/sys/fs/cgroup"):
    root = Path(cgroup)
    return {
        **parse_process_status(read_text(proc_status)),
        "memory_current_bytes": parse_counter(read_text(root / "memory.current")),
        "memory_peak_bytes": parse_counter(read_text(root / "memory.peak")),
        "memory_stat": parse_counters(read_text(root / "memory.stat")),
        "memory_events": parse_counters(read_text(root / "memory.events")),
    }


class MemorySampler:
    def __init__(self, output, *, snapshot=None, interval=SAMPLE_INTERVAL):
        self.output = Path(output)
        self.snapshot = snapshot or memory_snapshot
        self.interval = interval
        self.phases = []
        self.current = None
        self.error = None
        self.started = time.monotonic()
        self.stopped = threading.Event()
        self.lock = threading.Lock()

    def __enter__(self):
        self.stream = self.output.open("x", encoding="utf-8")
        self.thread = threading.Thread(target=self.run, name="ocr-memory-sampler", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stopped.set()
        self.thread.join()
        self.stream.close()

    def sample(self):
        with self.lock:
            return self.record()

    def record(self):
        memory = self.snapshot()
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "elapsed_seconds": time.monotonic() - self.started,
            "phase": self.current["name"] if self.current is not None else "between_phases",
            **memory,
        }
        self.stream.write(json.dumps(record, allow_nan=False) + "\n")
        self.stream.flush()
        if self.current is not None:
            phase = self.current
            phase["samples"] += 1
            if phase["initial"] is None:
                phase["initial"] = record
            phase["final"] = record
            for key in phase["sampled_max"]:
                value = memory[key]
                previous = phase["sampled_max"][key]
                if value is not None:
                    phase["sampled_max"][key] = value if previous is None else max(value, previous)
        return record

    def run(self):
        try:
            while not self.stopped.is_set():
                self.sample()
                self.stopped.wait(self.interval)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    @contextmanager
    def phase(self, name):
        with self.lock:
            if self.current is not None:
                raise RuntimeError("memory phases cannot overlap")
            summary = {"name": name, "samples": 0, "initial": None, "final": None,
                       "sampled_max": dict.fromkeys(MEMORY_GAUGES)}
            self.phases.append(summary)
            self.current = summary
            self.record()
        try:
            yield summary
        finally:
            with self.lock:
                self.record()
                self.current = None


def assess_memory(phases, error=None):
    failures = []
    if error:
        failures.append({"phase": None, "metric": None, "reason": "sampler_error", "value": error})
    if not phases:
        failures.append({"phase": None, "metric": None, "reason": "no_phases", "value": None})
    for phase in phases:
        name, samples = phase["name"], phase.get("samples")
        if type(samples) is not int or samples < 1:
            failures.append({"phase": name, "metric": "samples", "reason": "no_samples", "value": samples})
        for metric in MEMORY_GAUGES:
            value = (phase.get("sampled_max") or {}).get(metric)
            if type(value) is not int or value < 0:
                failures.append({"phase": name, "metric": metric, "reason": "missing_or_invalid", "value": value})
        for boundary in ("initial", "final"):
            events = (phase.get(boundary) or {}).get("memory_events") or {}
            for metric in ("oom", "oom_kill"):
                value = events.get(metric)
                reason = "missing_or_invalid" if type(value) is not int or value < 0 else "oom_observed" if value else None
                if reason:
                    failures.append({"phase": name, "metric": f"{boundary}.memory_events.{metric}",
                                     "reason": reason, "value": value})
    return {"passed": not failures, "failures": failures}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def request_json(path, *, timeout, body=None):
    if path not in {"/health", "/v1/manifests", "/v1/search/observe"}:
        raise ValueError("unsupported local endpoint")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    result = {"status": None, "body": None, "error": None, "body_truncated": False}
    started = time.monotonic()
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result["status"] = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        result["body_truncated"] = len(raw) > MAX_RESPONSE_BYTES
        text = raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
        if result["body_truncated"]:
            result.update(error="response_too_large", body_text=text)
        else:
            try:
                result["body"] = json.loads(text)
            except ValueError:
                result.update(error="response_not_json", body_text=text)
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_seconds"] = time.monotonic() - started
    return result


def load_cases(path):
    cases = json.loads(Path(path).read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty JSON array")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise TypeError("each case must be an object")
        identifier, image = case.get("id"), case.get("image")
        if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", identifier) is None or identifier in seen:
            raise ValueError("case IDs must be unique safe names")
        seen.add(identifier)
        if not isinstance(image, str) or not Path(image).is_absolute() or Path(image).suffix != ".png":
            raise ValueError("case image must be an absolute PNG path")
        if type(case.get("auto_orient")) is not bool:
            raise ValueError("auto_orient must be a boolean")
        if type(case.get("expected_rotation")) is not int or case["expected_rotation"] not in (0, 90, 180, 270):
            raise ValueError("expected_rotation must be a clockwise quarter turn")
        size = case.get("expected_size")
        if not isinstance(size, list) or len(size) != 2 or any(type(value) is not int or not 1 <= value <= 1600 for value in size):
            raise ValueError("expected_size must contain the two OCR output dimensions, at most 1600")
        if "expected_status" in case and case["expected_status"] not in ("upright", "corrected", "manual"):
            raise ValueError("expected_status must be upright, corrected, or manual")
    return cases


def assess_observation(case, response):
    result = {"id": case["id"], "case": case, "response": response,
              "inference_pass": False, "latency_budget_seconds": CLIENT_LATENCY_BUDGET,
              "latency_budget_pass": response["elapsed_seconds"] <= CLIENT_LATENCY_BUDGET,
              "passed": False, "result": "failed", "failures": []}
    body = response.get("body")
    if response.get("error") or response.get("status") != 200:
        result["failures"].append("http_request_failed")
    elif not isinstance(body, dict) or body.get("ok") is not True or not isinstance(body.get("orientation"), dict):
        result["failures"].append("invalid_response")
    else:
        orientation = body["orientation"]
        if orientation.get("status") == "uncertain":
            result["result"] = "needs_review"
            result["failures"].append("orientation_uncertain")
        else:
            if orientation.get("rotation_degrees") != case["expected_rotation"]:
                result["failures"].append("rotation_mismatch")
            if [body.get("width"), body.get("height")] != case["expected_size"]:
                result["failures"].append("size_mismatch")
            if "expected_status" in case and orientation.get("status") != case["expected_status"]:
                result["failures"].append("orientation_status_mismatch")
            result["inference_pass"] = not result["failures"]
    if not result["latency_budget_pass"]:
        result["failures"].append("client_latency_budget_exceeded")
    result["passed"] = not result["failures"]
    if result["passed"]:
        result["result"] = "passed"
    return result


def wait_healthy(timeout, *, request=request_json, clock=time.monotonic, sleeper=time.sleep):
    started, attempts, response = clock(), 0, None
    while (remaining := timeout - (clock() - started)) > 0:
        response = request("/health", timeout=min(5.0, remaining))
        attempts += 1
        body = response.get("body")
        if (not response.get("error") and response.get("status") == 200 and isinstance(body, dict)
                and body.get("ok") is True and body.get("ready") is True):
            return {"passed": True, "attempts": attempts, "elapsed_seconds": clock() - started, "response": response}
        sleeper(min(0.25, max(0, timeout - (clock() - started))))
    return {"passed": False, "attempts": attempts, "elapsed_seconds": clock() - started, "response": response}


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return number


def emit_progress(phase, result, elapsed, case_id=None):
    print(json.dumps({"phase": phase, "case_id": case_id, "result": result,
                      "elapsed_seconds": elapsed}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=positive_seconds, default=600)
    parser.add_argument("--request-timeout", type=positive_seconds, default=120)
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name in ("report.json", "memory.jsonl")):
        parser.error("output already contains report.json or memory.jsonl; choose a fresh directory")
    report = {
        "schema": "ocr-acceptance/v1", "passed": False,
        "environment": {"uid": os.getuid(), "gid": os.getgid(), "home": str(Path.home()),
                        "pid1_command": (read_text("/proc/1/cmdline") or "").replace("\u0000", " ").strip()},
        "measurement": {
            "sample_interval_seconds": SAMPLE_INTERVAL, "request_timeout_seconds": args.request_timeout,
            "startup_timeout_seconds": args.startup_timeout, "client_latency_budget_seconds": CLIENT_LATENCY_BUDGET,
            "kernel_peaks": "Cumulative process/cgroup peaks, never subtracted to infer a phase peak.",
            "sampled_peaks": "Observed samples only; short peaks can fall between samples.",
            "scope": "cgroup includes cache and probe/health processes; VmRSS/VmHWM describe PID 1 only.",
            "startup": "Sampling starts after container launch; cumulative kernel peaks include earlier startup.",
            "timeouts": "Timed-out inference is not cancelled; later cases may include its lock wait. Failures are not retried or cleared.",
        },
        "startup": None, "manifests": None, "cases": [], "error": None,
    }
    sampler = MemorySampler(args.output / "memory.jsonl")
    try:
        with sampler:
            with sampler.phase("startup"):
                report["startup"] = wait_healthy(args.startup_timeout, request=request_json)
            emit_progress("startup", "passed" if report["startup"]["passed"] else "failed",
                          report["startup"].get("elapsed_seconds"))
            if report["startup"]["passed"]:
                with sampler.phase("manifests"):
                    response = request_json("/v1/manifests", timeout=args.request_timeout)
                    body = response.get("body")
                    report["manifests"] = {
                        "response": response,
                        "passed": (not response.get("error") and response.get("status") == 200
                                   and isinstance(body, dict) and body.get("ok") is True
                                   and isinstance(body.get("providers"), list) and bool(body["providers"])),
                    }
                emit_progress("manifests", "passed" if report["manifests"]["passed"] else "failed",
                              response["elapsed_seconds"])
                for case in cases:
                    with sampler.phase("observe_" + case["id"]):
                        response = request_json("/v1/search/observe", timeout=args.request_timeout,
                                                body={"image": case["image"], "auto_orient": case["auto_orient"]})
                        result = assess_observation(case, response)
                        report["cases"].append(result)
                    emit_progress("observe", result["result"], response["elapsed_seconds"], case["id"])
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        emit_progress("probe", "failed", None)
    report["memory"] = {"phases": sampler.phases, "error": sampler.error,
                        **assess_memory(sampler.phases, sampler.error)}
    report["passed"] = bool(
        not report["error"] and report["memory"]["passed"] and report["startup"] and report["startup"]["passed"]
        and report["manifests"] and report["manifests"]["passed"]
        and len(report["cases"]) == len(cases) and all(case["passed"] for case in report["cases"])
    )
    with (args.output / "report.json").open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
