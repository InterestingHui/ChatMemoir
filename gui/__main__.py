"""Allow `python -m gui`."""
import sys
from gui import main
sys.exit(main() or 0)
