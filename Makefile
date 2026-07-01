.PHONY: lint fix format check-all

# Scans your code for linting errors but makes no changes
lint:
	poetry run ruff check .

# Automatically fixes any safe linting errors
fix:
	poetry run ruff check . --fix

# Formats your code to standard conventions
format:
	poetry run ruff format .

# Runs the auto-fixer, followed by the formatter
all: fix format
