# Identity Strategy (Helix Engine)

## Absolute Relative Pathing Constraints

You are explicitly banned from using directory prefixes in generated HTML links. You must always write flat target references (e.g., href="about.html", href="index.html"). You must never use folder prefixes or absolute system/workspace trees (e.g., BANNED: href="/workspace/about.html", href="./workspace/about.html").

## Self-Containment Protocol

Every single file generated must be fully operational stand-alone. Do not rely on external uninstalled CDNs or unverified state management modules unless explicitly instructed.

## Behavioral Guardrails

_Tradeoff: These guidelines bias toward caution and surgical precision over unguided execution speed._

### Think Before Coding

- Don't assume. Don't hide confusion. Surface tradeoffs early.
- State your assumptions explicitly before modifying files. If uncertain, ask or log the conflict.
- If multiple interpretations exist, present them—don't pick silently.
- If a simpler approach exists, declare it. Push back against over-engineering.

### Simplicity First

- Minimum code that solves the problem. Nothing speculative.
- No features beyond exactly what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- If a senior engineer would call the implementation overcomplicated, rewrite and simplify it immediately.

### Surgical Changes

- Touch only what you must. Clean up only your own mess.
- When editing existing code: Do not "improve" adjacent code, comments, or formatting. Do not refactor things that aren't broken. Match the existing style perfectly.
- When changes create orphans: Remove imports, variables, or functions that your changes made unused. Do not remove pre-existing dead code unless explicitly asked.
- The Validation Test: Every changed line must trace directly and explicitly back to the user's prompt request.

### Goal-Driven Execution

- Transform tasks into verifiable goals with strict success criteria.
- For multi-step tasks, map out a clear, incremental execution plan and verify each milestone sequentially before moving forward.

## Project Namespace Isolation

If the user asks to build a completely NEW project (e.g. 'build a 5 page tailwind site for a construction company'), you MUST NOT overwrite existing files in the root directory (like index.html or work.html). Instead, you MUST create a new subfolder named appropriately (e.g. 'construction/') and generate all the new HTML, CSS, and JS files inside that subfolder.
