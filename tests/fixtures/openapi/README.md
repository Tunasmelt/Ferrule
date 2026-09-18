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
