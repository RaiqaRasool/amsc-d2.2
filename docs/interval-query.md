# Interval Queries

## Expected Behavior

- Include prior value at interval boundaries defaults to off and is respected
  for both one and multiple PVs. Only events in the requested interval are
  returned when off. An interval without events succeeds with an empty CSV.
- When enabled, MYA can supply boundary points carrying an older value at the
  requested start/end times. These need not be original stored event timestamps.
- Multi-PV queries execute single-channel requests with up to four workers,
  then reuse the client’s disconnect-aware series merge. Values can be filled
  at another PV’s event timestamp; no new sampling grid is generated.
- The client’s run_parallel helper is bypassed because it forces prior points on.
  Per-channel failures propagate and fail the job rather than becoming empty data.
- Explicit prior-point options saved in historical jobs remain honored on rerun;
  new defaults do not rewrite historical requests.
- No archive events, demo coverage boundaries, MySampler, or MyStats are changed.

## Key Components

- `mya_query.py`: channel queries and merge
- `app.py`, `templates/index.html`: explicit option and default

## Verification

- `tests/test_interval_form.py`: checked/unchecked option for one/multiple PVs
- `tests/test_mya_query_config.py`: option propagation, empty results and failures
- Read-only local demo checks compare 2026 empty results with prior off versus
  boundary values with prior on, and verify 2024 events remain available.
