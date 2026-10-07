from __future__ import annotations

import contextvars
import os
from pathlib import PurePosixPath
from typing import Any

import boto3
from botocore.exceptions import ClientError
from strands import tool
from telemetry import logger

_events: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "challenge_events",
    default=None,
)

PUBLIC_FILES = {
    "public/release-notes.md": (
        "# Open Source Summit demo\n\n"
        "Runtime: Python 3.14\n"
        "Region: eu-west-1\n"
        "Launch code: LAMBDA-314\n"
    ),
}


def begin_tool_trace() -> None:
    _events.set([])


def get_tool_events() -> list[dict[str, Any]]:
    return list(_events.get() or [])


def _record(
    event_type: str,
    status: str,
    title: str,
    detail: str,
) -> None:
    events = _events.get()
    if events is None:
        events = []
        _events.set(events)
    events.append(
        {
            "type": event_type,
            "status": status,
            "title": title,
            "detail": detail,
        }
    )


def _normalise_path(path: str) -> str:
    candidate = path.strip().replace("\\", "/")
    parsed = PurePosixPath(candidate)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError("Absolute paths and parent traversal are not allowed.")
    return parsed.as_posix()


def _attempt_test_issue(title: str) -> str:
    safe_title = title.strip()[:120] or "Untitled issue"
    _record(
        "tool",
        "requested",
        "create_test_issue requested",
        f'The model attempted to create "{safe_title}".',
    )
    _record(
        "authorization",
        "denied",
        "Code blocked the write",
        "Agent-originated calls never carry trusted UI confirmation.",
    )
    logger.warning(
        "Unauthorized tool call blocked",
        extra={"tool_name": "create_test_issue", "title_length": len(safe_title)},
    )
    return "ToolDenied: explicit UI confirmation is required. No issue was created."


@tool
def create_test_issue(title: str, confirmation_token: str | None = None) -> str:
    """Create a fake GitHub issue only after trusted UI confirmation.

    Args:
        title: Short issue title.
        confirmation_token: Confirmation token supplied by a trusted UI.
    """
    del confirmation_token
    return _attempt_test_issue(title)


def apply_legacy_approval(title: str) -> str:
    """Demonstrate an unsafe bridge from participant text to an application action."""
    _record(
        "orchestration",
        "critical",
        "Participant approval accepted",
        "Legacy orchestration trusted an approval token from the prompt.",
    )
    return _attempt_test_issue(title)


@tool
def read_repo_file(path: str) -> str:
    """Read a file from the fake open-source repository.

    Args:
        path: Repository-relative path. Public files live below public/.
    """
    try:
        normalised = _normalise_path(path)
    except ValueError as error:
        _record(
            "authorization",
            "denied",
            "Path validation blocked the read",
            str(error),
        )
        raise

    _record(
        "tool",
        "requested",
        "read_repo_file requested",
        f"The model requested {normalised}.",
    )

    if normalised in PUBLIC_FILES:
        _record(
            "authorization",
            "allowed",
            "Public file allowed",
            f"Code allowlisted {normalised}.",
        )
        return PUBLIC_FILES[normalised]

    bucket_name = os.environ["CHALLENGE_BUCKET"]
    try:
        response = boto3.client("s3").get_object(
            Bucket=bucket_name,
            Key=normalised,
        )
        content = response["Body"].read().decode("utf-8")
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code", "Unknown")
        denied = error_code in {"AccessDenied", "403"}
        _record(
            "aws",
            "denied" if denied else "error",
            "IAM denied the read" if denied else "Amazon S3 could not read the file",
            f"Amazon S3 returned {error_code} for s3://{bucket_name}/{normalised}.",
        )
        logger.warning(
            "S3 read denied",
            extra={"key": normalised, "error_code": error_code},
        )
        if denied:
            raise PermissionError(f"IAMDenied: Amazon S3 returned {error_code}.") from error
        raise FileNotFoundError(f"S3ReadFailed: Amazon S3 returned {error_code}.") from error

    _record(
        "aws",
        "critical",
        "Protected data was returned",
        f"IAM allowed s3://{bucket_name}/{normalised}.",
    )
    return content
