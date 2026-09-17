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

    def test_rejects_duplicate_object_keys(self) -> None:
        for value in (b'{"x":1,"x":2}', b'{"a":{"x":1,"x":2}}'):
            with self.subTest(value=value), self.assertRaisesRegex(
                CanonicalizationError, 'duplicate object key: "x"'
            ):
                canonicalize(value)

    def test_deeply_nested_input_is_rejected_not_a_crash(self) -> None:
        # A RecursionError from Python's own recursion limit must surface
        # as a controlled CanonicalizationError, matching the documented
        # error contract -- not leak as an uncaught interpreter error.
        nested = b"[" * 2000 + b"]" * 2000
        with self.assertRaises(CanonicalizationError):
            canonicalize(nested)

    def test_rejects_unpaired_surrogate_escapes(self) -> None:
        for value in (rb'{"x":"\ud800"}', rb'{"x":"\udc00"}'):
            with self.subTest(value=value), self.assertRaises(CanonicalizationError):
                canonicalize(value)

    def test_accepts_valid_surrogate_pair_escape(self) -> None:
        # A real astral character written as a \uXXXX\uXXXX escape PAIR in
        # the JSON source text (not a literal UTF-8 character in this test
        # file) must still canonicalize, combined into the correct 4-byte
        # UTF-8 sequence. Built from ASCII bytes to keep the escape pair
        # literal in the source rather than something a tool could silently
        # normalise into an actual character.
        source = b'{"x":"a' + b"\\ud83d\\ude00" + b'b"}'
        self.assertEqual(b'{"x":"a\xf0\x9f\x98\x80b"}', canonicalize(source))


if __name__ == "__main__":
    unittest.main()
