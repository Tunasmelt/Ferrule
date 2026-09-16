import json
import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "artifact" / "python"))

from ferrule_artifact import CanonicalizationError, canonicalize  # noqa: E402


class CanonicalizationTests(unittest.TestCase):
    def test_is_idempotent(self) -> None:
        rng = random.Random(0)
        for _ in range(200):
            value = {
                str(rng.randrange(20)): [rng.randrange(-10**30, 10**30), rng.random()],
                "nested": {"value": rng.choice([None, True, False, "é", []])},
            }
            encoded = canonicalize(value)
            self.assertEqual(encoded, canonicalize(json.loads(encoded)))

    def test_is_order_independent(self) -> None:
        rng = random.Random(1)
        pairs = [(f"key-{index}", {"n": index}) for index in range(100)]
        expected = canonicalize(dict(pairs))
        for _ in range(100):
            rng.shuffle(pairs)
            self.assertEqual(expected, canonicalize(dict(pairs)))

    def test_shared_fixtures_are_canonical(self) -> None:
        fixtures = sorted((ROOT / "tests" / "fixtures" / "canonical").glob("*.json"))
        self.assertEqual(20, len(fixtures))
        for fixture in fixtures:
            raw = fixture.read_bytes()
            self.assertEqual(canonicalize(json.loads(raw)), canonicalize(raw), fixture.name)

    def test_rejects_non_finite_numbers(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(CanonicalizationError):
                canonicalize({"number": value})
        for token in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(token=token), self.assertRaises(CanonicalizationError):
                canonicalize(b'{"number":' + token + b"}")


if __name__ == "__main__":
    unittest.main()
