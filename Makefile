.PHONY: docs docs-build docs-install clean

docs-install:
	uv sync --project docs

docs: docs-install
	uv run --project docs zensical serve -f docs/zensical.toml -o

docs-build: docs-install
	uv run --project docs zensical build -f docs/zensical.toml

clean:
	rm -rf docs/site
