# Aperture: A Context-Engineering Runtime for AI Agents

**Research Validation, Advanced Gap Analysis, System Architecture, and 12-Month Implementation Plan**

Aperture Engineering · November 2026 · Primary-source validation dossier (PDF is the presentation copy; this Markdown is the editable mirror)

---


## 1. Executive Summary

This dossier validates the Aperture project thesis - **a model-agnostic context-engineering runtime that curates agent context through a library of swappable operators, driven by a learned policy-selector and instrumented end to end** - against the state of research, tooling, and industry practice as of November 2026. It is written for the engineering team that will build the system: every claim is sourced, every competitor is mapped on explicit capability axes, every advanced gap comes with a concrete solution and an owner module, and the 12-month implementation plan is expressed in phases, gates, and deliverables rather than aspirations. The companion Markdown file mirrors this document for editing and version control.

The validation verdict is positive with sharpened scope. The measured failure mode Aperture targets - context rot: degradation of model reliability as input grows, independent of task difficulty - is now one of the most consistently replicated findings in applied LLM research [1][2]. The economic pressure behind it is visible in production surveys: 57 percent of surveyed organizations already run agents in production and 32 percent name quality as the top barrier [3], while practitioner analyses report that 60 to 90 percent of tokens in a typical coding-agent session are tool outputs that are read once and never referenced again [4][5]. Meanwhile the tooling landscape has fragmented into compression research, provider-native features, memory frameworks, and optimization proxies - exactly the fragmentation the original proposal identified. No system we could verify combines all four of the properties Aperture claims: a learned per-step policy, a model-agnostic runtime, a composable operator library, and a full audit trace.

| Metric | Evidence |
|---|---|
| **57%** | of 1,300+ surveyed organizations have agents in production [3] |
| **32%** | cite quality as the number one production barrier [3] |
| **60-90%** | of coding-agent session tokens are read-once tool output [5] |
| **84%** | token cut from Anthropic context editing + memory over 100 turns [6] |

What has changed since the original proposal is the competitive temperature. Between May and September 2026, three independent groups published learned context-management systems: AdaCoM trains an external LLM to edit a frozen agent's context [7]; ContextEvo evolves context policies directly from long-horizon trajectories [8]; and the CompactionRL line of work makes compaction a training-time objective for the model itself [9]. This is validating - it confirms learned curation is the right direction - and dangerous, because it narrows the novelty window. The sharpened claim in this dossier therefore shifts from “we learn when to curate” to a three-part statement: **learned selection over a composable operator library** (not a single learned operator), **inside a model-agnostic, fully observable runtime** (not a harness or one manager-agent pair), **evaluated with a decision-level benchmark** that no prior system provides.

> **Validation verdict: GO.** The unified gap is still open as of November 2026. The window is estimated at 12 to 18 months given the publication trajectory of AdaCoM, ContextEvo, and provider tooling. Aperture should proceed on the sharpened claim, add the six advanced-gap features to its v2 scope, and treat the decision-level benchmark (CurateBench) as a first-class, independently publishable contribution.

Six advanced gaps emerged from the research, each evidence-backed and each absent from the original proposal: cache-aware curation economics (compaction breaks prompt caches, and no system co-optimizes the two); governance decay (compaction measurably erases safety constraints - violations rose from 0 to 30 percent, up to 59 percent, in a 1,323-episode study [10]); the absence of a decision-level benchmark for curation policies; policy non-stationarity across models and domains; typed context contracts for multi-agent handoffs; and curation latency on the agent's critical path. Section 6 specifies a solution for each; Section 7 integrates them into a v2 architecture; Sections 8 and 9 turn them into a gated 12-month plan and an evaluation protocol that includes the strongest new baselines.

**Table 1. Validation questions, verdicts, and where the evidence lives**

| Question | Verdict | Confidence | Primary evidence |
|---|---|---|---|
| Is context rot a real, replicated failure mode? | Yes | High | Chroma 18-model study [1]; Lost in the Middle [2]; LongMemEval focused-vs-full drops [1] |
| Does the cost pressure exist at production scale? | Yes | High | LangChain 2026 survey [3]; tool-output dominance reports [5]; caching economics [11] |
| Is the unified gap (library + learned policy + runtime + trace) still open? | Yes | Medium-High | Capability matrix in Section 5; closest threats AdaCoM [7] and ContextEvo [8] |
| Will providers absorb this into platform features? | Partially - locked to their stacks | High | Anthropic context editing / memory / compaction [6]; advanced tool use [12] |
| Is the learned-selector beat-fixed-heuristics claim still novel? | Narrowly - needs sharpening | Medium | ContextEvo, AdaCoM, CompactionRL all learn policies in narrower scopes [8][7][9] |
| Are there adjacent research gaps worth claiming? | Yes - six identified | High | Section 6, each with primary-source evidence |


### 1.1 How to read this dossier

The document is written to be entered from different doors depending on the reader's role, and the sections are self-contained enough to support that:

- **Engineers implementing the runtime:** Sections 6, 7, and 8 plus Appendix A are the working specification - Table 5 (module specs), the interface contracts in Section 7.3, and the trace schema in Appendix A are normative once the project starts.
- **Research reviewers:** Sections 2 through 5 carry the evidence chain from raw claims to the capability matrix; Section 9 fixes the evaluation protocol; Section 11 states the publication narrative in advance so it cannot be retrofitted.
- **Supervisors and gate reviewers:** Section 8 (Tables 6-8) defines phases and gate criteria; Section 10 defines the risk triggers that force re-planning decisions onto the agenda.
- **Anyone re-verifying the claims:** Table 2 lists exactly what was checked and how; the numbered reference list at the end of the body is the index into every primary source.


## 2. Research Methodology and Source Verification

All research for this dossier was conducted in the first week of November 2026. The method had three stages. First, a broad sweep across academic indexes (arXiv, OpenReview, ICML/ICLR/EMNLP listings), vendor documentation (Anthropic, Claude Platform docs), engineering blogs of record (Anthropic, LangChain, Chroma), and practitioner forums (r/AI_Agents, r/LocalLLaMA, engineering blogs) to enumerate every system that plausibly competes with or overlaps Aperture. Second, primary-source verification: for every load-bearing claim we fetched the arXiv abstract, vendor documentation page, or repository README directly, rather than relying on summaries. Third, triangulation of numbers: quantitative claims are quoted only where they appear in a primary source, or are explicitly marked as vendor-reported or secondary in this document.

Three verification standards are used throughout. **Primary-verified** means the number was read directly from the paper, documentation, or repository this dossier cites. **Vendor-reported** means the number comes from the vendor of the system (for example Headroom's compression rates); such numbers are useful for landscape sizing but must be re-measured in Aperture's own harness before being used in any comparison. **Secondary** means the claim is reported by a credible third party because the primary is unavailable; these are marked and are never load-bearing for the verdict.

The original proposal was audited claim by claim. Its factual core survived: every named system exists, and the headline numbers attached to them are either correct as stated or correct with the refinements in Table 2. Two refinements matter for the engineering plan. The Anthropic “up to 84 percent token savings” figure specifically measures context editing paired with the memory tool over a 100-turn agent run, with context editing alone improving a long-horizon evaluation by 29 percent [6] - so the correct provider-native baseline to reproduce is the combined editing-plus-memory configuration, not editing alone. And Context-Folding is now formally published at ICML 2026 with an open re-implementation [13], which means it graduates from “arXiv reference” to “mandatory baseline.”

**Table 2. Verification status of load-bearing claims in the original proposal**

| Claim in proposal | Status | Finding |
|---|---|---|
| Chroma 2025 tested 18 frontier models; all degrade with input length | Verified | GPT-4.1, Claude 4, Gemini 2.5, Qwen3 among 18 tested; performance degrades non-uniformly even on simple tasks; distractor impact amplifies with length [1] |
| Middle-placed relevant information degrades accuracy sharply | Verified | Consistent with Lost in the Middle (TACL 2024) and Chroma's NIAH extensions [2][1] |
| ACON: 26-54% peak-token reduction on AppWorld/OfficeBench | Verified | Abstract reports 26-54% peak usage reduction and up to 46% improvement for smaller LMs [14] |
| Context-Folding: about 10x smaller active context | Verified | Abstract: active context 10x smaller than baselines while matching or outperforming ReAct; FoldGRPO RL; open-source re-implementation, ICML 2026 [13] |
| AdaCoM (2026): external RL-trained manager edits frozen agent context | Verified | arXiv:2605.30785; flexible modification actions, end-to-end RL; one manager-agent pair per training run [7] |
| Anthropic tools: up to ~84% token savings, fixed token-threshold triggers | Verified with refinement | 84% figure = context editing + memory tool over 100 turns; editing alone = +29% on a long-horizon eval; thresholds are configurable but fixed at runtime [6] |
| Headroom: model-agnostic proxy compressing by content type | Verified | Repository active at headroomlabs-ai/headroom; claims 20% fewer tokens for coding agents, 60-95% for JSON; reversible compression (CCR) and cache aligner; routing by content type, not learned [4] |
| Mem0 / Zep / Letta solve cross-session memory, not in-task curation | Verified | Mem0: extraction-first hybrid vector + graph; Zep: temporal KG (Graphiti); Letta: agent-managed context paging - all focused on recall across sessions [15][16][17] |
| Kapoor et al. (2024): agent benchmarks must report cost jointly with accuracy | Verified | TMLR; cost-adjusted evaluation and reproducibility argument; since reinforced by METR's cost-adjusted ability metrics (2026) [18][19] |

Limitations of this study are acknowledged explicitly. Vendor-reported numbers (Headroom's savings, Zep's LongMemEval results, Anthropic's 84 percent) were not independently reproduced; they size the landscape rather than settle comparisons. Two 2026 papers (AdaCoM, ContextEvo) have limited independent citation records at the time of writing, which is expected for very recent work; their capability claims are taken from the papers themselves. Finally, arXiv identifiers of the form 2605.xxxxx and 2606.xxxxx correspond to 2026 submissions and were verified live; any reader re-verifying after future arXiv policy changes should search by title.


### 2.1 What changed between drafting the proposal and today

The original proposal was written against the mid-2025 landscape; this audit was run in November 2026, and the eighteen months between them matter. Provider-native context management moved from an announcement to a platform default: editing, memory, and compaction are now documented, cookbook-integrated features with published evaluation numbers [6][20], and tool-side bloat is attacked by a second generation of features [12]. Learned context management went from zero published systems to at least five (ACON, Context-Folding, AdaCoM, ContextEvo, the CompactionRL line), three of them inside the last twelve months. Observability became near-universal in production (89 percent adoption [3]), which lowers the barrier for Aperture's trace-first pitch but also raises the bar for what counts as a contribution - a dashboard alone is no longer interesting, a dashboard of curation decisions with counterfactual replay still is. And prompt caching graduated from an optimization trick to the dominant economic lever on agent spend [11], which the original proposal did not model at all. Each of these shifts is absorbed somewhere in this dossier: the sharpened claim (Section 1), the mandatory new baselines (Section 5), the cache-aware reward (Section 6.1), and the governance-survival machinery (Section 6.2).


## 3. The Problem, Quantified


### 3.1 Context rot is real, universal, and task-independent

The single most important empirical foundation for Aperture is the Chroma technical report *Context Rot* (July 2025), which evaluated 18 LLMs - including GPT-4.1, Claude 4, Gemini 2.5, and Qwen3 - on tasks deliberately designed to hold complexity constant while varying only input length [1]. The design matters: because Needle-in-a-Haystack-style tests scale task difficulty with length, the Chroma team isolated length itself using extensions of NIAH with varying needle-question similarity, distractor counts, needle-haystack similarity, and haystack structure, across 8 input lengths and 11 needle positions per configuration. The findings are uncomfortable for the “bigger windows solve it” position: performance degrades with length on every model tested; degradation accelerates as needle-question similarity drops; distractors - content that is topically related but wrong - cause non-uniform, model-specific damage that amplifies with length; and, strikingly, shuffling the haystack to destroy its logical structure *improved* performance across all 18 models.

The same report grounds the problem in a realistic setting. On LongMemEval [21], models that reliably answer focused inputs (only the relevant history) show consistent degradation on the full 113k-token input, where they must first find the relevant parts and then reason over them. This is precisely the situation of a long-running agent: a growing trajectory in which retrieval and reasoning are forced to share a single forward pass. Related measurement work reinforces the pattern: NoLiMa shows steep degradation when lexical matching is removed (72.4 percent of its needle-question pairs require external knowledge) [1], and Lost in the Middle established the positional component - models attend best to the start and end of long contexts and worst to the middle [2].


### 3.2 Production evidence: quality is the bottleneck, and context is where it dies

Industry data now matches the lab data. LangChain's *State of Agent Engineering* survey (June 2026, 1,300+ respondents) found 57 percent of organizations with agents already in production, with quality named the top barrier by 32 percent - cost concerns, notably, declined year over year [3]. The same survey found observability near-universal (89 percent) while evaluation adoption lags at 52 percent: teams can see what their agents did but cannot yet attribute why it went wrong. That is exactly the hole Aperture's context-health trace addresses - observability of *curation decisions*, not just API spans.

On the cost side, the dominant single factor is tool output. Practitioner measurements across several tooling communities converge on the estimate that 60 to 90 percent of tokens in a coding-agent session are tool results read once and never referenced again [5][4]. Anthropic's own engineering guidance frames context as a finite resource with an “attention budget,” and ships server-side machinery - tool-result clearing, context editing, compaction, a file-based memory tool - that would be unnecessary if passive accumulation worked [22][6]. Even Claude Code's operational behavior tells the story: its auto-compact threshold was moved earlier (community measurements around 64 to 75 percent full rather than 90+), trading session continuity for preserved reasoning quality - an implicit acknowledgment that context saturation degrades performance before any hard limit [23].


### 3.3 The economic twist the original proposal missed: prompt caches

Since the proposal was drafted, prompt caching has become the decisive economic lever for agents, and it interacts with curation in a non-obvious way. Provider caches (Anthropic, OpenAI, Gemini, Bedrock, DeepSeek) discount repeated *prefixes*: a 20,000-token stable prefix at 80 percent reuse cuts its effective cost by roughly 55 to 70 percent, and one documented production agent moved its cache hit rate from 7 to 84 percent by relocating a single unstable breakpoint [11]. The catch for curation is mechanical: every summarization or eviction rewrites the prefix, and a rewritten prefix is a cache cold start - one full-price turn, on every compaction [24][25]. Practitioners have internalized this: production patterns now order prompts by stability (long-lived instructions and tool definitions first, volatile state last), give the stable head a fixed budget, and compact only when the volatile tail threatens that head - treating caching as a routing problem rather than a prompt problem [26].

This reframes the research question. The original proposal asked how to maintain a compact, accurate, task-relevant context to reduce token cost. That is necessary but no longer sufficient: a curation policy that minimizes raw tokens can easily *increase* dollar cost by invalidating caches every turn, and a policy that never touches the prefix preserves cache hits but rots the window. The correct objective is cache-adjusted:

> **Reframed research question.** How can an agent dynamically maintain a compact, accurate, task-relevant context throughout a long-running workflow - minimizing **cache-adjusted token cost** (not raw tokens), preserving task performance, keeping safety-critical content intact, and making every curation decision auditable - across any model or framework?

Everything that follows inherits this reframing. The v2 policy-selector's reward function (Section 7), the Cache-Adjusted Token Cost metric (Section 9), and the cache-align operator (Section 6, AG1) are all direct consequences of taking prompt caching seriously as a first-class constraint on context engineering.


## 4. Literature and Landscape Review 2023-2026

This section maps the landscape in seven categories, ordered from measurement work through learned methods to productized infrastructure. Figure 1 places the milestones on one timeline; Figure 2 compares the token-savings numbers each system reports. The review is deliberately biased toward systems Aperture must position against; a comprehensive academic survey of context engineering (165 pages, 226+ citations) is available separately [27].

![Figure 1. Context engineering, 2023-2026: measurement studies, learned context management, provider tooling, and memory/infrastructure. Sources: per-reference arXiv listings and vendor release notes.](aperture_assets/fig1_timeline.png)

*Figure 1. Context engineering, 2023-2026: measurement studies, learned context management, provider tooling, and memory/infrastructure. Sources: per-reference arXiv listings and vendor release notes.*


### 4.1 Measurement and benchmarking

The measurement thread establishes both the failure mode and the rules for fair evaluation. Lost in the Middle (TACL 2024) demonstrated positional degradation in long contexts [2]. The Chroma Context Rot report (July 2025) generalized degradation across 18 models under controlled length-only variation [1]. LongMemEval (ICLR 2025) provides the conversational long-memory benchmark Chroma used to show focused-versus-full-input drops [21]. On the agent side, tau-bench and tau2-bench (Sierra) evaluate tool-using agents against simulated users and policies - early results showed GPT-4-class agents succeeding on fewer than half of tasks [28][29] - while AppWorld contributes a controllable apps-and-people environment with programmatic grading [30], and OfficeBench extends long-horizon evaluation into office workflows (used by ACON) [14]. Two methodology papers define how results must be reported: AI Agents That Matter (TMLR 2024) argues benchmarks that ignore cost reward needlessly expensive agents and establishes cost-matched comparison practice [18]; METR's 2026 metrics work operationalizes cost-adjusted ability scores [19]. The broader agent-evaluation landscape is surveyed in [31].


### 4.2 Prompt and context compression

Compression research supplies Aperture's single-operator predecessors. LLMLingua-2 (2024) formulates task-agnostic prompt compression as token classification distilled from GPT-4, achieving 2x-5x compression with 3x-6x faster compression and 1.6x-2.9x end-to-end latency speedup - evidence that a small trained compressor can run inline without wrecking latency [32]. ACON (October 2025) is the closest compression-side prior: it learns compression guidelines from agent failure cases and distills them into a small compressor, reducing peak token usage by 26 to 54 percent on AppWorld and OfficeBench while *improving* task success, and enabling smaller models to act as long-horizon agents (up to 46 percent improvement) [14]. Its structural limitation, as the original proposal states, is that it always compresses: one operator, refined offline, with no choice between compress, retrieve, isolate, or leave-alone.


### 4.3 Learned context management - the direct competitor set

This category is where the field moved fastest in 2026, and it deserves the closest reading. **Context-Folding** (October 2025; ICML 2026) trains an agent via a purpose-built RL method (FoldGRPO) to branch into sub-trajectories and fold them into summaries on completion, keeping the active context 10x smaller than baselines while matching or beating ReAct on deep-research and SWE tasks [13]. Its limitation is portability: the folding behavior lives in the trained weights of one base model. **AdaCoM** (May 2026) moves the learning outside the agent: an external LLM is trained with end-to-end RL to manage a frozen agent's context through flexible modification actions [7]. This is the closest prior work to Aperture in spirit - model-agnostic in the sense that the agent is frozen - but it optimizes one manager for one agent pair, with a single learned action set rather than a reusable operator library, and without an audit trace or a decision-level benchmark. **ContextEvo** (September 2026) learns context-management policies by reconstructing the model-visible context at key decision points of past trajectories, identifying context-related failures, and applying targeted policy updates; it improves several long-horizon benchmarks and performs comparably to strong agent harnesses [8]. It operates at the harness level (built on one harness) rather than as a reusable runtime with observable operator semantics. **CompactionRL** (2026, Zhipu/GLM team, reported via secondary source [9]) trains the model itself to expect and execute compaction, jointly optimizing task execution and summary generation - 66.8 percent Pass@1 on SWE-bench Verified (+7.0 points) on GLM-4.5-Air - the opposite pole from Aperture: learned, but baked into the model. **Memory-R1** (2025) trains ADD/UPDATE/DELETE/NOOP memory operations with RL (PPO/GRPO), generalizing from only 152 QA pairs across LoCoMo, MSC, and LongMemEval [33] - learned memory operations, but on the cross-session axis, not in-task curation. **MemAct** (2026, secondary source [9]) similarly treats context curation as policy actions optimized end to end.

The synthesis of this category is the pivotal finding of this review: **three independent groups converged on learned context management within five months** (AdaCoM in May, CompactionRL mid-2026, ContextEvo in September 2026), after ACON and Context-Folding set the stage in late 2025. For validation purposes this is the strongest possible external signal that Aperture's core direction is correct. For strategy purposes it means the generic claim “we learn when to curate” will be un-novel by the time the FYP publishes, and the defensible position is the decomposition: operator library + per-step selector + model-agnostic runtime + full trace + decision-level evaluation, unified in one system.


### 4.4 Provider-native context tooling

Anthropic shipped the most complete provider-native stack. Context editing (October 2025) automatically clears stale tool calls and results as the window fills; the memory tool persists state outside the window; server-side compaction summarizes and reinitializes conversations. Anthropic reports that context editing alone improved a long-horizon agent evaluation by 29 percent, and that editing paired with the memory tool cut token consumption by 84 percent over a 100-turn run [6]. The Claude cookbook (March 2026) now formally compares memory, compaction, and tool clearing as composable strategies with different cost profiles [20]. In November 2025, advanced tool use added a Tool Search Tool (deferred tool discovery), programmatic tool calling, and tool-use examples - attacking tool-definition bloat, the other half of context waste [12]. These features are effective but provider-locked, trigger on fixed token thresholds rather than learned policy, and (as Section 6 AG2 documents from independent research) their compaction can silently erase governance constraints. They are simultaneously Aperture's baseline to beat and its building blocks: v2 wraps them as fallback operators behind the same policy interface.


### 4.5 Cross-session memory frameworks

Mem0 (hybrid vector store plus knowledge graph, extraction-first) [15], Zep (temporal knowledge graph via Graphiti, with fact validity periods) [17], Letta/MemGPT (the OS-inspired original: the agent pages its own memory blocks) [16], MemOS (memory as a system resource with MemCube units spanning plaintext, activation, and parameter memory) [34], and MemoryOS (EMNLP 2025) [35] all solve the *recall-across-sessions* problem: distilling, storing, and resurfacing facts over days or weeks. They are complementary to Aperture rather than competing: their stores are natural sources for Aperture's semantic retrieval operator, and Section 6's watchlist notes the eventual convergence (a unified context plane serving both in-task curation and cross-session memory). The scope fence stands: Aperture curates one active trajectory in real time.


### 4.6 Infrastructure and products

**Headroom** is the closest existing market analog and the most useful product benchmark: an open-source proxy and SDK (pip/npm) that compresses tool outputs, logs, files, and RAG chunks before they reach the model, by content type - reporting 60 to 95 percent savings on JSON and about 20 percent for coding agents (vendor-reported) [4]. Two of its design choices matter to Aperture. Its compression is reversible (a CCR store keeps originals retrievable), an idea Aperture's artifact-offload plane adopts; and it ships a cache aligner that stabilizes timestamps and UUIDs to protect provider caches - evidence that cache-awareness is already productizable, though only at the content level, with fixed content-type routing and no learned, trace-aware policy, and no published task-level evaluation. **LangChain Deep Agents** (January 2026) builds context management into a framework: offloading, summarization, and a filesystem abstraction for long-running tasks [36], and LangChain's middleware pattern (dynamic prompts, memory, compression, isolation) is normalizing curation as a framework concern [3]. LangSmith/Langfuse-class platforms provide the observability layer teams already run (89 percent adoption [3]) but observe calls, not curation decisions. LiteLLM has become the de facto model-agnostic gateway, validating Aperture's foundation choice.


### 4.7 Adjacent paradigms worth tracking

Two lines of work attack the same problem from different assumptions. **Recursive Language Models** (MIT CSAIL, December 2025) treat a long prompt as an external environment that the model programmatically inspects and recursively decomposes, scaling past 10 million tokens and outperforming base models and task-agnostic scaffolds on long-context tasks [37] - an inference-strategy answer to context rot rather than a curation answer, and a plausible future operator inside Aperture (see the Section 6 watchlist). **ACE** (Agentic Context Engineering; ICLR 2026) treats contexts as evolving playbooks refined through generation, reflection, and curation, explicitly fighting “brevity bias” and “context collapse”; it gains 10.6 percent on agent benchmarks and 8.6 percent on domain tasks and matches a top-ranked production agent on the AppWorld leaderboard with a smaller open model [38]. ACE evolves the *content* of context across episodes; Aperture curates the *window* within an episode - orthogonal axes that share vocabulary and could share machinery.

![Figure 2. Reported token reductions by system. Metrics differ (peak context vs total tokens vs single tool-output class; active window vs cumulative spend); ranges shown where the source reports them. Vendor-reported numbers are marked and must be re-measured under identical harnesses before comparison. Sources: refs [4], [5], [14], [21], [26].](aperture_assets/fig2_savings.png)

*Figure 2. Reported token reductions by system. Metrics differ (peak context vs total tokens vs single tool-output class; active window vs cumulative spend); ranges shown where the source reports them. Vendor-reported numbers are marked and must be re-measured under identical harnesses before comparison. Sources: refs [4], [5], [14], [21], [26].*

Three converging signals close the review. First, the measurement literature is unanimous and current: context rot is universal across model families and worsens with distractors and structure. Second, every serious actor - compression researchers, RL labs, providers, framework authors, infrastructure startups - is now building context management, each into a different wall of the same room. Third, the evaluation layer has not kept up: no published benchmark scores curation *decisions* rather than end-task outcomes, and no system reports cache-adjusted cost. Those two evaluation holes are Aperture's cheapest novel contributions, and Section 6 turns them into concrete plans.


## 5. Competitive Matrix and Gap Verdict

The matrix below scores sixteen systems on the six axes that define Aperture's claim. The axes are: **Learned policy** (curation decisions made by a trained or online-learned selector, not fixed thresholds); **Model-agnostic** (works across providers without retraining any model); **Operator library** (multiple composable curation primitives, not one technique); **Audit trace** (every curation decision logged with what, why, and cost); **Decision-level eval** (published evaluation of individual curation decisions, not only end-task scores); and **In-task focus** (curating the active trajectory in real time, versus cross-session recall). Ratings are Y (yes), P (partial), or N (no), justified by the sources in Section 4.

**Table 3. Capability matrix: sixteen systems against Aperture's defining axes (Y = yes, P = partial, N = no)**

| System | Year | Learned policy | Model-agnostic | Operator library | Audit trace | In-task focus | Primary gap relative to Aperture |
|---|---|---|---|---|---|---|---|
| LLMLingua-2 [32] | 2024 | Y | Y | N | N | P | One operator (token pruning); prompt-level, not trajectory-aware; no task-level agent evaluation |
| ACON [14] | 2025 | Y | P | N | N | Y | Always compresses; guidelines distilled offline into one compressor; no selection among operators |
| Context-Folding [13] | 2025-26 | Y | N | N | N | Y | Folding behavior trained into one base model's weights; not portable; no audit trail |
| AdaCoM [7] | 2026 | Y | P | N | N | Y | One learned manager for one frozen agent pair; single action set; no library, trace, or benchmark |
| ContextEvo [8] | 2026 | Y | P | N | P | Y | Evolves policies inside one harness; no reusable runtime or operator semantics; no decision-level eval |
| CompactionRL [9] | 2026 | Y | N | N | N | Y | Compaction as training objective - model-specific; opposite pole from a model-agnostic runtime |
| Memory-R1 [33] | 2025 | Y | P | N | N | N | Cross-session memory operations, not in-task trajectory curation |
| MemAct [9] | 2026 | Y | P | N | N | Y | Curation-as-actions for one agent stack; no operator library or observability |
| ACE [38] | 2025-26 | Y | Y | P | P | N | Evolves playbook content across episodes; orthogonal to in-window per-step curation |
| Recursive Language Models [37] | 2025 | N | Y | P | N | Y | Inference-strategy paradigm; fixed recursive decomposition policy; heavy token economics |
| Anthropic editing + memory + compaction [6] | 2025 | N | N | P | P | Y | Provider-locked; fixed token-threshold triggers; compaction can silently drop constraints [10] |
| Anthropic advanced tool use [12] | 2025 | N | N | P | P | Y | Attacks tool-definition bloat only; provider-locked; no learned policy |
| LangChain Deep Agents [36] | 2026 | N | Y | P | P | Y | Framework-native offload/summarization; fixed strategies; no cross-model policy learning |
| Headroom [4] | 2025-26 | N | Y | P | P | Y | Routes by content type, not trace-aware policy; no learned trigger; no published task-level eval |
| Mem0 / Zep / Letta [15][17][16] | 2023-26 | P | Y | P | P | N | Cross-session recall systems; different problem slice; natural data sources for retrieval operator |
| MemOS [34] | 2025 | P | Y | P | P | N | Memory lifecycle OS; long-term memory management, not real-time window curation |

**The closest threats deserve individual analysis.** AdaCoM is the nearest neighbor on the research axis: it proves an external, learned manager can outperform fixed curation for a frozen agent, which is 40 percent of Aperture's thesis. What it does not provide is generality - the manager is trained per agent pair, its action set is fixed by its training, and nothing about its decisions is inspectable or reusable. ContextEvo is the nearest on policy learning: it extracts context-management policies from real trajectories, but as harness-level evolution rather than a runtime service, and it publishes no decision-level evaluation. Headroom is the nearest product: model-agnostic, cache-aware, already in the packaging developers want - but its routing is content-type heuristics, and no benchmark validates that its compressions preserve task success. Anthropic's stack is the nearest deployed baseline and the one Aperture must empirically match or beat on Claude specifically, while beating it on every other model.

> **Gap verdict.** As of November 2026 no verified system combines: (1) a learned, per-step policy over (2) a composable library of curation operators, running (3) model-agnostically across providers and frameworks, with (4) a complete audit trace of every decision, evaluated (5) at the decision level with (6) cache-adjusted cost and safety-survival metrics. Every neighbor covers one or two axes. The unified gap is open - but ContextEvo's September 2026 publication and the provider feature cadence put the realistic closure window at 12 to 18 months.

Three positioning requirements follow directly, and the rest of this document implements them. **First**, the headline research claim must be comparative over the library: the learned selector must beat not only full-history and naive heuristics, but the best single fixed strategy (including ACON-style always-compress and Anthropic-style threshold editing) - “learned selection beats every single fixed strategy” survives the 2026 literature, while “learned curation is new” does not. **Second**, observability must be promoted from feature to contribution: the context-health trace and its replay harness are what no learned competitor offers, and they are also what makes the claim falsifiable. **Third**, the decision-level benchmark should be built early and published independently: it converts even a negative selector result into a community contribution, and it is the piece most likely to outlive the specific policy.


## 6. Advanced Gaps and Proposed Solutions

The original proposal validated the gap; the research for this dossier found six gaps beyond it - failures and blind spots that *no* current system addresses, including Aperture as originally scoped. Each gap is presented as evidence, why it remains open, a proposed solution with its v2 module, and the evaluation metric that will prove the solution. Table 5 at the end of the section maps all six onto the plan.


### 6.1 AG1 - Cache-aware curation economics

**Evidence.** Provider prompt caches discount stable prefixes: a 20k-token prefix at 80 percent reuse cuts its effective cost 55 to 70 percent; misplaced dynamic content (a timestamp early in a system prompt) can drive hit rates to zero; one production agent moved from 7 to 84 percent hit rate by relocating a single breakpoint [11]. Compaction is mechanically hostile to caches - rewriting the prefix is a cache cold start [24][26]. Practitioners engineer around it by hand: stable-head prompt ordering, fixed head budgets, compact-only-when-needed triggers [26][25]. Headroom ships a content-level cache aligner [4]. **Why still open.** Every learned system in Section 4.3 optimizes token counts or end-task reward; none models cache-adjusted cost. Provider tools trigger on token thresholds and are cache-blind. No published policy co-optimizes curation value against prefix invalidation. **Proposed solution.** Make the cache a first-class sensor and the reward a first-class economic function: the v2 selector's reward is the expected cache-adjusted cost of the next N calls (Section 7), a new *cache-align* operator enforces stability-ordered layout with a fixed reusable head, and the compaction trigger becomes cache-aware (compact when the volatile tail threatens the head budget, absorbing the cold start deliberately rather than on a schedule). **Metric.** Cache-Adjusted Token Cost (CATC): dollars actually paid, crediting cached-prefix discounts, normalized per task; target is 15 percent CATC improvement over the raw-token-optimal policy at equal task success (Section 9). **Novelty:** high; **effort:** M (module exists, reward integration is new).


### 6.2 AG2 - Governance decay and curation safety

**Evidence.** The strongest new empirical finding of this research: *Governance Decay* (June 2026) shows that compaction silently erases in-context governance constraints. Across seven model families and 1,323 episodes on their ConstraintRot benchmark, prohibited-action rates rose from 0 percent with the policy in full context to 30 percent after compaction - up to 59 percent for the worst models - and the failure split is diagnostic: when constraints survived the summary, violations stayed at 0 percent; when the summary dropped them, violations hit 38 percent [10]. The authors also demonstrate a Compaction-Eviction Attack: adversarial in-context content can bias the summarizer into omitting legitimate policies, defeating every evaluated model. Their mitigation - Constraint Pinning, quarantining constraints from lossy compaction - is training-free and restores 0 percent violations, but it is a static heuristic with no detection layer. Enterprise security guidance now flags the same risk independently [39]. **Why still open.** Pinning protects only what it is told to, provides no observability when something is lost, does not integrate with learned curation (a selector can still choose an operator whose summary quietly paraphrases away a permission scope), and the adversarial biasing attack remains unsolved. **Proposed solution.** A protected-class system as runtime metadata: constraints, permissions, user intent, and safety-critical tool errors are tagged at ingestion, excluded from destructive operators by the guardrail layer, and held in the pinned store. After every destructive curation decision, cheap *survival probes* (templated questions over the post-curation context) verify that pinned content remains retrievable; failures raise decay alerts in the trace and feed a penalty into the selector's reward. The observability layer gains a governance view an operator or security team can audit. **Metric.** Constraint-survival rate at 100 percent on the pinned suite (reproducing ConstraintRot conditions), with the Compaction-Eviction Attack replayed against Aperture's summarizers as a stress test. **Novelty:** medium-high (integration + verification layer is new; pinning itself is published); **effort:** M.

![Figure 3. Governance decay under compaction. Left: prohibited-action rates before and after compaction across 7 model families and 1,323 episodes. Right: the same outcomes split by whether constraints survived the summary. Data: Governance Decay, arXiv:2606.22528 [10].](aperture_assets/fig3_governance.png)

*Figure 3. Governance decay under compaction. Left: prohibited-action rates before and after compaction across 7 model families and 1,323 episodes. Right: the same outcomes split by whether constraints survived the summary. Data: Governance Decay, arXiv:2606.22528 [10].*


### 6.3 AG3 - A decision-level benchmark for curation policies

**Evidence.** Agent benchmarks score end-task success, occasionally with cost (Kapoor's argument [18]; METR's cost-adjusted scores [19]); the evaluation landscape is fragmented [31]. No published benchmark isolates the quality of individual curation decisions: ConstraintRot covers governance only [10]; ACON and Folding report end-task and token metrics [14][13]; no system can currently answer “was dropping this specific observation the right call?”. **Why still open.** Decision-level evaluation requires replayable traces with counterfactual branches - re-running the same step under a different curation decision under controlled conditions - which no existing trace format supports; teams instead compare whole-system arms and cannot attribute gains. **Proposed solution.** Build **CurateBench**: a trace schema (every step's full context, the chosen operators and parameters, token costs, cache state, task outcome), a replay engine that can reconstruct any step's model call under an alternative operator policy, and decision-level metrics: *curation regret* (success-rate delta between the chosen decision and the best counterfactual at equal cost), *information-loss attribution* (which dropped spans correlate with later failure), constraint-survival, and cache-adjusted cost. Seed the benchmark with several hundred traces from AppWorld and tau2-bench runs across all evaluation arms, and release schema + engine + traces as the project's first artifact (Phase P3). **Metric.** Adoption-adjacent: CurateBench scores for Aperture's own selector vs fixed policies; the artifact's standalone publishability is the point. **Novelty:** high; **effort:** M-H.


### 6.4 AG4 - Policy non-stationarity and online adaptation

**Evidence.** Offline-trained curation policies face two drifts: the model behind the agent changes (frontier lineages turn over within months - tau2 leaderboards in 2026 are dominated by models that did not exist a year earlier [29]), and the task distribution shifts per deployment. ContextEvo's authors state directly that fixed or locally evolved context strategies fall short under long-horizon information pressure [8]; AdaCoM's manager is bound to its training pair [7]; ACON's distilled compressor inherits its training distribution [14]. **Why still open.** No published operator-selector adapts online, with a safety fallback, and reports staleness behavior. **Proposed solution.** The v2 selector is an online contextual bandit (LinUCB- or Thompson-sampling-class) over operator choices, updated from outcome rewards; a drift detector monitors feature-distribution shift; on high uncertainty or detected drift the selector falls back to the tuned fixed heuristic (safe mode), and per-model calibration profiles are learned in a lightweight first-run procedure. **Metric.** Policy-staleness curve: selector performance vs the best fixed policy as the evaluation model changes across at least three model families; online-regret vs the offline oracle. **Novelty:** medium-high in this applied form; **effort:** M.


### 6.5 AG5 - Typed context contracts for multi-agent handoffs

**Evidence.** Sub-agent isolation is already the community's favorite context-pollution defense - keep the parent's prefix byte-stable, do exploratory work in a child, return only the distilled result [26][36] - but the handoff itself is ad hoc: untyped dicts passed at spawn, no budget, no provenance, and practitioners note the child's context is re-paid in full on every spawn unless the spawn prompt is itself a stable cacheable prefix [26]. Multi-agent frameworks document handoff mechanics as message passing without context guarantees [40]. **Why still open.** No runtime treats a handoff as a first-class, typed, budgeted object with provenance and cache behavior. **Proposed solution.** Context Contracts: a schema (task id, objective, token budget, allowed context classes, TTL, provenance chain, required return schema) validated by the runtime; the sub-agent-isolation operator is upgraded to create contract-bound children whose spawn prompts are template-stable (therefore cacheable across spawns); violations (budget overrun, forbidden class inclusion) fail loudly in the trace. **Metric.** Spawn cache-reuse rate; child-context overhead per completed subtask; contract-violation count (target zero). **Novelty:** medium (engineering-novel, publishable as part of the runtime story); **effort:** S-M.


### 6.6 AG6 - Curation latency and asynchronous scheduling

**Evidence.** Curation that runs serially before every model call adds latency exactly where agents are most latency-sensitive. The compression literature engineers hard against this: LLMLingua-2 is 3x-6x faster than prior compressors with 1.6x-2.9x end-to-end speedups [32]; ACON distills its compressor into a small model [14]; RLM's economics are dominated by token execution cost [37]. Practitioners report compression proxies adding noticeable first-token delay. **Why still open.** Latency is treated as a compression-model property, not a scheduling problem; no published agent runtime overlaps curation with tool execution. **Proposed solution.** An async scheduler in the Curation Engine: while the agent executes a tool call, the runtime speculatively pre-computes the curation work the next model call will likely need (incremental embedding of the new observation, eager summarization of oversized outputs, cache-head revalidation); the selector then runs on precomputed features at decision time, and heavy operators execute only when their precomputed result is fresh. **Metric.** p50/p95 added latency per step vs the uncaged agent loop (target: p50 overhead under 10 percent); precomputation hit rate. **Novelty:** medium (systems-novel); **effort:** M.


### 6.7 Watchlist (monitored, not scheduled)

Five adjacent developments are tracked but deliberately out of scope for the 12-month window: unifying the context plane with cross-session memory systems (MemOS-style memory lifecycle [34] - convergence is likely post-FYP); a PII/privacy-scrubbing operator (compliance demand is real but evaluation is a project of its own); interplay with model-level KV-cache compression (a different layer of the same stack); formal information-theoretic guarantees on curation loss (interesting theory, weak near-term payoff); and RLM-style recursive decomposition as a tenth operator once the runtime is stable [37]. Each is recorded in the repository's research radar with a trigger condition for promotion into scope.

**Table 4. Advanced gap to solution mapping**

| Gap | Core solution | Owning module (v2) | Proving metric | Plan phase |
|---|---|---|---|---|
| AG1 Cache economics | Cache-aware reward + cache-align operator + cache-aware compaction trigger | Policy-Selector; Curation Engine | CATC at equal success | P4 (M9-M10) |
| AG2 Governance decay | Protected classes + pinning + survival probes + decay alerts | Context Plane; Observability | Constraint-survival 100% | P4 (M9-M10) |
| AG3 Decision-level benchmark | CurateBench: trace schema + counterfactual replay engine | Trace Ledger; release artifact | Curation regret; release | P3-P4 (M7-M10) |
| AG4 Non-stationarity | Online bandit + drift detection + safe fallback | Policy-Selector | Staleness curve; online regret | P3-P4 (M7-M10) |
| AG5 Context contracts | Typed handoff schema + cacheable spawn templates | Curation Engine; Context Plane | Spawn cache reuse; zero violations | P4 (M9-M10) |
| AG6 Curation latency | Async scheduler + speculative pre-curation | Curation Engine | p50 overhead < 10% | P4 (M9-M10) |


## 7. Aperture v2 Architecture

The v2 architecture keeps the original proposal's four-layer shape - it validated well - and adds what the advanced gaps require: a protected-class guardrail in the decision path, a cache-aware reward in the selector, an async scheduler in the engine, and a shared Context Plane that gives every operator versioned, addressable state. Figure 4 shows the full system; Figure 5 zooms into the per-step decision loop. The design principles extend the original three (model-agnostic, observable, policy-driven) with two forced by the 2026 evidence: **cache-faithful** (every decision accounts for its effect on prefix caches) and **safety-preserving** (protected content cannot be silently destroyed by any operator).

![Figure 4. Aperture v2 architecture. Layers 1-4 form the request path; the observability rail cross-cuts every layer; the context plane at the bottom is the shared state all operators read and write.](aperture_assets/fig5_architecture.png)

*Figure 4. Aperture v2 architecture. Layers 1-4 form the request path; the observability rail cross-cuts every layer; the context plane at the bottom is the shared state all operators read and write.*


### 7.1 Module specifications

**Table 5. v2 module specifications**

| Module | Responsibility | Key interface | Technology |
|---|---|---|---|
| Agent Interface | Intercept agent state before every model call; normalize framework-specific formats into the trace schema | on_pre_call(state) -> SessionView; adapters subscribe to framework events | LangGraph / CrewAI / raw SDK adapters; MCP tap |
| Curation Engine | Compose the next context window by executing the operator plan; enforce guardrails; schedule async work | compose(session, plan) -> Window; async submit(work) | Pure Python core; asyncio; pluggable operator registry |
| Operator Library | Seven composable operators with typed parameters (Figure 4, Layer 2); each returns a diff + audit record | Operator.apply(window, ctx, params) -> WindowDiff | BGE/E5 + Qdrant/FAISS (retrieval); Qwen2.5/Llama-3.x 7-8B quantized (summarize) |
| Policy-Selector | Choose operator plan per step; online updates; drift detection; safe fallback to tuned heuristic | select(features) -> OperatorPlan; update(reward) | LinUCB / Thompson sampling (scikit-learn + numpy); optional small MLP |
| Model Interface | Uniform calls to any provider; token + cache telemetry; provider-native tools exposed as fallback operators | complete(window) -> Response + Telemetry | LiteLLM; vLLM prefix-cache stats for open weights |
| Context Plane | Versioned shared state: embedding index, pinned store, artifact offload, cache telemetry, contract registry | put/get/versioned handles; pin(class, span); register(contract) | SQLite + local object store; Qdrant or FAISS |
| Observability + Trace Ledger | Append-only trace of every decision; survival probes; decay alerts; replay harness for counterfactuals | record(event); probe(window) -> SurvivalReport; replay(trace, alt_policy) | JSONL + OTel-style spans; React dashboard |


### 7.2 The per-step decision loop

![Figure 5. The v2 per-step decision loop. Steps 1-5 form the forward path; step 6 closes the loop with an online reward that prices task outcome, cache effect, and constraint survival together.](aperture_assets/fig6_loop.png)

*Figure 5. The v2 per-step decision loop. Steps 1-5 form the forward path; step 6 closes the loop with an online reward that prices task outcome, cache effect, and constraint survival together.*

One forward pass proceeds as follows. **(1) Observe:** the Agent Interface hands the engine a SessionView - budget consumed, task phase, tool-output volume since the last call, redundancy and drift signals, and the current prefix hash. **(2) Guardrail:** protected classes are resolved; destructive operators are constrained to exclude pinned spans; the guardrail may force-pin content that arrives tagged or that the drift detector flags as constraint-like. **(3) Select:** the contextual bandit maps features to an operator plan (which operators, in what order, with which parameters); when uncertainty is high or drift is detected, the plan degrades to the tuned fixed heuristic. **(4) Execute + log:** operators run - synchronously for cheap ones, speculatively during tool execution for expensive ones - and every diff (what was dropped, by which operator, why, how many bytes, expected cache effect) lands in the trace ledger. **(5) Call:** the composed window goes to the model through LiteLLM; response telemetry includes realized cache hit/miss and token counts. **(6) Reward:** the bandit is updated with a scalar combining task progress, cache-adjusted cost delta, and survival-probe results - the mechanism that makes AG1, AG2, and AG4 properties of the same loop rather than three bolted-on features.


### 7.3 Core interfaces and data contracts

```
# aperture/interfaces.py  (shape - not final signatures)

class Operator(Protocol):
    name: str                      # "keep_recent", "semantic_retrieval", ...
    cost_hint: Callable[[Window, Params], int]
    def apply(self, window: Window, ctx: SessionView,
              params: Params) -> WindowDiff: ...
    # WindowDiff: kept_spans, dropped_spans[(span_id, reason, bytes)],
    #             new_spans, cache_head_unchanged: bool, probe_targets: list[SpanId]

class PolicySelector(Protocol):
    def select(self, f: Features) -> OperatorPlan          # ops + params + order
    def update(self, r: Reward) -> None                    # online, per step
    def fallback(self) -> OperatorPlan                     # tuned fixed heuristic

class Reward(NamedTuple):
    task_progress: float        # graded or heuristic progress signal
    cost_delta_usd: float       # cache-adjusted: tokens x price - cache_credit
    cache_invalidation: int     # bytes of live prefix invalidated
    survival_penalty: float     # from post-edit constraint probes
    latency_ms: float

class ContextContract(NamedTuple):                          # AG5
    task_id: str; objective: str; token_budget: int
    allowed_classes: frozenset[str]; ttl_steps: int
    provenance: tuple[str, ...]; return_schema: str

# Trace event (append-only, one JSONL line per decision):
# { step, ts, features, plan, diffs[], cache: {prefix_hash, hit, invalid_bytes},
#   probes[], reward, task_outcome_later }
```


### 7.4 Repository layout

```
aperture/
  aperture/
    __init__.py            # pip-installable entry: aperture.wrap(agent_loop)
    session.py             # SessionView, Window, Span, protected-class metadata
    engine.py              # Curation Engine: compose(), guardrails, async scheduler
    operators/             # keep_recent, semantic_retrieval, summarize, dedupe,
      ...                  # subagent_isolation, pin_protected, cache_align
    policy/
      features.py  bandit.py  fallback.py  calibration.py
    models/
      litellm_gateway.py   # telemetry + provider-native fallback operators
    store/                 # context plane: index, pinned, artifacts, telemetry
    trace/
      ledger.py  probes.py  replay.py      # CurateBench replay engine lives here
    contracts.py           # AG5 context contracts
  adapters/
    langgraph.py  crewai.py  raw_loop.py  mcp_tap.py
  bench/                   # CurateBench: schema, scorer, seeded trace sets
  dashboard/               # React + OTel spans: context-health views
  eval/                    # harness for the 8-arm comparison (Section 9)
  tests/  docs/  examples/
```

Compatibility is preserved by construction: the runtime wraps any loop that calls an LLM, because every framework adapter reduces to the same pre-call hook. The summarizer runs as a quantized 7-8B model on a single consumer GPU or Colab/Kaggle session; the bandit is CPU-scale; everything else is orchestration. The heavyweight dependency is discipline: the trace schema is versioned from day one (Phase P0) because CurateBench, the replay harness, and the decay alerts all consume it - a schema change in month eight would invalidate the trace corpus and the benchmark seeds with it.


### 7.5 What v2 deliberately does not build

The original proposal's scope fence survives the v2 upgrade, and it is worth restating what is consciously excluded: no fine-tuning of base models (CompactionRL's path - powerful, but model-bound and out of reach on FYP compute); no new agent framework (Aperture wraps existing loops rather than replacing them); no cross-session memory store (the Mem0/Zep/Letta/MemOS territory - Aperture consumes such stores through its retrieval operator but does not build one); no hosted multi-tenant service (the deliverable is a library plus a benchmark, not a SaaS); and no custom model-level KV-cache machinery (a different layer of the stack, monitored on the watchlist). Each exclusion has the same justification: it protects the two contributions that are actually novel - the unified, observable runtime and the decision-level benchmark - from the gravitational pull of building adjacent infrastructure that already exists and is already good. Post-FYP, the highest-leverage extension is the memory-system integration named on the watchlist; it is a bridge, not a foundation, and the architecture keeps it that way.


## 8. 12-Month Implementation Plan

The plan preserves the original proposal's two-semester structure and upgrades its content with the v2 scope. It is organized as six phases (P0-P5) with four hard gates (G1-G4); each gate has measurable exit criteria, and slipping a gate triggers the re-planning rules at the end of this section rather than silent scope creep. Work runs in two-week sprints (26 in total), with a weekly research sync, a repository-level definition of done (code + tests + trace coverage + docs), and a rule that every experiment runs through the same harness so results stay comparable. Figure 6 shows the timeline; Tables 6 and 7 specify phases and gates.

![Figure 6. The 12-month plan. Six phases across two semesters; diamonds mark gates G1-G4. Phase P4 carries the six advanced-gap features; P5 is evaluation, release, and paper.](aperture_assets/fig4_gantt.png)

*Figure 6. The 12-month plan. Six phases across two semesters; diamonds mark gates G1-G4. Phase P4 carries the six advanced-gap features; P5 is evaluation, release, and paper.*

**Table 6. Phase objectives and deliverables**

| Phase | Months | Objectives | Deliverables |
|---|---|---|---|
| P0 | M1-M2 | Consolidate literature; independently reproduce the failure mode; freeze the trace schema | Context-rot measurement replication (LongMemEval focused-vs-full + extended NIAH) on 3-4 models; ConstraintRot reproduction; v1 trace schema (versioned); eval harness skeleton |
| P1 | M3-M4 | Build the operator library and the model-agnostic runtime | Seven operators behind the Operator protocol; LiteLLM gateway with cache telemetry; LangGraph + raw-loop adapters; pinned store and protected-class metadata (AG2 groundwork); unit + integration tests |
| P2 | M5-M6 | Ship the fixed-heuristic runtime end to end; mid-year demo | Tuned fixed-heuristic selector; 8-arm harness running AppWorld + tau2-bench subsets; mid-year demo: token savings at equal accuracy vs full-history; G1 |
| P3 | M7-M8 | Collect labelled traces; train the offline selector; seed CurateBench | 500-1,000 labelled trajectories across arms; offline selector (contextual bandit) beating fixed heuristics on held-out traces; CurateBench schema + replay engine + seeded trace set released as artifact; G2 |
| P4 | M9-M10 | v2 advanced operators: the six advanced-gap features | Cache-aware reward + cache-align operator (AG1); survival probes + decay alerts (AG2); online adaptation + safe fallback (AG4); context contracts + cacheable spawns (AG5); async scheduler (AG6); CurateBench decision metrics wired in (AG3); G3 |
| P5 | M11-M12 | Full comparative evaluation; dashboard; release; paper | Complete 8-arm evaluation with statistical rigor (Section 9); observability dashboard; benchmark + trace set + runtime released; final report; paper submitted to arXiv and a venue (Section 11); G4 |

**Table 7. Gate criteria (a missed gate triggers re-planning, not silent drift)**

| Gate | End of | Exit criteria (all mandatory) | If missed |
|---|---|---|---|
| G1 | M6 | Fixed-heuristic runtime: at least 30% cumulative token reduction at equal-or-better task success vs full-history on AppWorld and a tau2-bench subset; 100% of curation decisions logged with diffs | Reduce scope to 3 operators; re-check on smaller benchmark subset before proceeding |
| G2 | M8 | Offline selector matches or beats every fixed heuristic on held-out CurateBench traces; labelled trace set (500+ trajectories) frozen and checksummed; replay engine reproduces a recorded step bit-identically | Extend trace collection by 2 weeks; if still failing, pivot headline contribution to CurateBench + systematic comparison (still publishable) |
| G3 | M10 | Each AG feature shows its metric: CATC -15% or better vs raw-token-optimal at equal success; 100% constraint survival on pinned suite incl. attack replay; spawn cache reuse demonstrated; p50 added latency < 10% | Ship the subset of AG features that pass; move the rest to the watchlist with documented reasons |
| G4 | M12 | Full evaluation table (8 arms x 4+ benchmarks) with CIs; artifacts released (runtime MIT/Apache-2, CurateBench, trace sets); paper drafted and submitted | N/A - terminal gate; remaining work moves to post-FYP continuation |


### 8.1 Semester 1, week by week

**Table 8. Semester 1 detail (Semester 2 is gate-driven from Table 6/7)**

| Weeks | Build | Prove |
|---|---|---|
| 1-2 | Trace schema draft; eval harness skeleton; environment (LiteLLM, Qdrant/FAISS, quantized summarizer) | Pip-installable skeleton wraps a toy loop end to end |
| 3-4 | Context-rot replication: LongMemEval focused-vs-full, extended NIAH, 3-4 models | Replication memo with charts matching published direction; go/no-go on benchmark choice |
| 5-6 | ConstraintRot reproduction; protected-class metadata design | 0% vs 30-59% violation pattern reproduced on 2 models |
| 7-8 | Operators: keep_recent, summarize, dedupe + pinned store | Per-operator unit tests; byte-level diffs verified; first trace files written |
| 9-10 | Operators: semantic_retrieval, cache_align, pin_protected; LiteLLM telemetry | Cache telemetry validated against vLLM prefix-cache stats on an open model |
| 11-12 | Fixed-heuristic selector; subagent_isolation with v1 contracts; 8-arm harness on AppWorld | Mid-year dry run: savings at equal accuracy on a 50-task subset; G1 rehearsal |


### 8.2 Resources and assumptions

The plan assumes a solo engineer (or a two-person team with a shared runtime/eval split) plus a supervisor, one consumer GPU for the quantized summarizer, Colab/Kaggle for burst training, and API budget for trace collection and evaluation. A reasonable planning figure is 300 to 800 US dollars of API spend across the year (estimate, not a quote): the trace corpus dominates it, which is precisely why the cache-aware design matters - curation during trace collection also lowers the cost of building the dataset. Two assumptions are load-bearing and monitored: that provider APIs keep exposing cache-hit telemetry (LiteLLM normalizes what exists today), and that benchmark graders stay programmatically reproducible; both have fallbacks recorded in the risk register.


### 8.3 Working agreements and definition of done

Three working agreements keep a solo-paced project honest. First, the definition of done for any runtime change is: code merged with unit and integration tests, the trace schema version bumped if any logged field changed, and the affected operator re-run on a 20-task regression subset so savings and success deltas are visible the same day. Second, experiment hygiene: every evaluation run is launched by one command from the eval directory, writes a manifest (git hash, arm, benchmark, seeds, model IDs, price list) into the results tree, and is committed even if the result is unfavorable - results trees are append-only. Third, cadence: two-week sprints end with a demo against the regression subset, a one-page sprint note in the repository, and an explicit check of the current gate's criteria; a red item on the gate checklist is discussed in the weekly research sync with the supervisor rather than silently rescheduled. These agreements cost minutes per day and are what makes the G1-G4 gates trustworthy at review time.


## 9. Evaluation Protocol

The evaluation is designed around one principle borrowed from Kapoor et al.: accuracy and cost are reported jointly, always, or the numbers are not interpretable [18][19]. The protocol therefore fixes benchmarks, arms, and metrics up front, commits to statistical practice, and adds the three measurement innovations this dossier argues for: cache-adjusted cost, decision-level regret, and constraint survival.

**Table 9. Benchmarks and their role in the evaluation**

| Benchmark | Axis measured | Why included | Grading |
|---|---|---|---|
| AppWorld [30] | Interactive coding-agent tasks | Programmatic grading; used by ACON and ACE, giving two published anchor points | Unit-test based, programmatic |
| tau2-bench [29] | Tool-agent-user interaction under policy | Policy compliance is native to the benchmark - pairs naturally with governance metrics | Database + policy checks |
| OfficeBench (via ACON protocol) [14] | Long-horizon office workflows | Direct comparability with the strongest compression baseline | Programmatic |
| GAIA | General assistant reasoning | Out-of-domain robustness check for the selector | Exact-match levels |
| LongMemEval [21] | Context-rot axis (113k full inputs) | Focused-vs-full design isolates the rot Aperture must prevent | Programmatic QA |
| Extended NIAH (Chroma protocol) [1] | Controlled length/distractor rot | Independent replication of the failure mode, per model | Programmatic |
| ConstraintRot (reproduced) [10] | Governance survival | Measures AG2 directly; also replays the Compaction-Eviction Attack | Deterministic tool-call grading |
| CurateBench (ours) [41] | Decision-level curation quality | The contribution no prior benchmark provides; counterfactual regret | Replay engine + scorer |

**Arms.** Eight arms run under identical harnesses, seeds, and grading: (1) full-history; (2) keep-recent window (tuned); (3) threshold-triggered editing + compaction, re-implementing the Anthropic-style strategy model-agnostically; (4) provider-native Anthropic editing + memory on Claude (the only arm that is model-specific, reported separately); (5) ACON-style always-compress using the distilled compressor protocol (LLMLingua-2-class where the exact model is unavailable) [14][32]; (6) Headroom proxy as a content-type baseline [4]; (7) Aperture-fixed (tuned heuristic selector); (8) Aperture-learned (online bandit). Arms 5 and 6 carry explicit caveats: vendor-reported numbers are never copied into the results table; everything is re-measured.


### 9.1 Metrics and success criteria

Task success rate is graded by each benchmark's own programmatic checker. Cost metrics are cumulative spend in US dollars and tokens, peak context size, and **Cache-Adjusted Token Cost (CATC)** - dollars actually paid after crediting cached-prefix discounts from gateway telemetry, normalized per task. Decision-level metrics come from CurateBench: **curation regret**, the success delta between the chosen decision and the best equal-cost counterfactual on replay, and **constraint-survival rate**, the probe-verified share of pinned content still retrievable after each destructive decision. Systems metrics are added latency p50 and p95 per step and drift-detection precision/recall on an injected-drift suite.

Success criteria, upgraded from the original proposal: match or beat full-history success while cutting raw tokens at least 30 percent and CATC at least 15 percent; the learned selector beats every fixed arm (including ACON-style compression and the Headroom proxy) on at least two of three primary benchmarks at equal or lower cost; 100 percent constraint survival on the pinned suite including the attack replay; and p50 latency overhead under 10 percent. Even a partial pass is informative by construction - the comparison table itself, plus CurateBench's decision-level scores, is a publishable result, which is the insurance policy the original proposal correctly identified.


### 9.2 Statistical practice

Three seeds per stochastic arm; task-level paired bootstrap confidence intervals (10,000 resamples) for every arm comparison; all runs reported including failures and retries, per [18]; no result from a single run enters the paper; every number in the final report is regenerable by one command from the released harness and trace checksums. Cost figures use list prices on the evaluation dates and are archived alongside results so future readers can re-derive CATC. Where an arm is vendor software with non-deterministic routing (Headroom), five runs are used instead of three and the variance is reported explicitly rather than averaged away.


### 9.3 Threats to validity

Four threats are named in advance so results can be read with the right skepticism. **Construct validity:** CATC depends on the assumed price list; the protocol mitigates by archiving prices and reporting raw-token cost alongside. **Internal validity:** the learned selector sees outcome rewards that fixed arms do not, so a naive comparison would conflate online adaptation with selection quality; the protocol therefore also reports the offline selector (trained, then frozen) as a ninth exploratory arm. **External validity:** a benchmark suite cannot cover all agent shapes; the claim is scoped to long-horizon tool-using agents of the AppWorld, tau2, and GAIA family, and the paper will say so. **Statistical conclusion validity:** with eight arms and multiple metrics, multiplicity is real; primary outcomes (success at cost parity on the three primary benchmarks) are declared before the final runs, and everything else is labelled exploratory. Naming these in month zero converts the usual reviewer objections into protocol lines that are already answered.


## 10. Risk Register

Twelve risks are tracked, each with likelihood (L), impact (I), and a concrete mitigation with an owner trigger. The two that would genuinely hurt are R1 (the learned selector fails to beat fixed heuristics) and R3 (novelty collision); both have pivots that preserve a publishable contribution, which is the point of building CurateBench early.

**Table 10. Risk register (L/I: Low, Medium, High)**

| # | Risk | L | I | Mitigation and trigger |
|---|---|---|---|---|
| R1 | Learned selector ties or loses to the best fixed heuristic | M | H | This is the research risk, not a project failure: CurateBench + the systematic 8-arm comparison remain the contribution (G2 pivot). Mitigations: richer features (drift, phase, cache state), per-domain selectors, safe-mode ensembles; publish the negative result honestly [18] |
| R2 | Benchmarks saturate (tau2-telecom already near 99% for top models) | M | M | Use test-challenge splits, AppWorld full set, OfficeBench, GAIA; report cost-adjusted scores; drop any benchmark whose ceiling is hit during P0 |
| R3 | Novelty collision: AdaCoM/ContextEvo follow-ups close the unified gap first | M | H | Weekly arXiv watch (cs.LG/cs.CL); the three-part claim is decomposable - if selection is taken, library+trace+benchmark still stands; accelerate CurateBench release to stamp priority |
| R4 | Provider features absorb more curation (feature creep) | H | M | Position as the model-agnostic layer above providers; provider tools wrapped as fallback operators (Section 4.4); measure against them rather than compete feature-for-feature |
| R5 | Small-model summarizer too weak or slow in the loop | M | M | Quantized 7-8B on consumer GPU (LLMLingua-2 shows inline compression is feasible [32]); async scheduler hides latency (AG6); fallback to extractive summarization |
| R6 | Trace labelling cost explodes | M | M | Weak supervision from task outcomes; active learning on ambiguous steps; budget cap in Section 8.2; CurateBench seeds sized to 500-1,000, not millions |
| R7 | Cache telemetry unavailable/inconsistent across providers | M | M | LiteLLM normalization; vLLM self-hosting for ground-truth prefix stats; CATC reported with and without cache credit if telemetry degrades |
| R8 | Pinning hurts accuracy (over-preservation) | L | M | Pin budgets tunable per class; survival probes measure retention, ablations measure cost; selector learns when pinning is wasteful |
| R9 | Compute constraints (consumer GPU, API budget) | M | L | Colab/Kaggle burst; quantization; trace collection uses the runtime's own savings - the cheapest traces are the curated ones |
| R10 | High run-to-run variance makes comparisons unreliable | M | M | 3 seeds, paired bootstrap CIs, all-runs reporting [18]; variance checked in P0 replication before any arm comparison |
| R11 | Scope creep toward memory-framework territory | M | M | Out-of-scope fence in Section 6.7 watchlist; cross-session integration only post-FYP; supervisor sign-off required to promote any watchlist item |
| R12 | OSS release maintenance burden in the final semester | L | L | Release engineering in P5 only (docs, examples, CI); MIT/Apache-2; issues triaged post-submission; benchmark artifact separable from runtime |


## 11. Publication and Release Strategy

The publication strategy is artifact-first. Three artifacts are released, in this order of priority: (1) **CurateBench** - the decision-level benchmark: schema, replay engine, and the seeded trace set (end of P3, month 8); (2) the **Aperture runtime** - MIT or Apache-2 licensed, pip-installable, with the seven-operator library, online selector, and dashboard (month 12); (3) the **labelled trace corpus** with checksums and a regeneration harness. Artifact-first is not just optics: CurateBench's early release stamps priority on the evaluation contribution (R3 mitigation), and the trace corpus is the community's first reusable record of real curation decisions.

The paper targets the systems-and-agents track spectrum. An arXiv preprint goes up as soon as the full evaluation table is frozen (month 11-12), establishing priority and enabling feedback before review cycles complete. Venue selection then follows the typical windows below - dates are the historical cycles and must be verified against each venue's actual call when the time comes, as deadlines move year to year. The primary full-paper target is ICLR 2028 (typical submission window September 2027), which fits the project's end and rewards artifact-backed claims; EMNLP 2027 or NeurIPS 2027 (typical windows around May 2027) are earlier options if the G3 results are strong enough by then; ICML 2027 (typical window late January 2027) is reachable only for a short paper or a workshop version of CurateBench; TMLR is the rolling fallback with a strong lineage fit - the cost-aware evaluation argument Aperture extends was published there [18]. Agentic-AI workshops at the NeurIPS/ICLR 2027 cycles are the natural first outing for CurateBench alone.

**Table 11. Venue plan (windows are typical historical cycles - verify each call for papers)**

| Venue | Typical window | Fit | Submission target |
|---|---|---|---|
| arXiv preprint | Any | Priority stamp; feedback | M11 (as soon as eval table freezes) |
| ICML 2027 (workshop/short) | late Jan 2027 | CurateBench alone; early signal | Only if G2 lands early |
| ACL / EMNLP 2027 | Feb / May 2027 | Agent + context-management mainline | EMNLP 2027 if G3 is strong |
| NeurIPS 2027 (D&B track) | May 2027 | CurateBench as Datasets & Benchmarks paper | Strong fit for the benchmark artifact |
| ICLR 2028 | Sep 2027 | Primary full-paper target: runtime + selector + evaluation | Default plan (post-FYP polish) |
| TMLR | Rolling | Cost-aware evaluation lineage [18] | Fallback if conference cycles miss |

The narrative arc for the paper is fixed now, in month zero, so the evaluation cannot be retrofitted to whatever the results turn out to be: *context rot is measured; curation is fragmented; we present the first model-agnostic runtime that unifies curation as composable, observable operators; a learned per-step selector is compared against every fixed strategy under matched cost accounting; a decision-level benchmark makes the comparison attributable; and governance-survival metrics make it safe.* If the selector wins, the headline is the win; if it ties, the headline is the benchmark and the auditability - both papers are honest, and only one of them depends on a result we do not control.


## 12. References

All web and arXiv sources were accessed and verified between November 5 and 10, 2026. Vendor-reported numbers are marked in the text; entries marked (secondary) report findings whose primary source is not yet publicly indexable.


1. Hong, K., Troynikov, A., and Huber, J. (2025). Context Rot: How Increasing Input Tokens Impacts LLM Performance. Chroma Technical Report, July 14, 2025. research.trychroma.com/context-rot
2. Liu, N. F., et al. (2024). Lost in the Middle: How Language Models Use Long Contexts. Transactions of the Association for Computational Linguistics, 12, 157-173.
3. LangChain (2026). State of Agent Engineering - survey of 1,300+ practitioners, June 12, 2026. langchain.com/state-of-agent-engineering
4. Headroom (2026). The Context Optimization Layer for LLM Applications. github.com/headroomlabs-ai/headroom (PyPI/npm: headroom-ai).
5. cc-switch project issue tracker (2026). Feature discussion: Context Compression Middleware (Proxy Layer); tool-output token-share estimates for Claude Code sessions. June 2026 (secondary, practitioner).
6. Anthropic (2025). Managing Context on the Claude Developer Platform: context editing, memory tool, and compaction. platform.claude.com/docs, October 2025.
7. Yi, L., Lei, R., et al. (2026). Learning Agent-Compatible Context Management for Long-Horizon Tasks (AdaCoM). arXiv:2605.30785.
8. Li, W., Xu, J., Chen, A., Wang, X., Liang, S., Liang, J., and Yang, D. (2026). Beyond Skill Evolution: Self-Evolving Context Management Policies for Long-Horizon Agent Harnesses (ContextEvo). arXiv:2609.34649, September 28, 2026.
9. Crosley, B. (2026). Context Compaction Is Becoming a Training Objective. blakecrosley.com/blog/context-compaction-training-objective (secondary; reports CompactionRL results on GLM-4.5-Air and the Memory-R1/MemAct line).
10. Governance Decay: How Context Compaction Silently Erases Safety Constraints in Long-Horizon LLM Agents (2026). arXiv:2606.22528; ConstraintRot benchmark and Compaction-Eviction Attack described in Section 6.2.
11. Masood, A. (2026). Prompt Caching in Production AI Systems: Architecture, Economics, and Governance. August 31, 2026 (practitioner analysis; vendor break-even and hit-rate figures compiled therein).
12. Anthropic (2025). Introducing Advanced Tool Use for Claude (Tool Search Tool, programmatic tool calling, tool use examples). anthropic.com/research/advanced-tool-use, November 24, 2025.
13. Sun, W., et al. (2025). Scaling Long-Horizon LLM Agent via Context-Folding. arXiv:2510.11967; ICML 2026. Open re-implementation: github.com/sunnweiwei/FoldAgent.
14. Kang, M., et al. (2025). ACON: Optimizing Context Compression for Long-horizon LLM Agents. arXiv:2510.00615.
15. Coworker AI (2026). Mem0 vs Zep vs Letta: AI Agent Memory Frameworks Compared. coworker.ai/blog/mem0-vs-zep-vs-letta, August 2026 (updated November 3, 2026).
16. Packer, C., et al. (2023). MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560.
17. Rasmussen, D., et al. (2025). Zep: A Temporal Knowledge Graph Architecture for Agent Memory. arXiv:2501.13956.
18. Kapoor, S., Stroebl, B., Siegel, Z. S., Nadgir, N., and Narayanan, A. (2024). AI Agents That Matter. Transactions on Machine Learning Research. arXiv:2407.01502.
19. METR (2026). Metrics of Agent Ability. metr.org/notes/2026-07-24-metrics-of-model-ability, July 24, 2026.
20. Anthropic (2026). Context Engineering: Memory, Compaction, and Tool Clearing (cookbook). platform.claude.com/cookbook, March 20, 2026.
21. Wu, D., et al. (2024). LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory. ICLR 2025.
22. Anthropic Applied AI Team (2025). Effective Context Engineering for AI Agents. Anthropic Engineering Blog, September 2025. anthropic.com/research/effective-context-engineering-for-ai-agents
23. Matsuoka, R. (2025). How Claude Code Got Better by Protecting More Context. HyperDev, December 10, 2025 (practitioner analysis of auto-compact thresholds).
24. Bansal, K. (2026). Prompt Caching Doesn't Cache Prompts. karanbansal.in/blog/prompt-caching, July 7, 2026 (practitioner analysis).
25. Earendil Engineering (2026). Prompt Caching in Agents. earendil.com/posts/prompt-caching, July 22, 2026 (practitioner analysis).
26. r/AI_Agents (2026). How are people handling the trade-off between context compaction and prompt caching in production agents? Discussion thread with production measurements; accessed November 2026 (secondary, practitioner).
27. Mei, L., et al. (2025). A Survey of Context Engineering for Large Language Models. arXiv:2507.13334.
28. Yao, S., et al. (2024). tau-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains. arXiv:2406.12045; sierra.ai/blog/tau-bench.
29. Barres, V., et al. (2025). tau2-bench. Sierra Research; github.com/sierra-research/tau2-bench; leaderboards at artificialanalysis.ai/evaluations/tau2-bench.
30. Trivedi, H., et al. (2024). AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents. ACL 2024.
31. Srivastava, A., et al. (2025). Evaluation and Benchmarking of LLM Agents: A Survey. arXiv:2507.21504.
32. Pan, Z., et al. (2024). LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt Compression. arXiv:2403.12968.
33. Yan, S., et al. (2025). Memory-R1: Enhancing Large Language Model Agents to Manage and Utilize Memories via Reinforcement Learning. arXiv:2508.19828.
34. Li, Z., et al. (2025). MemOS: A Memory OS for AI System. arXiv:2507.03724.
35. Kang, J., et al. (2025). Memory OS of AI Agent. EMNLP 2025 (aclanthology.org/2025.emnlp-main.1318).
36. LangChain (2026). Context Management for Deep Agents. January 28, 2026. langchain.com/blog/context-management-for-deepagents
37. Zhang, A. L., et al. (2025). Recursive Language Models. arXiv:2512.24601; MIT CSAIL; project blog alexzhang13.github.io/blog/2025/rlm.
38. Zhang, Q., et al. (2025). Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models. arXiv:2510.04618; ICLR 2026.
39. Trussed AI (2026). Context Compaction in AI Agents: Security Risks Guide. trussed.ai/resources (secondary, practitioner).
40. Taskade Engineering (2026). Agent Handoff Explained: How AI Agents Pass Work. taskade.com/blog/agent-handoff-explained, September 23, 2026 (secondary, practitioner).
41. This document: CurateBench - decision-level context-curation benchmark proposed in Section 6.3; schema, replay engine, and seeded trace set planned for release at gate G2.


## Appendix A: CurateBench Trace Schema v1

CurateBench's trace format is the contract that makes decision-level evaluation possible. One JSON Lines record per model call captures the full state needed to reconstruct the step and to re-run it under a different curation policy: the features the selector saw, the plan it chose, the diffs every operator produced, the cache state before and after, the survival probes, and the eventual task outcome joined after the run completes. The schema is versioned from Phase P0; the example below is the v1 record shape that the Phase P3 trace corpus and the replay engine both consume.

```
{
  "schema": "curatebench/trace@v1",
  "step": 47,
  "ts": "2027-03-14T09:22:11.408Z",
  "session_id": "appworld-train-0031",
  "arm": "aperture_learned",
  "model": {"provider": "anthropic", "id": "claude-sonnet-4-5", "price_list": "2027-03-01"},
  "features": {
    "budget_used_frac": 0.41,
    "task_phase": "explore",
    "tool_output_tokens_recent": 5210,
    "redundancy_score": 0.33,
    "drift_score": 0.07,
    "prefix_hash": "b3f1c9...e2a0"
  },
  "plan": [
    {"op": "dedupe", "params": {"sim_threshold": 0.93}, "order": 1},
    {"op": "summarize", "params": {"budget_tokens": 900}, "order": 2},
    {"op": "cache_align", "params": {"head_budget": 4096}, "order": 0}
  ],
  "diffs": [
    {"op": "summarize", "dropped": [{"span_id": "s-318", "bytes": 6412,
      "reason": "verbose tool output folded", "classes": ["tool_result"]}],
     "new_spans": [{"span_id": "s-401", "bytes": 890, "summary_of": ["s-318", "s-319"]}],
     "cache_head_unchanged": true}
  ],
  "cache": {"prefix_tokens": 18422, "hit": true, "invalidated_bytes": 0,
            "discount_usd": 0.0413},
  "probes": [{"class": "constraint", "probe": "refund-policy-q3", "survived": true}],
  "call": {"input_tokens": 20087, "output_tokens": 412, "cost_usd": 0.0762,
           "latency_ms": 1841},
  "reward": {"task_progress": 0.25, "cost_delta_usd": 0.0095,
             "survival_penalty": 0.0, "latency_ms": 122},
  "outcome": {"task_success": true, "graded_at": "2027-03-14T09:31:02Z"}
}
```

**Table 12. Trace record fields and their consumers**

| Field group | Contents | Consumed by |
|---|---|---|
| model | Provider, model id, price list snapshot | CATC computation; price archival |
| features | Selector inputs: budget fraction, phase, tool-output volume, redundancy, drift, prefix hash | Replay engine reconstructs the same selector input; staleness analysis |
| plan | Chosen operators, parameters, ordering | Counterfactual replay swaps this field |
| diffs | Per-operator kept/dropped/new spans with reasons, byte counts, protected classes, cache-head effect | Information-loss attribution; audit views; AG2 decay forensics |
| cache | Prefix size, hit/miss, invalidated bytes, discount dollars | CATC; AG1 reward; cache-effect ablations |
| probes | Post-decision survival checks per protected class | Constraint-survival metric; decay alerts |
| call | Realized tokens, dollars, latency | Cost and latency metrics |
| reward | Online update signal for the bandit | Online-regret analysis (AG4) |
| outcome | Task-level grade joined after the run | Curation regret; all headline tables |


## Appendix B: Glossary

Terms are defined as used in this document; where a term originates in a cited work, the reference follows the definition.

**Table 13. Working vocabulary for the project**

| Term | Definition |
|---|---|
| Attention budget | The finite effective capacity of a model to attend over its context; depletes as tokens accumulate, independent of the stated window size [22] |
| Cache-adjusted token cost (CATC) | Dollars actually paid for a task after crediting provider prompt-cache discounts, normalized per task; Aperture's primary cost metric (Section 9.1) |
| Compaction | Summarizing a conversation approaching the window limit and reinitializing context from the summary; a provider-native technique [6] and a training objective in CompactionRL [9] |
| Context collapse | Iterative rewriting that erodes detail over time; named and fought by ACE [38] |
| Context contract | Aperture's typed, budgeted, provenance-tagged handoff object for sub-agent work (AG5) |
| Context rot | Degradation of model performance as input length grows even when task difficulty is held constant [1] |
| Contextual bandit | An online learning method that picks actions (here: operator plans) from contextual features and updates from scalar rewards; Aperture's selector class (AG4) |
| Curation regret | CurateBench metric: success delta between the decision actually taken and the best equal-cost counterfactual decision on replay (Section 6.3) |
| Distractor | Content topically related to a target but not answering it; amplifies degradation with length [1] |
| Drift detection | Monitoring feature-distribution shift in live traces; triggers selector fallback to a tuned fixed heuristic (AG4) |
| FoldGRPO / folding | Context-Folding's RL method: branch into a sub-trajectory, then fold it into a summary on completion, keeping the active window 10x smaller [13] |
| Governance decay | Silent erosion of in-context governance constraints by compaction, raising prohibited-action rates from 0 to 30 (up to 59) percent [10] |
| Protected class | Metadata category (constraint, permission, user intent, safety-critical error) whose spans are exempt from destructive operators (AG2) |
| Reversible compression (CCR) | Headroom's content-addressable store keeping originals retrievable after compression [4]; Aperture adopts the pattern in its artifact offload |
| Stable head | The byte-stable prefix of a prompt (instructions, tool definitions) that provider caches can reuse; protected by a fixed budget in cache-aware design (AG1) |
| Survival probe | A cheap templated check that pinned content remains retrievable after a curation decision; failures raise decay alerts (AG2) |
| Trace ledger | Aperture's append-only log of every curation decision with features, diffs, cache state, probes, and reward (Appendix A) |
| Window | The exact token set sent to the model on one call; the object all operators transform |
