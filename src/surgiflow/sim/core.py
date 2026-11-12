import heapq
import itertools
import json
from dataclasses import dataclass, field
from typing import List, Optional

## there are 3 entities surgery, operatingroom and simstate

## Surgery is the shared patient type (task 1.5): every module uses it.
## The generator (2.6) fills in everything except `hospital` (for emergencies),
## `arrival` stamping and `transfers`, which the simulator manages.
@dataclass
class Surgery:
    id: str
    duration: int                       # TRUE minutes; only the simulator reads this
    emergency: bool = False
    urgency: Optional[int] = None       # 1 critical, 2 urgent, 3 semi-urgent; None = elective
    procedure: str = "general"          # "general" | "cardiac" | "trauma"
    zone: Optional[int] = None          # where an emergency call came from
    needs_icu: bool = False
    expected_duration: Optional[int] = None   # what policies may see (defaults to duration)
    planned_room: Optional[int] = None  # electives: booked room
    planned_start: Optional[int] = None # electives: booked start minute
    arrival: int = 0                    # emergency: call time; elective: when it becomes available
    hospital: int = 0                   # hospital it is booked at / sent to
    transfers: int = 0                  # times moved between hospitals (2.11)

    def __post_init__(self):
        if self.expected_duration is None:
            self.expected_duration = self.duration

    @property
    def kind(self):
        return "emergency" if self.emergency else "elective"

## a room can be emoty or holds the surgery in progress
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
        return cls([Hospital(0, n_rooms)], ["Z0"], [[0]], [[0]])

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

    
## policy funtion to decide which surgery goes next
## will call any of the functions we hand it (SA, GA or RL)
## Scheduling policy contract (task 1.5): policy(hospital, clock) -> Surgery or None.
## It may read hospital.waiting, hospital.rooms, etc., but must not modify them.
## Returning None leaves the free room idle for now.
def fifo_policy(hospital, clock):
    """Pick the surgery that has been waiting longest."""
    return hospital.waiting[0]

#
class Simulator:
    def __init__(self, network, policy=fifo_policy):
        self.clock = 0
        self.network = network
        self.log = []
        self.policy = policy
        self._events = []
        self._tie = itertools.count()

    ##adds event to the heap as a tuple
    ## python sorts tuple left to right
    ## events order by time first
    ## if two events have the same time then it goes into tie number, to keep things in insertion order
    def schedule(self, time, kind, data=None):
        heapq.heappush(self._events, (time, next(self._tie), kind, data))

    ## public way to load a surgery
    def add_surgery(self, surgery, arrival_time=0, hospital=0):
        surgery.hospital = hospital
        self.schedule(arrival_time, "ARRIVAL", surgery)

    ## pop the ealiest event and set the clock its time
    ## if Arrival then stamp the arrival time and add the sugery to waiting
    ## if its END then set the room to empty
    def run(self, until=float("inf")):
        while self._events and self._events[0][0] <= until:
            self.clock, _, kind, data = heapq.heappop(self._events)
            if kind == "ARRIVAL":
                data.arrival = self.clock
                self.network.hospitals[data.hospital].waiting.append(data)
            elif kind == "END":
                data.current = None  # data is the room
            self._dispatch()

    ##runs after every event and fills any free room from the waiting list
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
                end = self.clock + s.duration
                self.log.append({
                    "surgery": s.id, "hospital": h.id, "room": room.id,
                    "kind": s.kind, "urgency": s.urgency, "procedure": s.procedure,
                    "arrival": s.arrival, "start": self.clock, "end": end,
                    "planned_start": s.planned_start, "transfers": s.transfers,
                })
                self.schedule(end, "END", room)
