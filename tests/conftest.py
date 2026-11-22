"""Point the agent at the small fixture database before `bank_support` is imported."""

import os
from pathlib import Path

os.environ['TAU2_DATA_DIR'] = str(Path(__file__).parent / 'data')
