# Compensation (sagas)

A side-effecting HTTP tool node can declare the action that undoes it:

```json
"harness": {"compensation": {"tool": "http_request",
  "arguments": {"method": "DELETE", "url": "https://api.example.com/reservations/{{reserve.output.body.id}}"},
  "description": "cancel the reservation"}}
```

When the node succeeds, its compensation is registered with a sequence number. If the run later fails:

- with `settings.compensation_enabled: true`, registered compensations run **automatically in reverse order**;
- otherwise they are listed on the run (Harness tab) and can be run by a user (`POST /api/v1/runs/{id}/compensate`).

Every compensating call passes the policy engine; an automatic run skips calls whose policy requires approval (a user
running it manually counts as the approval). Results (`succeeded` / `failed` / `skipped`) are recorded per action.
Compensation is best effort: a failing compensation is recorded and the next one still runs.

Verified live (`examples/10-saga-compensation`): `POST reserve → charge → ship`, failure, then `DELETE ship → charge →
reserve`. Design: [design/saga-compensation.md](design/saga-compensation.md).
