# Contributing to llm-apipool

Thank you for considering contributing to llm-apipool! Please read this guide to get started.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Git
- An IDE or text editor of your choice

### Installation

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/llm-apipool.git
   cd llm-apipool
   ```

3. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install the package in development mode with all dependencies:
   ```bash
   pip install -e ".[dev,all]"
   ```

   This installs:
   - The main package in editable mode (`-e`)
   - Development dependencies (`[dev]`)
   - All optional dependencies (`[all]`: GUI and proxy)

### Running Tests

To run the test suite:

```bash
pytest
```

To run tests with coverage:

```bash
pytest --cov=llm_apipool
```

### Linting and Type Checking

We use `ruff` for linting and `mypy` for type checking.

Run the linter:

```bash
ruff check .
```

To automatically fix fixable issues:

```bash
ruff check --fix .
```

Run the type checker:

```bash
mypy --strict llm_apipool
```

### Adding a New Provider

To add a new free-tier LLM provider to llm-apipool:

1. **Add provider metadata** to `llm_apipool/config/providers.json`:
   - Follow the existing format for each provider entry.
   - Include: `provider` name, `capabilities`, `base_url`, `openai_compatible` boolean, `default_model`, `models` list, `limits` (rpm, rpd), and `cooldown_fallback` strategy.

2. **Implement header parsing** (if needed) in `llm_apipool/providers/headers.py`:
   - If the provider returns rate-limit headers, add a function to parse them and return cooldown timestamps.
   - Follow the pattern of existing provider functions (e.g., `_groq`, `_cerebras`).
   - Add your function to the `collect_rl_headers` and `extract_cooldown` dispatch maps.

3. **Add tests** for your provider in `tests/test_providers.py`:
   - Test successful completion, rate limiting (429), network errors, timeouts, and unexpected errors.
   - If the provider supports streaming, test the streaming path as well.

4. **Update the provider list** in `README.md` (the Contributors section).

### Pull Request Guidelines

1. Keep your changes focused. If addressing multiple issues, consider separate PRs.
2. Follow the existing code style (ruff will enforce this).
3. Write clear, descriptive commit messages.
4. Add tests for new features or bug fixes.
5. Ensure all tests pass locally before submitting.
6. Update documentation as needed (e.g., new provider, configuration changes).
7. Your PR should target the `main` branch.

### Reporting Issues

Please use the GitHub issue tracker to report bugs or request features. Include:
- A clear, descriptive title
- Steps to reproduce the issue (if applicable)
- Expected vs. actual behavior
- Relevant logs or error messages
- Your environment (Python version, OS, etc.)

### Thank You!

Your contributions help make llm-apipool better for everyone. We appreciate your time and effort.
