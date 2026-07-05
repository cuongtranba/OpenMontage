# OpenMontage

**MANDATORY: Read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

There are no instructions in this file. All instructions are in AGENT_GUIDE.md.

# C3 Architecture

OpenMontage uses C3 for frozen architecture documentation. All architecture facts live in `.c3/` and are frozen — change them only through a gated change-unit.

## Key commands

```bash
c3() { C3X_MODE=agent bash ~/.claude/skills/c3/bin/c3x.sh "$@"; }

c3 list --compact          # topology overview (16 entities)
c3 search "<question>"     # concept → entities
c3 lookup <file>           # file → component
c3 read <id>               # entity content
c3 graph <id> --format mermaid  # relationship graph
c3 check                   # validate (add --include-adr for ADRs)
c3 eval                    # check fact vs code
```

## Topology

- **c3-0** OpenMontage (system)
- **c3-1** Production Engine — tool registry, BaseTool contract, pipeline state, schemas, provider tools, pipeline manifests/skills
- **c3-2** Backlot Board — local web server + browser UI
- **c3-3** Remotion Composer — Node.js/React render runtime
- **ref-instruction-layering** Three-layer instruction model (tools → skills → vendor knowledge)
- **ref-selector-pattern** Capability selector routing for multi-provider tools
- **rule-tool-contract** All tools subclass BaseTool, implement execute() → ToolResult
- **rule-project-workspace** All outputs under projects/<id>/ via explicit output_path

## Changing architecture

Architecture changes go through `c3 change new <slug>` → patches → `c3 change apply`. Never hand-edit `.c3/` instance files.
