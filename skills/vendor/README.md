# Vendor skills

Play skills (`build`, `review`, ...) are the kit's and say **what** a play must deliver.
Vendor skills are proven third-party `SKILL.md` folders that teach **technique**
(TDD, debugging, Playwright, React performance). They never override `AGENTS.md`.

## Pin, don't install

```bash
.sdlc/bin/sdlc skills catalog                                   # curated list
.sdlc/bin/sdlc skills add superpowers/test-driven-development   # pins commit + hash
.sdlc/bin/sdlc skills add https://github.com/org/repo --path skills/x --ref v1.2.0
```

`add` copies the folder to `skills/vendor/<name>/` and records source, commit and a
content hash in `skills.lock.json`. The `skills` gate check fails if a vendored skill
is edited, missing, or not in the lock, so every agent on every machine gets the
same bytes.

## Use

List a vendor skill on the tickets that need it (`skills: [build, frontend-patterns,
test-driven-development]`). `sdlc prompt` inlines exactly those skills, so the agent
does not depend on any tool's skill-discovery folder. Do not copy vendor skills into
`.claude/skills`, `.agents/skills` or similar auto-loaded folders: that makes them
always-on for every play.

## Update

Re-run `sdlc skills add <key>` (optionally `--ref <tag>`), review the diff of the
skill folder like code, and run one known ticket's gate before merging.
