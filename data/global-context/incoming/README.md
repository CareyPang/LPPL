# P2/P3 incoming artifacts

This directory is an optional handoff point for already-fetched JSON source
responses.  `scripts/update_global_context.py` reads only this directory; it
does not fetch URLs, invoke a browser, update LPPLS inputs, or write a Worker.

If `manifest.json` is absent, the nightly workflow emits an explicit
`not_requested` snapshot.  When a manifest is supplied, each source must name
its payload file and carry `license_status`, `frequency_status`, and
`mainland_network_status`.  These statuses default to `NOT_ESTABLISHED` and
must not be read as legal, rate-limit, or Mainland-network verification.
