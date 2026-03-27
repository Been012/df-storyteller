--- On-demand fortress state snapshot for df-storyteller.
--- Takes a snapshot only — does NOT start event monitoring.
--- For full setup (snapshot + events), use storyteller-begin instead.
---
--- Usage:
---   storyteller-snapshot       -- Take a snapshot now
---
--- Reference: https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html

-- Run storyteller-begin with a special flag that skips events and legends
dfhack.run_script('storyteller-begin', '--snapshot-only')
