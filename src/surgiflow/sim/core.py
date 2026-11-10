import heapq
import itertools
import json
from dataclasses import dataclass, field
from typing import List, Optional

## entities: Surgery, OperatingRoom, Hospital and Network

## surgery has facts like: id, duration, priority, emergency, arrival time
## so we initialize here
@dataclass
class Surgery:
    id: str
    duration: int            # planned minutes
    priority: int = 0        # higher = more urgent (unused by FIFO)
    emergency: bool = False
    arrival: int = 0         # filled in when the surgery arrives at its hospital
    hospital: int = 0        # which hospital it is booked at
    actual_duration: Optional[int] = None  # real length; None = same as duration
    procedure: str = "general"             # general / cardiac / trauma
    call_time: Optional[int] = None        # emergencies: when the call came in
    max_wait: Optional[int] = None         # emergencies: max acceptable wait (min)
    needs_bed: bool = False                # needs a recovery/ICU bed after surgery
    bed_stay: int = 0                      # minutes it will occupy that bed

## a room can be empty or holds the surgery in progress
@dataclass
class OperatingRoom:
    id: int
    current: Optional[Surgery] = None

@dataclass
class Hospital:
    id: int
    n_rooms: int
    recovery_beds: int = 0   # capacity only for now; enforced in 2.5
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


## policy function to decide which surgery goes next
## will call any of the functions we hand it (SA, GA or RL)
def fifo_policy(waiting, clock):
    """Pick the surgery that has been waiting longest."""
    return waiting[0]


class Simulator:
    def __init__(self, network, policy=fifo_policy):
        self.clock = 0
        self.network = network
        self.log = []
        self.cancellations = []
        self.policy = policy
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
        """Ambulance goes to the nearest capable hospital; the patient shows up
        there after the travel time. Returns the chosen hospital id."""
        surgery.emergency = True
        surgery.call_time = call_time
        hospital = self.network.nearest_capable(zone, surgery.procedure)
        arrive = call_time + self.network.travel_time(zone, hospital)
        self.add_surgery(surgery, arrive, hospital)
        return hospital

    def cancel_surgery(self, surgery, time):
        self.schedule(time, "CANCEL", surgery)

    ## pop the earliest event and set the clock to its time
    ## ARRIVAL: stamp the arrival time and add the surgery to its hospital's queue
    ## END: set the room to empty
    ## CANCEL: drop the surgery from the queue (too late if it already started)
    def run(self, until=float("inf")):
        while self._events and self._events[0][0] <= until:
            self.clock, _, kind, data = heapq.heappop(self._events)
            if kind == "ARRIVAL":
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

    ## runs after every event and fills any free room from the waiting list
    def _dispatch(self):
        for h in self.network.hospitals:
            for room in h.rooms:
                if room.current is None and h.waiting:
                    s = self.policy(h.waiting, self.clock)
                    h.waiting.remove(s)
                    room.current = s
                    actual = s.actual_duration if s.actual_duration is not None else s.duration
                    end = self.clock + actual
                    row = {
                        "surgery": s.id, "hospital": h.id, "room": room.id,
                        "arrival": s.arrival, "start": self.clock, "end": end,
                        "planned": s.duration, "actual": actual,
                        "emergency": s.emergency,
                        "call_time": s.call_time if s.call_time is not None else s.arrival,
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