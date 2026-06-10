"""Allow `python -m mrp_assistant <command>` as an alternative to `mrp`
(useful when the pip Scripts directory is not on PATH)."""
import sys

from .cli import main

sys.exit(main())
