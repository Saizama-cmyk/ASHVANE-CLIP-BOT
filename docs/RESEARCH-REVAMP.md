# Original research studio revamp

The research desk turns linked public evidence into an original spoken script and drafts for YouTube, TikTok, Instagram, Facebook, and Discord. Outputs remain text for human review and production. Research has no rendering or publishing access.

## Workflow and API

The desk retains public RSS/Atom entries and optional YouTube/Twitch trend leads. Steam-hosted CS2 and Dota 2 feeds are the initial defaults; Steam feeds can also contain community press. Trend video titles and view counts are leads, never evidence of events inside footage. Explicit source selection stays fixed for a draft; automatic selection ranks saved excerpts by topic words and recency.

A local director chooses an angle, a writer produces the script and platform prose, and an evidence judge checks the actual sentences. Each role can use a configured installed Ollama model or follow the current GPU profile. Separate role calls are not independent verification when they use the same model. All role calls share the pipeline GPU lock; one research job runs at a time.

- `GET /api/research`: status, sources, saved ideas, agents, errors and research settings.
- `POST /api/research/refresh`: collect linked evidence asynchronously.
- `POST /api/research/draft`: only `topic` and optional `source_ids`; starts an asynchronous draft.
- `DELETE /api/research/ideas/{id}`: delete a completed saved draft.

These routes use the app's existing session and mutation protections. Request size, topic length, evidence counts, script size, local output tokens, refresh intervals, role models, prompts and evidence rules are configurable and appear in generated settings.

## Evidence safeguards and practical output

The writer supplies a factual claim ledger with exact source IDs and quotes. The judge must audit every script sentence, hook sentence and prose sentence in every platform field, including details absent from the writer's ledger. Unknown IDs, invented quotes, title-only evidence, missing/duplicate audit units, unsupported quantities, changed negation and insufficient wording overlap prevent readiness. An optimistic model verdict cannot override these checks.

Calling an unsupported benefit an opinion cannot bypass the audit. Only exact configured nonfactual audience questions can be automatically accepted without factual evidence. These questions are checked independently of the judge's factual-support flag. Other opinion classifications need human review. The default questions are preference/engagement prompts; any custom entries should also be nonfactual questions.

Original research has its own platform instructions. Captured-clip templates previously requested reactions, streamer credits and daily-clip promises, which are inappropriate for unproduced original scripts. The writer now requests concise source-backed details and avoids padding thin evidence to a target duration. A returned sentence array becomes a spoken text string, and simple text platform posts become their corresponding text fields; the content is preserved and then audited.

Malformed writer structure and incomplete optimistic judge audits get bounded repair using the existing `ai.retries` setting, with the actual validation issues and prior output supplied as feedback. Evidence thresholds do not change during repair. A judge that rejects content retains the draft for human review instead of repeatedly rewriting it until approval.

`ready` means the local evidence and quality checks passed for text review. `needs_review` retains usable scripts and posts with specific evidence/audit warnings. `failed` retains any script completed before a later structural or connectivity failure. Interrupted jobs are marked interrupted on shutdown and restart. Saved sources and successful refresh time survive a later failed refresh, and failed saves/deletes roll back shelf changes.

## Fetching and persistence

Only public HTTPS feeds on the standard port are fetched. The fetcher rejects local/private hosts, mixed public/private DNS answers, redirects, oversized decoded responses, and XML document/entity declarations. It validates DNS, connects to a selected public IP, keeps original TLS SNI and Host, verifies certificates, and ignores ambient proxies. Feed markup is stripped before it reaches local models. Source and model text are treated as untrusted data, never tools or instructions.

Research persists atomically to `research.json` under the configured data directory. No capture or publisher database rows are created by research. Validation uses a separate artifact data directory, not the user's live data.

## Validation and limits

Focused verification: `python -m pytest tests/test_research.py tests/test_no_hardcoded.py -q` passed **130 tests**. Tests include GPU-lock serialization, model selection, persistence, route protections, bounded feeds, exact citations, incomplete audits, unsupported lighting benefits labelled either fact or opinion, changed numeric counts, changed negation, preserved plain-text posts/sentence arrays, and bounded writer/judge repairs that cannot clear unsupported content.

Live verification uses the installed `qwen3-vl:8b-instruct` model on the local GPU and a freshly fetched Steam CS2 patch note:

https://store.steampowered.com/news/app/730/view/675133527946167652

Refresh returned eight real sources; the Dota 2 feed reported no usable recent entries. The isolated validation cache is `artifacts/research-validation/research.json`, and the latest snapshot is `artifacts/live-research-verified.json`. Raw role responses are saved as `artifacts/live-research-{role}-output.json`. The cache also retains the earlier validation attempts for inspection.

A completed multi-detail live script correctly stated the agent-glove change and improved Warehouse lighting, then asked which change mattered to the viewer. All five platform drafts were produced. It remained `needs_review`: some titles cited only one part of a compound title, and added source-credit prose did not have an exact supporting quote. These were audit/provenance issues on otherwise source-backed script details; they were not a successful evidence approval. Earlier attempts also exposed unsupported streamer benefits and malformed post/script shapes, which were held or failed rather than promoted.

The final single-detail run used a 15-second target and a CS2-player audience. It completed script plus all five platforms in **77.06 seconds**, then remained `needs_review`: the model added “a cosmetic update with real-time visual impact,” which goes beyond the patch-note wording. The writer and optimistic judge did not reliably obey the narrow scope; the mechanical checks held the draft. No live attempt is reported as an approved original production. This is a content-grounding limitation, distinct from the earlier compound-title and citation-format warnings.

The checks are conservative heuristics, not a proof of truth. A valid paraphrase can need review because its vocabulary differs from its quote; a high wording match can still conceal a semantic error. The local judge may miss implications, and evidence excerpts can be incomplete or inaccurate. Hashtag/tag taxonomy is not audited as sentence prose. Generated durations are targets, not measured recorded speech. Human source inspection and production review remain necessary.
