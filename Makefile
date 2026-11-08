PY ?= python3

.PHONY: reproduce test live live-top collect manifest pages

## Offline: rebuild every number from data/ (no network, no keys). Writes out/report.html
reproduce:
	$(PY) -m vaultcheck reproduce

## Offline: unit tests + assertions on the published numbers
test:
	$(PY) -m unittest discover -s tests -v

## Online, keyless: check all 717 fungible tokens at the latest block (~2-3 min)
live:
	$(PY) -m vaultcheck live

## Online, keyless: only the 50 largest balances (~30 s)
live-top:
	$(PY) -m vaultcheck live --top 50

## Maintainer only: re-download data/ from public RPC (~1 h), then refresh the manifest
collect:
	$(PY) -m vaultcheck collect
	$(MAKE) manifest

## Maintainer: refresh the GitHub Pages copies in docs/ from a fresh reproduction
pages: reproduce
	mkdir -p docs
	cp out/demo.html docs/index.html
	cp out/report.html docs/report.html

manifest:
	$(PY) -c "from vaultcheck import manifest; print(manifest.write('data'), 'files hashed')"
