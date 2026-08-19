"""URL-provenance grounding for the Investigator (Phase 3) — the third
grounding mechanism in this codebase, after Phase 1's closed-ratio-table
lookup and Phase 2's verbatim-quote check. Pure functions, no model, no
network: everything here operates on a run's own `list[ModelMessage]` or on
a single URL string.

Native web_search/web_fetch tool calls are provider-executed, so pydantic-ai
represents them as NativeToolCallPart/NativeToolReturnPart message parts
(part_kind='builtin-tool-call'/'builtin-tool-return'), NOT as OTel tool-call
spans -- confirmed against the installed pydantic-evals 2.32.0, whose
agentic-evaluator span matching (_is_tool_call_span) only recognizes
locally-executed 'execute_tool'/'running tool' spans. That is why grounding
and trajectory extraction happen here, against message history, rather than
via a span-based evaluator. See .agents/plans/phase-3-investigator.md
Research Findings §2-3 for the full trace.

The closed set this module grounds against is: the URLs the provider
actually returned during this run. A candidate URL not in that set is
dropped, never trusted -- the same "drop, don't trust" idiom as
agents/flag_consolidator.py::_resolve_groups and
agents/financial_statements.py::_ground_candidates.
"""

from collections.abc import Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ModelResponsePart,
    NativeToolCallPart,
    NativeToolReturnPart,
)

from agentic_fundamental_analyst.contracts.investigation import (
    EvidenceCandidate,
    EvidenceItem,
    InvestigationTrajectory,
)

_NATIVE_SEARCH_TOOL_NAME = "web_search"
_NATIVE_FETCH_TOOL_NAME = "web_fetch"


def normalize_url(url: str) -> str:
    """Whitespace/scheme/host case and trailing-slash/fragment tolerant, but
    NOT lenient about the actual path or query -- two different query
    strings are two different pages, mirroring agents/grounding.py's
    whitespace-only leniency for quoted text."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def registrable_domain(url: str) -> str:
    """Host minus a leading 'www.' -- good enough to treat two pages on the
    same site as one domain for the multi-angle diversity check, without
    pulling in a public-suffix-list dependency this project doesn't
    otherwise need."""
    host = urlsplit(url.strip()).netloc.lower()
    host = host.split("@")[-1]  # strip any userinfo
    host = host.split(":")[0]  # strip any port
    return host[4:] if host.startswith("www.") else host


def _iter_response_parts(messages: Sequence[ModelMessage]) -> Iterator[ModelResponsePart]:
    for message in messages:
        if isinstance(message, ModelResponse):
            yield from message.parts


def extract_trajectory(messages: Sequence[ModelMessage]) -> InvestigationTrajectory:
    """Walk the run's message history for native web_search/web_fetch call
    and return parts. Never raises on a malformed/absent content shape --
    a search error object (see below) or an unexpected shape is simply
    skipped, since a crash here would take down a real investigation over
    a rate-limit response the agent otherwise handled fine."""
    search_queries: list[str] = []
    result_urls: list[str] = []
    fetched_urls: list[str] = []

    for part in _iter_response_parts(messages):
        if isinstance(part, NativeToolCallPart) and part.tool_name == _NATIVE_SEARCH_TOOL_NAME:
            args = part.args_as_dict()
            query = args.get("query") if isinstance(args, dict) else None
            if isinstance(query, str):
                search_queries.append(query)
        elif isinstance(part, NativeToolReturnPart) and part.tool_name == _NATIVE_SEARCH_TOOL_NAME:
            # Success: content is a list of result dicts, each with a 'url'.
            # Error (e.g. max_uses_exceeded, rate limit): content is a single
            # error dict, not a list -- branch on shape, don't assume success.
            content = part.content
            if isinstance(content, list):
                for result in content:
                    if isinstance(result, dict) and isinstance(result.get("url"), str):
                        result_urls.append(result["url"])
        elif isinstance(part, NativeToolReturnPart) and part.tool_name == _NATIVE_FETCH_TOOL_NAME:
            content = part.content
            if isinstance(content, dict) and isinstance(content.get("url"), str):
                fetched_urls.append(content["url"])

    all_result_urls = [*result_urls, *fetched_urls]
    domains = {registrable_domain(u) for u in all_result_urls}
    distinct_domains = sorted(d for d in domains if d)

    return InvestigationTrajectory(
        search_queries=search_queries,
        result_urls=result_urls,
        fetched_urls=fetched_urls,
        distinct_domains=distinct_domains,
    )


def ground_evidence(
    candidates: list[EvidenceCandidate], trajectory: InvestigationTrajectory
) -> tuple[list[EvidenceItem], list[str]]:
    """Drop any EvidenceCandidate whose url wasn't actually returned by the
    provider during this run. Returns (grounded, dropped_urls)."""
    returned = {normalize_url(u) for u in (*trajectory.result_urls, *trajectory.fetched_urls)}
    grounded: list[EvidenceItem] = []
    dropped: list[str] = []
    for candidate in candidates:
        if normalize_url(candidate.url) in returned:
            grounded.append(
                EvidenceItem(url=candidate.url, claim=candidate.claim, stance=candidate.stance)
            )
        else:
            dropped.append(candidate.url)
    return grounded, dropped
