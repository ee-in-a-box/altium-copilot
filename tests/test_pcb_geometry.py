import pytest

from server.services.pcb_geometry import (
    edge_to_edge,
    parallel_overlap,
    point_in_polygon,
    point_seg_distance,
    seg_seg_distance,
)


def test_point_seg_distance():
    assert point_seg_distance(0, 5, 0, 0, 10, 0) == 5.0
    assert point_seg_distance(-3, 4, 0, 0, 10, 0) == 5.0
    assert point_seg_distance(5, 0, 0, 0, 10, 0) == 0.0


def test_seg_seg_distance_parallel():
    assert seg_seg_distance(0, 0, 10, 0, 0, 3, 10, 3) == 3.0


def test_seg_seg_distance_crossing_is_zero():
    assert seg_seg_distance(0, 0, 10, 10, 0, 10, 10, 0) == 0.0


def test_seg_seg_distance_collinear_gap():
    assert seg_seg_distance(0, 0, 10, 0, 15, 0, 25, 0) == 5.0


def test_seg_seg_distance_degenerate_points():
    assert seg_seg_distance(1, 1, 1, 1, 4, 5, 4, 5) == 5.0


def test_edge_to_edge_subtracts_half_widths():
    assert edge_to_edge(3.0, 2.0, 1.0) == 1.5
    assert edge_to_edge(1.0, 2.0, 1.0) == 0.0


def test_parallel_overlap_full():
    assert parallel_overlap(0, 0, 10, 0, 2, 1, 8, 1) == pytest.approx(6.0)


def test_parallel_overlap_none_for_perpendicular():
    assert parallel_overlap(0, 0, 10, 0, 5, -5, 5, 5) == pytest.approx(
        0.0,
        abs=0.5,
    )


def test_parallel_overlap_partial():
    assert parallel_overlap(0, 0, 10, 0, 5, 1, 15, 1) == pytest.approx(5.0)


def test_point_in_polygon():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, square) is True
    assert point_in_polygon(15, 5, square) is False
    assert point_in_polygon(-1, -1, square) is False
