# G2T portal API timing: community measurements (2026-10-09)

This document records observations from controlled tests of an AlphaESS
SMILE-G3-EVCT11/S with a Peugeot e-208 (single-phase charging).
An independent Shelly 3EM Gen3 measured actual AC charging power.

## Observations

- In five 6 A → 10 A → 6 A cycles, the measured transition confirmation
  averaged **24.79 s up** and **26.83 s down**. Upward confirmations ranged
  **19.65–31.25 s** and downward confirmations **24.63–28.84 s**.
- The API PATCH request returned successfully in about **0.27 s** on average.
  A successful response therefore **does not mean** the wallbox has already
  applied the current.
- In a 120-second read-only trial, **108/108 GET requests succeeded** while
  polling configuration and live status at 10, 5, 2 and 1 s intervals.
  No HTTP 429 was seen **in this short test**. This is **not** evidence that
  continuous 1-second polling is permitted or advisable.
- Overlapping command trials (10 A followed by 6 A):
  - At a 15 s separation, no 10 A power increase was observed.
  - At 25 s, the power increase was observed after the 6 A PATCH had already
    been acknowledged, then power decreased again.
  - At 35 s, the 10 A increase had already taken effect before the 6 A command.

## Interpretation and boundaries

These observations are specific to the tested hardware, firmware, car and
network. They do not establish how the server internally queues commands.
The physical response may be influenced by cloud delivery, the wallbox, the
vehicle or measurement timing.

Do not use a fixed 20–30 s delay as a blanket API timeout. Distinguish:
1. HTTP acknowledgement;
2. the configuration reported by the portal;
3. the actual charging state/power.

The third observation requires reliable live telemetry; not every installation
has an independent power meter.

## Integration development guidance

- Preserve AlphaESS-managed charging strategies and Smart Mode; do not
  implement or override AlphaESS's PV surplus controller.
- Serialize concurrent GET-modify-PATCH transactions from this integration
  to avoid local lost updates. This **does not** protect against external
  app/portal writes or other integration instances.
- Do not assume an accepted PATCH is physically complete. Avoid blindly
  replaying old setpoints.
- Investigate adaptive refresh and API backoff separately, with long-running
  rate-limit tests before reducing the default polling interval.
- Avoid including bearer tokens, passwords or full identifiable device
  configuration in public diagnostics.

## Release validation still required

- G1T regression testing and G2T smoke tests for all writable entities.
- Concurrent updates to different fields, including time periods.
- Manual/App/Portal changes during Home Assistant operation.
- Rate limiting, timeouts, authentication refresh and reconnect behavior.
- Verification that schedule periods and Smart Mode are never unintentionally
  overwritten.
