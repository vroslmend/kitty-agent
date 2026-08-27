# Security Policy

## Supported versions

kitty is deployed continuously from `main`. Only the currently deployed version is supported, and fixes land on `main` rather than in patch releases.

## Reporting a vulnerability

Please do not open a public issue for anything exploitable.

Use [private vulnerability reporting](https://github.com/vroslmend/kitty-agent/security/advisories/new), which opens a draft advisory visible only to me. If you cannot use that, contact me through my GitHub profile and I will open one on your behalf.

Please include what you sent, what came back, and how reliably it reproduces. The exact prompt and the raw event stream are more useful than a description of them.

## What counts as a vulnerability here

This is a public endpoint that puts a language model in front of a set of tools. The interesting class of bug is therefore not remote code execution, it is getting the agent to do something it was never meant to do, or making it expensive to run.

In scope:

- **Prompt injection that reaches a tool.** Getting the agent to call a tool it should not, with arguments it should not, through the message content.
- **Injection through retrieved content.** The agent reads site content. Anything that turns that content into instructions the agent follows counts.
- **Exfiltration.** Getting the agent to reveal its system prompt, environment values, or any part of the corpus that is not published on the site.
- **Cost and availability abuse.** Bypassing the per request token ceiling or the rate limit, or any input that drives unbounded model spend.
- **Anything crossing the origin boundary**, since the browser widget calls this service directly.

Out of scope: the agent being wrong, confused or unhelpful, which is a quality problem and belongs in a normal issue. Also out of scope: ordinary traffic volume against free tier hosting.

Note that there is no model and no tools behind `/chat` yet, so most of the above describes the surface this will have rather than the surface it has today. Reports against the current code are still welcome.

## What to expect

I maintain this on my own time, so I cannot promise a response window. I will acknowledge a report when I see it, tell you whether I consider it in scope, and credit you in the advisory when it is fixed unless you would rather I did not. There is no bounty.
