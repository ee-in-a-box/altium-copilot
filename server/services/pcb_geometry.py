"""Two-dimensional geometry helpers for PCB proximity queries."""

import math


def point_seg_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    """Return the minimum distance from a point to a line segment."""
    dx = x2 - x1
    dy = y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - x1, py - y1)
    projection = ((px - x1) * dx + (py - y1) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    return math.hypot(
        px - (x1 + projection * dx),
        py - (y1 + projection * dy),
    )


def _segments_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    def orientation(ox, oy, px, py, qx, qy):
        value = (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
        return 0 if value == 0 else (1 if value > 0 else -1)

    first = orientation(ax, ay, bx, by, cx, cy)
    second = orientation(ax, ay, bx, by, dx, dy)
    third = orientation(cx, cy, dx, dy, ax, ay)
    fourth = orientation(cx, cy, dx, dy, bx, by)
    return first != second and third != fourth


def seg_seg_distance(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> float:
    """Return the minimum centerline distance between two segments."""
    if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
        return 0.0
    return min(
        point_seg_distance(ax, ay, cx, cy, dx, dy),
        point_seg_distance(bx, by, cx, cy, dx, dy),
        point_seg_distance(cx, cy, ax, ay, bx, by),
        point_seg_distance(dx, dy, ax, ay, bx, by),
    )


def edge_to_edge(
    centerline_distance: float,
    width_a: float,
    width_b: float,
) -> float:
    """Convert centerline separation to copper edge-to-edge clearance."""
    return max(0.0, centerline_distance - (width_a + width_b) / 2.0)


def parallel_overlap(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> float:
    """Approximate coupled run length using projected segment overlap."""
    unit_x = bx - ax
    unit_y = by - ay
    first_length = math.hypot(unit_x, unit_y)
    if first_length == 0:
        return 0.0
    unit_x /= first_length
    unit_y /= first_length
    projection_1 = (cx - ax) * unit_x + (cy - ay) * unit_y
    projection_2 = (dx - ax) * unit_x + (dy - ay) * unit_y
    low = min(projection_1, projection_2)
    high = max(projection_1, projection_2)
    overlap = max(0.0, min(high, first_length) - max(low, 0.0))
    second_length = math.hypot(dx - cx, dy - cy)
    if second_length == 0 or overlap == 0:
        return 0.0
    cosine = abs(
        (dx - cx) * unit_x + (dy - cy) * unit_y
    ) / second_length
    return overlap * cosine


def point_in_polygon(
    px: float,
    py: float,
    vertices: list[tuple[float, float]],
) -> bool:
    """Return whether a point is inside a polygon using ray casting."""
    inside = False
    for index, (x1, y1) in enumerate(vertices):
        x2, y2 = vertices[(index + 1) % len(vertices)]
        if (y1 > py) != (y2 > py):
            intersection_x = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < intersection_x:
                inside = not inside
    return inside


def oriented_rect_vertices(
    cx: float,
    cy: float,
    width: float,
    height: float,
    rotation_deg: float,
) -> list[tuple[float, float]]:
    """Return the four vertices of a centered, rotated rectangle."""
    angle = math.radians(rotation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    vertices = []
    for local_x, local_y in (
        (-width / 2.0, -height / 2.0),
        (width / 2.0, -height / 2.0),
        (width / 2.0, height / 2.0),
        (-width / 2.0, height / 2.0),
    ):
        vertices.append(
            (
                cx + local_x * cosine - local_y * sine,
                cy + local_x * sine + local_y * cosine,
            )
        )
    return vertices


def point_polygon_distance(
    px: float,
    py: float,
    vertices: list[tuple[float, float]],
) -> float:
    """Return minimum distance from a point to a filled polygon."""
    if not vertices:
        return math.inf
    if point_in_polygon(px, py, vertices):
        return 0.0
    closed = vertices + [vertices[0]]
    return min(
        point_seg_distance(px, py, x1, y1, x2, y2)
        for (x1, y1), (x2, y2) in zip(closed, closed[1:])
    )


def seg_polygon_distance(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    vertices: list[tuple[float, float]],
) -> float:
    """Return minimum distance from a segment to a filled polygon."""
    if not vertices:
        return math.inf
    if (
        point_in_polygon(x1, y1, vertices)
        or point_in_polygon(x2, y2, vertices)
    ):
        return 0.0
    closed = vertices + [vertices[0]]
    return min(
        seg_seg_distance(x1, y1, x2, y2, ax, ay, bx, by)
        for (ax, ay), (bx, by) in zip(closed, closed[1:])
    )


def polygon_polygon_distance(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
) -> float:
    """Return minimum distance between two filled polygons."""
    if not first or not second:
        return math.inf
    if (
        point_in_polygon(*first[0], second)
        or point_in_polygon(*second[0], first)
    ):
        return 0.0
    first_closed = first + [first[0]]
    second_closed = second + [second[0]]
    return min(
        seg_seg_distance(ax, ay, bx, by, cx, cy, dx, dy)
        for (ax, ay), (bx, by) in zip(
            first_closed,
            first_closed[1:],
        )
        for (cx, cy), (dx, dy) in zip(
            second_closed,
            second_closed[1:],
        )
    )
