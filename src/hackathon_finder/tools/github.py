"""GitHub API tools for fetching user profiles, repo info, and searching repos.

Provides tool definitions and async executors for the public GitHub REST API.
Rate-limited to 60 requests/hour without authentication.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from hackathon_finder.tools.web import _retry_http

logger = logging.getLogger(__name__)

_GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}

_rate_limit_remaining: int | None = None

# --- Tool definitions ---

FETCH_GITHUB_USER_TOOL: dict = {
    "name": "fetch_github_user",
    "description": (
        "Fetch a GitHub user's public profile and their 5 most recently updated "
        "repositories. Returns name, bio, company, location, repo count, followers, "
        "and recent repo details (name, language, stars)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "GitHub username"},
        },
        "required": ["username"],
    },
}

FETCH_GITHUB_REPO_TOOL: dict = {
    "name": "fetch_github_repo",
    "description": (
        "Fetch details about a specific GitHub repository including description, "
        "language, stars, forks, open issues, and topics."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner (user or org)"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    },
}

SEARCH_GITHUB_REPOS_TOOL: dict = {
    "name": "search_github_repos",
    "description": (
        "Search GitHub repositories by query string. Returns top results sorted "
        "by stars with name, description, stars, and language."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

GITHUB_TOOLS: list[dict] = [
    FETCH_GITHUB_USER_TOOL,
    FETCH_GITHUB_REPO_TOOL,
    SEARCH_GITHUB_REPOS_TOOL,
]


# --- Helpers ---


def _check_rate_limit(resp: httpx.Response) -> str | None:
    """Return an error message if the response indicates rate limiting."""
    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        return "GitHub API rate limited. Try again later (unauthenticated limit: 60 requests/hour)."
    return None


def _check_not_found(resp: httpx.Response, entity: str) -> str | None:
    """Return an error message if the response is 404."""
    if resp.status_code == 404:
        return f"GitHub {entity} not found."
    return None


# --- Tool execution ---


async def execute_fetch_github_user(
    username: str, http_client: httpx.AsyncClient
) -> str:
    """Fetch a GitHub user profile and their recent repositories."""
    global _rate_limit_remaining
    if _rate_limit_remaining is not None and _rate_limit_remaining <= 5:
        return "GitHub API rate limit nearly exhausted. Skipping to preserve remaining quota."
    url = f"https://api.github.com/users/{quote(username, safe='')}"
    try:
        resp = await _retry_http(
            lambda: http_client.get(url, headers=_GITHUB_HEADERS), url
        )
    except Exception as e:
        return f"Error fetching GitHub user {username}: {e}"

    rate_err = _check_rate_limit(resp)
    if rate_err:
        return rate_err

    not_found = _check_not_found(resp, f"user '{username}'")
    if not_found:
        return not_found

    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            _rate_limit_remaining = int(remaining)
        except ValueError:
            pass

    data = resp.json()
    parts = [f"GitHub User: {username}"]
    if data.get("name"):
        parts.append(f"Name: {data['name']}")
    if data.get("bio"):
        parts.append(f"Bio: {data['bio']}")
    if data.get("company"):
        parts.append(f"Company: {data['company']}")
    if data.get("location"):
        parts.append(f"Location: {data['location']}")
    parts.append(f"Public repos: {data.get('public_repos', 0)}")
    parts.append(f"Followers: {data.get('followers', 0)}")

    # Fetch recent repos
    repos_url = f"https://api.github.com/users/{quote(username, safe='')}/repos?sort=updated&per_page=5"
    try:
        repos_resp = await _retry_http(
            lambda: http_client.get(repos_url, headers=_GITHUB_HEADERS), repos_url
        )
        if repos_resp.status_code == 200:
            repos = repos_resp.json()
            if repos:
                parts.append("\nRecent repositories:")
                for repo in repos:
                    lang = repo.get("language") or "unknown"
                    stars = repo.get("stargazers_count", 0)
                    parts.append(f"  - {repo['name']} ({lang}, {stars} stars)")
    except Exception:
        logger.debug("Failed to fetch repos for %s", username)

    return "\n".join(parts)


async def execute_fetch_github_repo(
    owner: str, repo: str, http_client: httpx.AsyncClient
) -> str:
    """Fetch details about a specific GitHub repository."""
    global _rate_limit_remaining
    if _rate_limit_remaining is not None and _rate_limit_remaining <= 5:
        return "GitHub API rate limit nearly exhausted. Skipping to preserve remaining quota."
    url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    try:
        resp = await _retry_http(
            lambda: http_client.get(url, headers=_GITHUB_HEADERS), url
        )
    except Exception as e:
        return f"Error fetching GitHub repo {owner}/{repo}: {e}"

    rate_err = _check_rate_limit(resp)
    if rate_err:
        return rate_err

    not_found = _check_not_found(resp, f"repo '{owner}/{repo}'")
    if not_found:
        return not_found

    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            _rate_limit_remaining = int(remaining)
        except ValueError:
            pass

    data = resp.json()
    parts = [f"Repository: {data.get('full_name', f'{owner}/{repo}')}"]
    if data.get("description"):
        parts.append(f"Description: {data['description']}")
    if data.get("language"):
        parts.append(f"Language: {data['language']}")
    parts.append(f"Stars: {data.get('stargazers_count', 0)}")
    parts.append(f"Forks: {data.get('forks_count', 0)}")
    parts.append(f"Open issues: {data.get('open_issues_count', 0)}")
    topics = data.get("topics", [])
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")

    return "\n".join(parts)


async def execute_search_github_repos(
    query: str, http_client: httpx.AsyncClient, max_results: int = 5
) -> str:
    """Search GitHub repositories by query."""
    global _rate_limit_remaining
    if _rate_limit_remaining is not None and _rate_limit_remaining <= 5:
        return "GitHub API rate limit nearly exhausted. Skipping to preserve remaining quota."
    max_results = min(max_results, 20)
    params = urlencode({"q": query, "sort": "stars", "per_page": max_results})
    url = f"https://api.github.com/search/repositories?{params}"
    try:
        resp = await _retry_http(
            lambda: http_client.get(url, headers=_GITHUB_HEADERS), url
        )
    except Exception as e:
        return f"Error searching GitHub repos: {e}"

    rate_err = _check_rate_limit(resp)
    if rate_err:
        return rate_err

    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            _rate_limit_remaining = int(remaining)
        except ValueError:
            pass

    data = resp.json()
    items = data.get("items", [])
    if not items:
        return f"No repositories found for query: {query}"

    parts = [f"Search results for '{query}':"]
    for item in items:
        lang = item.get("language") or "unknown"
        stars = item.get("stargazers_count", 0)
        desc = item.get("description") or "No description"
        parts.append(f"  - {item['full_name']}: {desc} ({lang}, {stars} stars)")

    return "\n".join(parts)


# --- Dispatcher ---


async def execute_github_tool(
    name: str, input_data: dict, http_client: httpx.AsyncClient
) -> str | None:
    """Dispatch a GitHub tool by name. Returns None if name is not a GitHub tool."""
    if name == "fetch_github_user":
        return await execute_fetch_github_user(input_data["username"], http_client)
    elif name == "fetch_github_repo":
        return await execute_fetch_github_repo(
            input_data["owner"], input_data["repo"], http_client
        )
    elif name == "search_github_repos":
        return await execute_search_github_repos(
            input_data["query"],
            http_client,
            max_results=input_data.get("max_results", 5),
        )
    return None
