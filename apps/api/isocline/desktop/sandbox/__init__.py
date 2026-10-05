"""Python steps in Isocline Desktop.

On Windows, each Python step runs in its own AppContainer (the Windows sandbox used by Edge and Chrome) inside a Job
Object. Windows itself enforces that the code cannot read or write the user's files (only its private work folder and
the read-only Python runtime), cannot use the network (no network capabilities are granted, loopback included), cannot
start other programs, and is limited in memory, CPU time and wall-clock time. It is killed if Isocline exits.

The bundled runtime is a separate, complete CPython with numpy, pandas, scipy and matplotlib (built by
packaging/desktop/build.ps1), matching the server sandbox image. The escape tests in packaging/desktop/tests prove the
isolation on real Windows during every build.

Public API: ``available()`` and ``execute()`` (async) / ``run()`` (blocking). The result has the same shape as the
server sandbox's /execute response.
"""
from isocline.desktop.sandbox.runner import available, execute, run

__all__ = ["available", "execute", "run"]
