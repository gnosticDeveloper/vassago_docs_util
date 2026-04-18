import argparse
import subprocess
import sys
import json
import warnings
from pathlib import Path

# Suppress the Pydantic v1/Python 3.14 UserWarning — it's a LangChain
# internals issue, not ours, and doesn't affect actual execution on 3.13.
warnings.filterwarnings("ignore", message=".*Pydantic V1.*", category=UserWarning)

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

# ── Hardcoded internal configuration ─────────────────────────────────────────

OUTPUT_FILE = "README.md"
TEMP_JSON   = "codebase.json"
MODEL       = "claude-haiku-4-5-20251001"
MAX_TOKENS         = 2048   # standard mode
MAX_TOKENS_VERBOSE = 8192   # haiku's hard ceiling — streamed
MAX_TOKENS_PUBLIC  = 8192   # public READMEs can be long — streamed

# Haiku pricing (per million tokens)
COST_PER_M_INPUT  = 0.80
COST_PER_M_OUTPUT = 4.00
CHARS_PER_TOKEN   = 3.5

# ── Repomix ───────────────────────────────────────────────────────────────────

REPOMIX_CMD = (
    "npx repomix -o codebase.json --style json "
    "--no-file-summary --remove-comments --remove-empty-lines"
)

def run_repomix() -> dict:
    """Run repomix and return the parsed JSON output."""
    cwd = Path.cwd()

    code_extensions = {
        ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h",
        ".cs", ".rb", ".php", ".swift", ".kt", ".sh", ".toml", ".yaml",
        ".yml", ".json", ".md", ".html", ".css",
    }
    source_files = [
        f for f in cwd.rglob("*")
        if f.is_file()
        and f.suffix in code_extensions
        and ".git" not in f.parts
        and "node_modules" not in f.parts
        and ".venv" not in f.parts
    ]
    if not source_files:
        print(
            f"✗ No source files found in {cwd}\n"
            "  vassago_docs_util must be run from inside a project directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"→ {REPOMIX_CMD}")
    result = subprocess.run(REPOMIX_CMD, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"✗ repomix failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr or result.stdout, file=sys.stderr)
        sys.exit(result.returncode)

    if not Path(TEMP_JSON).exists():
        print(f"✗ repomix ran but {TEMP_JSON} was not created — unexpected repomix error.", file=sys.stderr)
        sys.exit(1)

    with open(TEMP_JSON, encoding="utf-8") as f:
        return json.load(f)

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a technical writer. Given a repository's file tree and source files, \
produce a concise Markdown README with two sections:

1. **Overview** – what the project does, its purpose, key dependencies, and \
how to run it (≤ 150 words).
2. **File Summaries** – a bullet per file: `path` — one-sentence description.

Rules:
- No fluff, no repeated info.
- Code blocks only where essential.
- Do NOT invent features not present in the code.
"""

SYSTEM_PROMPT_VERBOSE = """\
You are a technical writer. Given a repository's file tree and source files, \
produce a detailed Markdown README with the following sections:

1. **Overview** – what the project does, its purpose, key dependencies, and \
how to run it (≤ 150 words).

2. **File Summaries** – for each file:
   - `path` — what the file is for and when/how it is used by the rest of the codebase.
   - **Relations** – other files it imports from or that import it (one line each, \
e.g. `imported by main.py`).
   - **Methods / Functions** – a sub-bullet for every function or class method with: \
signature, one-sentence description of what it does, and its key parameters.

Rules:
- No fluff, no repeated info.
- Code blocks only where essential (e.g. non-obvious signatures).
- Do NOT invent features not present in the code.
- If a file has no functions (e.g. a config file), omit the Methods section for it.
"""

def build_system_prompt_public(context: dict) -> str:
    """Build the public README system prompt, injecting user-provided context."""
    purpose   = context.get("purpose")   or "infer from the code"
    audience  = context.get("audience")  or "infer from the code"
    setup     = context.get("setup")     or "infer from the code"

    return f"""\
You are a technical writer producing a public-facing README for an open source project.
A developer landing on this repo cold should be able to understand, install, and run it \
within 5 minutes.

The author has provided the following context:
- Purpose / motivation: {purpose}
- Intended audience: {audience}
- Non-obvious setup notes: {setup}

Produce a Markdown README with exactly these sections in order:

1. **Project name + one-line tagline** (infer a punchy tagline from the code if not given)
2. **Why this exists** – the motivation and problem it solves (2–4 sentences, \
use the author's stated purpose if provided, otherwise infer)
3. **Prerequisites** – every external dependency a user must have installed before \
they can run this (Node.js, Java, Docker, API keys, etc.) — be exhaustive
4. **Installation** – exact step-by-step commands from clone to ready-to-run, \
using real paths and commands found in the code
5. **Usage** – the full CLI/API surface with concrete examples for every flag or endpoint
6. **Overview** – how it works internally (architecture, key design decisions) in ≤ 150 words

Rules:
- Write for a developer who has never seen this project.
- Every command must be a real command that will actually work based on the code.
- Do NOT invent features not present in the code.
- Use fenced code blocks for all commands and code examples.
- No fluff, no marketing language.
"""

def build_user_message(data: dict, public_context: dict | None = None) -> str:
    structure  = data.get("directoryStructure", "")
    files_dict = data.get("files", {})
    lines = [f"## Directory structure\n```\n{structure}\n```\n"]
    for path, content in files_dict.items():
        lines.append(f"## {path}\n```\n{content}\n```\n")
    return "\n".join(lines)

# ── Public mode: clarifying questions ────────────────────────────────────────

CLARIFYING_QUESTIONS = [
    (
        "purpose",
        "What is this project and why did you build it?\n"
        "  (the 'why this exists' story — press Enter to let Claude infer)\n"
        "  > ",
    ),
    (
        "audience",
        "Who is the intended audience / user?\n"
        "  (e.g. 'backend devs evaluating auth patterns', press Enter to skip)\n"
        "  > ",
    ),
    (
        "setup",
        "Anything non-obvious about setup that isn't clear from the code?\n"
        "  (e.g. 'needs a running OpenBao instance', press Enter to skip)\n"
        "  > ",
    ),
]

def ask_clarifying_questions() -> dict:
    """Interactively collect public README context from the user."""
    print()
    print("  ── Public README: a few quick questions ──────────────────────")
    print("  Skipping a question tells Claude to infer it from the code.")
    print()
    context = {}
    for key, prompt in CLARIFYING_QUESTIONS:
        try:
            answer = input(f"  {prompt}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        context[key] = answer if answer else None
    print()
    return context

# ── Token / cost estimate ─────────────────────────────────────────────────────

def print_estimate(system: str, user_msg: str, mode: str) -> None:
    max_out = MAX_TOKENS if mode == "standard" else MAX_TOKENS_VERBOSE

    input_tokens  = int(len(system + user_msg) / CHARS_PER_TOKEN)
    output_tokens = max_out // 2 if mode == "standard" else max_out
    input_cost    = (input_tokens  / 1_000_000) * COST_PER_M_INPUT
    output_cost   = (output_tokens / 1_000_000) * COST_PER_M_OUTPUT

    print()
    print(f"  ┌─────────────────────────────────────────┐")
    print(f"  │     Token / cost estimate ({mode:>8})    │")
    print(f"  ├──────────────────────┬──────────────────┤")
    print(f"  │ Input tokens         │ ~{input_tokens:>12,}   │")
    print(f"  │ Est. output tokens   │ ~{output_tokens:>12,}   │")
    print(f"  ├──────────────────────┼──────────────────┤")
    print(f"  │ Input cost           │  ~${input_cost:>10.4f}   │")
    print(f"  │ Output cost          │  ~${output_cost:>10.4f}   │")
    print(f"  │ Total est. cost      │  ~${(input_cost + output_cost):>10.4f}   │")
    print(f"  └──────────────────────┴──────────────────┘")
    print(f"  (Model: {MODEL} · estimates may vary)")
    if mode in ("verbose", "public"):
        print("  ⚠  Output is streamed — actual tokens may exceed estimate on large repos.")
    print()

# ── Streaming helper ──────────────────────────────────────────────────────────

def stream_response(llm: ChatAnthropic, messages: list) -> str:
    """Stream LLM output to stdout and return the full text."""
    chunks = []
    for chunk in llm.stream(messages):
        text = chunk.content
        if text:
            print(text, end="", flush=True)
            chunks.append(text)
    print()
    return "".join(chunks)

# ── Core ──────────────────────────────────────────────────────────────────────

def generate_docs(skip_confirm: bool = False, verbose: bool = False, public: bool = False) -> None:
    # Determine mode
    if public:
        mode = "public"
    elif verbose:
        mode = "verbose"
    else:
        mode = "standard"

    max_tokens = MAX_TOKENS if mode == "standard" else MAX_TOKENS_VERBOSE
    llm = ChatAnthropic(model=MODEL, max_tokens=max_tokens)

    try:
        # Public mode: ask questions BEFORE running repomix so the session
        # feels natural (questions first, then the spinner, then cost estimate)
        public_context = None
        if public:
            public_context = ask_clarifying_questions()

        data     = run_repomix()
        user_msg = build_user_message(data)

        if mode == "public":
            system = build_system_prompt_public(public_context)
        elif mode == "verbose":
            system = SYSTEM_PROMPT_VERBOSE
        else:
            system = SYSTEM_PROMPT

        print_estimate(system, user_msg, mode)

        if not skip_confirm:
            try:
                answer = input("  Proceed? [Y/n] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                return
            if answer not in ("", "y", "yes"):
                print("Aborted.")
                return

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user_msg),
        ]

        if mode == "standard":
            print("→ Generating...")
            response = llm.invoke(messages)
            usage = response.usage_metadata
            if usage:
                print(f"  Actual tokens — input: {usage['input_tokens']}, output: {usage['output_tokens']}")
            readme = response.content
        else:
            print(f"→ Generating (streaming)...\n")
            readme = stream_response(llm, messages)

        Path(OUTPUT_FILE).write_text(readme, encoding="utf-8")
        print(f"\n✓ {OUTPUT_FILE} updated.")

    finally:
        if Path(TEMP_JSON).exists():
            Path(TEMP_JSON).unlink()

# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate README.md from this repo.")
    parser.add_argument("--yes",     "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--verbose", "-v", action="store_true", help="Per-method docs + file relations (streamed)")
    parser.add_argument("--public",  "-p", action="store_true", help="Public-facing README with onboarding sections (streamed)")
    args = parser.parse_args()

    if args.verbose and args.public:
        print("✗ --verbose and --public are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    generate_docs(skip_confirm=args.yes, verbose=args.verbose, public=args.public)