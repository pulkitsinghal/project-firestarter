# Scheduled Agent add-on

An opt-in "cloud session": a GitHub Actions workflow that runs an AI agent on a
schedule (or on demand), has it read the repo, and opens a **GitHub issue** for a
human to react to. Distilled from a sibling project's founder-proxy idea-drop.

Enable it at stamp time:

```bash
./bin/firestart.sh --set include_scheduled_agent=yes
```

## What you get

| File | Purpose |
|------|---------|
| `.github/workflows/scheduled-agent.yml` | The workflow. `workflow_dispatch` by default; a commented-out `schedule` block turns it recurring. Least-privilege (`contents: read`, `issues: write`). |
| `scripts/agent-drop.mjs` | Dependency-free Node 20 script (global `fetch`, no `npm install`): reads the prompt → calls the Anthropic Messages API → opens an issue via the GitHub REST API. |
| `.github/agent/prompt.md` | The agent's instructions. Edit this to define the recurring job (idea drop, triage sweep, dependency digest, …). |

## Setup

1. Add the API key secret (same one the AI PR reviewer uses):
   ```bash
   gh secret set ANTHROPIC_API_KEY
   ```
2. (Optional) pin the model with a repo variable, else it uses the stamped default:
   ```bash
   gh variable set CLAUDE_MODEL --body "{{ claude_model }}"
   ```
3. Run it once from the **Actions** tab → *Scheduled Agent* → *Run workflow*.
4. To make it recurring, uncomment the `schedule:` cron in the workflow. **Each
   run costs a small API charge**, which is why it ships OFF.

## Cost & safety

- It is **read-only** except for opening one issue (`issues: write`).
- The default prompt just asks for a short "what to look at this week" digest so
  the workflow is useful before you customize it.
- No new dependencies, no host toolchain — it runs entirely on the Actions runner.
