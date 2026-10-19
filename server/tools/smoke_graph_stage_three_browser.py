"""Exercise real browser delivery while the first route is paused before verification.

Use PLAYWRIGHT_MODULE / CHROME_EXECUTABLE to point at an existing installation.
No dependency download, LLM, external page or product database is needed.
"""

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.preview import make_server
from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from pathlib import Path

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "server/tests/solver/fixtures/graph-guided-stage-two/recorded/q01-20261018-02/stage-two-result.json"
    paused, release = Event(), Event()

    def barrier(state, _store):
        if state["route_id"] == "discriminant":
            paused.set()
            if not release.wait(55):
                raise TimeoutError("browser_smoke.release_timeout")

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run_sample, source, output / "run", hooks={"before_verification": barrier})
        if not paused.wait(30):
            release.set()
            task.result()
            raise AssertionError("route never reached verification barrier")
        server = make_server(output / "run")
        original = server.RequestHandlerClass

        class Handler(original):
            def do_GET(self):
                if self.path == "/test/release":
                    release.set()
                    self.send_response(204)
                    self.end_headers()
                else:
                    super().do_GET()

        server.RequestHandlerClass = Handler
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subprocess.run(["node", str(ROOT / "tools/verify-stage-three-browser.mjs"),
                            f"http://127.0.0.1:{server.server_port}/", str(output)], check=True, timeout=55)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()
        result = task.result()
        assert result["status"] == "completed"
    print(output / "browser-evidence.json")


if __name__ == "__main__":
    main()
