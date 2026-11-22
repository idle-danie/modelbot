# Structure

```
src/modelbot/
  cli.py         # typer entry point: scan / eval / run
  config.py      # modelbot.yaml schema and loader
  discovery.py   # Bedrock catalog, candidate selection, urgency
  runner.py      # Converse calls, concurrency, retries, aggregates
  pricing.py     # price table and budget tracking
  graders.py     # grader registry
  porter.py      # Strands prompt-porting agent + acceptance loop
  decision.py    # qualification and ranking (pure)
  report.py      # Markdown / JSON reports
  github_pr.py   # branch, file rewrite, PR create/update
examples/        # runnable example projects
tests/           # unit tests mirror src modules
```
Keep `decision.py`, `graders.py` (deterministic ones), and `report.py` free of I/O.
