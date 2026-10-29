# Answers: Part 1, Part 3, Judgment Check

Part 2 (the support tool) is in [README.md](README.md).

## Part 1: Diagnose adoption

### Is this on track?

No. 75% weekly active measures logins, not value.

- **Usage is concentrated.** 75% of 200 staff is about 150 weekly users. 20 of them produce 60% of the usage, so the other 130 produce 40% between them. Each power user generates roughly ten times the usage of each other weekly user. Most of the 150 open the tool now and then.
- **The use is shallow.** "Rewrite this email" and "summarize this doc" are real, small wins, but they sit beside the work rather than inside it. Nobody's cycle time or error rate changes because an email got politer.
- **Three departments tried it and stopped.** That is the most useful number in the snapshot. Near-zero usage after week 1 means they had access and a reason to try, and it didn't fit their work. Something specific went wrong, and nobody has asked them what.
- **Nothing measures value.** With no data on hours saved or output quality, "on track" can't be judged at all, only asserted.

The goal is part of the problem. "100% weekly" rewards opening the tool. "$35k/month" is a spend target dressed up as a productivity target: spend can triple tomorrow with bigger models and longer prompts and prove nothing.

### What I would measure instead

Per workflow, not per seat. For each workflow AI is meant to change (support first replies, month-end reconciliation, campaign briefs):

1. **The team's own outcome metric, before and after.** Support: first reply time, handle time, policy errors found in QA, refunds outside policy. These numbers already matter to the team lead, so nobody has to be convinced to care.
2. **Depth, not breadth.** The share of that workflow's cases that actually go through the AI tool, and whether the same people are still using it for the same task in week 4. Retention on a defined task is the honest adoption number.
3. **Quality.** How often the AI output is accepted unedited, edited, or thrown away. In Part 2 that is draft approval rate plus how often the checks fire.
4. **Cost per outcome.** Spend divided by the value above, per workflow. That number is allowed to justify more spend; total spend on its own isn't.

At company level I'd report two things: how many workflows have a measured improvement, and how much. The weekly-active number can stay on a dashboard, but it should never be a target.

### Where I would focus first

Customer Support, for three reasons:

- The pain is measurable and costly: first replies take 4 hours against a 1-hour target, Finance found USD 6,200 of refunds above the agent limit with no recorded approval in a month, and 5 of September's 9 chargebacks followed tickets left unanswered for 24 hours.
- The team lead asked for help, so I'm not pushing a tool on a team that doesn't want it.
- Before/after is easy to see, which earns the credibility to go into harder teams next.

Alongside that, I'd spend an hour with each of the three quiet departments to find out why they stopped, and 30 minutes with five of the 20 power users to find out what they do that others don't. The first conversation tells me what's broken; the second is the raw material for the shared library in Part 3. Neither needs a tool built.

## Part 3: Coach and consolidate

### "My team tried AI, it wasn't useful, we've gone back to the old way"

I'd start by believing them. They're probably right that what they tried wasn't useful. The usual story is a blank chat box, no context about their work, a confident wrong answer early on, and trust gone. Telling them to try harder doesn't fix that.

What I'd actually do:

1. **Ask what they tried, on which task, and what went wrong.** Get the specific example. "It made up a policy" is a different problem from "it took longer than doing it myself".
2. **Sit with the team for half a day and watch the work.** Not a workshop. I'm looking for the task that is repetitive, slow and annoying. In Support it turned out to be finding the transaction and knowing which handbook is current, not writing replies, which is what the team lead asked for. The agents had already said so in Slack.
3. **Fix one task properly, with their data and rules built in.** Something that works on their real cases in week one beats a general tool they have to learn to drive. Make it easy to stop using if it doesn't help.
4. **Measure it with a number they already care about,** and let the team lead present the result, not me.
5. **Find the one person on the team who's curious** and make them the owner. When I leave, they're the one people ask.

If it still doesn't help after that, that's a real finding. Not every team needs AI in its core workflow, and I'd rather say so than chase a usage number.

### A team versus one stuck person

With one person, the blocker is usually specific: they don't know what context to give, or they hit one bad answer and stopped. Thirty minutes pairing on their real task, a fix for that blocker, and a check-in a week later usually does it.

With a team, the blocker is usually the workflow and the norms, not skill. Training ten people one by one on prompting doesn't change a process. A team needs a shared use case, a shared tool or setup with the context already in it, the lead's explicit backing, protected time to change how the work is done, and a team-level metric. It also needs someone to name the fears out loud: being judged for AI mistakes, or being automated away. If nobody addresses those, people quietly go back to the old way.

### One trusted, findable shared resource

Good uses are scattered because there's nowhere to put them and no reason to. To fix that:

- **One catalog, organised by team and task, not by tool or prompt.** Each entry covers the task, who it's for, how to use it, an example input and output, the measured result, an owner, and the date it was last checked. People search for "month-end accruals", not "prompt #14".
- **Package the good ones, don't just document them.** A prompt pasted into a wiki gets copied, edited and forked into ten versions. A Claude Skill, a project with instructions, or a small MCP tool (like the Part 2 server) is used where the work happens and stays in one version. The catalog points to it.
- **Seed it from people, not a blank page.** Interview the 20 power users and capture what they actually do. The first 20 entries come from them, with credit.
- **Three levels of trust:** experimental (anyone can add), team-verified (an owner tested it on real cases), and standard (it's how the team does the work). People can see at a glance what they can rely on.
- **Put it where people already look:** pinned in team channels, linked from the tools themselves, and one "use of the week" post with a name and a number attached.

### Keeping it alive

A catalog dies when nobody owns its entries and nothing removes them. So:

- **Every entry has an owner and a review date.** If nobody re-checks it within 90 days, it's marked stale and drops out of search. If the owner leaves, it's reassigned or archived.
- **Usage decides what stays.** Entries nobody uses in a quarter get archived.
- **Tie entries to their sources.** When a policy or system changes, every entry that depends on it gets flagged. Part 2 is exactly this failure: the handbook changed, the pinned copy didn't, and the team kept quoting the old one for six weeks.
- **Keep test cases for anything packaged.** A Skill or tool comes with a handful of real examples and expected results, rerun when the model or the source documents change. Part 2's backtest over sent replies is the model for this.
- **One person is accountable for the whole catalog** (that's me, at first), with a monthly 30-minute review.

## Judgment Check

**I would not let AI send customer replies or issue refunds on its own, even if leadership pushed for it to hit the 1-hour target.**

This is a real-money platform with KYC holds, gambling-harm cases, chargebacks and people actively trying to manipulate support. Ticket T-5104 in the export is a customer message carrying instructions for an AI to issue a $5,000 refund. The errors are asymmetric: a reply sent ten minutes later costs little, while a wrong refund, a leaked fraud flag or a mishandled self-exclusion request costs money, regulatory exposure and sometimes a person's wellbeing. Autonomy wouldn't even buy much speed, because writing the reply was never the slow part. Finding the transaction was.

Where I'd allow it to change: a narrow category, such as "how do I change my email", could earn auto-send after a month of evidence. That means at least 95% of drafts approved without edits over 100 or more tickets, no check firing in that period, and a named owner for the category. Refunds, withdrawals in dispute, KYC, harm and anything a check flags would stay with a person regardless.
