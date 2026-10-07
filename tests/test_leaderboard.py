from __future__ import annotations

from typing import Any

import leaderboard


class FakeTable:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.update_calls: list[dict[str, Any]] = []

    def scan(self, **_: Any) -> dict[str, Any]:
        return {"Items": self.items}

    def update_item(self, **arguments: Any) -> dict[str, Any]:
        self.update_calls.append(arguments)
        return {
            "Attributes": {
                "display_name": arguments["ExpressionAttributeValues"][":name"],
                "score": 0,
            }
        }


def test_normalise_name_collapses_whitespace_and_limits_length() -> None:
    assert leaderboard.normalise_name("  Ada   Lovelace  ") == "Ada Lovelace"
    assert len(leaderboard.normalise_name("x" * 40)) == 24


def test_leaderboard_orders_by_score_and_completions(monkeypatch: Any) -> None:
    table = FakeTable(
        [
            {
                "display_name": "Grace",
                "score": 900,
                "completed_missions": {"extract"},
                "updated_at": 20,
            },
            {
                "display_name": "Ada",
                "score": 50,
                "completed_missions": {"extract", "override", "act", "iam"},
                "updated_at": 10,
            },
        ]
    )
    monkeypatch.setattr(leaderboard, "_table", lambda: table)

    ranking = leaderboard.get_leaderboard()

    assert ranking[0] == {
        "rank": 1,
        "name": "Ada",
        "score": 600,
        "completed": 3,
    }


def test_register_player_sets_seven_day_ttl(monkeypatch: Any) -> None:
    table = FakeTable([])
    monkeypatch.setattr(leaderboard, "_table", lambda: table)
    monkeypatch.setattr(leaderboard.time, "time", lambda: 1_000)

    profile = leaderboard.register_player("session-123", " Ada ")

    values = table.update_calls[0]["ExpressionAttributeValues"]
    assert values[":name"] == "Ada"
    assert values[":expires"] == 1_000 + leaderboard.RETENTION_SECONDS
    assert profile == {"name": "Ada", "score": 0, "completed": []}
