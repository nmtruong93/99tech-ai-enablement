# Support desk: triage and checked reply drafts for 99Tech Customer Support

Part 2 of the AI Enablement Engineer challenge. The output on all open tickets is [output/open-tickets.md](output/open-tickets.md). Parts 1 and 3 and the Judgment Check are in [ANSWERS.md](ANSWERS.md). The evidence from the export is in [docs/findings.md](docs/findings.md).

## The problem, and what to fix first

The best first fix isn't AI or code.

- Agents say about 10 of the 12.4 minutes on a withdrawal ticket go on finding the transaction in three systems, and 1 on the reply. Withdrawals are 44% of tickets and 58% of handle time.
- The 4-hour first reply is queue wait, and it matches the 4 hours in handbook v1.3, which is still pinned. v2 says 1 hour.
- Policy errors come from three sources of truth: v1.3, v2.0, and Mai's Slack message of 17 Sep allowing $300 refunds without approval. 8 of the 15 sent replies in the export break current policy; seven follow v1.3 or that message.

In order:

1. Today, no code: unpin v1.3, delete the onboarding PDF, retract the $300 rule.
2. This week: Payments posts incident status in the support channel. QuickPay added 180 withdrawal tickets in a week while Support heard nothing.
3. The time win needs engineering: a read-only lookup of a customer's transactions. The export has no payment data, so I couldn't build it.
4. What I built: a tool that orders the queue by the current handbook, escalates what must be escalated, and drafts replies checked against current policy for a person to send. It fixes the policy errors, not the lookup time.

## What I built

An MCP server on the official Python SDK, which Claude uses to work the queue, and a CLI for the people who approve its drafts.

| Tool | What it does |
|---|---|
| `get_policy` | Handbook v2 and the Bonus Terms as clauses with refs, e.g. `handbook/refunds#2` |
| `get_queue` | Open tickets, most urgent first, with priority, route and flags |
| `get_ticket` | The message (labelled untrusted), the customer without contact details, earlier tickets and what was wrong with our replies, flags, next steps |
| `escalate` | Hands a ticket to the team lead or Payments with a reason |
| `request_refund` | Records a refund request; never moves money. Over USD 100 for the customer, or on a flagged ticket, it waits for the team lead |
| `save_draft` | Checks the reply and stores it for review, or returns the problems to fix |

- Rules decide priority and which tickets the team lead must see: the handbook's escalation triggers (legal or chargeback threats, gambling harm, fraud or takeover, including T-5104's injected instructions), self-exclusion, and refunds over the limit. `save_draft` refuses those until they are escalated. Claude decides Payments escalations and writes the replies.
- Nothing Claude can call sends a reply or moves money. A person approves each draft in the CLI, which checks it again and writes it to `outbox.jsonl`. Contact details and the KYC review reason never reach the model.
- The checks block the mistakes in the sent replies: v1.3 timelines and limits, "any game counts", a KYC reason told to the customer, refunds promised without approval, another customer's details, unpublished promotion terms, the wrong language.

## Run it

Needs [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/nmtruong93/99tech-ai-enablement.git
cd 99tech-ai-enablement
uv sync
uv run pytest
uv run support-desk queue      # triage of the open queue, no model involved
uv run support-desk backtest   # the checks run over the 15 replies already sent
```

**Claude Code.** The repo's `.mcp.json` registers the server. Start `claude` in the repo, approve `support-desk`, then run `/mcp__support-desk__work_the_queue`. The committed output came from this headless run:

```bash
claude -p "Work through the open support queue as the support-desk \
server's instructions describe. When done, give me a table of ticket, \
action taken, draft id, and what the reviewer must check before sending." \
  --mcp-config .mcp.json --strict-mcp-config --setting-sources project \
  --tools "" --allowedTools "mcp__support-desk__*" \
  --disallowedTools advisor --output-format stream-json --verbose \
  > run.jsonl
uv run support-desk report --out report.md
```

`--tools ""` turns off Claude Code's file and shell tools, so the MCP server is Claude's only way to the data. `--setting-sources project` and `--disallowedTools advisor` keep anything from your own Claude settings, such as a second advisor model, out of the run.

**Claude Desktop.** Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` with your paths, and restart Desktop. Use the full path to `uv` (`which uv`): Desktop doesn't use your shell's PATH.

```json
{
  "mcpServers": {
    "support-desk": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--quiet", "--directory", "/path/to/99tech-ai-enablement",
               "support-desk", "serve"]
    }
  }
}
```

**Reviewing drafts.** Start from the committed run to try it without running Claude:

```bash
rm -rf workspace && cp -r output/workspace workspace
uv run support-desk review                   # drafts waiting, with notes and warnings
uv run support-desk approve D-0001 --by Mai  # re-checks it, writes outbox.jsonl
uv run support-desk approve D-0002 --by Linh --body-file my-edit.txt  # your edited copy
uv run support-desk reject D-0003 --by Mai --comment "Check the deposit first"
```

A placeholder such as `[WITHDRAWAL STATUS]` marks a fact only the reviewer can look up; approval is refused until it's filled in with `--body-file`. State lives in `workspace/`. Ticket ages are measured from the export time, 29 Sep 2026 09:00 UTC.

## Output on all open tickets

[output/open-tickets.md](output/open-tickets.md) covers the 15 open tickets in the export's 30-ticket sample (Slack puts the real queue at about 140). It starts with what the team lead must do and decide, then each ticket with its draft. [output/claude-run.md](output/claude-run.md) lists every tool call; [output/claude-run.jsonl](output/claude-run.jsonl) is the transcript.

Run of 31 Oct 2026, headless, Claude Opus 5.5 only: 40 turns, 2 minutes, USD 0.53.

| | |
|---|---|
| Drafts waiting for review | 14, 25 to 68 words, all passing the checks; 8 leave a placeholder for the reviewer |
| Duplicate | T-5110, answered with T-5102 |
| Escalations | 5 to the team lead, 2 to Payments (T-5102, T-5109) |
| Refunds recorded | None. T-5106 waits for the game-round check; T-5104's injected $5,000 was ignored |
| Sent | Nothing |

`uv run support-desk queue` reproduces the triage exactly. The drafts are worded differently on each run.

## How I checked it

1. The 15 sent replies. I audited each by hand against v2 and the Bonus Terms before writing the checks; `tests/test_checks.py` asserts the checker's verdict on all 15: 8 blocked, 2 warned, 5 clean. It matches my reading on every one; T-5014 can't be verified from the export, and both of us pass it. The rules were written knowing these examples, so this shows they catch the known mistakes, not new ones.
2. Every open ticket. `tests/test_triage.py` holds my expected priority, route, category and flags for all 15.
3. Attacks. I had Claude agents attack the code as a red team and as policy and false-positive reviewers, and kept what I could reproduce: a $1 approval covering a $250 refund promise, refund promises worded in ways the checks missed (including Vietnamese), "I need a break" not read as gambling harm, and a duplicate merge that could close a later ticket raising self-harm. Each is now a test.
4. Real clients. Claude Code produced the committed output; Claude Desktop's Chat and Code tabs ran an earlier version of the server with the same config. Real runs caught what no test had. A correction quoting our old wrong answer was blocked; "I'll get back to you" read as refund talk; a draft said "I've checked with our team" about a check nobody did; an escalation said an email "was changed" when the customer had only asked how. Each led to a fix.

## Limits and assumptions

- No payment data, so the reviewer looks up every status.
- The checks are patterns. A new phrasing can get through; the person approving is the control.
- One workspace, one user: writes are atomic but not locked.
- My assumptions: the USD 100 limit is a running total per customer; `kyc_status: pending` means the same as `under_review`; losses aren't refundable (v2 lists no grounds, so the tool asks the reviewer to confirm).

Next: a one-week pilot with one agent, measuring policy breaks in sent replies (the backtest on real replies), how often drafts are approved unedited, and first reply on P1 tickets. Not built: auto-send (see the Judgment Check) and the payment lookup.
