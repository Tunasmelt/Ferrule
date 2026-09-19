.PHONY: check conform signing-conform security gate-0a gate-0b gate-0c gate-1a gate-1b gate-1c gate-2a gate-2b gate-2c gate-2d gate-2 gate-3a gate-3b gate-3c gate-3 gate-4a gate-4b gate-4

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
	# -count=1 disables go test's build cache: without it, a second gate-2d
	# run with no source changes silently replays a stale cached result
	# instead of re-measuring real wall-clock latency, defeating the point
	# of a live timing benchmark. Found during milestone 4a's audit (same
	# gap, same root cause, in gate-4a's live network test) and fixed here
	# too rather than left in place now that it's diagnosed.
	FERRULE_LATENCY_BENCHMARK=1 go test ./services/proxy/... -run 'PermissionProbes|ProxyLatency' -count=1 -v

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

gate-4a:
	# -count=1 disables go test's build cache on both invocations. Without
	# it, a second run with no source changes silently replays a stale
	# cached result instead of actually skipping / actually calling the
	# real APIs again -- confirmed directly during the 4a audit: repeating
	# the live invocation returned an instant "(cached)" pass with zero
	# live traffic, which would silently defeat this test's entire purpose
	# (catching real-world drift, as it already did once for Open-Meteo)
	# on every run after the first.
	go test ./services/proxy/... -run '^TestSandbox' -count=1 -v
	FERRULE_SANDBOX_LIVE=1 go test ./services/proxy/... -run '^TestSandbox' -count=1 -v

gate-4b:
	python -m unittest tests.test_compiler_evidence tests.test_compiler_nodes_api -v

gate-4: gate-4a gate-4b
