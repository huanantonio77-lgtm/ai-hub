## The bet: self-maintenance before features

Two hundred sessions ago, ai-hub was going to be an arbitrage bot. Today it's something else: an autonomous system that heals, diagnoses, and updates itself, with DEX data feeds running in the background.

This is a short engineering retrospective. What worked, what I'd do differently.

### Why self-maintenance first

The single decision that shaped everything: **spend the first fifty sessions on internal mechanisms, not user-facing features.**

Concretely, that meant four axes:

1. **Autonomy** - a persistent daemon on macOS (launchd, PPID=1), REST feeds to eight DEX venues.
2. **Self-service** - twenty-seven healers that detect and repair their own failure modes.
3. **Self-diagnosis** - a blindness audit that lists what the agent cannot see, plus a signed CORE manifest (`sign_core` - 14/14 files valid, DRIFT=0).
4. **Self-learning** - autonomous lesson extraction from every session.

The alternative - build features first, add self-repair later - has a hidden cost: every new feature adds failure modes that the self-repair system has to catch up with. Starting from self-repair means each new feature is born into a system that already knows how to keep itself alive.

### Axis 1: Autonomy

The agent runs two launchd services: `self_daemon` (every two hours) and `agent_daemon` (every 120 seconds). Both are true daemons - PPID=1, KeepAlive=true, RunAtLoad=true.

Every cycle, `self_daemon`:

- runs an arbitrage scan against eight DEX venues
- appends to `ARBITRAGE_STATS.jsonl`
- once a day, pulls new papers from arXiv / OpenAlex / Crossref
- once a day, rolls 30-day stats into `SELF_TRADING.md`

Eight DEX venues today: Hyperliquid, dYdX v4, Paradex, Orca, Raydium, GMX, Injective, Curve. All read-only - `place_order` is a deliberate no-op. Fees are accounted for in the net-profit check; AMM fee is zero in the scanner to avoid double-counting.

### Axis 2: Self-service (27 healers)

Healers are small scripts, each with one job. Examples:

- `disk_janitor` - archives old session artifacts
- `lessons_hygiene` - detects garbage blocks in the lesson log
- `secrets_audit` - checks file permissions under `.secrets/`
- `family_audit` - flags modules that lack matching tests

The healers are not clever individually. What matters is the invariant: if something is fixable, some healer should already be trying to fix it. Adding a new failure mode is an invitation to write a new healer - not a reason to page a human.

### Axis 3: Self-diagnosis

Two mechanisms here.

**`sign_core`** - fourteen core files are signed with an Ed25519 key. Every session, `verify_core()` confirms nothing has drifted. If a signature is invalid, the session stops. This paranoia has paid off more than once.

**Blindness audit** - a periodic self-report of *what the agent cannot see*. Not "what's broken" but "what we're not even looking at." This is the axis with the least tooling today; if there's a blind spot we're not detecting, we won't learn it from metrics.

### Axis 4: Self-learning

Every session produces events (`EVENTS.jsonl`). A five-layer pipeline turns raw events into lessons:

1. **Capture** - the daemon and the curator emit events
2. **Filter** - only events with actionable shape survive
3. **Draft** - candidates get written to `lesson_suggest_s20N.json`
4. **Curate** - the human approves or rejects each draft
5. **Persist** - approved lessons go to `lessons.md` and are indexed + embedded

Current counts: 9,335 lessons, 303 in the search index, 304 embeddings. The "suggest five pending lessons" loop has been stable for six sessions in a row.

The point is not the number. It's that the agent gets better at its own job without being told what to learn.

### What I'd do differently

**Lesson quality over quantity.** 9,335 looks nice on a dashboard, but most of the index growth is routine session noise. If I started over, I would cap the daily intake at three lessons and require a stronger novelty signal before persisting.

**Cap features until healers exist.** A feature without a healer is a debt you pay later.

**Read-only phase one was right.** DEX integration tempts you to add `place_order` on day one. Don't. Get the data plumbing right first - orders come last.

### Numbers today

- 163 features, 167 checks, 163 alive
- 27 healers, 0 regressions in the last 13 sessions
- 221/221 tests passing
- 8 DEX venues, all read-only
- Docker + compose included, self-hosting works

### Links

- GitHub: https://github.com/huanantonio77-lgtm/ai-hub
