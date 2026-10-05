"""Started by Isocline Desktop as the first thing inside the sandboxed Python process.

The sandboxed process inherits no handles (no pipes, no console), so the request and result go through files in its
private work folder, which is also its current directory: request.json in, result.txt and stderr.txt out. Then the
standard harness (the same one the server sandbox uses) runs the user code.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

sys.stdin = open("request.json", encoding="utf-8")  # noqa: SIM115
_out = open("result.txt", "w", encoding="utf-8")  # noqa: SIM115
_err = open("stderr.txt", "w", encoding="utf-8")  # noqa: SIM115
sys.stdout = sys.__stdout__ = _out
sys.stderr = sys.__stderr__ = _err
try:
    runpy.run_path(os.path.join(HERE, "harness.py"), run_name="__main__")
finally:
    _out.flush()
    _err.flush()
