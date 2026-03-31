# flagrant

CLI tool that reviews your code before you commit. Uses LLMs to catch bugs, security issues, and bad patterns the same way a senior dev would in a PR review.

```
$ flagrant --staged

───────────────────────────────────
 flagrant | 3 issues flagged  (1 high | 1 medium | 1 low)
───────────────────────────────────

  ● HIGH    auth.py line 34
             SQL query built with string concatenation
             Fix: use parameterized queries

  ● MEDIUM  utils.py line 12
             Function has no error handling
             Fix: wrap in try/except, handle edge cases

  ● LOW     main.py line 5
             Unused import os
             Fix: remove it
───────────────────────────────────
```

Exits with code 1 on high-severity issues. Works as a pre-commit hook.

## install

```bash
pip install flagrant
```

## usage

```bash
flagrant .                  # review entire repo
flagrant --staged           # only staged changes (fast, cheap)
flagrant --file app.py      # single file
flagrant --strict           # security-focused pass
flagrant --explain          # explain why each issue matters
```

First run prompts for your API key. Supports **Claude**, **OpenAI**, **Gemini**, and **DeepSeek**.

```bash
flagrant config             # switch provider or update key
```

## git hook

```bash
flagrant install-hook       # auto-review on every commit
flagrant remove-hook        # undo
```

Blocks commits with high-severity issues. Skip with `git commit --no-verify`.

## project config

Drop a `.flagrant` file in your repo root:

```json
{
  "ignore": ["migrations/", "tests/", "vendor/"],
  "strict": true,
  "explain": false,
  "language": "python"
}
```

## how it works

1. Reads your files or git diff
2. Chunks large files to fit context windows
3. Sends to your configured LLM with a review-focused system prompt
4. Parses structured JSON issues from the response
5. Prints results, returns exit code 1 if anything is high severity

No telemetry. No accounts. Your code goes straight to whichever LLM provider you pick and nowhere else.

## providers

| Provider | Default model | Env var |
|----------|--------------|---------|
| Claude | claude-sonnet-4-20250514 | `ANTHROPIC_API_KEY` |
| OpenAI | gpt-4o | `OPENAI_API_KEY` |
| Gemini | gemini-2.5-flash | `GEMINI_API_KEY` |
| DeepSeek | deepseek-chat | `DEEPSEEK_API_KEY` |

## license

MIT
