# AI spending allowance

The source production allowance is **USD 0.50 per day**, reset at midnight
Asia/Kolkata. `backend/src/settings.py` defines the amount. Production has a
15-command-per-minute guard and no additional daily model-call or token ceiling;
local regression profiles have finite call/token limits. HTTP request middleware
has its own rate and payload limits.

In mobile mode the phone owns durable usage accounting. A command supplies the
current day's saved allowance state. The API reserves estimated input and maximum
output cost before a model call, then settles against provider-reported usage and
cost. The response carries an operation receipt; Android applies only the
nonnegative difference from the previous receipt, preventing retries from counting
the same usage twice. Reservations and settlement stay scoped to that operation.

Transport uncertainty retains a reservation rather than silently replaying a paid
call. A known context-window rejection can release an unused reservation. Model
pricing comes from the source pricing table, configured overrides, or the provider
catalog/fallback policy in `backend/src/api/spend_policy.py`; source prices are not
a statement of current market rates. `provider.max_price` bounds provider routing.

This allowance covers the application's configured model usage. It is not a
project-wide billing cap across simultaneous operations, replicas, resets or
reinstalls. Embedding compute, Chroma, Maps, builds and Cloud Run have their own
service costs. Input estimates and provider bills can differ, so a reservation is
not an exact price quote.

Sources: `backend/src/api/rate_limiter.py`, `backend/src/api/spend_policy.py`,
`backend/src/budget_profiles.py`, `backend/src/services/mobile_scope.py`, and
`mobile/lib/services/mobile_store.dart`.
