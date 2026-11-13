# Pipeline and ownership (task 1.5)

All randomness happens in the generator. The simulator is deterministic, so
every method is scored on exactly the same days.

```mermaid
flowchart LR
  C["configs/base.json"] --> G["Generator (2.6)<br/>config + seed"]
  G --> I["Instance<br/>electives + emergencies<br/>(true durations hidden)"]
  I --> S["Simulator (2.x)<br/>no random numbers"]
  A["Allocation policy<br/>allocate(patient, network, clock)<br/>→ hospital id"] -.-> S
  P["Scheduling policy<br/>policy(hospital, clock)<br/>→ surgery or None"] -.-> S
  S --> L["Log<br/>one record per surgery"]
  L --> O["Objective (1.6)<br/>→ cost + components"]
  C --> O
  style A fill:#2d6cdf,color:#fff
  style P fill:#2d6cdf,color:#fff
```

Blue boxes are the plug-ins: baselines (2.7, 2.8), SA/GA (3.x), and RL (4.x) all
provide these same two functions.
