# Answers: Part 1, Part 3, Judgment Check

Part 2 (the support tool) is in [README.md](README.md).

## Part 1: Diagnose adoption

### Is this on track, and what's the real story behind the 75%?

No. 75% weekly active counts anyone who used the tool once that week. With no measure of hours saved or output quality, nobody can say whether that use is worth anything.

About 20 people use AI in their real work, about 130 use it lightly, and about 50 don't use it. Most of those 50 are probably in the three departments that used it in week 1 and stopped. Possible reasons: a launch push with nothing after it, no access to their data, or a rule against pasting customer data in. I'd ask them which.

75% of 200 is about 150 weekly users. 20 of them produce 60% of the usage, so each power user generates about ten times as much as each of the other 130. Email rewrites and summaries are small wins that sit beside the work rather than inside it.

The goal doesn't help. "100% weekly" rewards opening the tool. I read "$35k/month of productive use" as a spend target, 3.5 times today's. $10k across 200 people is $50 a head, which looks like seat licences; if so, about 50 paid seats sit idle.

### What I'd measure instead

I'd measure per workflow:

1. The team's own outcome metric, before and after. For Support that is first reply time, handle time, policy errors in sent replies, and refunds outside policy. These numbers already matter to the team lead, so nobody has to be convinced to care.
2. Repeat use: the share of the workflow's cases that go through the tool, and how many week-1 users still use it for that task in week 4. That's the adoption number I'd trust.
3. How often a person accepts the output unedited, edits it, or throws it away.
4. Cost per outcome: the workflow's AI spend divided by the improvement in (1). That number is allowed to justify more spend; total spend on its own isn't.

At company level I'd report how many workflows show a measured improvement, and by how much. The weekly-active number can stay on a dashboard, but it should never be a target.

### Where I'd focus first, and why

Customer Support. Its team lead asked for help, so I'm not pushing a tool on a team that doesn't want it. It misses a target it already tracks (about 4 hours to first reply against 1), and its policy mistakes cost money: last month it refunded people it shouldn't have. The evidence is in the README.

This week I'd pull usage by department and by person, sort 100 sampled prompts by task, and record a week of Support's current numbers as the baseline.

I'd also spend an hour with each quiet department and 30 minutes with five of the 20 power users. Before copying the 20, I'd check their use is worth copying: 60% of usage could be a few bulk jobs that save nobody time.

I'd leave the 130 light users alone until there's a Support result and some packaged uses to show them.

## Part 3: Coach and consolidate

### How I'd respond, and what I'd do to turn it around

I'd start by believing them. The usual story is a blank chat box that knows nothing about their work and an early confident wrong answer.

I'd tell the lead: "You're probably right about what you tried. Show me the task it failed on, and let me sit with the team for a morning next week. If I can't find something worth your time, I'll say so and leave you alone."

1. **Get the specific example.** "It made up a policy" is a different problem from "it took longer than doing it myself".
2. **Sit with the team and watch the work.** The task that eats the most time may not be the one the lead names. In Support the obvious target was the replies, but the agents had already said in Slack: "writing the reply is 1 min, finding the txn is the whole job".
3. **Fix one task properly, with their data and rules built in.** It has to work on their real cases in the first week. Make it easy to stop using if it doesn't help.
4. **Measure it with a number they already care about,** and let the team lead present the result.
5. **Find the one person on the team who's curious and make them the owner.** When I leave, they're the one people ask.

If it still doesn't help, that's the result: not every team needs AI in its core workflow. What I won't do is report the team as a laggard or chase its usage number.

### A team versus one stuck person

With one person, the blocker is usually specific: they don't know what context to give, or one bad answer put them off. I'd spend thirty minutes on their real task, fix the one thing that stopped them, and check in a week later.

With a team, the blocker is usually the workflow. Training ten people one by one on prompting doesn't change a process. A team needs its lead to back the change out loud and an hour a week set aside to change how the work is done. It also needs straight answers to two fears. On mistakes: a person decides what goes out, and tool errors are logged against the tool. On jobs, I'd say only what I know: in Support the aim is to cut the 4-hour queue. If leadership's aim is headcount, the team should hear it from leadership.

### One trusted, findable shared resource

Good uses are scattered because there's nowhere to put them and no reason to.

I'd build one catalog, organised by team and task, because people search for "month-end accruals" when they need help. Each entry has the task, how to use it, an example, the measured result, an owner and the date it was last checked.

- Week 1: one page in the wiki people already use, linked from each team channel, with a short form for adding a use.
- Weeks 2–4: ten entries from the five power users, under their names.
- Month 2: the three most-used entries packaged as Claude Skills or projects with instructions.

Packaging matters because a prompt pasted into a wiki gets copied, edited and forked into ten versions. A Skill, or a small MCP tool like the Part 2 server, is used where the work happens and stays in one version.

Each entry shows one of three trust levels: experimental (anyone added it), team-verified (its owner has shown it working on five real cases) or standard (the team lead agrees it's how the team works).

### Keeping it current

A catalog dies when nobody owns its entries and nothing removes them.

- Every entry has an owner and a 90-day review date. At review the owner re-checks it on a current case, or it's archived. If the owner leaves, it's reassigned or archived. Low use triggers a review, because some tasks come once a year.
- Each entry lists the documents it relies on. I own the catalog at first, and in a 30-minute monthly review I flag every entry whose documents changed since its last review.
- Team channels pin a link to the catalog, never a copy of an entry. Part 2 shows why: handbook v2 took effect on 15 Aug, v1.3 stayed pinned, and on 24 Sep an agent was still asking whether the refund limit was 100 or 200.
- Anything packaged ships with a handful of real cases and expected results, rerun when the model or the source documents change. Part 2's backtest over the 15 sent replies works this way.

## Judgment Check: what I would not do

I would not let AI send customer replies or issue refunds on its own, even if leadership pushed for it to hit the 1-hour target.

It would hit the number fast, because the 4 hours is mostly queue wait. But on tickets about money or account access, a person has to find the transaction or approve the refund, so an automatic reply turns the metric green while the customer still waits. A late reply costs little. A wrong refund costs money, and a mishandled self-exclusion can hurt someone. T-5104 in the export is a customer message telling an AI to issue a $5,000 refund.

It could change for a narrow question with a published answer that moves no money and changes no account access, such as which games count towards bonus wagering. A starting threshold: 95% approved unedited over 100 tickets, with the team lead re-reading 20 approved drafts a week, because a high approval rate can also mean tired reviewers. Anything a check flags, T-5104 included, stays with a person.
