# Tipping Point Agent Starter Kit

## Install
Copy `AGENTS.md` and the `.agents/` directory into the Tipping Point repository root, beside the existing `.venv/` and `docs/tip-implementation-plan.md`.
Review and merge existing instructions; do not overwrite an existing `AGENTS.md` blindly.
The kit does not contain an implementation plan or modify your environment.

Use uppercase plural `AGENTS.md`, not `agent.md` or `AGENT.md`.
Do not put these instructions inside `.venv`.
No additional Python package, MCP server, multi-agent system, or global skill installation is needed for these Markdown instructions.

## Files
```text
tipping-point/
├── .venv/                         # Existing; not supplied; ignored by Git
├── AGENTS.md                      # Persistent repository policy
├── docs/tip-implementation-plan.md     # Your approved implementation plan
└── .agents/
    └── skills/
        ├── paypal-settlement/SKILL.md
        ├── workshop-economics/SKILL.md
        ├── sponsor-integrations/SKILL.md
        └── verification-release/SKILL.md
```

## Antigravity discovery
Current official Antigravity documentation lists root `AGENTS.md` and `.agents/skills/<name>/SKILL.md` as supported workspace customizations. Current IDE documentation also retains legacy `.agent/skills` compatibility. Use `.agents/skills` for this new setup.
See https://antigravity.google/docs/customization-discovery/ and https://antigravity.google/docs/ide/skills/ .

After copying the files, start a fresh agent task and ask it to list the applicable repository instructions and discovered skills before editing.
If an older installation does not discover them, consult that installed version's customization UI/documentation; do not create duplicate rule files with divergent contents or claim automatic loading was verified.

## Environment verification
Run from the repository root on POSIX systems:
```bash
.venv/bin/python -c "import pathlib,sys; p=pathlib.Path('.venv').resolve(); print('executable:',sys.executable); print('prefix:',sys.prefix); print('base_prefix:',sys.base_prefix); assert pathlib.Path(sys.prefix).resolve()==p; assert sys.prefix!=sys.base_prefix"
.venv/bin/python -m pip --version
```
On Windows use `.venv/Scripts/python.exe` instead.
Do not recreate an existing environment if a check fails; diagnose it first.

Calling the environment's Python explicitly does not require shell activation. See https://docs.python.org/3/library/venv.html .
Python packages/tools use `.venv`; frontend Node packages use the project's local package-manager environment. Do not force Node into the Python environment.

## Suggested Git ignores
Merge these with existing ignore rules:
```gitignore
.venv/
node_modules/
.env
.env.*
!.env.example
```
Do not accidentally ignore intended test fixtures or documentation through broader secret patterns.
Commit agent instructions and skills; never commit credentials or the environment directory.

## First prompt
```text
Read AGENTS.md and docs/tip-implementation-plan.md. List the relevant discovered skills.
Verify the repository-root .venv without replacing or modifying it.
Inspect the current repository and report the implementation baseline.
Propose the smallest Foundation Gate task and its acceptance checks.
Do not install dependencies, provision resources, change external accounts,
modify code, or run provider payment mutations yet. Stop for approval.
```

## Keep it small
These four skills are intentionally task-specific. Split sponsor-integrations into narrower skills only if it becomes difficult to maintain.
AGENTS.md contains always-needed policy; skills contain triggered workflows; the implementation plan contains product scope and sequence.
These instructions guide an agent but are not an execution sandbox. Retain IDE approval controls for destructive or external actions.
