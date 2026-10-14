# YouTube outcome learning

The official YouTube Analytics channel report supports engaged views, average view
duration, average percentage watched and subscribers gained, using an additional
read-only Analytics OAuth scope. Sources verified 13 October 2026:

- https://developers.google.com/youtube/analytics/channel_reports
- https://developers.google.com/youtube/analytics/metrics
- https://developers.google.com/youtube/analytics/reference/reports/query

Surge requests that scope on its existing Google Connect flow when outcome collection is
enabled. Hollow does not request it. Existing grants without that scope report permission
required. The connected production grant was checked without exposing token data and
does not currently include Analytics access. The owner must grant it through Google's
consent screen; no login has been performed on their behalf. Google Cloud may also need
the YouTube Analytics API enabled. HTTP denial reports permission/API access required.

Reports read channel==MINE and only tracked videos from the selected Surge profile,
in batches of at most 200 with bounded bytes, dates and a total deadline. They never
upload anything. Dates exclude the configurable recent reporting lag; Google can still
return a shorter available reporting period. Requested dates and capture time are stored
with every real row. Missing rows are unavailable, not fabricated zeroes. Replayed Shorts
can legitimately exceed 100% watched. Monetary reports are not requested.

The periodic refresh and explicit Growth refresh hold the profile lease through network
requests and drained cache writes. Concurrent refreshes serialize; explicit refreshes
have a cooldown and reject stale profile identities. Posts and outcome records are
filtered by destination profile. Switching profiles clears steering and uses a separate
cache. Old aggregate caches without ownership are discarded, not assigned to a profile.

View-based scores retain their existing baseline. With sufficient posts and engaged-view
counts, watch percentage and smoothed subscriber conversion add configurable bounded
weights relative to this profile's median. Sparse/missing outcomes add nothing. Group
shrinkage, exploration and anti-flood rules remain. This is measured-outcome steering,
not model weight training or a guarantee of future reach. Growth displays actual watch
metrics per post and reports missing permission/data explicitly.
