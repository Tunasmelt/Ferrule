.PHONY: check conform security gate-0a

check:
	python -m unittest discover -s tests -v
	go test ./...

conform:
	python tests/conformance.py

security:
	@echo "No proxy security suite exists before phase 2."

gate-0a: check conform
