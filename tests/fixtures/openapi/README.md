These are small, hand-authored OpenAPI 3.0 documents modeling a handful of
real, documented operations from 8 real public APIs (GitHub, Stripe,
PokeAPI, JSONPlaceholder, Open-Meteo, Slack, SendGrid, Twilio). They are
representative excerpts, not full downloads of the real specs (several of
which -- Stripe's and GitHub's in particular -- are tens of thousands of
lines) -- the same "recorded fixture, not a live call" approach milestone
1c already used for these same APIs. Method/path/operationId shapes match
each API's real, current public documentation as of this writing.

Used by services/compiler/python/ferrule_compiler's ingest tests to prove
against real-shaped operations, not synthetic ones invented to fit the
parser.

`synthetic-cookie-param.json` is the one exception: it is not one of the 8
real specs above and is not counted in "8 specs" or "20 GET operations"
test criteria. It is a small, explicitly hand-built, clearly-labeled
fixture used only by milestone 3b's plan-generation tests to exercise the
`not_representable` verdict honestly (a cookie-location parameter, which
the phase-1 plan language has no first-class support for) without forcing
a fake requirement onto one of the real API fixtures above.
