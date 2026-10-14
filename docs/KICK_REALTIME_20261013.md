# Kick realtime transport update

The old hardcoded Pusher application key returned error 4001 on us2, mt1, us3 and eu
in a live probe. Pusher's own protocol says permanent errors in that range must not
be retried with unchanged connection parameters. Source: [Pusher protocol](https://pusher.com/docs/channels/library_auth_reference/pusher-websockets-protocol/).

Kick's current public client negotiates a provider through
`https://web.kick.com/api/v1/realtime/connection`. Its current descriptor offered
Centrifugo. The public client obtains a short-lived anonymous connection grant through
`/api/v1/realtime/auth/connection`; public chat subscriptions do not require the owner's
account login. The implementation follows this observed client flow and does not send
chat messages, access private channels, or persist connection grants.

Primary observed client:
[Kick realtime client bundle](https://assets.kick.com/main/_next/static/chunks/0vf3mmzsywzg3.js).
This is observed public browser behavior, not a claim that these endpoints are a stable,
official third-party API contract. The official developer API separately documents
webhooks for supported chat events.

The new reader supports the descriptor's Centrifugo JSON transport and fresh Pusher
descriptors. It validates transport origin, bounds discovery/handshake/frame sizes,
renews expiring anonymous grants, handles ping/pong and batched frames, and reports
subscriptions only after provider acknowledgement. Failed handshakes no longer reset
exponential backoff. Source: [Centrifugo protocol](https://centrifugal.dev/docs/transports/client_protocol).

Live validation of the actual new reader: connected=true, transport=centrifugo,
joined=1, wanted=1, error empty. The selected public test room produced no messages
during that short test, so it verifies connection/subscription, not delivery of an
actual live chat message. Controlled frame tests verify message routing and filtering.
See artifacts/kick-negotiated-live-check.json. Grants were kept in memory only.

Capture status reads now use immutable observations published by existing buffer workers.
Snapshot replies expose observation age/availability/error and never enumerate or stat
capture storage. Slow-worker regression and real assembly tests passed. Native package
installation and post-restart response measurements follow the full suite/build.
