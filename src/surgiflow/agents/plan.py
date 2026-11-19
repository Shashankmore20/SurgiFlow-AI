from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

# this is a type alias for the rooms structure, 
# which is a tuple of tuples of tuples of strings. 
# Each string represents an elective ID, and the structure 
# represents the organization of electives in different rooms across hospitals.
Rooms = Tuple[Tuple[Tuple[str, ...], ...], ...]   # 

# the Plan class represents a surgical plan, which includes
# 1. the organization of electives in rooms, 
# 2. the duration of each elective, 
# 3. a limit on the total planned minutes per room.
@dataclass(frozen=True, eq=False)
class Plan:
    rooms: Rooms
    duration: Dict[str, int]   # id -> planned minutes (shared by all plans, read-only)
    limit: int                 # max planned minutes per room

    @classmethod
    def from_electives(cls, electives, config):
        """The generator's default plan (D11), rebuilt from planned_room/planned_start."""
        rooms = [[[] for _ in range(h["n_or"])] for h in config["hospitals"]]
        for s in sorted(electives, key=lambda s: (s.hospital, s.planned_room, s.planned_start)):
            rooms[s.hospital][s.planned_room].append(s.id)
        return cls(
            rooms=tuple(tuple(tuple(r) for r in h) for h in rooms),
            duration={s.id: s.duration for s in electives},
            limit=config["regular_hours_min"],
        )

## reading from a plan 
    def load(self, h, r):
        """Planned minutes in room r of hospital h."""
        return sum(self.duration[i] for i in self.rooms[h][r])

    def starts(self):
        """{id: (hospital, room, planned start)}, back to back from minute 0."""
        out = {}
        for h, rooms in enumerate(self.rooms):
            for r, ids in enumerate(rooms):
                t = 0
                for i in ids:
                    out[i] = (h, r, t)
                    t += self.duration[i]
        return out

    def is_valid(self):
        ids = [i for rooms in self.rooms for ids in rooms for i in ids]
        return (len(ids) == len(set(ids)) == len(self.duration)
                and all(self.load(h, r) <= self.limit
                        for h, rooms in enumerate(self.rooms) for r in range(len(rooms))))

## picking a move 
    def neighbour(self, rng):
            """One random move. Returns a new Plan, or None if the move picked is
            impossible here or would plan a room past regular hours."""
            move = rng.choice((self._swap_within, self._swap_between, self._move))
            return move(rng)

    ##swap within a room
    def _swap_within(self, rng):
        """Swap the order of two cases in one room (the room's load doesn't change)."""
        options = [(h, r) for h, rooms in enumerate(self.rooms)
                    for r, ids in enumerate(rooms) if len(ids) >= 2]
        if not options:
            return None
        h, r = rng.choice(options)
        ids = list(self.rooms[h][r])
        i, j = rng.sample(range(len(ids)), 2)
        if self.duration[ids[i]] == self.duration[ids[j]]:
            return None                    # same length: start times wouldn't change
        ids[i], ids[j] = ids[j], ids[i]
        return self._replace(h, {r: ids})

    ##swap between rooms
    def _swap_between(self, rng):
        """Swap two cases between two rooms of the same hospital."""
        options = [h for h, rooms in enumerate(self.rooms)
                    if sum(1 for ids in rooms if ids) >= 2]
        if not options:
            return None
        h = rng.choice(options)
        a, b = rng.sample([r for r, ids in enumerate(self.rooms[h]) if ids], 2)
        ra, rb = list(self.rooms[h][a]), list(self.rooms[h][b])
        i, j = rng.randrange(len(ra)), rng.randrange(len(rb))
        if self.duration[ra[i]] == self.duration[rb[j]]:
            return None                    # same length: start times wouldn't change
        ra[i], rb[j] = rb[j], ra[i]
        if not (self._fits(ra) and self._fits(rb)):
            return None
        return self._replace(h, {a: ra, b: rb})

    #move a case to another room
    def _move(self, rng):
        """Take one case out of a room and insert it into another room of the
        same hospital, at a random position."""
        options = [h for h, rooms in enumerate(self.rooms)
                    if len(rooms) >= 2 and any(rooms)]
        if not options:
            return None
        h = rng.choice(options)
        src = rng.choice([r for r, ids in enumerate(self.rooms[h]) if ids])
        dst = rng.choice([r for r in range(len(self.rooms[h])) if r != src])
        rs, rd = list(self.rooms[h][src]), list(self.rooms[h][dst])
        case = rs.pop(rng.randrange(len(rs)))
        rd.insert(rng.randrange(len(rd) + 1), case)
        if not self._fits(rd):
            return None
        return self._replace(h, {src: rs, dst: rd})

    ##helpers 

    def _fits(self, ids):
        return sum(self.duration[i] for i in ids) <= self.limit

    def _replace(self, h, changes):
        """New Plan with rooms[h][r] = ids for each r in changes."""
        rooms_h = list(self.rooms[h])
        for r, ids in changes.items():
            rooms_h[r] = tuple(ids)
        rooms = self.rooms[:h] + (tuple(rooms_h),) + self.rooms[h + 1:]
        return Plan(rooms, self.duration, self.limit)