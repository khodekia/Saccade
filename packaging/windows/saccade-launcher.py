"""Entry point for the frozen Windows build.

PyInstaller needs a plain script to start from, and freezing a package's
``__main__`` directly confuses its import analysis, so this is that script.
"""

import multiprocessing
import sys

from saccade.app import main

if __name__ == "__main__":
    # Without this a frozen build re-runs the whole program in every child
    # process Qt or Python happens to spawn.
    multiprocessing.freeze_support()
    sys.exit(main())
