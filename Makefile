.PHONY: check conform signing-conform security gate-0a gate-0b gate-0c gate-1a gate-1b gate-1c gate-2a

export GOCACHE := $(CURDIR)/.cache/go-build

check:
	python -m unittest discover -s tests -v
	go test ./...

conform:
	python tests/conformance.py

signing-conform:
	python tests/signing_conformance.py

security:
	@echo "No proxy security suite exists before phase 2."

gate-0a: check conform

gate-0b: check conform signing-conform

gate-0c: check
	python -m unittest tests.test_diff tests.test_cli -v

gate-1a:
	python -m unittest discover -s tests -v
	python -m unittest tests.test_plan_schema tests.test_cli -v

gate-1b:
	python -m unittest discover -s tests -v
	python -m unittest tests.test_cel tests.test_plan_schema -v

gate-1c:
	python -m unittest discover -s tests -v
	python -m unittest tests.test_interpreter tests.test_cli -v

gate-2a:
	go test ./services/proxy/...
