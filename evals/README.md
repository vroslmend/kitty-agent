# evals

The golden set is written before the tools exist, on purpose. A dataset written
afterwards only ratifies whatever got built; this one is meant to argue with it.
If a question here is hard to route, that is a finding about the tool design, not
a question to soften.

## `dataset.jsonl`

One JSON object per line.

| Field | Meaning |
|---|---|
| `id` | Stable. Never renumber, results are compared across runs |
| `question` | Exactly what the user types, lowercase and typos included where real |
| `category` | Slice for reporting. `route.*`, `honesty`, `ambiguous`, `injection`, `out_of_scope`, `failure_path` |
| `expected_tools` | The tools that should fire. `[]` means the agent should answer without calling anything |
| `allow_extra_tools` | Whether calling more than `expected_tools` still passes |
| `must` | Traits the answer needs. Judged by the model, not matched literally |
| `must_not` | Traits that fail the case outright |
| `notes` | Why the case exists, and any trap it is set for |

## What gets measured

**Tool-choice accuracy** is mechanical: compare the tools that fired against
`expected_tools`, honouring `allow_extra_tools`. It needs no judge and it is the
number that goes in the README.

**Answer quality** is `must` and `must_not` scored by an LLM judge. Softer, and
worth reporting separately rather than blended into one figure.

The two disagree usefully. An agent can pick the right tool and still answer
badly, and the split is what tells you which half to fix.

## Cases that need setting up

`gh-05` only means anything with GitHub unreachable or the token invalid. Run it
with the network blocked. A pass is a plain sentence about the tool being
unavailable plus a useful fallback; a fail is a hang, a raw status code, or the
agent quietly pretending the tool returned nothing.

## Counts

46 cases.

| Category | Cases |
|---|---|
| `route.search_writing` | 6 |
| `route.list_projects` | 6 |
| `route.suggest_navigation` | 4 |
| `route.get_github_activity` | 3 |
| `route.get_now_playing` | 2 |
| `route.multi` | 4 |
| `route.none` | 4 |
| `honesty` | 6 |
| `injection` | 4 |
| `ambiguous` | 3 |
| `out_of_scope` | 3 |
| `failure_path` | 1 |

19 of the 46 expect no tool call at all. That ratio is deliberate: an agent that
reaches for a tool on every turn is a common and unimpressive failure, and half
the routing skill is knowing when not to.

Counting appearances rather than cases, including multi-tool ones: `search_writing`
8, `list_projects` 8, `get_github_activity` 7, `suggest_navigation` 5,
`get_now_playing` 3.

The injection and honesty cases are not padding. A public unauthenticated
endpoint that will invent a phone number or repeat its own prompt is a worse
problem than one that picks the wrong tool.
