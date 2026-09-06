"""Tests for the README star count updater.

No network access: the star counts are injected as a plain dict, so only the
pure rewrite logic is under test here.
"""

import unittest

from update_stars import rewrite_readme

README = """\
[VibePod](https://vibepod.dev) - a unified CLI.

[VoiceVault](https://github.com/nezhar/voicevault) - voice conversations.

| Repository | Description | Stars |
|------------|-------------|-------|
| [vibepod-cli](https://github.com/vibepod/vibepod-cli) | The main CLI | * 135 |
| [vibepod-proxy](https://github.com/vibepod/vibepod-proxy) | Traffic capture & logging | - |
| [wordpress-docker-compose](https://github.com/nezhar/wordpress-docker-compose) | Easy WordPress development | * 2,040 |
| [snypy-backend](https://github.com/snypy/snypy-backend) | REST API & admin | * 12 |

<a href="https://github.com/sponsors/nezhar"><img src="badge.svg" alt="Sponsors"/></a>
""".replace(
    "* ", "★ "
).replace(
    "| - |", "| — |"
)


def stars_of(text, name):
    """Return the raw star cell of the row linking to the repo called `name`."""
    for line in text.splitlines():
        if f"/{name})" in line and line.startswith("|"):
            return line.rsplit("|", 2)[1].strip()
    raise AssertionError(f"no table row for {name}")


class RewriteReadmeTest(unittest.TestCase):
    def test_increased_count_is_written_to_the_cell(self):
        text, _ = rewrite_readme(README, {"vibepod/vibepod-cli": 141})

        self.assertEqual(stars_of(text, "vibepod-cli"), "★ 141")

    def test_only_the_star_cell_of_the_row_changes(self):
        text, _ = rewrite_readme(README, {"vibepod/vibepod-cli": 141})

        before = [line for line in README.splitlines() if "vibepod-cli)" in line][0]
        after = [line for line in text.splitlines() if "vibepod-cli)" in line][0]
        self.assertEqual(before.replace("★ 135", "★ 141"), after)

    def test_first_star_replaces_the_em_dash(self):
        text, _ = rewrite_readme(README, {"vibepod/vibepod-proxy": 7})

        self.assertEqual(stars_of(text, "vibepod-proxy"), "★ 7")

    def test_dropping_to_zero_stars_renders_an_em_dash(self):
        text, _ = rewrite_readme(README, {"snypy/snypy-backend": 0})

        self.assertEqual(stars_of(text, "snypy-backend"), "—")

    def test_counts_above_a_thousand_get_a_separator(self):
        text, _ = rewrite_readme(README, {"nezhar/wordpress-docker-compose": 2137})

        self.assertEqual(stars_of(text, "wordpress-docker-compose"), "★ 2,137")

    def test_repo_missing_from_the_lookup_keeps_its_cell(self):
        text, _ = rewrite_readme(README, {"vibepod/vibepod-cli": 141})

        self.assertEqual(stars_of(text, "snypy-backend"), "★ 12")

    def test_github_links_outside_tables_are_untouched(self):
        text, _ = rewrite_readme(README, {"nezhar/voicevault": 99})

        self.assertIn("[VoiceVault](https://github.com/nezhar/voicevault) - voice", text)
        self.assertIn('href="https://github.com/sponsors/nezhar"', text)

    def test_unchanged_counts_produce_no_edit_and_no_changes(self):
        text, changes = rewrite_readme(README, {"vibepod/vibepod-cli": 135})

        self.assertEqual(text, README)
        self.assertEqual(changes, [])

    def test_changes_report_repo_old_and_new_values(self):
        _, changes = rewrite_readme(
            README,
            {"vibepod/vibepod-cli": 141, "vibepod/vibepod-proxy": 7},
        )

        self.assertEqual(
            changes,
            [
                ("vibepod/vibepod-cli", "★ 135", "★ 141"),
                ("vibepod/vibepod-proxy", "—", "★ 7"),
            ],
        )


class TrackedReposTest(unittest.TestCase):
    def test_lists_every_repo_that_has_a_star_cell(self):
        from update_stars import tracked_repos

        self.assertEqual(
            tracked_repos(README),
            [
                "vibepod/vibepod-cli",
                "vibepod/vibepod-proxy",
                "nezhar/wordpress-docker-compose",
                "snypy/snypy-backend",
            ],
        )

    def test_repos_are_listed_once_each(self):
        from update_stars import tracked_repos

        doubled = README + README
        self.assertEqual(len(tracked_repos(doubled)), 4)


class ClassifyHttpErrorTest(unittest.TestCase):
    """GitHub answers 403 both for an unreachable repo and for rate limiting.

    Treating a rate limit as "unreachable" would silently keep every star count
    stale, so the two have to be told apart.
    """

    def test_missing_repo_is_skipped(self):
        from update_stars import classify_http_error

        self.assertEqual(classify_http_error(404, {}), "skip")

    def test_forbidden_repo_with_quota_left_is_skipped(self):
        from update_stars import classify_http_error

        headers = {"x-ratelimit-remaining": "57"}
        self.assertEqual(classify_http_error(403, headers), "skip")

    def test_forbidden_with_exhausted_quota_is_a_rate_limit(self):
        from update_stars import classify_http_error

        headers = {"x-ratelimit-remaining": "0"}
        self.assertEqual(classify_http_error(403, headers), "rate_limit")

    def test_too_many_requests_is_a_rate_limit(self):
        from update_stars import classify_http_error

        self.assertEqual(classify_http_error(429, {}), "rate_limit")

    def test_bad_credentials_are_fatal(self):
        from update_stars import classify_http_error

        self.assertEqual(classify_http_error(401, {}), "fatal")

    def test_server_errors_are_retried(self):
        from update_stars import classify_http_error

        self.assertEqual(classify_http_error(502, {}), "retry")


if __name__ == "__main__":
    unittest.main()
