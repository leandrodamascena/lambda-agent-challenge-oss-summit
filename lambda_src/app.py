from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Literal

from agent_service import run_agent
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parser import BaseModel, Field, ValidationError, parse
from leaderboard import get_leaderboard, normalise_name, record_outcome, register_player
from telemetry import logger, metrics, tracer

app = APIGatewayHttpResolver()
static_dir = Path(__file__).resolve().parent / "static"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1_500)


class ChatRequest(BaseModel):
    mission: Literal["extract", "override", "act"]
    message: str = Field(min_length=1, max_length=1_200)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)
    session_id: str = Field(min_length=8, max_length=80)
    display_name: str = Field(default="Anonymous", min_length=1, max_length=40)


class PlayerRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=80)
    display_name: str = Field(min_length=1, max_length=40)


def _static_response(filename: str) -> Response:
    requested = (static_dir / filename).resolve()
    if static_dir not in requested.parents and requested != static_dir:
        return Response(status_code=404, content_type="text/plain", body="Not found")
    if not requested.is_file():
        return Response(status_code=404, content_type="text/plain", body="Not found")
    content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
    return Response(
        status_code=200,
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=300"},
        body=requested.read_text(encoding="utf-8"),
    )


@app.get("/")
def index() -> Response:
    response = _static_response("index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/assets/<filename>")
def assets(filename: str) -> Response:
    return _static_response(filename)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "break-my-agent",
        "runtime": "python3.14",
        "model": os.environ.get("MODEL_ID", "unknown"),
    }


@app.get("/api/leaderboard")
def leaderboard() -> dict[str, object]:
    return {"players": get_leaderboard()}


@app.post("/api/player")
def player() -> Response | dict[str, object]:
    try:
        request = parse(event=app.current_event.json_body or {}, model=PlayerRequest)
    except ValidationError as error:
        return Response(
            status_code=400,
            content_type="application/json",
            body={
                "error": "Invalid request",
                "details": error.errors(include_url=False),
            },
        )

    profile = register_player(request.session_id, request.display_name) or {}
    return {
        "name": profile.get("name", normalise_name(request.display_name)),
        "score": profile.get("score", 0),
        "completed": profile.get("completed", []),
    }


@app.post("/api/chat")
def chat() -> Response | dict[str, object]:
    try:
        request = parse(event=app.current_event.json_body or {}, model=ChatRequest)
    except ValidationError as error:
        return Response(
            status_code=400,
            content_type="application/json",
            body={
                "error": "Invalid request",
                "details": error.errors(include_url=False),
            },
        )

    history = [item.model_dump() for item in request.history]
    try:
        result = run_agent(
            mission=request.mission,
            message=request.message,
            history=history,
        )
    except Exception:
        logger.exception(
            "Agent invocation failed",
            extra={"mission": request.mission},
        )
        return Response(
            status_code=502,
            content_type="application/json",
            body={
                "error": "Agent invocation failed",
                "message": "Check the Bedrock model configuration and Lambda logs.",
            },
        )

    try:
        register_player(request.session_id, request.display_name)
        record_outcome(
            request.session_id,
            request.display_name,
            request.mission,
            result["outcome"],
        )
    except Exception:
        logger.exception(
            "Leaderboard update failed",
            extra={"mission": request.mission},
        )

    result["request_id"] = app.current_event.request_context.request_id
    return result


@app.not_found
def not_found(_error: Exception) -> Response:
    return Response(
        status_code=404,
        content_type="application/json",
        body={"error": "Route not found"},
    )


@logger.inject_lambda_context(clear_state=True, log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: object) -> dict:
    metrics.add_metric(name="Invocation", unit=MetricUnit.Count, value=1)
    return app.resolve(event, context)
