"""Animated, interactive replay of one simulated day (matplotlib).

Controls:  space = play/pause   right/left = faster/slower   home = restart
           drag the time slider to jump anywhere in the day.
Also exports the animation as a GIF (or MP4 if ffmpeg is installed).
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Rectangle
from matplotlib.widgets import Button, Slider

from .timeline import clock_label

URGENCY_COLOR = {1: "#d62728", 2: "#ff7f0e", 3: "#e3b505"}
ELECTIVE_COLOR = "#6f93c4"
BG = "white"
SPEEDS = [1, 2, 5, 10, 20, 40]          # simulated minutes per animation frame

# Display-only map positions (x, y) for base.json; other configs use a circle.
BASE_LAYOUT = {
    "hospitals": {"Central Trauma Center": (0.45, 0.45), "Riverside General": (0.85, 0.50),
                  "Northside Community": (0.45, 0.88)},
    "zones": {"Downtown": (0.22, 0.42), "East": (0.88, 0.22), "North": (0.18, 0.86),
              "Suburbs": (0.62, 0.08)},
}


def _layout(names, known):
    import math
    if all(n in known for n in names):
        return [known[n] for n in names]
    k = len(names)
    return [(0.5 + 0.38 * math.cos(2 * math.pi * i / k), 0.5 + 0.38 * math.sin(2 * math.pi * i / k))
            for i in range(k)]


class ReplayViewer:
    def __init__(self, timeline, title="SurgiFlow replay", cost=None):
        self.tl = timeline
        self.t = 0.0
        self.playing = True
        self.speed_i = 2
        self._syncing = False

        self.fig = plt.figure(figsize=(15, 8.4), facecolor=BG)
        self.fig.suptitle(title, fontsize=14, fontweight="bold", x=0.02, ha="left")
        if cost is not None:
            total, parts = cost
            shown = "  ".join(f"{k} {v:.0f}" for k, v in parts.items()
                              if k in ("wait", "delay", "overtime", "disruption", "unserved"))
            self.fig.text(0.02, 0.925, f"Day cost {total:.0f}   ({shown})", fontsize=10, color="#444")

        gs = self.fig.add_gridspec(2, 3, left=0.085, right=0.98, top=0.88, bottom=0.17,
                                   hspace=0.35, wspace=0.28, width_ratios=[1.35, 1.35, 1])
        self.ax_g = self.fig.add_subplot(gs[:, :2])
        self.ax_m = self.fig.add_subplot(gs[0, 2])
        self.ax_s = self.fig.add_subplot(gs[1, 2])

        self._draw_gantt()
        self._draw_map()
        self._draw_status()
        self._draw_controls()

        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self._render()

    # ---------------------------------------------------------------- static parts
    def _draw_gantt(self):
        ax, tl = self.ax_g, self.tl
        self.row_of, labels, y = {}, [], 0
        for h in tl.hospitals:
            for room in h.rooms:
                self.row_of[(h.id, room.id)] = y
                labels.append(f"{(h.name or f'H{h.id}').split()[0]} OR{room.id + 1}")
                y += 1
            y += 0.6                                      # gap between hospitals
        n_rows = y

        # after-hours shading sits above the curtain so it's always visible
        ax.axvspan(tl.regular, tl.horizon, color="#000", alpha=0.05, zorder=6, lw=0)
        ax.axvline(tl.regular, color="#888", lw=1, ls="--", zorder=6)
        ax.text(tl.regular + 8, -0.75, "after regular hours (on-call)", fontsize=8,
                color="#666", zorder=6)

        for r in tl.rows:
            yy = self.row_of[(r["hospital"], r["room"])]
            color = URGENCY_COLOR.get(r["urgency"], "#888") if r["emergency"] else ELECTIVE_COLOR
            ax.add_patch(Rectangle((r["start"], yy - 0.38), r["end"] - r["start"], 0.76,
                                   facecolor=color, edgecolor="white", lw=0.8, zorder=2))
            if r["release"] > r["end"]:                   # stuck waiting for a recovery bed
                ax.add_patch(Rectangle((r["end"], yy - 0.38), r["release"] - r["end"], 0.76,
                                       facecolor="white", edgecolor="#555", hatch="////",
                                       lw=0.6, zorder=2))
            if r["end"] - r["start"] >= 45:
                ax.text((r["start"] + r["end"]) / 2, yy, r["surgery"], ha="center",
                        va="center", fontsize=7, color="white", zorder=3)

        # the "curtain" hides the future; moving it is the animation
        self.curtain = Rectangle((0, -1), tl.horizon, n_rows + 1, facecolor=BG,
                                 edgecolor="none", zorder=4)
        ax.add_patch(self.curtain)
        self.now_line = ax.axvline(0, color="#222", lw=1.5, zorder=5)

        ax.set_xlim(0, tl.horizon)
        ax.set_ylim(n_rows - 0.4, -1.2)
        ax.set_yticks(list(self.row_of.values()))
        ax.set_yticklabels(labels, fontsize=9)
        ticks = list(range(0, tl.horizon + 1, 120))
        ax.set_xticks(ticks)
        ax.set_xticklabels([clock_label(m) for m in ticks], fontsize=9)
        ax.set_title("Operating rooms", loc="left", fontsize=11)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

        legend = [Rectangle((0, 0), 1, 1, color=ELECTIVE_COLOR, label="elective")]
        legend += [Rectangle((0, 0), 1, 1, color=c, label=f"emergency U{u}")
                   for u, c in URGENCY_COLOR.items()]
        legend.append(Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#555",
                                hatch="////", label="waiting for bed"))
        ax.legend(handles=legend, loc="lower right", fontsize=8, ncol=5, frameon=False,
                  bbox_to_anchor=(1, -0.13))

    def _draw_map(self):
        ax, tl = self.ax_m, self.tl
        self.h_pos = _layout([h.name for h in tl.hospitals], BASE_LAYOUT["hospitals"])
        self.z_pos = _layout(list(tl.zones), BASE_LAYOUT["zones"])
        for zx, zy in self.z_pos:
            for hx, hy in self.h_pos:
                ax.plot([zx, hx], [zy, hy], color="#e5e5e5", lw=0.8, zorder=0)
        for (x, y), name in zip(self.z_pos, tl.zones):
            ax.scatter(x, y, marker="s", s=60, color="#bbb", zorder=1)
            ax.text(x, y - 0.07, name, ha="center", fontsize=8, color="#777")
        for (x, y), h in zip(self.h_pos, tl.hospitals):
            ax.scatter(x, y, marker="P", s=260, color="#2d6cdf", zorder=2)
            caps = "/".join(c[0].upper() for c in h.capabilities)
            ax.text(x, y + 0.07, f"{(h.name or f'H{h.id}').split()[0]} ({caps})",
                    ha="center", fontsize=8, fontweight="bold")
        self.amb = ax.scatter([], [], s=55, zorder=3, edgecolor="black", linewidth=0.5)
        ax.set_xlim(-0.02, 1.08)
        ax.set_ylim(-0.05, 1.02)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title("Ambulances on the way", loc="left", fontsize=11)

    def _draw_status(self):
        ax, tl = self.ax_s, self.tl
        names = [(h.name or f"H{h.id}").split()[0] for h in tl.hospitals]
        n = len(names)
        ys = range(n)
        cap = max([h.n_rooms for h in tl.hospitals] + [h.recovery_beds for h in tl.hospitals] + [6])
        self.bar_busy = ax.barh([y - 0.25 for y in ys], [0] * n, height=0.22, color="#2d6cdf",
                                label="ORs busy")
        self.bar_wait = ax.barh(list(ys), [0] * n, height=0.22, color="#ff7f0e", label="waiting")
        self.bar_beds = ax.barh([y + 0.25 for y in ys], [0] * n, height=0.22, color="#2ca02c",
                                label="beds in use")
        for y, h in zip(ys, tl.hospitals):
            ax.plot([h.n_rooms] * 2, [y - 0.36, y - 0.14], color="#2d6cdf", lw=2)
            ax.plot([h.recovery_beds] * 2, [y + 0.14, y + 0.36], color="#2ca02c", lw=2)
        ax.set_yticks(list(ys))
        ax.set_yticklabels(names, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(0, cap + 1)
        ax.legend(fontsize=8, loc="lower right", frameon=False)
        ax.set_title("Right now (lines = capacity)", loc="left", fontsize=11)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        self.info = self.fig.text(0.68, 0.035, "", fontsize=10, family="monospace")
        self.clock = self.fig.text(0.98, 0.93, "", fontsize=22, fontweight="bold", ha="right")

    def _draw_controls(self):
        ax_sl = self.fig.add_axes([0.24, 0.05, 0.38, 0.03])
        self.slider = Slider(ax_sl, "", 0, self.tl.horizon, valinit=0, color="#2d6cdf")
        self.slider.valtext.set_visible(False)
        self.slider.on_changed(self._on_slide)
        self.btn_play = Button(self.fig.add_axes([0.06, 0.04, 0.07, 0.05]), "Pause")
        self.btn_play.on_clicked(lambda _: self._toggle())
        self.btn_speed = Button(self.fig.add_axes([0.14, 0.04, 0.08, 0.05]), "")
        self.btn_speed.on_clicked(lambda _: self._faster(wrap=True))
        self._label_speed()

    # ------------------------------------------------------------------ updates
    def _render(self):
        t, tl = self.t, self.tl
        st = tl.state_at(t)
        self.curtain.set_x(t)
        self.curtain.set_width(tl.horizon - t + 1)
        self.now_line.set_xdata([t, t])

        pts, colors = [], []
        for z, h, frac, u in st["ambulances"]:
            (zx, zy), (hx, hy) = self.z_pos[z], self.h_pos[h]
            pts.append((zx + (hx - zx) * frac, zy + (hy - zy) * frac))
            colors.append(URGENCY_COLOR.get(u, "#888"))
        self.amb.set_offsets(pts if pts else [[float("nan")] * 2])
        if colors:
            self.amb.set_color(colors)

        for bars, vals in ((self.bar_busy, st["busy"]), (self.bar_wait, st["waiting"]),
                           (self.bar_beds, st["beds"])):
            for b, v in zip(bars, vals):
                b.set_width(v)

        next_day = (7 * 60 + t) >= 24 * 60
        self.clock.set_text(clock_label(t) + ("  +1d" if next_day else ""))
        end_note = f"   unserved at end: {tl.unserved}" if t >= tl.horizon else ""
        self.info.set_text(f"started {st['started']:3d}   waiting {sum(st['waiting']):2d}   "
                           f"in ambulance {len(st['ambulances']):2d}   "
                           f"cancelled {st['cancelled']:2d}{end_note}")
        if not self._syncing:
            self._syncing = True
            self.slider.set_val(t)
            self._syncing = False

    def _step(self, _frame):
        if self.playing:
            self.t = min(self.t + SPEEDS[self.speed_i], self.tl.horizon)
            if self.t >= self.tl.horizon:
                self.playing = False
                self.btn_play.label.set_text("Play")
            self._render()

    def _on_slide(self, val):
        if not self._syncing:
            self.t = float(val)
            self._render()
            self.fig.canvas.draw_idle()

    def _toggle(self):
        if self.t >= self.tl.horizon:
            self.t = 0
        self.playing = not self.playing
        self.btn_play.label.set_text("Pause" if self.playing else "Play")

    def _faster(self, wrap=False):
        self.speed_i = (self.speed_i + 1) % len(SPEEDS) if wrap else min(self.speed_i + 1, len(SPEEDS) - 1)
        self._label_speed()

    def _label_speed(self):
        self.btn_speed.label.set_text(f"{SPEEDS[self.speed_i]} min/frame")

    def _on_key(self, event):
        if event.key == " ":
            self._toggle()
        elif event.key == "right":
            self._faster()
        elif event.key == "left":
            self.speed_i = max(self.speed_i - 1, 0)
            self._label_speed()
        elif event.key == "home":
            self.t = 0
            self._render()

    # ----------------------------------------------------------------- entry points
    def show(self):
        self.anim = FuncAnimation(self.fig, self._step, interval=40, cache_frame_data=False)
        plt.show()

    def save(self, path, minutes_per_frame=5, fps=20):
        """Export the whole day as a GIF (or .mp4 if ffmpeg is installed)."""
        self.playing = False
        frames = list(range(0, self.tl.horizon + 1, minutes_per_frame))

        def draw(t):
            self.t = t
            self._render()

        anim = FuncAnimation(self.fig, draw, frames=frames, cache_frame_data=False)
        if str(path).endswith(".gif"):
            from matplotlib.animation import PillowWriter
            anim.save(path, writer=PillowWriter(fps=fps))
        else:
            anim.save(path, fps=fps)

    def snapshot(self, path, t):
        self.t = t
        self._render()
        self.fig.savefig(path, dpi=110)
