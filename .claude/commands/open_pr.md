---
description: Create a pull request from current branch with summary and test plan
---

# Open Pull Request

You are tasked with opening a GitHub pull request for the current branch.

## Process:

1. **Understand what changed:**
   - Run `git branch --show-current` to confirm the branch
   - Run `git log main..HEAD --oneline` to see all commits on this branch
   - Run `git diff main...HEAD --stat` to see changed files
   - Run `git diff main...HEAD` to understand the full diff
   - Run `git status` to check for uncommitted work

2. **Handle uncommitted work:**
   - If there are uncommitted changes, ask the user whether to commit them first or proceed without them

3. **Push the branch:**
   - Run `git push -u origin HEAD` to ensure the branch is on the remote

4. **Draft the PR:**
   - Write a concise title (under 70 chars, imperative mood)
   - Write a summary with 1-3 bullet points explaining what and why
   - Include a test plan with specific verification steps
   - If the changes touch pipeline stages, mention which ones

5. **Create the PR:**
   ```bash
   gh pr create --title "title" --body "$(cat <<'EOF'
   ## Summary
   - bullet points

   ## Test plan
   - [ ] verification steps
   EOF
   )"
   ```

6. **Return the PR URL** to the user

## Important:
- Base branch is `main` unless the user specifies otherwise
- If `$ARGUMENTS` is provided, use it as context for the PR description
- Keep the title short; put details in the body
- Mention breaking changes or required env var updates prominently
