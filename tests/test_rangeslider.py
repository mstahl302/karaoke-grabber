import tkinter as tk

import pytest

from karaokegrab import rangeslider as rs


# --- pure math ----------------------------------------------------------------

def test_track_maps_both_ways():
    tr = rs.Track(0, 300, 20, 620)          # 2 px per second
    assert tr.to_x(0) == 20 and tr.to_x(300) == 620 and tr.to_x(150) == 320
    assert tr.to_t(320) == 150
    for t in (0, 4.5, 123.25, 300):
        assert tr.to_t(tr.to_x(t)) == pytest.approx(t)


def test_track_clamps_outside_values():
    tr = rs.Track(10, 20, 0, 100)
    assert tr.to_x(-5) == 0 and tr.to_x(99) == 100
    assert tr.to_t(-50) == 10 and tr.to_t(500) == 20


def test_track_degenerate_ranges():
    assert rs.Track(5, 5, 0, 100).to_x(5) == 0
    assert rs.Track(0, 10, 50, 50).to_t(70) == 0


def test_handles_cannot_cross_and_keep_the_gap():
    assert rs.move_handle(0, 50, 10, 40, 0, 100, gap=1) == (39, 40)
    assert rs.move_handle(1, 5, 10, 40, 0, 100, gap=1) == (10, 11)
    assert rs.move_handle(0, -9, 10, 40, 0, 100, gap=1) == (0, 40)
    assert rs.move_handle(1, 999, 10, 40, 0, 100, gap=1) == (10, 100)


def test_fade_handles_may_meet():
    assert rs.move_handle(0, 70, 10, 60, 0, 100, gap=0) == (60, 60)


def test_gap_larger_than_the_range_is_capped():
    assert rs.move_handle(1, 0.2, 0, 0.5, 0, 0.5, gap=1) == (0, 0.5)


@pytest.mark.parametrize("x, expected", [
    (100, 0), (108, 0), (113, None), (300, 1), (290, 1), (200, None),
])
def test_pick_handle(x, expected):
    assert rs.pick_handle(x, 100, 300, grab=12) == expected


def test_pick_overlapping_handles_by_side():
    assert rs.pick_handle(95, 100, 100) == 0
    assert rs.pick_handle(105, 100, 100) == 1


def test_blend():
    assert rs.blend("#000000", "#ffffff", 0) == "#000000"
    assert rs.blend("#000000", "#ffffff", 1) == "#ffffff"
    assert rs.blend("#000000", "#ffffff", 0.5) == "#808080"


# --- the widget, driven with synthetic mouse events ---------------------------

@pytest.fixture
def slider():
    root = tk.Tk()
    root.geometry("660x120")
    seen = {"change": [], "seek": []}
    s = rs.RangeSlider(root, min_gap=1.0,
                       on_change=lambda a, b, final: seen["change"].append((a, b, final)),
                       on_seek=seen["seek"].append)
    s.pack(fill="x")
    s.set_range(0, 300)
    s.set_values(30, 270)
    s.set_enabled(True)
    root.update()
    s.seen = seen
    yield s
    root.destroy()


def _drag(s, x0, x1):
    y = s.winfo_height() // 2
    s.event_generate("<ButtonPress-1>", x=int(x0), y=y)
    s.event_generate("<B1-Motion>", x=int(x1), y=y)
    s.event_generate("<ButtonRelease-1>", x=int(x1), y=y)


def test_dragging_a_handle_reports_changes_then_a_final(slider):
    tr = slider.track()
    _drag(slider, tr.to_x(30), tr.to_x(60))
    a, b = slider.a, slider.b
    assert a == pytest.approx(60, abs=1) and b == 270
    assert slider.seen["change"][-1] == (a, b, True)
    assert slider.seen["change"][0][2] is False
    assert slider.seen["seek"] == []


def test_dragging_past_the_other_handle_stops_at_the_gap(slider):
    tr = slider.track()
    _drag(slider, tr.to_x(270), tr.to_x(0))
    assert slider.b == pytest.approx(31)


def test_click_on_the_track_seeks(slider):
    tr = slider.track()
    _drag(slider, tr.to_x(150), tr.to_x(150))
    assert slider.seen["seek"] == [pytest.approx(150, abs=1)]
    assert slider.seen["change"] == []


def test_disabled_slider_ignores_the_mouse(slider):
    slider.set_enabled(False)
    tr = slider.track()
    _drag(slider, tr.to_x(30), tr.to_x(90))
    assert slider.a == 30
    assert slider.seen == {"change": [], "seek": []}


def test_cursor_is_drawn_only_inside_the_range(slider):
    slider.set_cursor(100)
    assert slider.find_withtag("cursor")
    slider.set_cursor(400)
    assert not slider.find_withtag("cursor")
    slider.set_cursor(None)
    assert not slider.find_withtag("cursor")
