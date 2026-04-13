---
description: Run the test suite, diagnose failures, and fix them
---

# Fix Tests

Run the test suite, diagnose any failures, and fix them.

## Process:

1. **Run lint first:**
   ```bash
   uv run ruff check src/ scripts/ tests/
   uv run ruff format --check src/ scripts/ tests/
   ```
   - If lint fails, fix the issues before proceeding to tests

2. **Run the full test suite:**
   ```bash
   uv run pytest -v
   ```

3. **If all tests pass:** report success and stop.

4. **If tests fail, for each failure:**
   - Read the failing test to understand what it expects
   - Read the source code it exercises
   - Identify root cause: is it a test bug or a source bug?
   - Fix the source code (preferred) or the test if the test is wrong
   - Do NOT weaken assertions just to make tests pass

5. **Re-run after fixes:**
   - Run the full suite again: `uv run pytest -v`
   - If new failures appear, repeat step 4
   - Continue until all tests pass

6. **Final lint check:**
   ```bash
   uv run ruff check src/ scripts/ tests/
   uv run ruff format --check src/ scripts/ tests/
   ```

## Important:
- If `$ARGUMENTS` is provided (e.g. a specific test file or test name), run only that instead of the full suite
- Do not skip or delete failing tests without asking the user
- If a fix requires changing behavior, explain the tradeoff before making the change
- Keep fixes minimal and focused on the actual failure
