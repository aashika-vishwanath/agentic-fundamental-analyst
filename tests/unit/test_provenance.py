from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    TextPart,
    UserPromptPart,
)

from agentic_fundamental_analyst.agents.provenance import (
    extract_trajectory,
    ground_evidence,
    registrable_domain,
)
from agentic_fundamental_analyst.contracts.investigation import EvidenceCandidate, EvidenceStance


def _search_call(query: str, call_id: str = "c1") -> NativeToolCallPart:
    return NativeToolCallPart(tool_name="web_search", args={"query": query}, tool_call_id=call_id)


def _search_return(results: list[dict], call_id: str = "c1") -> NativeToolReturnPart:
    return NativeToolReturnPart(tool_name="web_search", content=results, tool_call_id=call_id)


def _search_error_return(error_code: str, call_id: str = "c1") -> NativeToolReturnPart:
    return NativeToolReturnPart(
        tool_name="web_search",
        content={"type": "web_search_tool_result_error", "error_code": error_code},
        tool_call_id=call_id,
    )


def _fetch_call(url: str, call_id: str = "f1") -> NativeToolCallPart:
    return NativeToolCallPart(tool_name="web_fetch", args={"url": url}, tool_call_id=call_id)


def _fetch_return(url: str, call_id: str = "f1") -> NativeToolReturnPart:
    return NativeToolReturnPart(
        tool_name="web_fetch",
        content={
            "content": "page text",
            "url": url,
            "retrieved_at": "2026-08-19",
            "type": "web_fetch_result",
        },
        tool_call_id=call_id,
    )


# --- extract_trajectory ---


def test_extract_trajectory_collects_search_queries_and_result_urls():
    messages = [
        ModelRequest(parts=[UserPromptPart(content="investigate")]),
        ModelResponse(
            parts=[
                _search_call("capex spike AI buildout"),
                _search_return(
                    [
                        {"type": "web_search_result", "url": "https://reuters.com/a", "title": "A"},
                        {"type": "web_search_result", "url": "https://sec.gov/b", "title": "B"},
                    ]
                ),
                TextPart(content="based on this, I'll check further"),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.search_queries == ["capex spike AI buildout"]
    assert trajectory.result_urls == ["https://reuters.com/a", "https://sec.gov/b"]
    assert trajectory.distinct_domains == ["reuters.com", "sec.gov"]


def test_extract_trajectory_handles_search_error_object_without_crashing():
    """A rate-limited/max-uses-exceeded search returns content as a single
    error dict, not a list -- must not crash and must not add any URLs."""
    messages = [
        ModelResponse(
            parts=[
                _search_call("second query"),
                _search_error_return("max_uses_exceeded"),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.search_queries == ["second query"]
    assert trajectory.result_urls == []
    assert trajectory.distinct_domains == []


def test_extract_trajectory_collects_fetched_urls_separately_from_search_results():
    messages = [
        ModelResponse(
            parts=[
                _search_call("query"),
                _search_return(
                    [{"type": "web_search_result", "url": "https://a.com/x", "title": "A"}]
                ),
                _fetch_call("https://a.com/x"),
                _fetch_return("https://a.com/x"),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.result_urls == ["https://a.com/x"]
    assert trajectory.fetched_urls == ["https://a.com/x"]
    # same domain from both search and fetch counts once
    assert trajectory.distinct_domains == ["a.com"]


def test_extract_trajectory_two_urls_same_domain_count_as_one_distinct_domain():
    messages = [
        ModelResponse(
            parts=[
                _search_call("query"),
                _search_return(
                    [
                        {
                            "type": "web_search_result",
                            "url": "https://news.example.com/1",
                            "title": "1",
                        },
                        {
                            "type": "web_search_result",
                            "url": "https://news.example.com/2",
                            "title": "2",
                        },
                    ]
                ),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.distinct_domains == ["news.example.com"]


def test_extract_trajectory_www_prefix_treated_same_as_bare_host():
    messages = [
        ModelResponse(
            parts=[
                _search_call("query"),
                _search_return(
                    [
                        {
                            "type": "web_search_result",
                            "url": "https://www.example.com/1",
                            "title": "1",
                        },
                        {"type": "web_search_result", "url": "https://example.com/2", "title": "2"},
                    ]
                ),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.distinct_domains == ["example.com"]


def test_extract_trajectory_ignores_unrelated_native_tool_names():
    messages = [
        ModelResponse(
            parts=[
                NativeToolCallPart(tool_name="tool_search", args={}, tool_call_id="ts1"),
                NativeToolReturnPart(
                    tool_name="tool_search", content={"results": []}, tool_call_id="ts1"
                ),
            ]
        ),
    ]
    trajectory = extract_trajectory(messages)
    assert trajectory.search_queries == []
    assert trajectory.result_urls == []


def test_extract_trajectory_empty_messages_yields_empty_trajectory():
    trajectory = extract_trajectory([])
    assert trajectory.search_queries == []
    assert trajectory.result_urls == []
    assert trajectory.fetched_urls == []
    assert trajectory.distinct_domains == []


# --- registrable_domain ---


def test_registrable_domain_strips_www_and_port():
    assert registrable_domain("https://www.example.com:8443/path") == "example.com"


def test_registrable_domain_bare_host_unchanged():
    assert registrable_domain("https://sec.gov/x") == "sec.gov"


# --- ground_evidence ---


def _trajectory_with(*urls: str):
    from agentic_fundamental_analyst.contracts.investigation import InvestigationTrajectory

    return InvestigationTrajectory(
        search_queries=["q"],
        result_urls=list(urls),
        fetched_urls=[],
        distinct_domains=sorted({registrable_domain(u) for u in urls}),
    )


def test_ground_evidence_keeps_url_that_was_actually_returned():
    trajectory = _trajectory_with("https://reuters.com/story")
    candidates = [
        EvidenceCandidate(
            url="https://reuters.com/story", claim="reported growth", stance=EvidenceStance.CONTEXT
        )
    ]
    grounded, dropped = ground_evidence(candidates, trajectory)
    assert len(grounded) == 1
    assert grounded[0].url == "https://reuters.com/story"
    assert dropped == []


def test_ground_evidence_drops_fabricated_url_not_in_trajectory():
    trajectory = _trajectory_with("https://reuters.com/story")
    candidates = [
        EvidenceCandidate(
            url="https://totally-fabricated.example/nonexistent",
            claim="made up",
            stance=EvidenceStance.SUPPORTS_CONCERNING,
        )
    ]
    grounded, dropped = ground_evidence(candidates, trajectory)
    assert grounded == []
    assert dropped == ["https://totally-fabricated.example/nonexistent"]


def test_ground_evidence_tolerates_trailing_slash_and_fragment_differences():
    trajectory = _trajectory_with("https://example.com/page")
    candidates = [
        EvidenceCandidate(
            url="https://example.com/page/#section-2",
            claim="cited with a fragment",
            stance=EvidenceStance.CONTEXT,
        )
    ]
    grounded, dropped = ground_evidence(candidates, trajectory)
    assert len(grounded) == 1
    assert dropped == []


def test_ground_evidence_does_not_conflate_different_query_strings():
    trajectory = _trajectory_with("https://example.com/page?id=1")
    candidates = [
        EvidenceCandidate(
            url="https://example.com/page?id=2",
            claim="different page entirely",
            stance=EvidenceStance.CONTEXT,
        )
    ]
    grounded, dropped = ground_evidence(candidates, trajectory)
    assert grounded == []
    assert dropped == ["https://example.com/page?id=2"]


def test_ground_evidence_grounds_against_fetched_urls_too():
    from agentic_fundamental_analyst.contracts.investigation import InvestigationTrajectory

    trajectory = InvestigationTrajectory(
        search_queries=["q"],
        result_urls=[],
        fetched_urls=["https://sec.gov/filing"],
        distinct_domains=["sec.gov"],
    )
    candidates = [
        EvidenceCandidate(
            url="https://sec.gov/filing",
            claim="from the fetched page",
            stance=EvidenceStance.CONTEXT,
        )
    ]
    grounded, dropped = ground_evidence(candidates, trajectory)
    assert len(grounded) == 1
    assert dropped == []
