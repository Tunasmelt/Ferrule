.PHONY: check conform signing-conform security gate-0a gate-0b gate-0c gate-1a gate-1b gate-1c gate-2a gate-2b gate-2c gate-2d gate-2 gate-3a gate-3b gate-3c gate-3

export GOCACHE := $(CURDIR)/.cache/go-build

check:
	python -m unittest discover -s tests -v
	go test ./...

conform:
	python tests/conformance.py

signing-conform:
	python tests/signing_conformance.py

security:
	go test ./services/proxy/... -run '^TestPermissionProbes$$' -v

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

# 2b's tests live in the same services/proxy package as 2a's (there is no
# per-milestone test binary split yet); the gate is named separately per
# PHASES.md's convention since it is a distinct milestone checkpoint.
gate-2b:
	go test ./services/proxy/...

gate-2c:
	go test ./services/proxy/...

gate-2d:
	FERRULE_LATENCY_BENCHMARK=1 go test ./services/proxy/... -run 'PermissionProbes|ProxyLatency' -v

# PHASES.md's phase-level gate: the union of that phase's milestone gates,
# plus make security (also required, but tracked as its own invocation per
# CLAUDE.md/AGENTS.md, not folded silently into this target).
gate-2: gate-2a gate-2b gate-2c gate-2d

gate-3a:
	python -m unittest tests.test_compiler_ingest tests.test_compiler_resolve tests.test_compiler_api tests.test_compiler_store -v

gate-3b:
	python -m unittest tests.test_compiler_generate -v

gate-3c:
	python -m unittest tests.test_compiler_mocktest tests.test_compiler_claims tests.test_compiler_budget -v

# test_compiler_pipeline spans 3a/3b/3c (ingest -> resolve -> generate ->
# mock-verify -> claims through the real HTTP API) so it belongs to no
# single milestone gate; it runs once here instead of being duplicated
# into gate-3a/3b/3c.
gate-3: gate-3a gate-3b gate-3c
	python -m unittest tests.test_compiler_pipeline -v
