# Artifact canonicalization

Ferrule manifests use compact UTF-8 JSON with:

- object keys sorted by Unicode code point;
- arrays kept in their original order;
- only required JSON string escaping; and
- numbers written as plain decimal with no exponent or insignificant zeroes
  (`1.0` becomes `1`, `1.2e-3` becomes `0.0012`, and negative zero becomes `0`).

NaN and positive or negative Infinity are rejected. The Python and Go
implementations share the fixtures in `tests/fixtures/canonical`.

## Build, hash, sign, verify

`build` produces the canonical manifest bytes. For milestone 0b,
`artifact_hash` is `sha256(canonical(manifest))`; plan and fixture content will
be added to the hash when those artifact parts exist. Ed25519 signs the raw
32-byte SHA-256 digest and signatures are detached, so the signed content does
not contain a self-referential signature field.

The CLI exposes `ferrule artifact build`, `hash`, `sign`, and `verify`. Generate
a local keypair with:

```console
ferrule artifact keygen
ferrule artifact sign manifest.json --private-key .ferrule/keys/dev-private.pem > signature.txt
ferrule artifact verify manifest.json --signature signature.txt --public-key .ferrule/keys/dev-public.pem
```

`keygen` is strictly a development convenience, not production key custody.
It writes an unencrypted private key under the gitignored `.ferrule/keys/`
directory. Production signing must use managed key custody; never copy or
commit a development private key.
