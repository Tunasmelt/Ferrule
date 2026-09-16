# Artifact canonicalization

Ferrule manifests use compact UTF-8 JSON with:

- object keys sorted by Unicode code point;
- arrays kept in their original order;
- only required JSON string escaping; and
- numbers written as plain decimal with no exponent or insignificant zeroes
  (`1.0` becomes `1`, `1.2e-3` becomes `0.0012`, and negative zero becomes `0`).

NaN and positive or negative Infinity are rejected. The Python and Go
implementations share the fixtures in `tests/fixtures/canonical`.
