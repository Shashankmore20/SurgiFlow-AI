import heapq
import itertools
from dataclasses import dataclass
from typing import Optional

from dataclasses import dataclass, field
from typing import List, Optional
## there are 3 entities surgery, operatingroom and simstate

##surgery has facts like: id, duration, priority, emergency, arrival time
##so we initialize here 
@dataclass
class Surgery:
    id: str
    duration: int            # minutes
    priority: int = 0        # higher = more urgent (unused by FIFO)
    emergency: bool = False
    arrival: int = 0         # filled in when the surgery arrives
    hospital: int = 0        # which hospital is booked at 

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
    rooms: List[OperatingRoom] = field(default_factory=list)
    waiting: List[Surgery] = field(default_factory=list)

    def __post_init__(self):
        self.rooms = [OperatingRoom(i) for i in range(self.n_rooms)]


class Network:
    """Hospitals plus a travel-time matrix (minutes) between them."""

    def __init__(self, hospitals, travel):
        n = len(hospitals)
        if len(travel) != n or any(len(row) != n for row in travel):
            raise ValueError("travel matrix must be n x n")
        if any(travel[i][i] != 0 for i in range(n)):
            raise ValueError("travel time from a hospital to itself must be 0")
        if any(t < 0 for row in travel for t in row):
            raise ValueError("travel times must be non-negative")
        self.hospitals = hospitals
        self.travel = travel

    @classmethod
    def single(cls, n_rooms):
        return cls([Hospital(0, n_rooms)], [[0]])

    def travel_time(self, a, b):
        return self.travel[a][b]

## policy funtion to decide which surgery goes next
## will call any of the functions we hand it (SA, GA or RL)
def fifo_policy(waiting, clock):
    """Pick the surgery that has been waiting longest."""
    return waiting[0]

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
                    if room.current is None and h.waiting:
                        s = self.policy(h.waiting, self.clock)
                        h.waiting.remove(s)
                        room.current = s
                        end = self.clock + s.duration
                        self.log.append({
                            "surgery": s.id, "hospital": h.id, "room": room.id,
                            "arrival": s.arrival, "start": self.clock, "end": end,
                        })
                        self.schedule(end, "END", room)