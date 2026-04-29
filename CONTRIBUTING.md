# Contributing to DQ-tool

Thank you for your interest in contributing to DQ-tool! We welcome all kinds of contributions—bug reports, feature requests, documentation improvements, and code contributions.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Submitting Pull Requests](#submitting-pull-requests)
- [Code Style](#code-style)
- [Testing](#testing)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Enhancements](#suggesting-enhancements)

---

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/DQ-tool.git
   cd DQ-tool
   ```
3. **Add upstream remote** to keep in sync:
   ```bash
   git remote add upstream https://github.com/shubhamdhakne/DQ-tool.git
   ```

---

## Development Setup

### Prerequisites
- Python 3.8 or higher
- pip or conda

### Setup Development Environment

#### Using venv (Windows)
```bash
cd DQ-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Dev dependencies
```

#### Using venv (macOS/Linux)
```bash
cd DQ-tool
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

#### Using conda
```bash
conda env create -f environment.yml
conda activate dq-tool
pip install -r requirements-dev.txt
```

### Install Development Tools

```bash
# Code formatting and linting
pip install black flake8 isort

# Testing
pip install pytest pytest-cov

# Type checking
pip install mypy

# Pre-commit hooks (optional but recommended)
pip install pre-commit
pre-commit install
```

---

## Making Changes

### Create a Feature Branch

Use descriptive branch names:
```bash
git checkout -b feature/add-gcp-support
git checkout -b fix/null-handling-bug
git checkout -b docs/improve-readme
```

**Branch naming conventions:**
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `perf/` - Performance improvements
- `test/` - Test additions or updates

### Make Your Changes

1. Edit files as needed
2. Add or update tests for your changes
3. Update documentation if applicable
4. Keep commits focused and descriptive

---

## Submitting Pull Requests

### Before Submitting

1. **Sync with upstream**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run tests**:
   ```bash
   pytest
   ```

3. **Format code**:
   ```bash
   black dq_tool/ dashboard/
   isort dq_tool/ dashboard/
   ```

4. **Lint**:
   ```bash
   flake8 dq_tool/ dashboard/ --max-line-length=100
   ```

5. **Type check** (optional):
   ```bash
   mypy dq_tool/
   ```

### Submit PR

1. Push to your fork:
   ```bash
   git push origin feature/add-gcp-support
   ```

2. Open a pull request on GitHub with:
   - Clear title describing the change
   - Description of what changed and why
   - Reference to any related issues (#123)
   - Checklist items completed
   - Screenshots (if UI changes)

---

## Code Style

### Python Style Guide (PEP 8)

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with some modifications:

- **Line length**: 100 characters max
- **Indentation**: 4 spaces
- **Imports**: Organized with isort (stdlib, third-party, local)
- **Type hints**: Strongly encouraged (not required)

### Formatting with Black

```bash
# Auto-format all files
black dq_tool/ dashboard/

# Check without modifying
black --check dq_tool/ dashboard/
```

### Linting with Flake8

```bash
# Check code quality
flake8 dq_tool/ dashboard/ --max-line-length=100 --extend-ignore=E203,W503
```

### Import Ordering

```bash
# Auto-sort imports
isort dq_tool/ dashboard/
```

### Docstring Format

Use Google-style docstrings:

```python
def profile_data(df, include_sample=True):
    """
    Profile a pandas DataFrame for data quality metrics.
    
    Args:
        df (pd.DataFrame): Input DataFrame to profile.
        include_sample (bool): Whether to include sample rows. Default is True.
    
    Returns:
        dict: Dictionary containing quality metrics.
    
    Raises:
        TypeError: If df is not a pandas DataFrame.
    
    Example:
        >>> import pandas as pd
        >>> df = pd.read_csv('data.csv')
        >>> profile = profile_data(df)
    """
    pass
```

---

## Testing

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=dq_tool --cov-report=html

# Run specific test file
pytest tests/test_profiler.py

# Run specific test
pytest tests/test_profiler.py::test_null_detection
```

### Write Tests

Place tests in the `tests/` directory matching the module structure:

```python
# tests/test_profiler.py
import pytest
import pandas as pd
from dq_tool.profiler import profile_data


def test_profile_data_basic():
    """Test basic profiling functionality."""
    df = pd.DataFrame({
        'col1': [1, 2, 3],
        'col2': ['a', 'b', None]
    })
    result = profile_data(df)
    
    assert 'row_count' in result
    assert result['row_count'] == 3
    assert result['null_count'] == 1


def test_profile_data_empty():
    """Test profiling empty DataFrame."""
    df = pd.DataFrame()
    result = profile_data(df)
    
    assert result['row_count'] == 0
```

---

## Reporting Bugs

### Bug Report Template

When submitting a bug report:

1. **Use a clear, descriptive title**
2. **Describe the exact steps to reproduce** the problem
3. **Describe the observed behavior** and what you expected
4. **Include code samples** or file attachments
5. **Include your environment**: Python version, OS, package versions
6. **Include screenshots** if applicable

### Example

```
Title: Null count incorrect for datetime columns

Steps to reproduce:
1. Create a DataFrame with datetime column containing NaT
2. Run profile_data()
3. Check null_count in results

Expected: null_count should include NaT values
Actual: NaT values are not counted

Environment:
- Python 3.9.5
- pandas 1.3.0
- DQ-tool 0.1.0
```

---

## Suggesting Enhancements

### Feature Request Template

When suggesting a feature:

1. **Use a clear, descriptive title**
2. **Provide a description** of the suggested feature
3. **Explain the motivation** and use case
4. **List examples** of similar functionality in other tools
5. **Describe alternative solutions** you've considered

### Example

```
Title: Add support for GCP Cloud Storage

Description:
Allow profiling data directly from Google Cloud Storage buckets, 
similar to existing AWS S3 and Azure Blob support.

Use case:
Teams using GCP need to profile large datasets in Cloud Storage 
without downloading locally.

Examples:
--gcp-bucket my_bucket --gcp-project my-project
```

---

## Code Review Process

- At least one maintainer review is required
- All CI checks must pass
- Code style and test coverage must meet standards
- Constructive feedback is provided for improvements

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## Questions?

Feel free to:
- Open an issue with `[question]` tag
- Start a discussion in GitHub Discussions
- Contact the maintainers

Thank you for contributing! 🎉
