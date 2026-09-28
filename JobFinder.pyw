# Double-click to open Job Finder (Windows, with Python installed). The .exe uses this too.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobfinder.gui import main  # noqa: E402

raise SystemExit(main())
