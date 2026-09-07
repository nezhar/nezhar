#!/usr/bin/env python3
"""Refresh the GitHub star counts in the profile README.

The README is the source of truth for which repositories are tracked: every
markdown table row whose first cell links to a GitHub repository and whose last
cell holds a star count gets refreshed. Nothing else in the file is touched.

Usage:
    python .github/scripts/update_stars.py [--readme PATH] [--dry-run]

Reads GITHUB_TOKEN from the environment when present. Without it the GitHub API
is queried anonymously, which is rate limited to 60 requests per hour but is
enough to run the script locally.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.github.com/repos/{repo}"
RETRIES = 3
RETRY_DELAY_SECONDS = 2

# A tracked row looks like:
#   | [name](https://github.com/owner/repo) | description | ★ 135 |
#   | [name](https://github.com/owner/repo) | description | — |
ROW_PATTERN = re.compile(
    r"^(\|\s*\[[^\]]+\]\(https://github\.com/([\w.-]+)/([\w.-]+)\)\s*\|.*\|\s*)"
    r"(★\s*[\d,]+|—)"
    r"(\s*\|)$",
    re.MULTILINE,
)


def format_stars(count):
    """Render a star count the way the README writes it."""
    return f"★ {count:,}" if count else "—"


def tracked_repos(text):
    """Return the `owner/repo` of every tracked row, in order, without duplicates."""
    repos = []
    for match in ROW_PATTERN.finditer(text):
        repo = f"{match.group(2)}/{match.group(3)}"
        if repo not in repos:
            repos.append(repo)
    return repos


def rewrite_readme(text, stars):
    """Replace the star cells for which `stars` holds a count.

    `stars` maps `owner/repo` to a star count. Repositories missing from it keep
    their current cell, which is how a failed lookup is handled.

    Returns the new text and a list of `(repo, old_cell, new_cell)` changes.
    """
    changes = []

    def replace(match):
        prefix, owner, name, current, suffix = match.groups()
        repo = f"{owner}/{name}"
        if repo not in stars:
            return match.group(0)
        updated = format_stars(stars[repo])
        if updated != current:
            changes.append((repo, current, updated))
        return f"{prefix}{updated}{suffix}"

    return ROW_PATTERN.sub(replace, text), changes


def classify_http_error(code, headers):
    """Decide how to react to an HTTP status from the GitHub API.

    GitHub answers 403 both for a repository the token may not see and for an
    exhausted rate limit; the remaining-quota header separates the two. Getting
    that wrong would keep every star count stale without failing the run.
    """
    if code == 401:
        return "fatal"
    if code == 429:
        return "rate_limit"
    if code == 403:
        remaining = headers.get("x-ratelimit-remaining")
        return "rate_limit" if remaining == "0" else "skip"
    if code == 404:
        return "skip"
    return "retry"


def fetch_star_count(repo, token):
    """Return the star count for `owner/repo`, or None if the repo is unreachable.

    A missing or forbidden repository (renamed, deleted, made private) yields
    None so the run can continue with its existing value. Anything else is
    retried and then raised, so a broken run never writes a partial README.
    """
    request = urllib.request.Request(API_URL.format(repo=repo))
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "nezhar-readme-star-updater")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["stargazers_count"]
        except urllib.error.HTTPError as error:
            reaction = classify_http_error(error.code, error.headers)
            if reaction == "skip":
                print(f"warning: {repo} returned HTTP {error.code}, keeping current value")
                return None
            if reaction == "fatal":
                raise SystemExit("error: GITHUB_TOKEN was rejected (HTTP 401)")
            if reaction == "rate_limit":
                reset = error.headers.get("x-ratelimit-reset", "unknown")
                raise SystemExit(
                    f"error: GitHub API rate limit exhausted while reading {repo} "
                    f"(resets at epoch {reset}); README left untouched"
                )
            if attempt == RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            if attempt == RETRIES:
                raise
        time.sleep(RETRY_DELAY_SECONDS * attempt)


def report(changes):
    """Print the changes to stdout and, in Actions, to the job summary."""
    lines = [f"{repo}: {old} → {new}" for repo, old, new in changes]
    for line in lines:
        print(line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        body = "\n".join(f"- `{line}`" for line in lines) if lines else "No changes."
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"### Star counts\n\n{body}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md", help="path to the README")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the changes without writing the file",
    )
    args = parser.parse_args(argv)

    with open(args.readme, encoding="utf-8") as readme:
        text = readme.read()

    token = os.environ.get("GITHUB_TOKEN")
    stars = {}
    for repo in tracked_repos(text):
        count = fetch_star_count(repo, token)
        if count is not None:
            stars[repo] = count

    updated, changes = rewrite_readme(text, stars)
    report(changes)

    if not changes:
        print("README is up to date.")
        return 0

    if args.dry_run:
        print("Dry run, README not written.")
        return 0

    with open(args.readme, "w", encoding="utf-8") as readme:
        readme.write(updated)
    print(f"Updated {len(changes)} row(s) in {args.readme}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
