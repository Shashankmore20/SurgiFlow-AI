"""Turns a finished simulation into "what was happening at minute t".

Pure Python (no matplotlib), so it can be tested in CI. The viewer
(viewer.py) only asks this class questions; it never touches the simulator.
"""
from __future__ import annotations

DAY_START_HOUR = 7          # minute 0 is shown as 07:00


def clock_label(minute):
    total = DAY_START_HOUR * 60 + int(minute)
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


class Timeline:
    def __init__(self, sim, patients, cfg):
        """sim: a Simulator after run(); patients: every Surgery loaded into it."""
        self.cfg = cfg
        self.horizon = cfg["horizon_min"]
        self.regular = cfg["regular_hours_min"]
        self.hospitals = sim.network.hospitals
        self.zones = sim.network.zones
        by_id = {p.id: p for p in patients}

        self.rows = []
        for r in sim.log:
            p = by_id.get(r["surgery"])
            row = dict(r)
            # room is busy until it is released (later than end if bed-blocked);
            # if the run stopped mid-surgery, use the planned end
            row["release"] = r["room_release"] if r["room_release"] is not None else r["end"]
            row["zone"] = p.zone if p else None
            row["bed"] = None
            if p is not None and p.needs_bed and r["room_release"] is not None:
                row["bed"] = (r["room_release"], r["room_release"] + p.bed_stay)
            self.rows.append(row)

        # (hospital, from, to): time each patient spent in a hospital's queue
        self.queue_spans = [(r["hospital"], r["arrival"], r["start"]) for r in self.rows]
        for h in self.hospitals:
            self.queue_spans += [(h.id, s.arrival, self.horizon) for s in h.waiting]

        # ambulance trips: (zone, hospital, call_time, arrival, urgency)
        self.trips = [(r["zone"], r["hospital"], r["call_time"], r["arrival"], r["urgency"])
                      for r in self.rows if r["emergency"] and r["zone"] is not None]
        cancelled = getattr(sim, "_cancelled", set())     # PR #57: cancelled in transit
        for _, _, kind, s in sim._events:
            if (kind == "ARRIVAL" and s.emergency and s.zone is not None
                    and s.id not in cancelled):
                eta = s.call_time + sim.network.travel_time(s.zone, s.hospital)
                self.trips.append((s.zone, s.hospital, s.call_time, eta, s.urgency))

        self.cancellations = list(sim.cancellations)
        self.unserved = len(sim.unserved())

    def state_at(self, t):
        """Snapshot of the network at minute t."""
        n = len(self.hospitals)
        waiting, beds, busy = [0] * n, [0] * n, [0] * n
        for h, a, b in self.queue_spans:
            if a <= t < b:
                waiting[h] += 1
        for r in self.rows:
            if r["start"] <= t < r["release"]:
                busy[r["hospital"]] += 1
            if r["bed"] and r["bed"][0] <= t < r["bed"][1]:
                beds[r["hospital"]] += 1
        ambulances = [(z, h, (t - c) / max(a - c, 1e-9), u)
                      for z, h, c, a, u in self.trips if c <= t < a]
        return {
            "waiting": waiting, "beds": beds, "busy": busy,
            "ambulances": ambulances,
            "started": sum(r["start"] <= t for r in self.rows),
            "cancelled": sum(c["time"] <= t for c in self.cancellations),
        }
