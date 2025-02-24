"""Script to run all code quality checks before release."""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def run_command(cmd: List[str], description: str) -> Tuple[int, str]:
    """Run a command and return its exit code and output.
    
    Args:
        cmd: Command to run as list of strings
        description: Description of what the command does
        
    Returns:
        Tuple of (exit_code, output)
    """
    print(f"\n=== Running {description} ===")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ {description} failed!")
        print(result.stdout)
        print(result.stderr)
    else:
        print(f"✅ {description} passed!")
    return result.returncode, result.stdout + result.stderr


def main() -> int:
    """Run all prerelease checks.
    
    Returns:
        0 if all checks pass, 1 if any fail
    """
    root = Path(__file__).parent.parent
    src = root / "src" / "faye"
    tests = root / "tests"
    
    # First run black to format all files
    black_result, _ = run_command(
        ["black", str(src)],
        "black (code formatting)"
    )
    
    # Run ruff autofix to automatically fix common issues
    ruff_fix_result, _ = run_command(
        ["ruff", "--fix", str(src)],
        "ruff (auto-fixing)"
    )
    
    # Then run pytype for type checking
    pytype_result, _ = run_command(
        ["pytype", "--config", str(root / "pytype.cfg"), str(src)],
        "pytype (type checking)"
    )
    
    # Run ruff for remaining linting issues
    ruff_result, _ = run_command(
        ["ruff", "check", str(src)],
        "ruff (linting)"
    )

    # Run pytest with coverage
    pytest_result, pytest_output = run_command(
        [
            "pytest",
            str(tests),
            "-v",  # Verbose output
            "--cov=" + str(src),  # Enable coverage for src directory
            "--cov-report=term-missing",  # Show lines missing coverage
            "--cov-report=html:coverage_html",  # Generate HTML report
            "--cov-fail-under=80",  # Fail if coverage is below 80%
        ],
        "pytest (unit tests with coverage)"
    )
    
    # Summarize results
    all_passed = all(x == 0 for x in [
        black_result, 
        ruff_fix_result, 
        pytype_result, 
        ruff_result,
        pytest_result
    ])
    
    if all_passed:
        print("\n✨ All checks passed! Ready for release.")
        print("\nTest Coverage Report:")
        print("--------------------")
        # Extract and print coverage summary
        for line in pytest_output.split('\n'):
            if "TOTAL" in line or "coverage:" in line:
                print(line)
        print("\nDetailed coverage report available in ./coverage_html/index.html")
        return 0
    else:
        print("\n❌ Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 