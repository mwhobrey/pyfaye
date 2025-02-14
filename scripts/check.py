#!/usr/bin/env python
import subprocess
import sys


def run_command(command: list[str]) -> tuple[int, str]:
    """Run a command and return exit code and output."""
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
        return 0, output.decode()
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output.decode()


def main() -> int:
    """Run all checks and tests."""
    checks = [
        (["poetry", "run", "black", "src/faye/", "--check"], "Black"),
        (["poetry", "run", "mypy", "src/faye/"], "mypy"),
        (["poetry", "run", "ruff", "src/faye/"], "ruff"),
    ]

    # Run code quality checks first
    for command, name in checks:
        print(f"\nRunning {name}...")
        exit_code, output = run_command(command)
        if exit_code != 0:
            print(f"{name} failed:")
            print(output)
            return exit_code

    # If all checks pass, run tests
    print("\nAll code quality checks passed! Running tests...")
    test_command = ["poetry", "run", "pytest", "-v"]
    exit_code, output = run_command(test_command)
    print(output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
