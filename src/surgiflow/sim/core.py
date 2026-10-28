import heapq
import itertools
from dataclasses import dataclass
from typing import Optional

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

## a room can be emoty or holds the surgery in progress
@dataclass
class OperatingRoom:
    id: int
    current: Optional[Surgery] = None

## policy funtion to decide which surgery goes next
## will call any of the functions we hand it (SA, GA or RL)
def fifo_policy(waiting, clock):
    """Pick the surgery that has been waiting longest."""
    return waiting[0]

#
class Simulator:
    def __init__(self, n_rooms, policy=fifo_policy):
        self.clock = 0
        self.rooms = [OperatingRoom(i) for i in range(n_rooms)]
        self.waiting = []
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
    def add_surgery(self, surgery, arrival_time=0):
        self.schedule(arrival_time, "ARRIVAL", surgery)

    ## pop the ealiest event and set the clock its time
    ## if Arrival then stamp the arrival time and add the sugery to waiting
    ## if its END then set the room to empty
    def run(self, until=float("inf")):
        while self._events and self._events[0][0] <= until:
            self.clock, _, kind, data = heapq.heappop(self._events)
            if kind == "ARRIVAL":
                data.arrival = self.clock
                self.waiting.append(data)
            elif kind == "END":
                data.current = None  # data is the room
            self._dispatch()

    ##runs after every event and fills any free room from the waiting list
    def _dispatch(self):
        for room in self.rooms:
            if room.current is None and self.waiting:
                s = self.policy(self.waiting, self.clock)
                self.waiting.remove(s)
                room.current = s
                end = self.clock + s.duration
                self.log.append({
                    "surgery": s.id, "room": room.id,
                    "arrival": s.arrival, "start": self.clock, "end": end,
                })
                self.schedule(end, "END", room)