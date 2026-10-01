"""Runs inside the isolated container. Reads {"code","inputs"} JSON from stdin, executes the code with
INPUTS bound, and prints a single JSON result line. Never runs inside the API process."""
import base64
import contextlib
import io
import json
import os
import sys
import traceback

MAX_STREAM = 64 * 1024
MAX_FILE = 1024 * 1024


def main():
    req = json.loads(sys.stdin.read())
    out_dir = os.path.abspath("out")
    os.makedirs(out_dir, exist_ok=True)
    stdout, stderr = io.StringIO(), io.StringIO()
    ok, error = True, None
    g = {"__name__": "__main__", "INPUTS": req.get("inputs") or {}}
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            exec(compile(req["code"], "<user_code>", "exec"), g)
        except SystemExit as e:
            ok = e.code in (None, 0)
            if not ok:
                error = f"SystemExit({e.code})"
        except BaseException:
            ok = False
            error = traceback.format_exc(limit=8)
    files = []
    for name in sorted(os.listdir(out_dir))[:20]:
        p = os.path.join(out_dir, name)
        if os.path.isfile(p) and os.path.getsize(p) <= MAX_FILE:
            with open(p, "rb") as f:
                files.append({"name": name, "size": os.path.getsize(p), "base64": base64.b64encode(f.read()).decode()})
    sys.__stdout__.write("\n__AF_SANDBOX__" + json.dumps({
        "success": ok, "stdout": stdout.getvalue()[:MAX_STREAM], "stderr": stderr.getvalue()[:MAX_STREAM],
        "error": error, "files": files, "stdout_truncated": len(stdout.getvalue()) > MAX_STREAM}) + "\n")


if __name__ == "__main__":
    main()
