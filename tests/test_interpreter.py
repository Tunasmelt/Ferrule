import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "packages" / "interpreter" / "python"))
sys.path.insert(0, str(ROOT / "packages" / "plan-schema" / "python"))

from ferrule_interpreter import (  # noqa: E402
    PlanRejected,
    Response,
    ResponseTooLargeError,
    UndeclaredHostError,
    classify_plan,
    run,
)
from ferrule_interpreter.interpreter import (  # noqa: E402
    MAX_RESPONSE_BODY_BYTES,
    _http,
    _request,
)
from ferrule_interpreter.mock import FixtureServer  # noqa: E402
from ferrule_plan_schema import validate_schema  # noqa: E402


class InterpreterTests(unittest.TestCase):
    fixtures = ROOT / "tests" / "fixtures"

    def test_all_fifteen_plans_execute_without_real_network(self) -> None:
        plans = sorted((self.fixtures / "plans" / "execution").glob("*.json"))
        inputs = json.loads((self.fixtures / "plans" / "inputs.json").read_text())
        expected = json.loads((self.fixtures / "plans" / "expected.json").read_text())
        self.assertEqual(15, len(plans))
        with FixtureServer(self.fixtures / "http.json") as server:
            original = socket.getaddrinfo

            def local_address(
                host: str, port: int, family: int = 0, type: int = 0,
                proto: int = 0, flags: int = 0,
            ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
                del host, port, family, type, proto, flags
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", server.port))]

            with patch("socket.getaddrinfo", side_effect=local_address):
                for path in plans:
                    with self.subTest(plan=path.name):
                        result = run(json.loads(path.read_text()), inputs[path.stem])
                        self.assertEqual(expected[path.stem], result)
            self.assertEqual(15 + 3, len(server.requests))
            self.assertTrue(all(host != "127.0.0.1" for host, _ in server.requests))
            socket.getaddrinfo = original

    def test_invalid_plan_is_rejected_before_transport(self) -> None:
        plan = json.loads((self.fixtures / "plans" / "execution" / "github-repo.json").read_text())
        plan["steps"][0]["exec"] = "curl example.com"
        called = False

        def transport(*args: object) -> Response:
            nonlocal called
            called = True
            raise AssertionError("transport must not run")

        with self.assertRaises(PlanRejected):
            run(plan, {}, transport=transport)
        self.assertFalse(called)

    def test_offset_pagination_rejects_undeclared_host_before_transport(self) -> None:
        plan = json.loads((self.fixtures / "plans" / "execution" / "poke-list.json").read_text())
        requests: list[object] = []

        def transport(request: object) -> Response:
            requests.append(request)
            return Response(200, {}, {"results": [], "next": "https://attacker.invalid/next"})

        with self.assertRaisesRegex(UndeclaredHostError, "attacker.invalid"):
            run(plan, {}, transport=transport)
        self.assertEqual(1, len(requests))

    def test_link_header_pagination_rejects_undeclared_host_before_transport(self) -> None:
        plan = json.loads((self.fixtures / "plans" / "execution" / "github-issues.json").read_text())
        requests: list[object] = []

        def transport(request: object) -> Response:
            requests.append(request)
            return Response(200, {"link": '<https://attacker.invalid/next>; rel="next"'}, {"data": []})

        with self.assertRaisesRegex(UndeclaredHostError, "attacker.invalid"):
            run(plan, {}, transport=transport)
        self.assertEqual(1, len(requests))

    def test_offset_pagination_allows_declared_host(self) -> None:
        plan = json.loads((self.fixtures / "plans" / "execution" / "poke-list.json").read_text())
        responses = iter([
            Response(200, {}, {"results": [{"name": "bulbasaur"}], "next": "https://pokeapi.co/page/2"}),
            Response(200, {}, {"results": [{"name": "ivysaur"}], "next": None}),
        ])
        requests: list[object] = []

        def transport(request: object) -> Response:
            requests.append(request)
            return next(responses)

        result = run(plan, {}, transport=transport)
        self.assertEqual({"route": "ok", "output": {"names": ["bulbasaur", "ivysaur"]}}, result)
        self.assertEqual(2, len(requests))

    def test_oversized_response_is_rejected_before_json_parsing(self) -> None:
        class RawResponse:
            status = 200

            def read(self, amount: int) -> bytes:
                self.amount = amount
                return b"{" * amount

            def getheaders(self) -> list[tuple[str, str]]:
                return []

        class Connection:
            raw = RawResponse()

            def request(self, method: str, target: str, body: bytes | None, headers: dict[str, str]) -> None:
                del method, target, body, headers

            def getresponse(self) -> RawResponse:
                return self.raw

            def close(self) -> None:
                pass

        request = _request(
            {"method": "GET", "url": "https://example.com", "headers": {}},
            {}, {}, {"example.com"},
        )
        with patch("ferrule_interpreter.interpreter.http.client.HTTPSConnection", return_value=Connection()):
            with self.assertRaisesRegex(ResponseTooLargeError, "1048576 bytes"):
                _http(request)
        self.assertEqual(MAX_RESPONSE_BODY_BYTES + 1, Connection.raw.amount)

    def test_request_rendering_is_canonical(self) -> None:
        first = {
            "method": "GET", "url": "https://example.com/items?z=0",
            "headers": {"x-foo-bar": "a", "ACCEPT": "application/json"},
            "query": {"b": "2", "a": "1"},
        }
        second = {
            "method": "GET", "url": "https://example.com/items?z=0",
            "headers": {"accept": "application/json", "X-FOO-BAR": "a"},
            "query": {"a": "1", "b": "2"},
        }
        rendered_first = _request(first, {}, {}, {"example.com"})
        rendered_second = _request(second, {}, {}, {"example.com"})
        self.assertEqual(rendered_first, rendered_second)
        self.assertEqual("https://example.com/items?a=1&b=2&z=0", rendered_first.url)
        self.assertEqual({"Accept": "application/json", "X-Foo-Bar": "a"}, rendered_first.headers)

    def test_crlf_header_is_rejected_as_plan_error(self) -> None:
        plan = json.loads((self.fixtures / "plans" / "execution" / "github-repo.json").read_text())
        plan["steps"][0]["headers"] = {"X-Input": "{{ input.value }}"}
        with self.assertRaisesRegex(PlanRejected, "invalid HTTP request") as raised:
            run(plan, {"value": "safe\r\nInjected: true"})
        self.assertNotEqual(ValueError, type(raised.exception))

    def test_coverage_artifact_has_all_plans(self) -> None:
        records = json.loads((self.fixtures / "plans" / "coverage.json").read_text())
        self.assertEqual(15, len(records))
        self.assertTrue(all(item["verdict"] == "representable" for item in records))
        for path in (self.fixtures / "plans" / "execution").glob("*.json"):
            self.assertEqual("representable", classify_plan(json.loads(path.read_text())))

    def test_dangerous_shapes_are_schema_inexpressible(self) -> None:
        base = json.loads((self.fixtures / "plans" / "execution" / "github-repo.json").read_text())
        attacks = [
            lambda p: p.update({"filesystem": "/etc/passwd"}),
            lambda p: p["steps"][0].update({"exec": "id"}),
            lambda p: p["steps"][0].update({"shell": True}),
            lambda p: p["steps"][0].update({"command": ["whoami"]}),
            lambda p: p["steps"][0].update({"url": "file:///etc/passwd"}),
            lambda p: p["steps"][0].update({"pagination": "unbounded"}),
            lambda p: p["steps"][0].update({"method": "EXEC"}),
            lambda p: p["steps"][0].update({"steps": [p["steps"][0].copy()]}),
            lambda p: p["steps"][0].update({"max_pages": 101}),
            lambda p: p["steps"][0]["expect"]["200"].update({"loop": "forever"}),
            lambda p: p["steps"][0].update({"imports": ["subprocess"]}),
        ]
        for index, mutate in enumerate(attacks):
            plan = json.loads(json.dumps(base))
            mutate(plan)  # type: ignore[no-untyped-call]
            with self.subTest(attack=index):
                self.assertTrue(validate_schema(plan))

    def test_execution_modules_have_no_ambient_inputs(self) -> None:
        package = ROOT / "packages" / "interpreter" / "python" / "ferrule_interpreter"
        forbidden = ("os.environ", "os.getenv", "open(", ".read_text(", ".read_bytes(",
                     "time.time(", "datetime.now(", "datetime.utcnow(")
        for name in ("interpreter.py", "render.py", "coverage.py"):
            source = (package / name).read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(file=name, token=token):
                    self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
