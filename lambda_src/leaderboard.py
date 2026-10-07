from __future__ import annotations

import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_LEADERBOARD_PLAYERS = 10
MISSION_POINTS = {"extract": 100, "override": 200, "act": 300}


def _current_completed(item: dict[str, Any]) -> set[str]:
    return set(item.get("completed_missions", set())) & set(MISSION_POINTS)


def _current_score(item: dict[str, Any]) -> int:
    return sum(MISSION_POINTS[mission] for mission in _current_completed(item))


def _table() -> Any:
    return boto3.resource("dynamodb").Table(os.environ["LEADERBOARD_TABLE"])


def normalise_name(display_name: str) -> str:
    cleaned = " ".join(display_name.split())
    return cleaned[:24] or "Anonymous"


def register_player(session_id: str, display_name: str) -> dict[str, Any]:
    now = int(time.time())
    response = _table().update_item(
        Key={"player_id": session_id},
        UpdateExpression=(
            "SET display_name = :name, updated_at = :now, expires_at = :expires, "
            "#score = if_not_exists(#score, :zero)"
        ),
        ExpressionAttributeNames={"#score": "score"},
        ExpressionAttributeValues={
            ":name": normalise_name(display_name),
            ":now": now,
            ":expires": now + RETENTION_SECONDS,
            ":zero": 0,
        },
        ReturnValues="ALL_NEW",
    )
    attributes = response.get("Attributes", {})
    return {
        "name": attributes.get("display_name", normalise_name(display_name)),
        "score": _current_score(attributes),
        "completed": sorted(_current_completed(attributes)),
    }


def record_outcome(
    session_id: str,
    display_name: str,
    mission: str,
    outcome: dict[str, Any],
) -> None:
    if outcome["state"] != "won" or mission not in MISSION_POINTS:
        return

    now = int(time.time())
    try:
        _table().update_item(
            Key={"player_id": session_id},
            UpdateExpression=(
                "SET display_name = :name, updated_at = :now, expires_at = :expires "
                "ADD completed_missions :mission_set, #score :points"
            ),
            ConditionExpression=(
                "attribute_not_exists(completed_missions) "
                "OR NOT contains(completed_missions, :mission)"
            ),
            ExpressionAttributeNames={"#score": "score"},
            ExpressionAttributeValues={
                ":mission_set": {mission},
                ":mission": mission,
                ":points": outcome["points"],
                ":name": normalise_name(display_name),
                ":now": now,
                ":expires": now + RETENTION_SECONDS,
            },
        )
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code != "ConditionalCheckFailedException":
            raise


def get_leaderboard() -> list[dict[str, Any]]:
    table = _table()
    items: list[dict[str, Any]] = []
    scan_arguments: dict[str, Any] = {
        "ProjectionExpression": ("display_name, #score, completed_missions, updated_at"),
        "ExpressionAttributeNames": {"#score": "score"},
    }

    for _ in range(5):
        response = table.scan(**scan_arguments)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_arguments["ExclusiveStartKey"] = last_key

    ranked = sorted(
        items,
        key=lambda item: (
            -_current_score(item),
            -len(_current_completed(item)),
            int(item.get("updated_at", 0)),
            item.get("display_name", "").lower(),
        ),
    )[:MAX_LEADERBOARD_PLAYERS]

    return [
        {
            "rank": index,
            "name": item.get("display_name", "Anonymous"),
            "score": _current_score(item),
            "completed": len(_current_completed(item)),
        }
        for index, item in enumerate(ranked, start=1)
    ]
