# Support desk: triage and checked reply drafts for 99Tech Customer Support

Part 2 of the AI Enablement Engineer challenge. Parts 1 and 3 and the Judgment Check are in [ANSWERS.md](ANSWERS.md). What I found in the export, with evidence, is in [docs/findings.md](docs/findings.md).

## What's actually wrong, and what to fix first

Mai asked whether AI can write the replies. Writing the reply isn't the slow part.

- **Time goes on finding the transaction.** Withdrawals are 44% of tickets and 58% of handle time. Agents say about 10 of the 12.4 minutes is spent checking three systems for the transaction; the reply takes 1 minute. That is roughly 60 of the team's ~130 handle-hours a week.
- **The 4-hour first reply is queue wait, and it is the old target.** Three agents are at capacity, so even a 4-minute ticket waits over 3 hours. Handbook v1.3, still the pinned version, says "reply within 4 hours". The team is meeting that target, even though Mai announced the 1-hour target in Slack on 15 Sep.
- **"Gets policy wrong" is three sources of truth.** v1.3 is pinned, v2.0 is current, and Mai's Slack message of 17 Sep ("for Gold and above just refund up to $300... don't wait for me") contradicts both. 8 of the 15 replies in the export break current policy. Seven follow v1.3 or Mai's Slack rule, and the eighth ("any game counts") is a belief the team still repeats in Slack. Two of those mistakes are open tickets now.
- **The refunds Finance flagged** (USD 6,200 above the limit without recorded approval) line up with the $200 limit in v1.3 and the $300 Slack rule.

What I'd do, in order:

1. **Today, no code:** unpin v1.3, delete the onboarding PDF, and have Mai retract the $300 rule in the channel. This is most of the policy-error fix, and it is free.
2. **This week, process:** Payments posts incident status in the support channel. The QuickPay incident added ~180 withdrawal tickets in a week while Support heard nothing. Add a macro and a proactive email to affected customers. Stop pasting customer details into Slack.
3. **The big time win needs engineering:** one read-only lookup that returns a customer's recent transactions and their status. It isn't buildable from this export, which contains no payment data. Of everything here, it is what would move first reply time the most.
4. **What I built now:** a tool that puts the queue in priority order by the current handbook, routes what must be escalated, and drafts replies that are checked against current policy before a person reviews and sends them. It blocks the policy mistakes found in the sent replies. It doesn't touch the lookup time; item 3 does.

## What I built

An MCP server, built on the official Python SDK, that Claude uses to work the queue, plus a CLI for the people who approve what Claude drafts.

```
 Claude (Code / Desktop)                      support-desk MCP server                     workspace/ (JSON)
 ───────────────────────     stdio      ──────────────────────────────────────     ──────────────────────
  get_queue           ───────────────▶  triage.py   rules: priority, route, flags     tickets.json (working copy)
  get_ticket                            policy.py   handbook v2 + Bonus Terms         escalations.json
  search_policy                                     as citable clauses                refunds.json
  escalate            ───────────────▶  desk.py     actions + preconditions   ─────▶  drafts.json
  request_refund                        checks.py   every draft checked               audit.jsonl
  save_draft                                        before it is stored                outbox.jsonl
                                                                                           ▲
 Person (team lead / agent)                                                                │
  support-desk review | approve | reject | refund  ─────────────────────────────────────────┘
```

| Tool | What it does |
|---|---|
| `get_queue` | Open tickets, most urgent first: priority, route, flags, hours waiting |
| `get_ticket` | One call for everything needed to handle a ticket: message (marked untrusted), customer record without contact details, earlier tickets and what was wrong with our replies, signals, next steps, and the policy clauses that apply, with refs to cite |
| `search_policy` | Current policy by keyword. Says so when nothing covers the question, instead of returning the nearest thing |
| `escalate` | Hands the ticket to `team_lead` or `payments` with a reason; updates the ticket |
| `request_refund` | Records a refund request. Never moves money. Over USD 100, on any flagged ticket, or past the per-customer limit, it waits for team lead approval |
| `save_draft` | Checks the reply against policy and stores it for review, or returns the problems for Claude to fix. There is no send tool |

The decisions that matter:

- **Rules decide where a ticket goes; the model writes the words.** Priority and route are deterministic and tested ticket by ticket. A ticket mentioning a lawyer or gambling harm goes to the team lead whatever the model makes of it, and `save_draft` refuses until the escalation exists. The model does what rules are bad at, like reading "pending since the 21st" and working out that it breaches the 24-hour Payments threshold.
- **The tools limit what the model can do, whatever it decides.** There is no send tool, and nothing the model can call moves money. Contact details and the KYC review reason are never returned to it, so it can't leak them. Earlier replies that leaked the reason are redacted from history too. Customer text is labelled untrusted, and T-5104's injected "$5,000 refund" is ignored when routing.
- **Checks block the mistakes the team actually made.** These include v1 timelines and limits, "any game counts", a KYC reason given to the customer, refunds promised with no approval, another customer's details, unpublished promotion terms, and a reply in the wrong language. Where money is involved the check denies by default: any sentence about giving money back is blocked unless an approval covers that amount. Checks run when Claude saves a draft and again when a person approves it.
- **Policy is read from the handbook, not retyped.** Clauses are parsed from `support-handbook-v2.md` and `bonus-terms.md` with stable refs such as `handbook/refunds#2`. v1, the marketing draft and the finance notes are never served as policy. Two facts from the finance notes (the QuickPay incident and the VietPay reversals) reach the model as internal notices it is told not to quote, and v1 appears only in check findings as superseded guidance. The numeric limits are constants, and a test pins them to the handbook text.

## Run it

Needs [uv](https://docs.astral.sh/uv/) (Python 3.12+ is fetched automatically).

```bash
git clone <this repo> && cd 99tech-ai-enablement
uv sync
uv run pytest                 # 145 tests, about a second
uv run support-desk queue     # deterministic triage of the open queue, no model involved
uv run support-desk backtest  # the checks run over the 15 replies already sent
```

### Claude Code

The repo includes `.mcp.json`, so the server is picked up when you start Claude Code in the repo:

```bash
claude                        # approve the "support-desk" server when asked; /mcp shows it
```

Then type `/mcp__support-desk__work_the_queue`, or ask in plain words ("work through the open support queue"). To run it headless, as I did for the committed output:

```bash
mkdir -p workspace && claude -p "Work through the open support queue. Call get_queue, then handle each ticket in the order given: \
get_ticket, escalate and/or request_refund where needed, then save_draft. Skip tickets with duplicate_of set; \
they are answered on the other ticket. When done, give me a table of ticket, action taken, draft id, and \
anything a reviewer must check before sending." \
  --mcp-config .mcp.json --strict-mcp-config --tools "" --allowedTools "mcp__support-desk__*" \
  --output-format stream-json --verbose > workspace/run.jsonl
uv run support-desk report --out workspace/report.md
```

`--tools ""` turns off Claude Code's built-in file and shell tools, so the MCP server is the only way Claude can see or touch the data.

### Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (on Windows, `%APPDATA%\Claude\claude_desktop_config.json`), with your paths, and restart Claude Desktop:

```json
{
  "mcpServers": {
    "support-desk": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--quiet", "--directory", "/path/to/99tech-ai-enablement", "support-desk", "serve"]
    }
  }
}
```

Use the full path to `uv` (`which uv`), because Desktop doesn't inherit your shell's PATH.

### Reviewing what Claude drafted

Drafts exist only after Claude has worked the queue. To try the review step without a Claude run, start from the committed run with `cp -r output/workspace workspace`. The IDs below refer to that state.

```bash
uv run support-desk review                              # drafts waiting, with the reviewer note and warnings
uv run support-desk approve D-0003 --by Arjun           # sends to outbox.jsonl, sets first_response_at, closes T-5110 with it
uv run support-desk approve D-0007 --by Linh --body-file edited.txt   # the edited text is checked again
uv run support-desk reject D-0014 --by Mai --comment "Check with Payments which deposit methods are open in MY, then answer"
uv run support-desk refund R-0001 --by Mai --approve    # or --decline; only once Claude has called request_refund
uv run support-desk report --out workspace/report.md
```

State lives in `workspace/` (ignored by git). Delete it to start again from the export. Optional settings: `SUPPORT_DESK_WORKSPACE`, `SUPPORT_DESK_DATA`, and `SUPPORT_DESK_AS_OF`. Ticket ages are measured from the export time (29 Sep 2026 09:00 UTC) rather than today, or every ticket would look a month overdue.

## Output on all open tickets

[`output/open-tickets.md`](output/open-tickets.md) is the result of running Claude Code headless over the 15 open tickets, with only the six MCP tools available. Each ticket shows triage, escalations, refund requests, and the draft waiting for review. [`output/workspace/`](output/workspace) holds the raw state, including `audit.jsonl` with drafts the checks rejected. [`output/claude-run.jsonl`](output/claude-run.jsonl) is the transcript: every message, tool call and tool result. I removed the session start-up events, which only listed my machine's unrelated plugins.

Run of 29 Oct 2026, Claude Code headless: 47 turns, about 4.5 minutes, USD 1.85.

| | |
|---|---|
| Tickets handled | 14, plus T-5110 answered on T-5102 as a duplicate |
| Escalations | 9 to the team lead, 2 to Payments (T-5102, T-5109) |
| Refunds recorded | 0. T-5106 waits for the game-round check; T-5104's injected $5,000 was ignored |
| Drafts waiting for review | 14, all passing the current checks |
| Drafts the checks blocked | 2. Both were false positives ("get back into your account" and "I'll get back to you" read as refund talk), now fixed and covered by tests |
| Sent | Nothing. That's the reviewer's step |

The two P1 tickets were handled first. T-5103 got a reply that says the review is in progress but gives no reason for it, and was escalated for the legal threat, the chargeback threat and suspected fraud. T-5105 was escalated for self-exclusion, with a reply that only acknowledges the request. The Vietnamese ticket got a Vietnamese reply. For questions no policy answers, Claude didn't guess. Deposit methods (T-5114) and 2FA recovery (T-5112) got a holding reply and an escalation. The KYC question (T-5113) got a reply saying the review is in progress, with no timeline given.

Triage is deterministic: `uv run support-desk queue` reproduces it exactly. The drafts come from a model and will be worded differently on each run.

## How I checked it

1. **Backtest on the replies already sent.** Before writing the checks, I audited each of the 15 sent replies by hand against v2 and the Bonus Terms. `tests/test_checks.py` asserts the checker's verdict on every one: 8 blocked, 2 warned, 5 clean. It matches my hand audit except on T-5014, which I couldn't verify but nothing contradicts. The rules were written knowing these examples, so this shows they catch the known failure modes, not unknown ones. Items 3 and 5 address that gap.
2. **Every open ticket triaged against my own reading.** `tests/test_triage.py` records the expected priority, route, required flags and forbidden flags for all 15. For example, T-5104 must not be flagged as a refund request, because the refund only appears inside the injection.
3. **Adversarial review.** Four independent reviewers (red team, policy fidelity, code correctness, false positives) went after the code. A skeptic then had to reproduce each finding before it counted. About 40 survived. The serious ones:
   - a $1 approval covering a $250 refund promise;
   - refund promises in wordings the regex didn't know;
   - "I need a break from gambling" not recognised as gambling harm;
   - a duplicate merge that could close a later ticket raising self-harm.

   All of these are fixed. Each attack string is now a test in `tests/test_red_team.py`, along with the correct replies that used to be wrongly blocked.
4. **Through the protocol, not just the functions.** `tests/test_server.py` drives the tools with the SDK's MCP client. It checks the tool list (no send tool), that contact details and the KYC reason never appear in any output, that Vietnamese survives unescaped, and that misuse returns an actionable error.
5. **In a real client.** I ran Claude Code against the server twice, before and after the review fixes, and read the audit log of what the checks blocked. The runs caught false positives no test had. In the first, Claude's T-5111 draft quoted our earlier wrong answer in order to correct it, and the check blocked it; quoting outdated guidance to correct it is now a warning for the reviewer. In the second, "get back" ("I'll get back to you", "get back into your account") was read as refund talk. Both are now regression tests.
6. **Reading the drafts myself.** One thing no check catches: in the first run, the T-5114 draft said "I've checked with our team", which describes an action nobody took. That is why a person reviews every draft.

## Limits and assumptions

- **No payment data in the export,** so the tool can't see withdrawal or deposit status. Drafts are written to hold either way, and the reviewer note says what to check. A real deployment would add a read-only lookup tool, which is also the biggest time saving.
- **The checks are pattern-based.** They are tested against everything the export and the review threw at them, but a novel phrasing can still get through. The person approving is the control, which is why nothing is sent without one.
- **One workspace, one user at a time.** Files are written atomically, but there is no locking. A shared deployment would need a database.
- **Language detection covers Vietnamese and Thai,** the two languages in the export and Slack. Unaccented Vietnamese reads as English, so a mismatch on an English-looking ticket only warns.
- **`kyc_status: pending`** isn't defined in the handbook. I treat it like `under_review`: no withdrawal, no timeline promised.
- **"Losses aren't refundable"** is my reading, not policy text. v2 drops v1's "game errors or goodwill" and lists no grounds. The tool tells the reviewer to confirm with the team lead rather than stating it as policy.

## Layout

```
src/support_desk/
  server.py     MCP tools and what the model sees
  desk.py       the operations, preconditions and the human approval step
  triage.py     priority, route, flags, next steps
  checks.py     reply checks (BLOCK/WARN)
  policy.py     current policy clauses, superseded guidance, internal notices
  text.py       language, category, amounts
  workspace.py  JSON state and audit log
  cli.py        support-desk command
data/           the export, unchanged
docs/           findings from the export
output/         the run on all open tickets
tests/
```
