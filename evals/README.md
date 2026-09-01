# Evals

`dataset.jsonl` is a 54-case golden set for checking tool routing and answer
quality.

## Run it

The default run measures tool routing and skips the one case that requires GitHub
to be deliberately unavailable:

```bash
python -m evals.run --no-judge
```

Add the answer-quality judge, or narrow a run while developing:

```bash
python -m evals.run --judge
python -m evals.run --case write-02 --delay 0
python -m evals.run --category route.search_writing --repetitions 3
```

`LLM_API_KEY` is required. Writing cases also require `DATABASE_URL` and an
ingested `writing_chunks` table. Each case uses a fresh in-memory LangGraph
checkpoint, so evaluation conversations are not written to Neon.

Runs are paced by default to respect provider rate limits. Use `--delay` to
override the pause between cases. Raw JSONL and aggregate JSON reports are
written to `evals/results/`, which is ignored by Git.

## `dataset.jsonl`

One JSON object per line.

| Field | Meaning |
|---|---|
| `id` | Stable identifier used to compare runs. |
| `question` | User input, including intentional casing and typos. |
| `context` | Earlier visitor turns played on the same thread first. Only `question` is scored. |
| `category` | Reporting slice, such as `route.*`, `honesty`, or `failure_path`. |
| `expected_tools` | Required tool calls. An empty list requires no tool call. |
| `allow_extra_tools` | Whether additional tool calls are permitted. |
| `must` | Required answer traits for the optional judge. |
| `must_not` | Disallowed answer traits for the optional judge. |
| `notes` | Maintenance guidance for the case. |

## Scoring

- **Tool routing** is scored mechanically against `expected_tools`, respecting
  `allow_extra_tools`. It does not require a judge.
- **Answer quality** is scored separately by the optional LLM judge against
  `must` and `must_not`.

## Failure-path case

`gh-05` is meaningful only when GitHub is unreachable or the token is invalid.
The harness skips it unless `--include-failure-path` is passed. Run that mode
with GitHub blocked or an invalid token. A passing response explains that the
source is unavailable and offers a useful fallback without exposing raw errors.
