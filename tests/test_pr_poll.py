"""Bounded, read-only GitHub PR polling through a stubbed gh CLI."""

import json
from types import SimpleNamespace

import pytest

import fleet


def _args(*extra):
    return fleet.build_parser().parse_args(["pr-poll", "42", "--since", "a" * 40, *extra])


def test_pr_poll_reports_change_as_json_without_network(capsys):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"headRefOid": "b" * 40}), stderr="")

    assert fleet.cmd_pr_poll(_args("--repo", "octo/repo", "--json"), run=fake_run,
                             which=lambda name: "/stub/gh") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is True
    assert result["changes"] == {"from": "a" * 40, "to": "b" * 40}
    assert calls == [(
        ["/stub/gh", "pr", "view", "42", "--json", "headRefOid", "--repo", "octo/repo"],
        {"capture_output": True, "text": True, "timeout": fleet.PR_POLL_TIMEOUT_SECONDS},
    )]


def test_pr_poll_reports_unchanged_human_output(capsys):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"headRefOid": "a" * 40}), stderr="")

    assert fleet.cmd_pr_poll(_args(), run=fake_run, which=lambda name: "gh") == 0
    assert capsys.readouterr().out.strip() == f"42: unchanged ({'a' * 40} -> {'a' * 40})"


def test_pr_poll_accepts_bounded_sha_file(tmp_path, capsys):
    path = tmp_path / "recorded-sha"
    path.write_text("a" * 40 + "\n", encoding="utf-8")
    args = fleet.build_parser().parse_args(["pr-poll", "42", "--since-file", str(path), "--json"])

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"headRefOid":"a' + 'a' * 39 + '"}', stderr="")

    assert fleet.cmd_pr_poll(args, run=fake_run, which=lambda name: "gh") == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False


def test_pr_poll_rejects_invalid_sha_before_running_gh():
    args = fleet.build_parser().parse_args(["pr-poll", "42", "--since", "not-a-sha"])
    with pytest.raises(fleet.FleetCliError, match="recorded SHA"):
        fleet.cmd_pr_poll(args, run=lambda *a, **k: pytest.fail("gh must not run"),
                          which=lambda name: "gh")


def test_pr_poll_timeout_is_bounded():
    args = _args()

    def fake_run(argv, **kwargs):
        raise fleet.subprocess.TimeoutExpired(argv, kwargs["timeout"])

    with pytest.raises(fleet.FleetCliError, match="timed out after"):
        fleet.cmd_pr_poll(args, run=fake_run, which=lambda name: "gh")

