# Core data boundaries

Ashvane is a local Python/FastAPI desktop hub with four business workspaces. The
desktop and phone use authenticated profile sessions; state-changing requests also
require the existing custom action header and host checks. Core and Growth routes
inherit those checks and are not public routes.

| Data | Owner/access | Processing and destination |
|---|---|---|
| Channel credentials, OAuth tokens, account profiles | Existing business account services | Windows-protected local stores; never copied into repair or tool containers |
| Business media, manuscripts, lyrics, references | Respective business | Existing local generation/publishing workflow; Core receives aggregate busy/error signals rather than private content exports |
| Local file discovery | Core browser | Bounded local metadata/text reads; credential stores, account/runtime data, links and hardlinks rejected; no arbitrary write tool |
| Application source and tests | Core engineer/evaluator | Sanitized snapshots, excluding generated dependencies/output and private filenames; isolated Docker checks; hash-bound source promotion and backups |
| Public web research | Core researcher | Public HTTPS with DNS/IP checks, response limits, no redirects/proxies or ambient credentials; treated as untrusted evidence |
| Public MCP packages and skills | Core extensions | Pinned public wheel acquisition; isolated image build and offline invocation without host mounts; skills remain untrusted text |
| Repair evidence and datasets | Core ledger | Bounded local records, secret redaction, provenance, quarantine and separate held-out exports; no hosted inference or model-weight training |
| Linked YouTube channel metadata/statistics | Growth, selected Surge account profile | Explicit read-only sync using existing OAuth; fixed Google endpoints; per-profile cache; no downloads, candidate creation or publication |
| Live processing telemetry | Growth | Local cached application state while page is visible; platform measurements retain their actual capture timestamps |

Private capabilities from the existing conversational agent registry are not reused
by Core. The protected loader, evaluation/tool boundaries and private account code
are excluded from autonomous edits. Code promotion requires independent review and
real baseline/reproduction/candidate phases; an AI-provided success flag is insufficient.
Startup health and hash checks provide rollback on the next launch after an
unconfirmed or tampered overlay boot. The master switch persists before work drains.

Growth holds the selected account's lease across sync and cache writes. Its cache
cannot cross account IDs, and stale responses are discarded after a profile change.
Legacy account-history rows without recorded ownership remain explicitly
unattributed; they are not silently assigned to another profile.
