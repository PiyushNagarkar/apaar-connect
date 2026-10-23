# AICTE APAAR Connect Demonstration & Automation Tooling
.PHONY: demo-reset demo-check benchmark test test-ui help

help:
	@echo "=================================================================="
	@echo "AICTE APAAR Connect - Demo & Automation Tooling"
	@echo "=================================================================="
	@echo "  make demo-reset  - Re-seeds fresh deterministic demonstration state (seed 42)"
	@echo "  make demo-check  - Verifies health, seeded counts, and 7 role logins"
	@echo "  make benchmark   - Ingests 10k CSV and benchmarks validation, commit, p95 latency (demo-scale)"
	@echo "  make test        - Executes all 11 automated must-pass contract tests"
	@echo "  make test-ui     - Executes Playwright automated UI flow tests"
	@echo "=================================================================="

demo-reset:
	python scripts/reset_demo_data.py --seed 42

demo-check:
	python scripts/demo_check.py

benchmark:
	python scripts/benchmark_performance.py

test:
	pytest backend/tests/test_must_pass_contract.py -v

test-ui:
	pytest backend/tests/test_playwright_ui_flows.py -v
