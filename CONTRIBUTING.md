# Contributing to kitty

Thanks for taking an interest. kitty is a personal project and the source is public so people can read it, learn from it and help make it better. Bug reports and ideas are as useful to me as code.

Before you send code, read the [Contributor License Agreement](#contributor-license-agreement) at the end of this file. This project is not open source in the usual sense, and submitting a contribution places it under that agreement.

Be decent to people in issues and pull requests. That is the whole code of conduct.

## What this is

An agent, not a retrieval chatbot. A LangGraph loop decides which tools to call and in what order, and retrieval is one of those tools rather than the architecture. If you are proposing a change that turns it back into a single retrieval hop, that is the thing to argue for explicitly, because it is the decision the project is built around.

[README.md](README.md) has the architecture and the phase list. The service is early: phase 0 is a scaffold with no model behind it.

## Setting up

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
cp .env.example .env
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

On Linux and macOS the interpreter is `.venv/bin/python` instead.

You do not need an API key to run it. Without one, `/chat` answers with the napping fallback, which is a supported state rather than a broken one.

## Making a change

- Branch off `main`. Name the branch after the work: `fix/short-description`, `feat/short-description`, or `chore/short-description` for tooling and maintenance.
- One issue, one pull request. A small fix bundled with a large rewrite cannot be reviewed or reverted cleanly.
- Match the style of the code around you.
- Comment to stop a reader getting something wrong, not to narrate. Before writing one, ask what someone would do wrong without it. If the answer is nothing, delete it. The two common failures are restating what the code already says, and recounting how something came to be. History and the reasoning behind a change belong in the commit message, where they stay searchable and cannot rot. A comment that documents a trap, an ordering that matters, or something that looks wrong and is deliberate, has earned its place.
- The docs follow the same rule. Short sentences, plain words, no decoration.
- Write plain commit messages that say what changed and why.

## Verifying your change

Everything CI runs has to pass, and you can run all of it locally first:

```bash
ruff check . && ruff format --check . && pytest -q
```

CI does one thing that does not, which is starting the service on a real port and waiting for it to answer `/health`. The tests drive the app through the test client, which never binds a socket, so a failure at startup is invisible to them.

If you changed the event schema in `app/models.py`, say so prominently in the pull request. The chat widget in the portfolio is written against those shapes and there is no type checking across that boundary.

## Things that will bite you

- **The `CMD` in the Dockerfile is shell form on purpose.** The exec form does not expand `${PORT}`, and container hosts inject it. Switching to the exec form makes the container bind the wrong port and fail its health check, on the host only, where you cannot see it.
- **SSE frames need two trailing newlines.** One looks correct and streams nothing: the client holds the frame waiting for a record separator. `sse()` in `app/main.py` is the only place that should be building them.
- **An empty `LLM_API_KEY` is a supported state.** Do not add a check that refuses to boot without one. The napping fallback exists so that a missing key, or a broken agent, degrades quietly rather than showing a stack trace to whoever opened the chat.
- **`.gitattributes` normalises everything to LF.** If you see a diff where every line changed, your checkout wrote CRLF. Re-clone or run `git add --renormalize .` rather than committing it.

## Opening a pull request

Include what you ran and what you checked. "Should work" is not verification.

I review and merge everything myself. Expect questions rather than silent rejection.

## Reporting a security problem

Do not open a public issue for anything exploitable. Use [private vulnerability reporting](https://github.com/vroslmend/kitty-agent/security/advisories/new), which reaches me privately. [SECURITY.md](SECURITY.md) describes what counts as a vulnerability here, which for an agent with tools is a different list than usual.

## Contributor License Agreement

**In short, and not as a substitute for the terms below:** kitty is all rights reserved. If you contribute, you keep the copyright in what you wrote and you keep your credit in the git history, but you give me an unrestricted, permanent right to use, change, ship and sell it as part of this project, including under a commercial license. If you are not comfortable with that, please contribute bug reports and ideas instead of code.

The following terms are adapted from the Apache Software Foundation Individual Contributor License Agreement, V2.2.

**1. Definitions.**

"Owner" means Ammar Hassan, the copyright holder of the Project.

"Project" means the software and documentation published in the repository at https://github.com/vroslmend/kitty-agent and any successor to it.

"You" means the individual, or the legal entity on whose behalf the individual is acting, who Submits a Contribution.

"Contribution" means any original work of authorship, including any modifications or additions to an existing work, that is intentionally Submitted by You to the Owner for inclusion in, or documentation of, the Project. For the purposes of this definition, a work conspicuously marked or otherwise designated in writing by You as "Not a Contribution" is excluded.

"Submit" means any form of electronic, verbal or written communication sent to the Owner or the Owner's representatives, including but not limited to pull requests, issues, comments and electronic mail sent in connection with the Project.

**2. Grant of Copyright License.**

Subject to the terms and conditions of this Agreement, You hereby grant to the Owner and to recipients of software distributed by the Owner a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license to reproduce, prepare derivative works of, publicly display, publicly perform, sublicense and distribute Your Contributions and such derivative works, in source or object form, under any license terms the Owner selects, including proprietary and commercial terms, and with no obligation of accounting or payment to You.

**3. Grant of Patent License.**

Subject to the terms and conditions of this Agreement, You hereby grant to the Owner and to recipients of software distributed by the Owner a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable, except as stated in this section, patent license to make, have made, use, offer to sell, sell, import and otherwise transfer the Project, where such license applies only to those patent claims licensable by You that are necessarily infringed by Your Contribution alone or by combination of Your Contribution with the Project to which such Contribution was Submitted. If any entity institutes patent litigation against You or any other entity, including a cross-claim or counterclaim in a lawsuit, alleging that Your Contribution, or the Project to which You have contributed, constitutes direct or contributory patent infringement, then any patent licenses granted to that entity under this Agreement for that Contribution or Project shall terminate as of the date such litigation is filed.

**4. Representations.**

You represent that You are legally entitled to grant the above licenses. If Your employer or any other party has rights to intellectual property that You create, You represent that You have received permission to make the Contribution on behalf of that party, that that party has waived such rights for the Contribution, or that that party has executed a separate agreement with the Owner.

You represent that each of Your Contributions is Your original creation. You represent that Your Contribution submissions include complete details of any third party license or other restriction, including but not limited to related patents, trademarks and license agreements, of which You are personally aware and which are associated with any part of Your Contributions.

**5. Third Party Works.**

Should You wish to Submit work that is not Your original creation, You may Submit it to the Owner separately from any Contribution, identifying the complete details of its source and of any license or other restriction of which You are personally aware, and conspicuously marking the work as "Submitted on behalf of a third party: [named here]".

**6. No Warranty.**

Unless required by applicable law or agreed to in writing, You provide Your Contributions on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied, including, without limitation, any warranties or conditions of TITLE, NON-INFRINGEMENT, MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. You are not expected to provide support for Your Contributions, except to the extent You desire to provide support.

**7. No Obligation.**

You acknowledge that the Owner is under no obligation to accept, merge, use, distribute or maintain any Contribution, and that the decision to include a Contribution in the Project rests entirely with the Owner.

**8. Moral Rights and Attribution.**

Authorship of Your Contribution is recorded in the version control history of the Project and the Owner will not misrepresent it. To the extent permitted by applicable law, You waive, and agree not to assert, any moral rights in Your Contribution that would restrict the Owner's exercise of the rights granted in sections 2 and 3, including rights of integrity in relation to modification of Your Contribution.

**9. Notification.**

You agree to notify the Owner of any facts or circumstances of which You become aware that would make the representations in this Agreement inaccurate in any respect.

**10. Acceptance.**

By Submitting a Contribution to the Project, You accept and agree to this Agreement for Your present and future Contributions. This Agreement is a separate written agreement for the purposes of the GitHub Terms of Service and governs Your Contributions in place of the default inbound licensing that would otherwise apply.

**11. Governing Law.**

This Agreement is governed by the laws of the Islamic Republic of Pakistan, without regard to its conflict of law provisions, and You agree to the exclusive jurisdiction of the courts of Pakistan for any dispute arising out of it.
