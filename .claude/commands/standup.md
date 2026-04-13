---
description: Generate a daily standup update from recent git activity
---

# Daily Standup

Generate a standup update based on recent git activity in this repo.

## Process:

1. **Gather recent activity:**
   - Run `git log --author="$(git config user.name)" --since="yesterday" --oneline` for what was done
   - Run `git log --author="$(git config user.name)" --since="2 days ago" --oneline` as fallback if yesterday is empty (e.g. Monday morning)
   - Run `git diff --stat HEAD~5` for a sense of scope
   - Run `git branch --show-current` to note current branch
   - Run `git status --short` to see in-progress work

2. **Check for open PRs:**
   - Run `gh pr list --author=@me --state=open` to find PRs awaiting review

3. **Format the standup:**

   ```
   **Yesterday / Last session:**
   - [completed work, grouped by theme, derived from commits]

   **Today / Next:**
   - [inferred next steps based on in-progress work, open PRs, branch state]

   **Blockers:**
   - [any stuck PRs, failing CI, or empty if none]
   ```

4. **Present the standup** to the user for review and editing before they share it.

## Important:
- Keep each bullet to one line
- Use plain language, not commit-message style
- Group related commits into a single bullet (e.g. "Added layout visualization and fixed region merging" not 5 separate commit summaries)
- If there's no recent activity, say so honestly
- If `$ARGUMENTS` includes a number of days (e.g. `3`), look back that many days instead of the default
