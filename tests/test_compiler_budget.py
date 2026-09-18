import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.budget import median_seconds, timed  # noqa: E402
from ferrule_compiler.generate import compile_operation  # noqa: E402
from ferrule_compiler.openapi import ingest  # noqa: E402

REAL_FIXTURES = {
    "github.json": "https://api.github.com",
    "stripe.json": "https://api.stripe.com",
    "pokeapi.json": "https://pokeapi.co/api/v2",
    "jsonplaceholder.json": "https://jsonplaceholder.typicode.com",
    "open-meteo.json": "https://api.open-meteo.com",
    "slack.json": "https://slack.com/api",
    "sendgrid.json": "https://api.sendgrid.com",
    "twilio.json": "https://api.twilio.com",
}

MAX_P50_SECONDS = 180.0  # 3 minutes, per PHASES.md milestone 3c's test criterion


class CompilerBudgetTests(unittest.TestCase):
    def test_compile_p50_is_under_3_minutes_across_all_get_operations(self) -> None:
        fixtures_dir = ROOT / "tests" / "fixtures" / "openapi"
        durations: list[float] = []
        for name, base_url in REAL_FIXTURES.items():
            spec = ingest((fixtures_dir / name).read_bytes())
            for operation in spec.operations:
                if operation.method == "GET":
                    _, elapsed = timed(lambda op=operation: compile_operation(base_url, op))
                    durations.append(elapsed)

        self.assertGreaterEqual(len(durations), 20)
        p50 = median_seconds(durations)
        self.assertLess(p50, MAX_P50_SECONDS)
        # Record the real measured number, not just that it cleared the bar.
        print(f"\ncompile p50 across {len(durations)} operations: {p50 * 1000:.3f} ms")


if __name__ == "__main__":
    unittest.main()
