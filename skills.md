---
name: drive-agents
description: How to drive claude, opencode, codex, and gemini coding agents in tmux sessions, including waiting for completion with tmux-wait
user-invocable: false
---

Use this knowledge whenever the user asks you to run, drive, or compare AI coding agents (claude, opencode, codex, or gemini) in tmux sessions.

## Starting sessions

```bash
# Claude (skip all permission prompts for unattended driving)
tmux new-session -d -s claude-driver -x 220 -y 50
tmux send-keys -t claude-driver "claude --dangerously-skip-permissions" Enter
tmux-wait claude-driver "esc to interrupt"  # wait until startup prompt appears

# opencode (synthetic/hf:zai-org/GLM-5.1)
tmux new-session -d -s opencode-driver -x 220 -y 50
tmux send-keys -t opencode-driver "opencode -m 'synthetic/hf:zai-org/GLM-5.1'" Enter
tmux-wait opencode-driver "ctrl\+p commands"  # wait until startup prompt appears

# opencode using Codex via GitHub Copilot (github-copilot/gpt-5.3-codex)
tmux new-session -d -s opencode-driver-codex -x 220 -y 50
tmux send-keys -t opencode-driver-codex "opencode -m 'github-copilot/gpt-5.3-codex'" Enter
tmux-wait opencode-driver-codex "ctrl\+p commands"  # wait until startup prompt appears

# opencode using DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
tmux new-session -d -s opencode-driver-deepseek -x 220 -y 50
tmux send-keys -t opencode-driver-deepseek "opencode -m 'opencode-go/deepseek-v4-pro'" Enter
tmux-wait opencode-driver-deepseek "ctrl\+p commands"

# opencode using Qwen 3.6 Plus (opencode-go/qwen3.6-plus)
tmux new-session -d -s opencode-driver-qwen -x 220 -y 50
tmux send-keys -t opencode-driver-qwen "opencode -m 'opencode-go/qwen3.6-plus'" Enter
tmux-wait opencode-driver-qwen "ctrl\+p commands"

# opencode using Qwen 3.6 27B via TPL (vllm/qwen3.6-27b)
tmux new-session -d -s opencode-driver-qwen27B -x 220 -y 50
tmux send-keys -t opencode-driver-qwen27B "opencode -m 'vllm/qwen3.6-27b'" Enter
tmux-wait opencode-driver-qwen27B "ctrl\+p commands"

# opencode using Minimax 2.7 (opencode-go/minimax-2.7)
tmux new-session -d -s opencode-driver-minimax -x 220 -y 50
tmux send-keys -t opencode-driver-minimax "opencode -m 'opencode-go/minimax-2.7'" Enter
tmux-wait opencode-driver-minimax "ctrl\+p commands"

# opencode using Kimi K2.6 (opencode-go/kimi-k2.6)
tmux new-session -d -s opencode-driver-kimi -x 220 -y 50
tmux send-keys -t opencode-driver-kimi "opencode -m 'opencode-go/kimi-k2.6'" Enter
tmux-wait opencode-driver-kimi "ctrl\+p commands"

# codex (--full-auto: sandboxed, skips approval prompts)
tmux new-session -d -s codex-driver -x 220 -y 50
tmux send-keys -t codex-driver "codex --full-auto" Enter
sleep 3  # codex has no persistent busy indicator during startup; short sleep is fine here

# gemini (--yolo: skips all approval prompts for unattended driving)
tmux new-session -d -s gemini-driver -x 220 -y 50
tmux send-keys -t gemini-driver "gemini --yolo" Enter
tmux-wait gemini-driver "esc to interrupt"
```

`-x 220 -y 50` gives both agents enough columns to render their TUI without wrapping.

## Sending prompts

```bash
tmux send-keys -t SESSION "your prompt here" Enter
```

No quoting tricks needed — `tmux send-keys` treats the string literally.

## Waiting for completion: tmux-wait

`tmux-wait` lives at `~/.local/bin/tmux-wait`. It polls the pane every second and exits once the pane output no longer matches the busy pattern. Signature:

```
tmux-wait SESSION BUSY_PATTERN [TIMEOUT_SECS]
```

| Agent    | Busy pattern        | Notes                                                      |
|----------|---------------------|------------------------------------------------------------|
| claude                  | `esc to interrupt`  | Shown in status bar while working                          |
| opencode                | `esc interrupt`     | Shown in status bar while working                          |
| opencode-driver-codex   | `esc interrupt`     | Same opencode UI, but using `github-copilot/gpt-5.3-codex` |
| opencode-driver-deepseek | `esc interrupt`     | Same opencode UI, but using `opencode-go/deepseek-v4-pro`  |
| opencode-driver-qwen     | `esc interrupt`     | Same opencode UI, but using `opencode-go/qwen3.6-plus`    |
| opencode-driver-qwen27B  | `esc interrupt`     | Same opencode UI, but using `vllm/qwen3.6-27b` (TPL)       |
| opencode-driver-minimax  | `esc interrupt`     | Same opencode UI, but using `opencode-go/minimax-2.7`      |
| opencode-driver-kimi     | `esc interrupt`     | Same opencode UI, but using `opencode-go/kimi-k2.6`        |
| codex                   | `esc to interrupt`  | Shown inline as `• Working (Ns • esc to interrupt)`        |
| gemini                  | `esc to interrupt`  | Shown in status bar while working                          |

## Full round-trip pattern

```bash
# Send prompt
tmux send-keys -t claude-driver "audit the codebase and summarize findings" Enter

# Block until done (no sleeping)
tmux-wait claude-driver "esc to interrupt"

# Read the result
tmux capture-pane -t claude-driver -p -S -200
```

```bash
tmux send-keys -t opencode-driver "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver "esc interrupt"
tmux capture-pane -t opencode-driver -p -S -200
```

```bash
tmux send-keys -t opencode-driver-codex "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-codex "esc interrupt"
tmux capture-pane -t opencode-driver-codex -p -S -200
```

```bash
tmux send-keys -t codex-driver "audit the codebase and summarize findings" Enter
tmux-wait codex-driver "esc to interrupt"
tmux capture-pane -t codex-driver -p -S -200
```

```bash
tmux send-keys -t opencode-driver-deepseek "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-deepseek "esc interrupt"
tmux capture-pane -t opencode-driver-deepseek -p -S -200
```

```bash
tmux send-keys -t opencode-driver-qwen "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-qwen "esc interrupt"
tmux capture-pane -t opencode-driver-qwen -p -S -200
```

```bash
tmux send-keys -t opencode-driver-qwen27B "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-qwen27B "esc interrupt"
tmux capture-pane -t opencode-driver-qwen27B -p -S -200
```

```bash
tmux send-keys -t opencode-driver-minimax "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-minimax "esc interrupt"
tmux capture-pane -t opencode-driver-minimax -p -S -200
```

```bash
tmux send-keys -t opencode-driver-kimi "audit the codebase and summarize findings" Enter
tmux-wait opencode-driver-kimi "esc interrupt"
tmux capture-pane -t opencode-driver-kimi -p -S -200
```

```bash
tmux send-keys -t gemini-driver "audit the codebase and summarize findings" Enter
tmux-wait gemini-driver "esc to interrupt"
tmux capture-pane -t gemini-driver -p -S -200
```

## Reading output

```bash
tmux capture-pane -t SESSION -p           # last screenful
tmux capture-pane -t SESSION -p -S -200   # last ~200 lines of scrollback
```

## Cleanup

```bash
tmux kill-session -t claude-driver
tmux kill-session -t opencode-driver
tmux kill-session -t opencode-driver-codex
tmux kill-session -t opencode-driver-deepseek
tmux kill-session -t opencode-driver-qwen
tmux kill-session -t opencode-driver-qwen27B
tmux kill-session -t opencode-driver-minimax
tmux kill-session -t opencode-driver-kimi
tmux kill-session -t codex-driver
tmux kill-session -t gemini-driver
```

## Notes

- Both agents inherit the working directory from the shell that created the session (usually the project root via direnv).
- `--dangerously-skip-permissions` bypasses all tool-use confirmations in claude. Only use it for unattended driving with trusted prompts.
- opencode shows a running cost/token counter in its status bar (e.g. `12.4K (6%) · $0.01`) — worth watching on long tasks.
- opencode's `esc interrupt` disappears as soon as the response is complete; `tmux-wait` detects this correctly.
- `opencode-driver-codex` is useful when you want the opencode interface/workflow but with the Codex model from GitHub Copilot.
- codex may prompt to switch models when approaching rate limits; handle this with an extra `tmux send-keys -t codex-driver "2" Enter` (keep current model) if running unattended.
- `--full-auto` in codex enables sandboxed auto-execution. Use `--dangerously-bypass-approvals-and-sandbox` only in fully trusted, externally sandboxed environments.
- `--yolo` in gemini skips all tool-use confirmations. Only use it for unattended driving with trusted prompts.
