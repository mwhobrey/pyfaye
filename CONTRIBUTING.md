# Contributing to PyFaye

Thank you for your interest in contributing to PyFaye! This document provides guidelines and instructions for contributing.

## Development Setup

1. Fork and clone the repository:
```bash
git clone https://github.com/yourusername/pyfaye.git
cd pyfaye
```

2. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

3. Install dependencies:
```bash
poetry install
```

4. Install pre-commit hooks:
```bash
poetry run pre-commit install
```

## Development Process

1. Create a new branch for your feature:
```bash
git checkout -b feature/your-feature-name
```

2. Make your changes, following our coding standards:
- Use Black for code formatting
- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write tests for new features
- Update documentation as needed

3. Run tests and checks:
```bash
# Run tests
poetry run pytest

# Run type checking
poetry run mypy src

# Run linting
poetry run ruff check src
```

4. Commit your changes:
```bash
git add .
git commit -m "feat: your descriptive commit message"
```

## Pull Request Process

1. Update documentation:
   - Add/update docstrings
   - Update README.md if needed
   - Add to CHANGELOG.md under [Unreleased] section

2. Push your changes:
```bash
git push origin feature/your-feature-name
```

3. Create a Pull Request:
   - Use a clear title and description
   - Reference any related issues
   - Ensure all checks pass

## Code Style

- Follow PEP 8 guidelines
- Use type hints
- Write descriptive docstrings
- Keep functions focused and small
- Write clear commit messages following [Conventional Commits](https://www.conventionalcommits.org/)

## Testing

- Write tests for all new features
- Maintain or improve code coverage
- Test both success and error cases
- Use pytest fixtures appropriately
- Mock external dependencies

## Documentation

- Keep docstrings up to date
- Follow Google docstring format
- Update README.md for significant changes
- Add examples for new features

## Questions?

Feel free to open an issue for any questions about contributing. 