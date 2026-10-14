# Ashvane: functional and visual overhaul research

Owner request: restore Self Tune and live preview, make Core useful and observable,
then rebuild the desktop/phone visual language as an interactive interstellar business
control room. Research must precede design, with at least five minutes of active online
investigation. Keep all four independent businesses and current account boundaries.

Questions to test before selecting dependencies:

1. Can the existing local Three.js renderer support a selectable, truthful agent and
   workflow scene without a framework migration or new paid runtime?
2. Can adaptive rendering, on-demand frames, reduced motion and a readable fallback
   retain useful interaction on phones and embedded desktop WebViews?
3. Which primary-maintained tools improve observable agent execution, isolated code
   evaluation and MCP capability discovery, rather than adding decorative complexity?
4. Which original vector, typography and motion workflows support consistent branding
   across desktop, mobile and GitHub with clear licensing and no remote runtime dependency?
5. What verifiable evaluation separates useful generated training examples, better
   prompts/memory and actual weight training? No consciousness or automatic intelligence
   claim is justified by animated nodes or self-generated examples alone.

The first active research pass ran from 22:00:54 to 22:06:03 UTC; later targeted reads
continued during implementation. [The origin ledger](interstellar-research-ledger.json)
records claims and gaps. Vendor documentation establishes supported features, not a
measured performance or quality advantage on this computer.

## Decisions

| Candidate | Decision and evidence |
|---|---|
| Three.js + matching EffectComposer/UnrealBloomPass/OutputPass | Selected. Existing local engine, ray selection and bounded postprocessing; original procedural disk and neuron art. Single origin: [maintainer docs](https://threejs.org/docs/pages/UnrealBloomPass.html). |
| pmndrs/postprocessing | Considered. Its [maintainer guide](https://github.com/pmndrs/postprocessing) explains framebuffer/color-management tradeoffs. Matching Three addons avoid another package/version boundary here. Single origin; no performance comparison was run. |
| React Three Fiber | Considered. [React renderer](https://github.com/pmndrs/react-three-fiber) is appropriate for React scenes; the existing desktop is vanilla JS, so a migration is not required to produce this visual. Single origin. |
| React Flow / Cytoscape.js | Considered for workflow editors and graph analysis. [React Flow](https://reactflow.dev/) and [Cytoscape](https://js.cytoscape.org/) document different graph workloads; this small actual agent roster uses direct semantic layout. No invented graph editor was added. |
| Rive | Considered for authored cross-platform vector motion. [Its runtime comparison](https://rive.app/docs/runtimes/web/canvas-vs-webgl) describes rendering/context tradeoffs. Native finite transitions and shared Three art meet this request without an extra authoring/runtime dependency. Single origin. |
| Anime.js | [Maintainer documentation](https://animejs.com/documentation/) offers timelines, SVG and WAAPI helpers. Existing native browser/React Native motion suffices for the bounded launch and crossing transitions. Single origin. |
| Space Grotesk / IBM Plex | Selected locally with retained OFL licenses. Display/navigation and long reading have separate roles; no font CDN is required at runtime. See [Space Grotesk](https://github.com/floriankarsten/space-grotesk), [IBM Plex](https://github.com/IBM/plex). |
| Playwright + Playwright MCP | Useful development tools for repeatable browser/phone fixtures and screenshot comparisons. [Primary test docs](https://playwright.dev/docs/test-snapshots), [MCP project](https://github.com/microsoft/playwright-mcp). Production account browsing is not a dependency of Core. Single maintainer origin. |
| MCP Registry / Inspector | Useful discovery and protocol inspection tools, already aligned with Core's isolated extension workflow. [Registry](https://registry.modelcontextprotocol.io/docs), [Inspector](https://modelcontextprotocol.io/docs/tools/inspector). A listing is not a trust or private-access grant. Single project origin. |
| LangGraph | [Checkpoint/store design](https://docs.langchain.com/oss/python/langgraph/persistence) informs durability. Replacing the existing tested supervisor wholesale is not necessary for receipts, blockers, idle wakeups and preserved outcome memory. Single origin. |
| OpenTelemetry | [Python instrumentation](https://opentelemetry.io/docs/languages/python/) is a useful future export boundary. Local bounded observations/receipts satisfy current diagnostics without adding a collector to every installation. Single origin. |
| Figma plugin | Discoverable and unconnected. Editable design collaboration is optional; no account setup or private export was needed to build code-native assets. |

## A useful brain requires grounded feedback

[Self-Refine](https://arxiv.org/abs/2303.17651) and [Reflexion](https://arxiv.org/abs/2303.11366)
describe different feedback/refinement approaches. They support investigating explicit
feedback memory, not a claim that this local model has acquired human cognition.
Core's actual tool results, failed/successful regressions and held-out owner corrections
provide the evidence. [The model-collapse study](https://www.nature.com/articles/s41586-024-07566-y)
is a single primary origin for recursive-data degradation under its studied conditions;
it supports avoiding indiscriminate training on self-generated output. Ashvane currently
exports provenance-linked examples and uses memory; automatic weight retraining is not shipped.

## Gaps

No local Qwen page-fetch MCP was available, so primary reads were bounded and targeted.
Apple's motion HIG required JavaScript and Sigma's homepage fetch failed; neither supports
a reported finding. No hardware performance superiority, native iPhone render result,
third-party installation or new paid service is claimed. Library alternatives are a
reasoned architecture choice, not a benchmark ranking. Source facts were checked on
13 October 2026; assets are pinned and their installed hashes recorded.
