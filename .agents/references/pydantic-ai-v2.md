# Pydantic AI v2 — Research Notes

> **Versions documented:** `pydantic-ai` **2.31.1**, `pydantic-evals` **2.31.1** (released as part of the same monorepo/release train as pydantic-ai), `pydantic-ai-harness` **0.22.0**, `logfire` **4.40.0**.
> **Research date:** 2026-08-17, via `ai.pydantic.dev` (which now 301-redirects to `pydantic.dev/docs/ai/*`), `pypi.org` JSON API, and `github.com/pydantic/pydantic-ai(-harness)`.
> **Why this matters:** pydantic-ai ships near-daily point releases (six 2.x releases in the week before this research). Anything below not marked "stable across versions" should be re-verified against the live docs before relying on it in code. Docs canonical home moved from `ai.pydantic.dev` to `pydantic.dev/docs/ai/` — old links still resolve via redirect but should be updated when citing sources going forward.
> **Method note:** Most of the content below was pulled via `WebFetch`, which summarizes fetched pages through a small model rather than returning raw HTML. Code snippets are reproduced as fetched; treat anything not directly attributed to a quoted string with a little more caution, and re-fetch the source URL directly if a snippet needs to be pasted verbatim into production code.

---

## 1. Agent definitions with typed outputs

Source: [Agents guide](https://pydantic.dev/docs/ai/core-concepts/agent/), [Output guide](https://pydantic.dev/docs/ai/core-concepts/output/), [Dependencies guide](https://pydantic.dev/docs/ai/core-concepts/dependencies/), [Tools guide](https://pydantic.dev/docs/ai/tools-toolsets/tools/) (also mirrored under the legacy `/docs/dependencies.md`, `/docs/agent.md` paths in the GitHub repo).

### Constructing an `Agent`

An `Agent` is generic over `Agent[DepsT, OutputT]` and is "a container for instructions, function tools, structured output type, dependency type constraint, LLM model, and model settings." Key constructor args:

- `model` — e.g. `'openai:gpt-5.2'`, `'anthropic:claude-opus-4-7'`
- `deps_type` — the **type** (not instance) used for dependency injection
- `output_type` — the structured type the LLM must return at the end of a run
- `system_prompt` / `instructions` — static string or dynamic function; **`instructions` is preferred over `system_prompt`** because instructions are *not* replayed from `message_history`, while system prompts are
- `model_settings` — default per-request model behavior (temperature, etc.)
- `retries` — retry budget for tool/output validation failures
- `max_concurrency` — cap on concurrent runs
- `capabilities` — see Section 2
- `tools` — list of functions or `Tool(...)` objects registered at construction time

```python
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

class ChatResult(BaseModel):
    user_id: int
    message: str

agent = Agent(
    'openai:gpt-5.2',
    output_type=ChatResult,
)
```

Type-safety note: `agent: Agent[User, bool] = Agent('test', deps_type=User, output_type=bool)` — pydantic-ai is designed to work with mypy/pyright; pyright handles generic inference for unions/lists better than mypy currently does (open mypy issues tracked upstream).

### Output types

`output_type` accepts one or more types or **output functions**: scalars, `list`/`dict` (including `TypedDict` and `StructuredDict`), dataclasses, Pydantic `BaseModel`s, and type unions. Three structured-output *mechanisms* exist:

1. **Tool Output (default)** — leverages the model's tool-calling; each output type becomes a separate output tool. Default because "it's supported by virtually all models and has been shown to work very well."
2. **Native Output** — wrap the type in `NativeOutput(...)` to use provider-native structured output (e.g. OpenAI JSON-schema mode). Not supported by all models and "sometimes comes with restrictions."
3. **Prompted Output** — wrap in `PromptedOutput(...)`; JSON schema is injected into instructions directly. Least reliable but universal.

Other output features worth knowing for this project:
- **Output functions**: instead of a data shape, pass a function; the model is forced to call it, arguments are Pydantic-validated (optionally with `RunContext`), the function can `raise ModelRetry(...)` to ask the model to correct itself, and its return value ends the run.
- **`@agent.output_validator`**: async validator decorator for validation requiring I/O; raising `ModelRetry` consumes the output retry budget (note: output validators do *not* support `ToolFailed`).
- **`validation_context`**: static object or `RunContext`-aware function passed to the Agent; available inside Pydantic field validators (but not sent to the model).
- **Optional output**: include `None` in `output_type` (e.g. `str | None`) so an agent that finishes via tool calls without a final message returns `None` instead of retrying.
- **Streaming**: Pydantic validates *partial* objects incrementally as they stream in.
- **`StructuredDict()`**: dynamically-generated JSON schema when no static type fits.

```python
def run_sql_query(query: str) -> list[Row]:
    """Run a SQL query on the database."""
    ...
```

This maps directly onto "every stage boundary is a typed Pydantic model" — each single-shot island agent should declare a `BaseModel` as `output_type`, and validation/retry happens automatically via the tool-output path.

### Dependency injection (`deps_type` / `RunContext`)

Dependencies are a dataclass (or any type) holding whatever services/data an agent's tools, system prompts, and output validators need — explicit DI rather than globals.

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class MyDeps:
    api_key: str
    http_client: httpx.AsyncClient

agent = Agent('openai:gpt-5.2', deps_type=MyDeps)

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[MyDeps]) -> str:
    response = await ctx.deps.http_client.get('https://example.com')
    ...

deps = MyDeps('foobar', client)
result = await agent.run('Tell me a joke.', deps=deps)
```

- You register the **type** via `deps_type=`; you pass an **instance** via `deps=` at `run`/`run_sync` time.
- `RunContext[DepsT]` also exposes `.agent` (the running agent, useful for hooks/capabilities that need to read agent properties like `name` or `output_type`) and `.deps`.
- Non-async dependency-consuming functions run in a thread pool (`run_in_executor`), so sync and async agent code interop.
- For testing, `with agent.override(deps=test_deps): ...` swaps dependencies (and separately, model — see Section 4) without touching call sites.

### Tool registration

Three registration paths:

```python
@agent.tool
async def get_user(ctx: RunContext[DatabaseConn], name: str) -> int:
    """Get a user's ID from their full name."""
    return ctx.deps.users.get(name)

@agent.tool_plain
def calc_volume(size: int) -> int:
    """Calculate box volume."""
    return size ** 3

agent = Agent(
    'google:gemini-3-flash-preview',
    tools=[roll_dice, get_player_name],   # constructor-time registration
)
# or, for fine-grained control:
tools=[
    Tool(roll_dice, takes_ctx=False),
    Tool(get_player_name, takes_ctx=True),
]
```

- `@agent.tool` — tool needs `RunContext` (deps access). `@agent.tool_plain` — stateless, no context.
- Tool JSON schemas are auto-extracted from the function signature; parameter *descriptions* come from the docstring (Google/NumPy/Sphinx formats supported): `@agent.tool_plain(docstring_format='google', require_parameter_descriptions=True)`.
- Per-tool retry budgets: `@agent.tool(retries=2)`.
- `toolsets=` parameter groups collections of tools (your own, or from an MCP server / third party).
- Tools can call `RunContext.enqueue()` to inject follow-up messages mid-run.
- **Deferred tools** (distinct from the "on-demand loading" of tool *definitions* covered in Section 2) are pydantic-ai's human-in-the-loop / external-execution mechanism — a tool marked `requires_approval=True` (or that raises `ApprovalRequired`) pauses the run and returns `DeferredToolRequests`; a tool that can't complete synchronously raises `CallDeferred` and is resolved later via `DeferredToolResults` or the `HandleDeferredToolCalls` capability. Source: [Deferred tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/). This is likely relevant to the investigator agent if any tool call needs human sign-off, but is a separate concept from ToolSearch's on-demand catalog loading.

---

## 2. The capabilities system

Sources: [v2 announcement article](https://pydantic.dev/articles/pydantic-ai-v2), [Capabilities overview](https://pydantic.dev/docs/ai/core-concepts/capabilities/), [`pydantic_ai.capabilities` API reference](https://pydantic.dev/docs/ai/api/pydantic-ai/capabilities/), [WebSearch capability](https://pydantic.dev/docs/ai/capabilities/web-search/), [WebFetch capability](https://pydantic.dev/docs/ai/capabilities/web-fetch/), [`pydantic-ai-harness` README](https://github.com/pydantic/pydantic-ai-harness/blob/main/README.md).

**This is the headline v2 change.** Capabilities are the new composable unit that replaced ad-hoc constructor args for cross-cutting agent behavior: "A capability bundles an agent's instructions, tools, lifecycle hooks, and model settings into a single, composable unit." A capability can provide any mix of: tools (toolsets or native), lifecycle hooks, static/dynamic instructions, static/per-step model settings, and adaptive model selection.

Two packages matter here:
- **`pydantic-ai` (core, 2.31.1)** ships general-purpose capabilities: `Thinking`, `WebSearch`, `WebFetch`, `XSearch`, `ImageGeneration`, `MCP`, `ToolSearch`, `PrepareTools`/`PrepareOutputTools`, `Compaction`, `Instrumentation`, durable-execution integrations (Temporal/DBOS/Prefect/etc.), and low-level building blocks (`Capability`, `Hooks`, `DynamicCapability`, `CombinedCapability`).
- **`pydantic-ai-harness` (0.22.0, separate PyPI package)** ships opinionated, higher-level stacks aimed at building agent products: `Coder`, `Researcher`, `FileSystem`, `Shell`, `SpendLimits`, `Guardrails`, `Memory`, `Subagents`, `Planning`, `Skills`, etc. **`SpendLimits` lives in the harness package, not core pydantic-ai** — worth knowing since this project only needs core.

### Basic usage

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking, WebSearch

agent = Agent(
    'anthropic:claude-opus-4-7',
    instructions='Research thoroughly and cite your sources.',
    capabilities=[
        Thinking(effort='high'),
        WebSearch(local='duckduckgo'),
    ],
)
```

### `Thinking`

- Purpose: "Provider-adaptive extended thinking at configurable effort" — a *unified* thinking setting on `ModelSettings` that works portably across providers, instead of setting provider-specific fields yourself.
- Constructor: `Thinking(effort: ThinkingLevel = True)`, where effort ∈ `'minimal' | 'low' | 'medium' | 'high' | 'xhigh'`, or `True` (provider default) / `False` (disabled — silently ignored on always-on-thinking models).
- Provider-specific settings (`anthropic_thinking`, `openai_reasoning_effort`, etc.) take precedence over the capability if both are set explicitly.
- Model-support note found in docs: some Anthropic models (from claude-opus-4-6 onward) use *adaptive* thinking (model decides whether/how much to think) which deprecates/removes classic extended-thinking toggles on newer Opus/Sonnet models — i.e., `Thinking(effort=...)` may map to different underlying mechanics per model generation. **Verify current model-support matrix in the live docs before depending on a specific effort level for a specific model**, since this changes across model releases, not just library releases.

### `WebSearch`

- `WebSearch()` — native-only; **raises an error** if the selected model has no native web search.
- `WebSearch(local='duckduckgo')` — native when available, else falls back to a local DuckDuckGo-backed tool. Requires the `duckduckgo` optional extra (`pydantic-ai-slim[duckduckgo]`).
- `WebSearch(local=my_search)` — custom fallback callable.
- Additional native-mode config fields: `search_context_size`, `user_location`, `blocked_domains`, `allowed_domains`, `max_uses`, and OpenAI-Responses-specific `external_web_access`.
- It is a subclass of the generic `NativeOrLocalTool` pattern (see below) — same shape as `WebFetch`, `ImageGeneration`, `XSearch`, `MCP`.
- Provider support specifics (which models support native search) are **not fully enumerated in the fetched pages** — the docs point to `WebSearchTool` API reference for the current matrix. Flagged as **unverified/needs live check** for this project's chosen model.

### `WebFetch`

- `WebFetch()` — native-only.
- `WebFetch(local=True)` — native with a bundled markdownify-based local fallback (requires the `web-fetch` optional extra).
- `WebFetch(local=my_fetch)` — custom fallback.
- Native config fields: `allowed_domains`, `blocked_domains`, `max_uses` (only `max_uses` required for native), `enable_citations`, `max_content_tokens`.
- Domain allow/block-lists are enforced at the local-fallback level when native isn't in play.
- Exact content-size limits/thresholds were **not stated explicitly** in the fetched page content — check `max_content_tokens` default and the native `WebFetchTool` reference directly if page-size truncation matters for the investigator agent.

### `SpendLimits` (harness package — `pydantic-ai-harness`)

- Description from the harness README: "Cross-window USD/token budgets and per-response cost tracking, per model and per tenant." Also referenced elsewhere as providing "spend and token budgets over windows longer than a single run, shareable across worker processes."
- A related/example pattern surfaced via search (not confirmed against a primary doc page, so treat as **illustrative, not verified API**): `cost_budget_usd=2.50` causing a run to stop once the budget is hit, and cost tracking as a capability that "sees every model call, including the ones inside sub-agents."
- **Gap**: I could not load a dedicated `SpendLimits` API/constructor page (the harness repo doesn't have the same generated docs site depth as core pydantic-ai, and direct fetch of a harness-specific doc page 404'd). If per-stage cost caps are a hard requirement for this project, either (a) add `pydantic-ai-harness` as a dependency and read `SpendLimits`'s actual source/docstring, or (b) implement budget checks manually using Logfire's captured `gen_ai.usage.*` / cost attributes (Section 5) at each pipeline stage boundary, which doesn't require the harness package at all. This is the single biggest open gap in this research.

### On-demand / deferred *capability and tool* loading — `ToolSearch`, `defer_loading`

This is distinct from "deferred tools" (Section 1's human-approval mechanism). Two related mechanisms:

1. **`defer_loading=True`** — a flag on any `Capability`/`AbstractCapability` (or `MCP(...)`) that keeps its instructions/tools out of the prompt until the model actually needs them: "the model sees only the one-line description in a compact catalog, then loads the whole bundle, instructions and tools together, in a single step." Useful for keeping prompt size down when an agent has many optional capabilities (e.g. many document-type-specific tool bundles) that aren't all needed on every run.
2. **`ToolSearch`** capability — "Provides tool discovery for large toolsets... Load tool definitions on demand instead of carrying hundreds in every prompt." Constructor exposes `strategy` (`None | 'keywords' | 'bm25' | 'regex' | callable`) and `max_results` (default 10). Built "on exactly the same public hooks your own capabilities would use," i.e. it's implemented as a normal capability, not special-cased framework internals — meaning a custom on-demand-loading capability is a supported, first-class pattern if `ToolSearch`'s built-in strategies don't fit.

### Other capabilities worth flagging for this architecture

- **`Compaction`** — provider-native context compaction (OpenAI, Anthropic) — relevant if the investigator agent's loop runs long.
- **`ToolOutputLimits`** (harness) — truncates/spills/summarizes oversized tool returns; relevant since WebFetch/WebSearch results can be large.
- **`Instrumentation`** — wraps OpenTelemetry/Logfire tracing as a capability rather than a global call (see Section 5 — there appear to be two coexisting ways to enable instrumentation: the top-level `logfire.instrument_pydantic_ai()` call, and an explicit `Instrumentation` capability with `InstrumentationSettings`; the docs show both, exact precedence/interaction between them was **not fully clarified** in what I fetched and should be checked directly if both are used together).
- **`Hooks`** — register lifecycle hook functions via decorator or constructor kwargs without subclassing `AbstractCapability`; the general extension point everything else (including `ToolSearch`) is built on.

---

## 3. Pydantic Evals

Sources: [Evals overview](https://pydantic.dev/docs/ai/evals/evals/) (also `/docs/ai/evals/`), [Built-in evaluators](https://pydantic.dev/docs/ai/evals/evaluators/built-in/), [LLM Judge](https://pydantic.dev/docs/ai/evals/evaluators/llm-judge/).

### `Case`

A `Case` is a single test scenario: task inputs plus optional expected output, metadata, and case-specific evaluators.

```python
from pydantic_evals import Case

case1 = Case(
    name='simple_case',
    inputs='What is the capital of France?',
    expected_output='Paris',
    metadata={'difficulty': 'easy'},
)
```

Fields: `name` (identifier), `inputs` (task input — any type, typically your pipeline stage's input model), `expected_output` (optional), `metadata` (optional dict for categorization, e.g. difficulty/tags), `evaluators` (optional, case-specific, additive to dataset-level evaluators).

### `Dataset`

Groups many `Case`s and (optionally) dataset-wide evaluators for reuse across runs.

```python
from pydantic_evals import Dataset

dataset = Dataset(name='capital_quiz', cases=[case1])
dataset.add_evaluator(IsInstance(type_name='str'))
```

Datasets support save/load — docs reference YAML-based "Dataset Management" (generate/save/load) at `/docs/ai/evals/how-to/dataset-management/`, but I did not fetch that page directly; **treat exact YAML schema as unverified** until checked.

### Built-in evaluators (`pydantic_evals.evaluators`)

| Evaluator | Constructor params | What it checks |
|---|---|---|
| `EqualsExpected` | — | output exactly equals `case.expected_output` |
| `Equals` | `value`, `evaluation_name` | output equals a fixed value |
| `Contains` | `value`, `case_sensitive`, `as_strings`, `evaluation_name` | output contains a substring/value |
| `IsInstance` | `type_name`, `evaluation_name` | output is an instance of the named type |
| `MaxDuration` | `seconds` (float or `timedelta`) | task completes within a time budget |
| `LLMJudge` | `rubric`, `model`, `include_input`, `include_expected_output`, `model_settings`, `score`, `assertion` | LLM-as-judge scoring against a natural-language rubric |
| `GEval` | `criteria`, `evaluation_steps`, `score_range`, `include_input`, `model`, `model_settings`, `evaluation_name` | chain-of-thought scoring against explicit rubric steps, integer score in range |
| `HasMatchingSpan` | `query` (`SpanQuery`), `evaluation_name` | checks OpenTelemetry spans emitted during the run match a query (e.g. "was a specific tool called") |
| `ConfusionMatrixEvaluator` | — | classification confusion matrix across the dataset run |
| `PrecisionRecallEvaluator` | — | precision/recall curve + AUC across the dataset run |

```python
from pydantic_evals.evaluators import Contains, IsInstance, LLMJudge

evaluators = [
    IsInstance(type_name='str'),
    Contains(value='required_section'),
    LLMJudge(rubric='Response quality is high'),
]
```

`HasMatchingSpan` is notable for this project: since Logfire captures a span per tool call / model request (Section 5), an evaluator can assert on agent *behavior* (e.g., "the investigator agent actually called WebSearch at least once") not just final output shape — useful for the investigator's agentic-loop testing where output alone doesn't prove it searched.

### Custom evaluators

Subclass `Evaluator[InputType, OutputType]` and implement `evaluate(ctx: EvaluatorContext[...])`, returning a score (`float`/`bool`), or a `dict` of named sub-scores:

```python
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

class MyEvaluator(Evaluator[str, str]):
    def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
        if ctx.output == ctx.expected_output:
            return 1.0
        return 0.0
```

A `dataclass`-based variant returning multiple named metrics at once is also supported:

```python
from dataclasses import dataclass
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

@dataclass
class ComprehensiveCheck(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> dict[str, bool | float | str]:
        return {
            'valid_format': self._check_format(ctx.output),
            'quality_score': self._score_quality(ctx.output),
            'category': self._classify(ctx.output),
        }
```

### Running evals and reports

```python
async def guess_city(question: str) -> str:
    return 'Paris'

report = dataset.evaluate_sync(guess_city)
report.print(include_input=True, include_output=True, include_durations=False)
```

`Dataset.evaluate_sync(task_fn)` (an async `evaluate(...)` also exists) runs the task function against every case, applies all evaluators (dataset-level + case-level), and returns an `EvaluationReport` with per-case inputs/outputs/scores/assertion pass-fail and aggregate averages; `report.print(...)` renders a table.

**Design implication for this project**: since the pipeline is "a plain async Python function" per stage, each stage's typed-input → typed-output function is directly usable as the `task` passed to `dataset.evaluate_sync`/`evaluate` — no adapter layer needed, as long as `inputs` on the `Case` matches the stage function's argument shape.

---

## 4. TestModel and test doubles

Source: [Testing guide](https://pydantic.dev/docs/ai/guides/testing/).

### `TestModel`

Offline, deterministic model double — generates schema-valid structured data via plain Python (no ML), so it doesn't hit any real API.

```python
from pydantic_ai.models.test import TestModel

with weather_agent.override(model=TestModel()):
    await run_weather_forecast([(prompt, user_id)], conn)
```

- Default behavior: calls **all** registered tools once, then returns either plain text or a structured response matching the agent's `output_type`.
- `TestModel(custom_output_text=...)` — override the default response with fixed text.
- `custom_output_args` — customize structured output payload directly.
- Generated tool-call args won't look "realistic" but will satisfy Pydantic validation in most cases.
- **Limitation**: `TestModel` cannot emulate provider-executed *native* tools (i.e., capabilities like native `WebSearch`/`WebFetch` that run on the provider's side). Recommended pattern: `agent.override(model=TestModel(), native_tools=[])` unless the test specifically targets native-tool integration. This directly matters for testing the investigator agent, which uses real web search — tests should either strip native tools or use `FunctionModel` to simulate the tool-call sequence explicitly.

### `FunctionModel`

Full manual control — you supply a function that receives message history and agent metadata and returns a `ModelResponse` (including simulated tool calls), for scripting exact multi-step agentic-loop scenarios deterministically.

```python
from pydantic_ai.models.function import FunctionModel, AgentInfo

def call_weather_forecast(
    messages: list[ModelMessage], info: AgentInfo
) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart('tool_name', args)])

with weather_agent.override(model=FunctionModel(call_weather_forecast)):
    ...
```

This is likely the right tool for testing the investigator's agentic loop end-to-end offline: script a `FunctionModel` callback that issues a `ToolCallPart` for `web_search`, inspects `messages` to decide the next step, and eventually returns the final structured output — exercising the real loop logic without any network call.

### Safety net: `ALLOW_MODEL_REQUESTS`

```python
from pydantic_ai import models
models.ALLOW_MODEL_REQUESTS = False
```

Set globally in a test suite to hard-fail any accidental real API call that slips past a missing `override`.

### `Agent.override`

Context manager to swap `model`, `deps`, and/or `toolsets`/`native_tools` for the duration of a `with` block, without changing call sites — usable both as an inline context manager and wrapped in a pytest fixture:

```python
@pytest.fixture
def override_weather_agent():
    with weather_agent.override(model=TestModel()):
        yield
```

### Recommended test stack (per docs)

`pytest` + `anyio` (`pytestmark = pytest.mark.anyio` for async tests), `capture_run_messages()` context manager to inspect the exact `ModelRequest`/`ModelResponse` exchange and assert on tool calls, and `dirty-equals` (e.g. `IsNow()`) for comparing structures containing timestamps.

---

## 5. Logfire instrumentation

Source: [Pydantic AI ↔ Logfire integration guide](https://pydantic.dev/docs/ai/integrations/logfire/), [Logfire manual tracing guide](https://pydantic.dev/docs/logfire/instrument/add-manual-tracing/), [Logfire metrics-in-spans reference](https://pydantic.dev/docs/logfire/reference/metrics-in-spans/).

### Enabling auto-instrumentation

```bash
pip install "pydantic-ai-slim[logfire]"   # or full pydantic-ai
logfire auth
logfire projects new   # or: logfire projects use
```

```python
import logfire
from pydantic_ai import Agent

logfire.configure()               # reads token from .logfire dir / env
logfire.instrument_pydantic_ai()  # turns on tracing for all agents

agent = Agent('openai:gpt-5.2', name='hello_world_agent')
result = agent.run_sync('Your prompt here')
```

- `name=` on the `Agent` constructor labels its run span in Logfire — recommended when running multiple distinct agents (directly applicable: name each pipeline-stage agent so spans are identifiable, e.g. `name='investigator'`).
- Optional: `logfire.instrument_httpx(capture_all=True)` to also capture raw HTTP requests/responses to model providers (headers + body) for deep debugging.

### What's captured by default

- One trace per agent run; a span per model request and per tool call.
- Token usage (`gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`) on model-request spans; `gen_ai.aggregated_usage.*` on the agent-run span (rolled up, not double-counted).
- Cost estimation in USD when available for the model — `operation.cost` attribute, described as recorded by pydantic-ai since v1.0.11 (i.e., a long-standing feature, not v2-specific) and specifically surfaced in the Logfire UI when present.
- `gen_ai.provider.name`, `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.response.model` — conforms to OpenTelemetry Semantic Conventions for GenAI (cited version 1.37.0).
- Time-to-first-chunk latency for streaming responses.

### Privacy / verbosity configuration

```python
from pydantic_ai.models.instrumented import InstrumentationSettings

instrumentation_settings = InstrumentationSettings(
    include_content=False,                    # drop prompts/completions/tool args+results
    include_binary_content=False,              # drop image/audio/doc bytes, keep media-type metadata
    include_model_request_parameters=False,    # drop tool schemas from spans (reduces export size)
)
Agent.instrument_all(instrumentation_settings)
```

There is also a capability-based path: `capabilities=[Instrumentation(settings=instrumentation_settings)]` on a specific agent. **Exact precedence between the global `logfire.instrument_pydantic_ai()` call, `Agent.instrument_all(...)`, and the per-agent `Instrumentation` capability was not fully clarified from the fetched pages — verify directly before relying on layered configuration** (e.g. global defaults + one agent overriding via capability).

`InstrumentationSettings(version=5)` is the current default span-shape version; versions 2–4 are deprecated legacy formats. Version 5 improves handling of deferred-tool-call exceptions (`CallDeferred`/`ApprovalRequired` no longer recorded as span errors).

### Custom spans/attributes for per-stage cost or signal tracking

Standard Logfire API (not pydantic-ai-specific), directly applicable to a fixed-pipeline architecture — wrap each pipeline stage in its own span and attach whatever attributes you want to track:

```python
with logfire.span('Pipeline execution') as pipeline:
    with logfire.span('Stage 1: Validation') as stage1:
        stage1.set_attribute('cost', 5.0)
        stage1.set_attribute('signal', 0.98)

    with logfire.span('Stage 2: Processing') as stage2:
        stage2.set_attribute('cost', 12.50)
        stage2.set_attribute('signal', 0.87)
```

Nested spans become parent/child in the trace tree automatically; Logfire's UI shows the hierarchy and per-span duration. `span.set_attribute(key, value)` can also be called after a span opens but before it closes. Plain `logfire.info('msg', cost=..., signal=...)` calls also attach structured attributes without a span, for point-in-time logs.

For **aggregated** numeric metrics (e.g. summing cost across many LLM calls inside one pipeline-stage span), Logfire supports `logfire.configure(metrics=logfire.MetricsOptions(collect_in_spans=True))`, after which counters/histograms recorded inside a span roll up into a `logfire.metrics` attribute on that span automatically.

### Alternative backends

Because instrumentation is OpenTelemetry-native, `logfire.configure(send_to_logfire=False)` plus `OTEL_EXPORTER_OTLP_ENDPOINT` routes the same spans to any OTel collector (Langfuse, W&B Weave, Arize, SigNoz, Sentry, etc.) without touching agent code — useful to know if Logfire itself is ever swapped out, since none of the instrumentation code is Logfire-specific.

---

## Open questions / gaps for follow-up

1. **`SpendLimits` exact API** (harness package) — description-level only; no constructor signature or "what happens when the budget is hit" behavior confirmed from a primary doc page. If hard cost caps per pipeline run are required, either pull in `pydantic-ai-harness` and read source directly, or build budget enforcement manually on top of Logfire's `operation.cost` attribute at each stage boundary (fully achievable with core `pydantic-ai` + `logfire` alone, no harness dependency needed).
2. **Native WebSearch/WebFetch provider support matrix** — not enumerated; needs a direct check of `WebSearchTool`/`WebFetchTool` API reference pages against whatever model(s) this project targets, since "native vs. local fallback" behavior differs by provider and changes as providers add support.
3. **`Instrumentation` capability vs. `logfire.instrument_pydantic_ai()` / `Agent.instrument_all()` precedence** — docs show all three paths exist; interaction/precedence when combined wasn't confirmed.
4. **Dataset YAML save/load schema** (`pydantic_evals`) — referenced but not fetched; needed if datasets should be checked into the repo as data files rather than defined in Python.
5. Given the release cadence observed (roughly one 2.x release every 1–3 days), **re-verify version numbers and any capability constructor signatures directly against `pydantic.dev/docs/ai/` immediately before writing code that depends on them** — this document is a snapshot, not a living reference.
