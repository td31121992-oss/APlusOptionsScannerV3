# AI trading agent (shadow judge)

A Claude model that looks at each trade the scanner took, using ONLY facts known at the moment of entry, and answers TAKE or SKIP with a probability of profit. It never places, blocks or changes
anything. Its answers are stored and graded against what the trades really did, like every other forward experiment (id AI01 in `experiments.json`).

| File | What |
|---|---|
| `agent_packet.py` | the packet: the ~60 entry-time facts the agent sees; a hindsight guard refuses any packet that contains post-entry fields |
| `agent_judge.py` | `MockJudge` (a fixed rule, free) and `ClaudeJudge` (Anthropic SDK, structured JSON answer, per-day cost cap, never raises into the caller) |
| `agent_run.py` | `run` (judge trades, append to `data/ai_agent/decisions.jsonl`), `grade` (TAKE vs SKIP against the real result, AUC, what enforcing it would change) |
| `agent_baseline.py` | a plain statistical model on the same facts, walk-forward; the bar the agent has to clear |

## Switching it on
1. Put your key in `.env` (never in chat): `ANTHROPIC_API_KEY=...`
2. Optional: `APLUS_AGENT_MODEL` (default `claude-sonnet-5-5`), `APLUS_AGENT_DAILY_USD_CAP` (default 2.0), `APLUS_AGENT_NIGHTLY=0` to stop the nightly run.
3. Try the pipeline for free: `python agent_run.py run --agent mock --backfill` then `python agent_run.py grade --agent mock`.
4. A first real read on past trades (about 520 calls, a few dollars; the agent is told only the base rates of EARLIER days): `python agent_run.py run --agent claude --backfill --limit 60` first, then the rest.
5. From then on the nightly archive job (16:30) judges that day's trades; the Supervisor lists AI01 with the other experiments.

## Honest limits
- The statistical baseline on these facts found no usable signal (AUC 0.49-0.57, chance range 0.45-0.56). An LLM can only help if it brings information the baseline does not, so expect "no better than chance" as a real possibility.
- About 520 trades over 29 days: ranges are wide. The agent graduates only by the same pass marks as every other experiment, and only you can switch anything live.
- Refusals and API errors are recorded as ERROR and skipped; the daily cap stops further calls.
