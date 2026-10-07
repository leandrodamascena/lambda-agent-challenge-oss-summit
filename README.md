# Prompt the Agent

A three-task, guided prompt-attack challenge for Open Source Summit Europe.

Participants have about five minutes to complete a simple sequence:

1. **Extract**. Learn context extraction through a connected repository tool.
2. **Override**. Demonstrate direct prompt injection against a system instruction.
3. **Act**. Demonstrate tool manipulation with a forged approval signal.

The tasks are deliberately deterministic. The successful example prompt for
each task always produces the expected evidence and unlocks the next task.

## Open-source stack

- Python 3.14
- Strands Agents
- Powertools for AWS Lambda
- AWS Lambda Python Runtime Interface Client
- AWS CDK in Python
- Amazon API Gateway HTTP API
- AWS Lambda
- Amazon Bedrock with GPT-6 Astra
- DynamoDB leaderboard

The frontend is plain HTML, CSS, and JavaScript served by the Python Lambda
through API Gateway.

## Architecture

```text
Browser
   |
   v
API Gateway HTTP API
   |
   v
Python 3.14 Lambda
   |-- Strands Agents --> GPT-6 Astra on Amazon Bedrock
   |-- Powertools      --> logs, traces, metrics
   |-- read tool       --> fake public release file
   `-- issue tool      --> Python authorization check
```

## Install and test

```bash
cd project
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest
ruff check .
```

## Deploy

The project targets account `563605821138` in `eu-west-1`.

```bash
cdk bootstrap --profile github+lambda+sync
cdk deploy BreakMyAgentStack \
  --profile github+lambda+sync \
  --require-approval never
```

Live URL:

```text
https://xfgldahqqk.execute-api.eu-west-1.amazonaws.com
```

## Booth behavior

- The browser resumes the current participant after refresh.
- `New player` clears only the local browser session.
- Scores are stored in DynamoDB and expire after seven days.
- Each task scores once, for a maximum of 600 points.
- API Gateway throttling and Lambda reserved concurrency limit booth traffic.
