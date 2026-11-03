# Release notes and announcements in SMG

How SMG writes a release page and its announcement: the section skeleton the release tool renders, the writing rules the v1.14.0 page followed once its first draft was sent back as hard to read, the constraints, the Slack form, and how a draft is produced and checked.
Evidence: the published v1.13.0 and v1.14.0 pages (github.com/smg-project/smg/releases), the two drafts of the v1.14.0 page (every change between them is a rule below), `scripts/release/README.md` ("Writing the notes") and the `release-notes` target of the `Makefile` at SMG `176ce3ae`. The rewrite kept the nine sections and every fact of Upgrade notes and took the authored part from 9,662 words to 3,857, 275 semicolons to 7, 134 parentheses to 59, 160 bold spans to 49.

## The skeleton

One Markdown file, these sections in this order and no others. `scripts/release/NOTES-TEMPLATE.md` carries the same names; `make release-notes` renders it (see [How the notes are produced](#how-the-notes-are-produced)). <!-- anchor-ignore -->

1. The title line "# Shepherd Model Gateway vX.Y.Z". The GitHub release title is "vX.Y.Z" and nothing else.
2. The intro, three sentences: the three headline changes; one performance sentence with its baseline ("up to 3.3× the request rate of v1.13.0 within the same latency target"); the commit and contributor counts, the first-time contributors among them, and the pointer to Before you upgrade.
3. "## Before you upgrade": a checklist. One line per item, the fact first, the action second; the upgrade order (gateways first, then engine pods with the matching servicer package) is one item.
4. "## Highlights": "###" groups by theme, a one-sentence lead per group, then bullets. Performance first (the shipped-defaults comparison against the previous release, the fleet comparison, the configuration behind the numbers), then the headline features, then the areas (tokenizer, multimodal, operations, observability, discovery, APIs). A table only after a sentence that defines its measure, with plain column names.
5. "### How this release was validated": the last group under Highlights. One line per proof with its counts: the provider verification suites, the parity censuses, the soak, the single-node comparison, what CI runs on every PR.
6. "## Notable fixes": only bugs that shipped in the previous release. The first line under the heading says so ("Bugs that shipped in v1.13.0. Problems introduced and fixed within this cycle are not listed."). "### Security" first, then the areas (streaming and APIs, storage, routing and metrics, engine servicers and start-up).
7. "## Upgrade notes", fixed subsections in this order: Configuration that now refuses to start, Changed defaults, API behavior, Metrics, Engine side, Bindings and Rust crates. A Storage subsection opens the list only when the release carries a schema migration (v1.13.0 had migration 4, v1.14.0 had none). An empty subsection is deleted, never left as a heading.
8. "## Packages": the gateway package, image and chart; the engine images with their engine versions; the servicer packages; the library crates at the tag; what is not published this time.
9. "## Known limits": one line per limit, no mechanism.
10. The thanks line naming the first-time contributors by handle, then the full-changelog link.
11. "## What's Changed": the generated list by type (Features, Fixes, Performance, Documentation, Maintenance). The Maintenance list folds into one count line with the compare link (485 items in v1.14.0).

## Writing rules

Each rule is one change between the first draft of the v1.14.0 page ("before") and the published page ("after").

1. **Three sentences open the page.** The first draft opened with six, four of them carrying a parenthesis, and a third paragraph on where the figures come from. Before: "brings the Rust engine servicers to every engine (TensorRT-LLM joins vLLM, SGLang and TokenSpeed, and SGLang and TokenSpeed gain prefill/decode disaggregation and multimodal input on the Rust path)". After: "brings the Rust engine servicers to every engine". The detail is the first bullet of its Highlights group.
2. **Define the measure in one sentence before the table, and let the column header say what is measured.** Before: a 60-word method sentence ("under open-loop ramps of the same 8k-token chat shape ... with the capacity read at the last step that holds the latency objective") and the header "Capacity at the objective (requests/s)". After: "The table shows the highest request rate each build sustains while time-to-first-token p99 stays under 1 second." and the header "Max req/s at TTFT p99 < 1 s (v1.13.0 → v1.14.0)". A reader who skips the sentence still reads the header right.
3. **A number stands beside its baseline.** Before: "holds the objective to 264 requests/s on the warm ladder and to 272, the ladder's top, on the gentle approach, where the other router holds none and 240". After: "SMG sustains 264–272 req/s within the latency target. The other router sustains 240 on a gentle ramp and none on a warm one." A ratio names the version it is against: "3.3× the request rate of v1.13.0", never "3.3× faster".
4. **One idea per bullet, the fact in bold first, a flag named once per sentence.** Before: "**Parser:** Symphony reads chat completions, Messages and Responses by default. Pass `--parser legacy` (config `parser: legacy`) to keep the older per-model parsers for a gateway, or the request header `X-SMG-Parser: legacy` for one request. Existing `--tool-call-parser` and `--reasoning-parser` names keep a working parser: a name whose format a table reads selects the table, and the twelve names no table answers to keep the legacy parsers (see Known limits)." After: "**Symphony is the default parser.** `--parser legacy` (or the request header `X-SMG-Parser: legacy`) keeps the old parsers. Existing `--tool-call-parser` and `--reasoning-parser` names keep working." The twelve names are in Known limits, once.
5. **No semicolon chains.** Before: "`--access-log-fields` adds the client address, forwarded-for, user agent, tenant, key fingerprint, byte counts and routed worker to the access log on request; every line that names a worker masks its credentials; the console log is coloured on a terminal only; the writer threads write queued lines in batches (0.038 write calls per line instead of one) and text lines cost a third of the work; `--enable-trace` exports spans at every log level." After: "`--access-log-fields` extends the access log. Every log line masks worker credentials. The writer threads batch lines. `--enable-trace` exports spans at every log level." Four facts, four sentences; the one nobody upgrades for moved to Changed defaults.
6. **At most one parenthesis per bullet.** Before: "Give startup probes, rollout deadlines (`router.progressDeadlineSeconds`, now 1920 s in the chart), `helm --wait --timeout` and any serving controller's readiness deadline the engine's budget." After: "Raise startup probes and rollout deadlines to match; the chart's `router.progressDeadlineSeconds` is now 1920 s."
7. **Short headings, no claims in them.** Before: "Faster at every family's shipped defaults, never slower", "Eight engines behind one router, against another open-source router", "A leaner, exact tokenizer". After: "Faster at the shipped defaults", "Eight engines behind one router", "Tokenizer". The claim is the first sentence under the heading.
8. **Before you upgrade is a checklist.** Before: nine items of three to four sentences, two of them pointing at three other sections. After: nine items of one to three short sentences, the fact first ("**Engine pods take longer to become Ready, on purpose.**"), the action second ("Raise startup probes and rollout deadlines to match"), and the upgrade order as its own item: "Roll gateways first, then engine pods with `smg` 1.14.0 and `smg-grpc-servicer` 0.15.0." What a reader does not act on goes to Upgrade notes.
9. **Explain a gain in named bullets with one number each.** Before: three paragraphs of 60 to 110 words, the second naming seven mechanisms. After: "Engine step shape", "Router cost" ("A chat request costs 0.37M user-space instructions in the router, down from 2.04M", four mechanisms), "Engine-side CPU" ("1.3–1.5 ms of CPU per request where the Python servicer spent 7.5–12.2 ms").
10. **A fix is the symptom and what happens now, in one or two sentences.** Before: "**The gateway's own API key was forwarded upstream.** A request without an `Authorization` header of its own reached external providers and workers with the gateway's key as the caller's credential. The key now ends at the auth middleware; the upstream's configured key is used." After: "The gateway's own API key was forwarded upstream when a request carried no `Authorization` header. It now ends at the auth middleware."
11. **A validation line is one proof and its counts.** Before: the soak line carried the first 24 hours (73,362 requests, 2 client-side errors, 425 → 426 MB of router memory), hour 45, and "runs on to its 72nd hour". After: "A 72-hour soak of the release images on four engines and one router under closed-loop agentic traffic: through hour 45, 233,859 requests, 0 request errors, 0 5xx, 0 restarts, router memory flat."
12. **Code-block comments are one line.** Before: a three-line comment above the `vllm serve` line (the capture cap, the KV-event publisher, the warm-up, the metrics endpoint). After: "# Engine host: vLLM behind SMG's Rust gRPC servicer". What the comment explained is said once, in Highlights.
13. **Lab words stay in the lab.** Before: "arm" for a side of a comparison, "objective", "ladder", "cell", "bed", "placement noise", "gang". After: "side", "latency target", "ramp", "run", "two-node". No checker knows these words; read for them.
14. **Bold marks the fact a bullet leads with and the headline numbers of the intro.** The first draft bolded every table cell and every "less"; the published table bolds the after-number of each row and nothing else.
15. **Short sentences.** Roughly, the first draft's median sentence ran 61 words and the published page's 23, with the same facts; a sentence over 30 words is two sentences or a list.

## Constraints

- GitHub refuses a release body over 125,000 characters. The first v1.14.0 draft was 122,019 characters with its lists; the published page 90,459. The generated Maintenance list folds into one count line with the compare link, which keeps the page under the cap for a cycle of 1,000 commits.
- The release title is "vX.Y.Z" and nothing else; the page's own title line is "# Shepherd Model Gateway vX.Y.Z".
- Another vendor's router is never named: "another open-source router with KV-aware routing", "the engine's own HTTP server".
- No hardware, host, cluster or internal names: "on the same hosts", "eight engines at tensor parallel 4", "a two-node pair". Engine and model family names with their versions are fine (vLLM 0.31.0, SGLang 0.5.21, TensorRT-LLM 1.3.0rc24, GLM 5.3 Flash, DeepSeek V4 Flash).
- The private tracker and its issue numbers never appear; a defect is described in words (the same rule as for PR text).
- The vocabulary rules of `writing.md` bind the page: sides, roles and pools; no generated-sounding filler.

## The announcement

The Slack post is the page's first screen, in five to seven bullets, for a reader who will not open the page. The form:

```text
:rocket: *SMG vX.Y.Z is out*
<the release link>

*What's new*
• five to seven bullets: a bold lead, one sentence, the number beside its baseline

*Before you upgrade*
• three to five bullets, each an action

*Packages*: one line
```

The v1.14.0 announcement, as posted:

```text
:rocket: *SMG v1.14.0 is out*
https://github.com/smg-project/smg/releases/tag/v1.14.0

*What's new*
• *Symphony is the default parser.* One table per model format, typed content/reasoning/tool-call events, tool call ids unique per request, and parse failures visible in metrics. `--parser legacy` keeps the old parsers.
• *Rust servicers for every engine.* TensorRT-LLM joins vLLM, SGLang and TokenSpeed; SGLang and TokenSpeed gain prefill/decode disaggregation and multimodal input on the Rust path; one `/metrics` endpoint on every engine.
• *TokenSpeed on the direct ZMQ lane*, no gRPC servicer in between, same throughput as the gRPC path.
• *Faster at the shipped defaults.* Up to 3.3x the request rate of v1.13.0 within the same latency target (GLM 5.3 Flash 3.0 → 9.8 req/s, DeepSeek V4 Flash 4.4 → 9.8), never slower on any family, and 21–59% less router CPU per request everywhere. Eight engines behind one SMG router sustain 264–272 req/s where another open-source KV-aware router holds 240 or less, at a third of the front CPU and a fifth of the memory.
• *Readiness follows the engine*: servicers warm up before SERVING, workers register only once their engine is healthy.
• Consul and Slurm discovery, a separate admin listener, secrets from env/files instead of the command line, a 41-panel Helm dashboard with alert rules.

*Before you upgrade*
• Roll gateways first, then engine pods with `smg` 1.14.0 + `smg-grpc-servicer` 0.15.0.
• `--kv-index` and the two `--kv-indexer-*` flags are removed; a config that sets them does not start.
• Engine pods take about a minute longer to become Ready (planned warm-up). Raise startup probes and rollout deadlines.
• `tool_choice: "none"` now renders the tools; prompt token counts for those requests change once.
• Six unused metric families removed, `smg_router_request_errors_total` gains a `reason` label.

*Packages*: `smg` 1.14.0 on PyPI and crates.io, `ghcr.io/smg-project/smg:1.14.0`, Helm chart 1.14.0, engine images for vLLM 0.31.0, SGLang 0.5.21, TensorRT-LLM 1.3.0rc24 and TokenSpeed. No Go module release this time.
```

## How the notes are produced

`make release-notes VERSION=X.Y.Z > notes.md` renders `scripts/release/NOTES-TEMPLATE.md` through `scripts/release/notes.py`: the sections above in order, seeded with every merged pull request's release-note sentence (the "## Release note" section of its body, or a "Release note:" line) under the area of its subject's scope, features and performance changes under Highlights, fixes under Notable fixes, declared breaking changes, removed flags and changed defaults under Upgrade notes, the packages and images at the tag under Packages, and the list by type under What's Changed. <!-- anchor-ignore -->
What only the author knows (the intro, Before you upgrade, every narrative, the validation, Known limits) stays as `<!-- AUTHOR: ... -->` markers that say what goes there; the author replaces them by the rules above. `scripts/release/release.sh notes --check notes.md` refuses a draft that still carries a marker or a template token, and runs before the tag and before `gh release create`. A pull request's sentence is written to be pasted as it stands, which is why the contribute skill asks for one on every PR (`none`, with the reason, when a user sees no change). The flow, from `scripts/release/README.md`: draft at the first candidate, write during the cycle as candidates land, render again before the final and diff the candidate lists, the release manager reviews before the tag, the check passes before publication.

## Review questions

1. Does the intro say the three headline changes, one performance number beside its baseline, and the counts, in three sentences?
2. Does every table follow one sentence that defines its measure, and does every column header say what is measured, with its unit and the versions compared?
3. Is any number on the page without its baseline, or any ratio without the version it is against?
4. Is there a bullet with two ideas, a semicolon chain, a second parenthesis, or a flag named twice?
5. Does Before you upgrade read as actions, and is every detail that is not an action under Upgrade notes?
6. Are the sections named and ordered as the template renders them, with the Storage subsection present only for a schema migration and no empty subsection left?
7. Does Notable fixes hold only bugs that shipped in the previous release, Security first?
8. Is a vendor's router, a host, a hardware name, a cluster or a tracker number anywhere in the page or the announcement?
9. Does `release.sh notes --check` pass on the file that goes into `gh release create`, and is the release title "vX.Y.Z"?
