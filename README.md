# vassago_docs_util

Automate README generation from your codebase using Claude AI.

## Why this exists

Keeping documentation in sync with code is tedious and error-prone. This tool extracts your repository structure and source files, sends them to Claude, and generates a polished README in seconds. It supports three modes: standard summaries, detailed per-method documentation, or public-facing onboarding guides. Perfect for bootstrapping documentation on new projects or refreshing stale READMEs.

## Prerequisites

- **Python** 3.11 or later
- **Node.js** 14+ (for `npx` and `repomix`)
- **Anthropic API key** (set as `ANTHROPIC_API_KEY` environment variable)
- **uv** package manager (optional but recommended; the install script will use it if available, or fall back to manual Python setup)

## Installation

1. Clone the repository:
```bash
git clone <repo-url>
cd vassago_docs_util
```

2. Run the install script:
```bash
bash install.sh
```

The script will:
- Create a Python virtual environment with dependencies
- Verify or install Node.js
- Install `repomix` globally via npm
- Write a system-wide launcher to `/usr/local/bin/vassago_docs_util`

3. Verify the installation:
```bash
vassago_docs_util --help
```

## Usage

Run from any project directory where you want to generate a README:

```bash
# Standard mode: brief overview + file summaries
vassago_docs_util

# Verbose mode: per-method docs + file relations (streamed)
vassago_docs_util --verbose

# Public mode: onboarding-focused (streamed, asks clarifying questions)
vassago_docs_util --public

# Skip confirmation prompt
vassago_docs_util --yes

# Combine flags
vassago_docs_util --public --yes
vassago_docs_util --verbose --yes
```

**Flags:**
- `--yes` / `-y` — Skip the confirmation prompt before generating
- `--verbose` / `-v` — Include detailed per-method documentation and file relations; output is streamed
- `--public` / `-p` — Generate a public-facing README with project name, prerequisites, installation, and usage sections; prompts for project purpose, intended audience, and setup notes

**Output:** Writes to `README.md` in the current directory. Temporary files are cleaned up automatically.

## Overview

The tool operates in three stages:

1. **Extract:** Runs `repomix` to scan the repository and collect source files (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.sh`, `.toml`, `.yaml`, `.json`, `.md`, etc.), excluding `.git`, `node_modules`, and `.venv`.

2. **Estimate:** Calculates approximate token counts and API costs for Claude Haiku, displays the estimate, and awaits user confirmation (skip with `--yes`).

3. **Generate:** Sends the repository structure and code to Claude with a mode-specific system prompt. Standard mode returns a complete response. Verbose and public modes stream output in real-time for responsiveness on large repositories.