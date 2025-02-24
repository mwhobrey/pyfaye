"""Script to run pytype type checking."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run pytype type checking.
    
    Returns:
        Exit code from pytype
    """
    root = Path(__file__).parent.parent
    config = root / "pytype.cfg"
    src = root / "src" / "faye"
    
    cmd = ["pytype", "--config", str(config), str(src)]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main()) 