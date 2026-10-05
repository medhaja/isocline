"""Entry point of the packaged desktop app (Isocline.exe). Equivalent to `python -m isocline.desktop`."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for any multiprocessing use inside a frozen Windows app
    from isocline.desktop.launcher import main
    sys.exit(main())
