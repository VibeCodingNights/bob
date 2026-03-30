"""Tests for GitHub API tools."""

from __future__ import annotations

import json

import httpx
import pytest

import bob.tools.github as github_module
from bob.tools.github import (
    GITHUB_TOOLS,
    execute_fetch_github_repo,
    execute_fetch_github_user,
    execute_github_tool,
    execute_search_github_repos,
)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Reset module-level rate limit state between tests."""
    github_module._rate_limit_remaining = None
    yield
    github_module._rate_limit_remaining = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        headers=headers or {},
    )
    return resp


def _mock_client(*responses: httpx.Response) -> httpx.AsyncClient:
    """Return an AsyncClient whose .get() yields responses in order."""

    class _Transport(httpx.AsyncBaseTransport):
        def __init__(self):
            self._responses = list(responses)
            self._idx = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            resp = self._responses[self._idx]
            self._idx = min(self._idx + 1, len(self._responses) - 1)
            return resp

    return httpx.AsyncClient(transport=_Transport())


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


_USER_JSON = {
    "login": "octocat",
    "name": "The Octocat",
    "bio": "GitHub mascot",
    "company": "@github",
    "location": "San Francisco",
    "public_repos": 42,
    "followers": 1000,
}

_REPOS_JSON = [
    {"name": "hello-world", "language": "Python", "stargazers_count": 10},
    {"name": "cool-lib", "language": "Rust", "stargazers_count": 5},
]


class TestFetchGitHubUser:
    @pytest.mark.asyncio
    async def test_parse_user_profile(self):
        client = _mock_client(
            _mock_response(json_data=_USER_JSON),
            _mock_response(json_data=_REPOS_JSON),
        )
        result = await execute_fetch_github_user("octocat", client)

        assert "GitHub User: octocat" in result
        assert "Name: The Octocat" in result
        assert "Bio: GitHub mascot" in result
        assert "Company: @github" in result
        assert "Location: San Francisco" in result
        assert "Public repos: 42" in result
        assert "Followers: 1000" in result
        assert "hello-world (Python, 10 stars)" in result
        assert "cool-lib (Rust, 5 stars)" in result

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        client = _mock_client(_mock_response(status_code=404, json_data={"message": "Not Found"}))
        result = await execute_fetch_github_user("nonexistent", client)
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_user_rate_limited(self):
        client = _mock_client(
            _mock_response(
                status_code=403,
                json_data={"message": "rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0"},
            )
        )
        result = await execute_fetch_github_user("octocat", client)
        assert "rate limited" in result.lower()


# ---------------------------------------------------------------------------
# Repo info
# ---------------------------------------------------------------------------


_REPO_JSON = {
    "full_name": "octocat/hello-world",
    "description": "A test repository",
    "language": "Python",
    "stargazers_count": 100,
    "forks_count": 50,
    "open_issues_count": 3,
    "topics": ["hello", "world"],
}


class TestFetchGitHubRepo:
    @pytest.mark.asyncio
    async def test_parse_repo_info(self):
        client = _mock_client(_mock_response(json_data=_REPO_JSON))
        result = await execute_fetch_github_repo("octocat", "hello-world", client)

        assert "Repository: octocat/hello-world" in result
        assert "Description: A test repository" in result
        assert "Language: Python" in result
        assert "Stars: 100" in result
        assert "Forks: 50" in result
        assert "Open issues: 3" in result
        assert "Topics: hello, world" in result

    @pytest.mark.asyncio
    async def test_repo_not_found(self):
        client = _mock_client(_mock_response(status_code=404, json_data={"message": "Not Found"}))
        result = await execute_fetch_github_repo("octocat", "nonexistent", client)
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_repo_rate_limited(self):
        client = _mock_client(
            _mock_response(
                status_code=403,
                json_data={"message": "rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0"},
            )
        )
        result = await execute_fetch_github_repo("octocat", "hello-world", client)
        assert "rate limited" in result.lower()


# ---------------------------------------------------------------------------
# Repo search
# ---------------------------------------------------------------------------


_SEARCH_JSON = {
    "total_count": 2,
    "items": [
        {
            "full_name": "foo/bar",
            "description": "A foo bar lib",
            "language": "Go",
            "stargazers_count": 500,
        },
        {
            "full_name": "baz/qux",
            "description": None,
            "language": None,
            "stargazers_count": 200,
        },
    ],
}


class TestSearchGitHubRepos:
    @pytest.mark.asyncio
    async def test_parse_search_results(self):
        client = _mock_client(_mock_response(json_data=_SEARCH_JSON))
        result = await execute_search_github_repos("hackathon", client)

        assert "foo/bar" in result
        assert "A foo bar lib" in result
        assert "Go" in result
        assert "500 stars" in result
        assert "baz/qux" in result
        assert "No description" in result
        assert "unknown" in result

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        client = _mock_client(
            _mock_response(json_data={"total_count": 0, "items": []})
        )
        result = await execute_search_github_repos("xyznonexistent", client)
        assert "No repositories found" in result

    @pytest.mark.asyncio
    async def test_search_rate_limited(self):
        client = _mock_client(
            _mock_response(
                status_code=403,
                json_data={"message": "rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0"},
            )
        )
        result = await execute_search_github_repos("hackathon", client)
        assert "rate limited" in result.lower()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestExecuteGitHubTool:
    @pytest.mark.asyncio
    async def test_dispatch_fetch_user(self):
        client = _mock_client(
            _mock_response(json_data=_USER_JSON),
            _mock_response(json_data=_REPOS_JSON),
        )
        result = await execute_github_tool(
            "fetch_github_user", {"username": "octocat"}, client
        )
        assert result is not None
        assert "GitHub User: octocat" in result

    @pytest.mark.asyncio
    async def test_dispatch_fetch_repo(self):
        client = _mock_client(_mock_response(json_data=_REPO_JSON))
        result = await execute_github_tool(
            "fetch_github_repo", {"owner": "octocat", "repo": "hello-world"}, client
        )
        assert result is not None
        assert "Repository: octocat/hello-world" in result

    @pytest.mark.asyncio
    async def test_dispatch_search_repos(self):
        client = _mock_client(_mock_response(json_data=_SEARCH_JSON))
        result = await execute_github_tool(
            "search_github_repos", {"query": "hackathon"}, client
        )
        assert result is not None
        assert "foo/bar" in result

    @pytest.mark.asyncio
    async def test_dispatch_unknown(self):
        client = _mock_client()
        result = await execute_github_tool("nonexistent", {}, client)
        assert result is None

    def test_tool_definitions_present(self):
        names = {t["name"] for t in GITHUB_TOOLS}
        assert names == {"fetch_github_user", "fetch_github_repo", "search_github_repos"}
