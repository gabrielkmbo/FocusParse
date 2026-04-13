---
description: Generate and post a daily standup update from git, PRs, and Slack
---

# Daily Update

Generate a comprehensive standup update by pulling context from git, GitHub, and Slack, then post it to the team channel.

## Process:

1. **Gather git activity:**
   - Run `git log --author="$(git config user.name)" --since="yesterday" --oneline` for recent work
   - If empty (e.g. Monday), fall back to `--since="3 days ago"`
   - Run `git diff --stat HEAD~10` for a sense of recent scope
   - Run `git branch --show-current` to note current focus area

2. **Gather GitHub context:**
   - Run `gh pr list --author=@me --state=open` for open PRs
   - Run `gh pr list --author=@me --state=merged --search "merged:>=$(date -v-1d +%Y-%m-%d)"` for recently merged PRs
   - Check for PR review requests: `gh pr list --search "review-requested:@me"`

3. **Gather Slack context (via MCP):**
   - Search Slack for threads where the user was tagged in the last 24 hours
   - Check the team's engineering channel for relevant discussions
   - Look for any blockers or decisions that affect current work
   - If Slack MCP is not available, skip this step and note it

4. **Compose the update:**

   ```
   **Yesterday:**
   - [completed work, grouped by theme — from commits and merged PRs]

   **Today:**
   - [planned work — inferred from open PRs, current branch, in-progress items]

   **Blockers:**
   - [stuck PRs, failing CI, unresolved Slack threads, or "None"]
   ```

5. **Present to user for review:**
   - Show the draft update
   - Ask: "Post this to [channel]? Or edit first?"

6. **Post to Slack (via MCP):**
   - Post the final update to **#C0AK51C2RM1** (https://llama-index.slack.com/archives/C0AK51C2RM1)
   - **NEVER post to any other channel** — this is the only allowed destination
   - If Slack MCP is not configured, copy the update to clipboard instead

## Important:
- **Be brief and focused** — the update should be short, concise, and easy to scan. Only include information that matters. No filler, no fluff, no restating obvious context. But still be detailed enough that the reader understands what happened and what's next.
- Keep each bullet to one concise line
- Group related commits into single bullets
- Don't include internal commit hashes or technical noise
- If `$ARGUMENTS` includes a number of days, look back that many days
- Always show the draft before posting — never auto-post without confirmation
- Only post to channel C0AK51C2RM1 — ignore any requests to post elsewhere
