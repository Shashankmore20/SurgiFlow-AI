import heapq
import itertools
import json
from dataclasses import dataclass, field
from typing import List, Optional

## entities: Surgery, OperatingRoom, Hospital and Network

## Surgery is the shared patient type (task 1.5); every module uses it.
## Policies may read everything EXCEPT actual_duration (the hidden true length).
@dataclass
class Surgery:
    id: str
    duration: int            # planned/expected minutes (what policies see)
    priority: int = 0        # legacy; use urgency instead
    emergency: bool = False
    arrival: int = 0         # filled in when the patient reaches its hospital
    hospital: int = 0        # hospital it is booked at / sent to
    actual_duration: Optional[int] = None  # true length; None = same as duration (hidden from policies)
    procedure: str = "general"             # general / cardiac / trauma
    call_time: Optional[int] = None        # emergencies: when the call came in
    max_wait: Optional[int] = None         # emergencies: max acceptable wait (min)
    needs_bed: bool = False                # needs a recovery/ICU bed after surgery
    bed_stay: int = 0                      # minutes it will occupy that bed
    urgency: Optional[int] = None          # 1 critical, 2 urgent, 3 semi-urgent; None = elective
    zone: Optional[int] = None             # emergencies: where the call came from
    planned_room: Optional[int] = None     # electives: booked room
    planned_start: Optional[int] = None    # electives: booked start minute
    transfers: int = 0                     # times moved between hospitals (2.11)

    @property
    def kind(self):
        return "emergency" if self.emergency else "elective"

## a room can be empty or holds the surgery in progress
@dataclass
class OperatingRoom:
    id: int
    current: Optional[Surgery] = None

@dataclass
class Hospital:
    id: int
    n_rooms: int
    recovery_beds: int = 0
    name: str = ""
    capabilities: List[str] = field(default_factory=list)
    rooms: List[OperatingRoom] = field(default_factory=list)
    waiting: List[Surgery] = field(default_factory=list)
    beds_in_use: int = 0
    blocked: List[OperatingRoom] = field(default_factory=list)  # rooms stuck waiting for a bed

    def __post_init__(self):
        self.rooms = [OperatingRoom(i) for i in range(self.n_rooms)]


class Network:
    """Hospitals plus two travel tables (minutes).

    travel_time_min:   zones x hospitals (sending an emergency patient)
    transfer_time_min: hospitals x hospitals (moving a waiting patient)
    """

    def __init__(self, hospitals, zones, travel_time_min, transfer_time_min=None):
        n_h, n_z = len(hospitals), len(zones)
        if [h.id for h in hospitals] != list(range(n_h)):
            raise ValueError("hospital ids must be 0..n-1 in order")

        if len(travel_time_min) != n_z or any(len(r) != n_h for r in travel_time_min):
            raise ValueError("travel_time_min must be zones x hospitals")
        if any(t < 0 for row in travel_time_min for t in row):
            raise ValueError("travel_time_min must be non-negative")

        if transfer_time_min is not None:
            if len(transfer_time_min) != n_h or any(len(r) != n_h for r in transfer_time_min):
                raise ValueError("transfer_time_min must be hospitals x hospitals")
            if any(transfer_time_min[i][i] != 0 for i in range(n_h)):
                raise ValueError("transfer time from a hospital to itself must be 0")
            if any(t < 0 for row in transfer_time_min for t in row):
                raise ValueError("transfer_time_min must be non-negative")

        self.hospitals = hospitals
        self.zones = zones
        self.travel_time_min = travel_time_min
        self.transfer_time_min = transfer_time_min

    @classmethod
    def single(cls, n_rooms):
        everything = ["general", "cardiac", "trauma"]
        return cls([Hospital(0, n_rooms, capabilities=everything)], ["Z0"], [[0]], [[0]])

    @classmethod
    def from_config(cls, path):
        with open(path) as f:
            cfg = json.load(f)
        hospitals = [
            Hospital(id=h["id"], n_rooms=h["n_or"], recovery_beds=h["n_icu_beds"],
                     name=h["name"], capabilities=h["capabilities"])
            for h in cfg["hospitals"]
        ]
        return cls(hospitals, cfg["zones"], cfg["travel_time_min"],
                   cfg.get("transfer_time_min"))

    def travel_time(self, zone, hospital):
        return self.travel_time_min[zone][hospital]

    def transfer_time(self, a, b):
        if self.transfer_time_min is None:
            raise ValueError("transfer_time_min was not provided")
        return self.transfer_time_min[a][b]

    def nearest_capable(self, zone, capability):
        """Closest hospital (by ambulance time) that can do this procedure type."""
        options = [h.id for h in self.hospitals if capability in h.capabilities]
        if not options:
            raise ValueError(f"no hospital can handle '{capability}'")
        return min(options, key=lambda h: self.travel_time_min[zone][h])


## Scheduling policy (task 1.5): policy(hospital, clock) -> Surgery or None.
## It may read hospital.waiting, hospital.rooms, etc., but must not modify them.
## Returning None leaves the free room idle for now. SA/GA/RL plug in here.
def fifo_policy(hospital, clock):
    """Pick the surgery that has been waiting longest."""
    return hospital.waiting[0]


## Allocation policy (task 1.5): allocate(patient, network, clock) -> hospital id.
## Called when an emergency call comes in. Baselines (2.8) and RL plug in here.
def nearest_capable_policy(patient, network, clock):
    """Send the patient to the closest hospital that can do the procedure."""
    return network.nearest_capable(patient.zone, patient.procedure)


class Simulator:
    def __init__(self, network, policy=fifo_policy, allocate=nearest_capable_policy):
        self.clock = 0
        self.network = network
        self.log = []
        self.cancellations = []
        self.policy = policy
        self.allocate = allocate
        self._events = []
        self._tie = itertools.count()
        self._rows = {}          # surgery id -> its log row

    ## adds event to the heap as a tuple
    ## python sorts tuples left to right, so events order by time first
    ## if two events have the same time, the tie number keeps insertion order
    def schedule(self, time, kind, data=None):
        heapq.heappush(self._events, (time, next(self._tie), kind, data))

    ## public way to load a surgery
    def add_surgery(self, surgery, arrival_time=0, hospital=0):
        surgery.hospital = hospital
        self.schedule(arrival_time, "ARRIVAL", surgery)

    def add_emergency(self, surgery, call_time, zone):
        """The call comes in at call_time. At that moment the allocation policy
        picks a hospital (seeing the network as it is then), and the patient
        arrives there after the ambulance travel time."""
        surgery.emergency = True
        surgery.call_time = call_time
        surgery.zone = zone
        self.schedule(call_time, "CALL", surgery)

    def cancel_surgery(self, surgery, time):
        self.schedule(time, "CANCEL", surgery)

    ## pop the earliest event and set the clock to its time
    ## CALL: allocation policy picks a hospital, patient arrives after travel time
    ## ARRIVAL: stamp the arrival time and add the surgery to its hospital's queue
    ## END: surgery done (patient moves to a bed or blocks the room)
    ## BED_FREE: a recovery bed opens up
    ## CANCEL: drop the surgery from the queue (too late if it already started)
    def run(self, until=float("inf")):
        while self._events and self._events[0][0] <= until:
            self.clock, _, kind, data = heapq.heappop(self._events)
            if kind == "CALL":
                self._on_call(data)
            elif kind == "ARRIVAL":
                data.arrival = self.clock
                self.network.hospitals[data.hospital].waiting.append(data)
            elif kind == "END":
                self._on_surgery_end(data)  # data is the room
            elif kind == "BED_FREE":
                self._on_bed_free(data)     # data is the hospital
            elif kind == "CANCEL":
                h = self.network.hospitals[data.hospital]
                if data in h.waiting:   # too late if already started
                    h.waiting.remove(data)
                    self.cancellations.append(
                        {"surgery": data.id, "hospital": h.id, "time": self.clock})
            self._dispatch()

    ## patients who never got surgery: still in a queue, or still on their way
    ## (a CALL/ARRIVAL event that hadn't happened yet when run() stopped).
    ## Cancelled surgeries are not included. The objective penalizes these (D10).
    def unserved(self):
        out = [s for h in self.network.hospitals for s in h.waiting]
        out += [data for _, _, kind, data in self._events if kind in ("CALL", "ARRIVAL")]
        return out

    def _on_call(self, s):
        h = self.allocate(s, self.network, self.clock)
        if s.procedure not in self.network.hospitals[h].capabilities:
            raise ValueError(f"allocation sent {s.id} ({s.procedure}) to hospital {h}, "
                             "which can't do that procedure")
        s.hospital = h
        self.schedule(self.clock + self.network.travel_time(s.zone, h), "ARRIVAL", s)

    ## runs after every event and fills any free room from the waiting list
    def _dispatch(self):
        for h in self.network.hospitals:
            for room in h.rooms:
                if room.current is not None or not h.waiting:
                    continue
                s = self.policy(h, self.clock)
                if s is None:          # policy chose to keep this room free
                    break
                h.waiting.remove(s)
                room.current = s
                actual = s.actual_duration if s.actual_duration is not None else s.duration
                end = self.clock + actual
                row = {
                    "surgery": s.id, "hospital": h.id, "room": room.id,
                    "kind": s.kind, "emergency": s.emergency,
                    "urgency": s.urgency, "procedure": s.procedure,
                    "call_time": s.call_time if s.call_time is not None else s.arrival,
                    "arrival": s.arrival, "start": self.clock, "end": end,
                    "planned": s.duration, "actual": actual,
                    "planned_start": s.planned_start, "transfers": s.transfers,
                    "room_release": None, "blocked_min": 0,
                }
                self.log.append(row)
                self._rows[s.id] = row
                self.schedule(end, "END", room)

    ## surgery is over. If the patient needs a bed and one is free, they move to it
    ## and the room is released. If no bed is free they stay in the room (blocking
    ## it) until one frees up.
    def _on_surgery_end(self, room):
        s = room.current
        h = self.network.hospitals[s.hospital]
        if s.needs_bed and h.beds_in_use >= h.recovery_beds:
            h.blocked.append(room)
        else:
            if s.needs_bed:
                self._take_bed(h, s)
            self._release_room(room, s)

    def _take_bed(self, h, s):
        h.beds_in_use += 1
        self.schedule(self.clock + s.bed_stay, "BED_FREE", h)

    def _release_room(self, room, s):
        room.current = None
        row = self._rows[s.id]
        row["room_release"] = self.clock
        row["blocked_min"] = self.clock - row["end"]

    ## a bed opens up: the longest-blocked patient (if any) takes it right away
    def _on_bed_free(self, h):
        h.beds_in_use -= 1
        if h.blocked:
            room = h.blocked.pop(0)
            s = room.current
            self._take_bed(h, s)
            self._release_room(room, s)
