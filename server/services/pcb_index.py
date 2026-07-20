"""In-memory SQLite spatial index over parsed PCB data."""

import json
import math
import sqlite3
from collections import defaultdict

try:
    from parsers.pcb_doc import PcbData
    from services.pcb_geometry import (
        parallel_overlap,
        point_in_polygon,
        point_polygon_distance,
        point_seg_distance,
        polygon_polygon_distance,
        oriented_rect_vertices,
        seg_polygon_distance,
        seg_seg_distance,
    )
except ImportError:
    from server.parsers.pcb_doc import PcbData
    from server.services.pcb_geometry import (
        parallel_overlap,
        point_in_polygon,
        point_polygon_distance,
        point_seg_distance,
        polygon_polygon_distance,
        oriented_rect_vertices,
        seg_polygon_distance,
        seg_seg_distance,
    )

_SCHEMA = """
CREATE TABLE layers (
    v6_id INTEGER,
    name TEXT,
    kind TEXT,
    stack_order INTEGER,
    copper_thick_mil REAL,
    diel_height_mil REAL,
    diel_const REAL,
    material TEXT
);
CREATE TABLE nets (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE components (
    id INTEGER PRIMARY KEY,
    refdes TEXT,
    sch_refdes TEXT,
    source_uid TEXT,
    channel_path TEXT,
    x REAL,
    y REAL,
    rotation REAL,
    side TEXT,
    minx REAL,
    miny REAL,
    maxx REAL,
    maxy REAL
);
CREATE INDEX idx_components_refdes ON components(refdes);
CREATE TABLE prims (
    id INTEGER PRIMARY KEY,
    kind TEXT,
    net_id INTEGER,
    layer INTEGER,
    layer_to INTEGER,
    component INTEGER,
    pour_id INTEGER,
    x1 REAL,
    y1 REAL,
    x2 REAL,
    y2 REAL,
    width REAL,
    height REAL,
    rotation REAL,
    shape INTEGER,
    source_id INTEGER,
    hole REAL,
    pad_name TEXT,
    minx REAL,
    miny REAL,
    maxx REAL,
    maxy REAL
);
CREATE INDEX idx_prims_net ON prims(net_id);
CREATE INDEX idx_prims_layer ON prims(layer);
CREATE INDEX idx_prims_bbox ON prims(minx, maxx, miny, maxy);
CREATE TABLE pours (
    id INTEGER PRIMARY KEY,
    net_id INTEGER,
    layer INTEGER,
    hatch_style TEXT,
    vertices TEXT,
    minx REAL,
    miny REAL,
    maxx REAL,
    maxy REAL
);
"""


class PcbIndex:
    """Queryable in-memory representation of parsed PCB data."""

    MAX_NET_DETAIL_RESULTS = 100

    @staticmethod
    def _field(primitive, name):
        try:
            return primitive[name]
        except (IndexError, KeyError, TypeError):
            return getattr(primitive, name)

    def _primitive_geometry(self, primitive):
        """Return (segment, radius, polygon) for exact copper distance."""
        kind = self._field(primitive, "kind")
        x1 = self._field(primitive, "x1")
        y1 = self._field(primitive, "y1")
        x2 = self._field(primitive, "x2")
        y2 = self._field(primitive, "y2")
        width = self._field(primitive, "width")
        if kind != "pad":
            return (x1, y1, x2, y2), width / 2.0, None

        height = self._field(primitive, "height") or width
        rotation = self._field(primitive, "rotation") or 0.0
        shape = self._field(primitive, "shape")
        if shape == 1:
            minor = min(width, height)
            major = max(width, height)
            angle = rotation + (90.0 if height > width else 0.0)
            half_centerline = max(0.0, (major - minor) / 2.0)
            dx = math.cos(math.radians(angle)) * half_centerline
            dy = math.sin(math.radians(angle)) * half_centerline
            return (
                x1 - dx,
                y1 - dy,
                x1 + dx,
                y1 + dy,
            ), minor / 2.0, None
        polygon = oriented_rect_vertices(
            x1,
            y1,
            width,
            height,
            rotation,
        )
        return None, 0.0, polygon

    def _primitive_bounds(self, primitive):
        segment, radius, polygon = self._primitive_geometry(primitive)
        if polygon is not None:
            x_values = [point[0] for point in polygon]
            y_values = [point[1] for point in polygon]
            return (
                min(x_values),
                min(y_values),
                max(x_values),
                max(y_values),
            )
        x1, y1, x2, y2 = segment
        return (
            min(x1, x2) - radius,
            min(y1, y2) - radius,
            max(x1, x2) + radius,
            max(y1, y2) + radius,
        )

    def _primitive_distance(self, first, second) -> float:
        first_segment, first_radius, first_polygon = (
            self._primitive_geometry(first)
        )
        second_segment, second_radius, second_polygon = (
            self._primitive_geometry(second)
        )
        if first_polygon is not None and second_polygon is not None:
            return polygon_polygon_distance(first_polygon, second_polygon)
        if first_polygon is not None:
            distance = seg_polygon_distance(
                *second_segment,
                first_polygon,
            )
            return max(0.0, distance - second_radius)
        if second_polygon is not None:
            distance = seg_polygon_distance(
                *first_segment,
                second_polygon,
            )
            return max(0.0, distance - first_radius)
        distance = seg_seg_distance(*first_segment, *second_segment)
        return max(0.0, distance - first_radius - second_radius)

    def _point_primitive_distance(
        self,
        x: float,
        y: float,
        primitive,
    ) -> float:
        segment, radius, polygon = self._primitive_geometry(primitive)
        if polygon is not None:
            return point_polygon_distance(x, y, polygon)
        return max(
            0.0,
            point_seg_distance(x, y, *segment) - radius,
        )

    def __init__(self, pcb: PcbData, netlist: dict | None):
        self.pcb = pcb
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE prims_rtree USING rtree("
                "id, minx, maxx, miny, maxy)"
            )
            self._has_rtree = True
        except sqlite3.OperationalError:
            self._has_rtree = False
        self._insert_static()
        self._resolve_refdes(netlist)

    def _insert_static(self) -> None:
        self.db.executemany(
            "INSERT INTO layers VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    layer.v6_id,
                    layer.name,
                    layer.kind,
                    layer.stack_order,
                    layer.copper_thick_mil,
                    layer.diel_height_mil,
                    layer.diel_const,
                    layer.material,
                )
                for layer in self.pcb.board.layers
            ],
        )
        self.db.executemany(
            "INSERT INTO nets VALUES (?,?)",
            list(enumerate(self.pcb.nets)),
        )
        for primitive in self.pcb.primitives:
            min_x, min_y, max_x, max_y = self._primitive_bounds(
                primitive
            )
            cursor = self.db.execute(
                "INSERT INTO prims ("
                "kind, net_id, layer, layer_to, component, pour_id, "
                "x1, y1, x2, y2, width, height, rotation, shape, "
                "source_id, "
                "hole, pad_name, "
                "minx, miny, maxx, maxy"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    primitive.kind,
                    primitive.net,
                    primitive.layer,
                    primitive.layer_to,
                    primitive.component,
                    primitive.pour_id,
                    primitive.x1,
                    primitive.y1,
                    primitive.x2,
                    primitive.y2,
                    primitive.width,
                    primitive.height,
                    primitive.rotation,
                    primitive.shape,
                    primitive.source_id,
                    primitive.hole,
                    primitive.pad_name,
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                ),
            )
            if self._has_rtree:
                self.db.execute(
                    "INSERT INTO prims_rtree VALUES (?,?,?,?,?)",
                    (cursor.lastrowid, min_x, max_x, min_y, max_y),
                )
        for pour in self.pcb.pours:
            x_values = [vertex[0] for vertex in pour.vertices] or [0.0]
            y_values = [vertex[1] for vertex in pour.vertices] or [0.0]
            self.db.execute(
                "INSERT INTO pours VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    pour.pour_id,
                    pour.net,
                    pour.layer,
                    pour.hatch_style,
                    json.dumps(pour.vertices),
                    min(x_values),
                    min(y_values),
                    max(x_values),
                    max(y_values),
                ),
            )
        for component in self.pcb.components:
            row = self.db.execute(
                "SELECT MIN(minx) a, MIN(miny) b, "
                "MAX(maxx) c, MAX(maxy) d "
                "FROM prims WHERE component = ? AND kind = 'pad'",
                (component.index,),
            ).fetchone()
            min_x = row["a"] if row["a"] is not None else component.x
            min_y = row["b"] if row["b"] is not None else component.y
            max_x = row["c"] if row["c"] is not None else component.x
            max_y = row["d"] if row["d"] is not None else component.y
            self.db.execute(
                "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    component.index,
                    component.refdes,
                    None,
                    component.source_uid_tail,
                    component.channel_path,
                    component.x,
                    component.y,
                    component.rotation,
                    component.side,
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                ),
            )
        self.db.commit()

    def _pad_net_signature(self, component_id: int) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT p.pad_name, n.name AS net_name "
            "FROM prims p LEFT JOIN nets n ON n.id = p.net_id "
            "WHERE p.component = ? AND p.kind = 'pad'",
            (component_id,),
        ).fetchall()
        return {
            row["pad_name"]: row["net_name"]
            for row in rows
            if row["pad_name"]
        }

    def _resolve_refdes(self, netlist: dict | None) -> None:
        if not netlist:
            return
        netlist_components = netlist.get("components", {})
        by_unique_id: dict[str, list[str]] = defaultdict(list)
        for refdes, component in netlist_components.items():
            unique_id = component.get("unique_id")
            if unique_id:
                by_unique_id[unique_id].append(refdes)

        for component in self.pcb.components:
            schematic_refdes = None
            if (
                component.refdes
                and component.refdes in netlist_components
            ):
                schematic_refdes = component.refdes
            elif (
                component.source_uid_tail
                and component.source_uid_tail in by_unique_id
            ):
                candidates = by_unique_id[component.source_uid_tail]
                if len(candidates) == 1:
                    schematic_refdes = candidates[0]
                else:
                    signature = {
                        str(pad): net
                        for pad, net in self._pad_net_signature(
                            component.index
                        ).items()
                        if net
                    }
                    exact_matches = []
                    for candidate in candidates:
                        pins = netlist_components[candidate].get("pins", {})
                        candidate_signature = {
                            str(pin): metadata.get("net")
                            for pin, metadata in pins.items()
                            if metadata.get("net")
                        }
                        if candidate_signature == signature:
                            exact_matches.append(candidate)
                    if len(exact_matches) == 1:
                        schematic_refdes = exact_matches[0]
            if schematic_refdes:
                self.db.execute(
                    "UPDATE components SET sch_refdes = ? WHERE id = ?",
                    (schematic_refdes, component.index),
                )
        self.db.commit()

    def counts(self) -> dict:
        row = self.db.execute(
            "SELECT "
            "SUM(kind='track' AND pour_id IS NULL) tracks, "
            "COUNT(DISTINCT CASE WHEN kind='arc' "
            "THEN source_id END) arcs, "
            "SUM(kind='via') vias, "
            "SUM(kind='pad') pads "
            "FROM prims"
        ).fetchone()
        return {
            "tracks": row["tracks"] or 0,
            "arcs": row["arcs"] or 0,
            "vias": row["vias"] or 0,
            "pads": row["pads"] or 0,
            "pours": self.db.execute(
                "SELECT COUNT(*) c FROM pours"
            ).fetchone()["c"],
            "nets": self.db.execute(
                "SELECT COUNT(*) c FROM nets"
            ).fetchone()["c"],
            "components": self.db.execute(
                "SELECT COUNT(*) c FROM components"
            ).fetchone()["c"],
        }

    def unmatched_components(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) c FROM components WHERE sch_refdes IS NULL"
        ).fetchone()["c"]

    def resolve_layer(self, name_or_id: str | int | None) -> int | None:
        if name_or_id is None:
            return None
        if isinstance(name_or_id, int):
            resolved = name_or_id
        else:
            resolved = self.pcb.layer_name_to_v6.get(
                str(name_or_id).lower()
            )
        if resolved is None:
            return None
        row = self.db.execute(
            "SELECT 1 FROM layers "
            "WHERE v6_id = ? AND kind = 'copper'",
            (resolved,),
        ).fetchone()
        return resolved if row else None

    def layer_name(self, v6_id: int | None) -> str:
        if v6_id is None:
            return "?"
        row = self.db.execute(
            "SELECT name FROM layers WHERE v6_id = ?",
            (v6_id,),
        ).fetchone()
        return row["name"] if row else f"layer{v6_id}"

    def find_components(self, refdes: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM components "
            "WHERE refdes = ? COLLATE NOCASE "
            "OR sch_refdes = ? COLLATE NOCASE",
            (refdes, refdes),
        ).fetchall()
        return [dict(row) for row in rows]

    def net_id(self, name: str) -> int | None:
        row = self.db.execute(
            "SELECT id FROM nets WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        return row["id"] if row else None

    def net_summary(self, name: str) -> dict | None:
        net_id = self.net_id(name)
        if net_id is None:
            return None
        net_name = self.db.execute(
            "SELECT name FROM nets WHERE id = ?",
            (net_id,),
        ).fetchone()["name"]
        layers = []
        layer_rows = self.db.execute(
            "SELECT layer, COUNT(DISTINCT CASE "
            "WHEN kind='arc' THEN 'a' || source_id "
            "ELSE 't' || id END) n, "
            "MIN(width) wmin, MAX(width) wmax, "
            "SUM(SQRT((x2-x1)*(x2-x1) + (y2-y1)*(y2-y1))) total_len, "
            "MIN(minx) a, MIN(miny) b, MAX(maxx) c, MAX(maxy) d "
            "FROM prims "
            "WHERE net_id = ? AND kind IN ('track','arc') "
            "AND pour_id IS NULL "
            "GROUP BY layer ORDER BY layer",
            (net_id,),
        )
        for row in layer_rows:
            layers.append(
                {
                    "layer": self.layer_name(row["layer"]),
                    "segment_count": row["n"],
                    "length_mil": round(row["total_len"], 1),
                    "width_min_mil": row["wmin"],
                    "width_max_mil": row["wmax"],
                    "bbox_mil": {
                        "minx_mil": row["a"],
                        "miny_mil": row["b"],
                        "maxx_mil": row["c"],
                        "maxy_mil": row["d"],
                    },
                }
            )
        vias = [
            {
                "x_mil": row["x1"],
                "y_mil": row["y1"],
                "diameter_mil": row["width"],
                "hole_mil": row["hole"],
                "span": (
                    f"{self.layer_name(row['layer'])} -> "
                    f"{self.layer_name(row['layer_to'])}"
                ),
            }
            for row in self.db.execute(
                "SELECT * FROM prims "
                "WHERE net_id = ? AND kind = 'via'",
                (net_id,),
            )
        ]
        pads = [
            {
                "refdes": row["refdes"],
                "sch_refdes": row["sch_refdes"],
                "pin": row["pad_name"],
                "x_mil": row["x1"],
                "y_mil": row["y1"],
                "layer": self.layer_name(row["layer"]),
            }
            for row in self.db.execute(
                "SELECT p.*, c.refdes, c.sch_refdes "
                "FROM prims p "
                "LEFT JOIN components c ON c.id = p.component "
                "WHERE p.net_id = ? AND p.kind = 'pad' "
                "ORDER BY c.refdes",
                (net_id,),
            )
        ]
        pours = [
            {
                "layer": self.layer_name(row["layer"]),
                "hatch": row["hatch_style"],
                "bbox_mil": {
                    "minx_mil": row["minx"],
                    "miny_mil": row["miny"],
                    "maxx_mil": row["maxx"],
                    "maxy_mil": row["maxy"],
                },
            }
            for row in self.db.execute(
                "SELECT * FROM pours WHERE net_id = ?",
                (net_id,),
            )
        ]
        bbox = self.db.execute(
            "SELECT MIN(minx) a, MIN(miny) b, "
            "MAX(maxx) c, MAX(maxy) d "
            "FROM prims WHERE net_id = ?",
            (net_id,),
        ).fetchone()
        via_count = len(vias)
        pad_count = len(pads)
        pour_count = len(pours)
        return {
            "net": net_name,
            "layers": layers,
            "via_count": via_count,
            "vias": vias[: self.MAX_NET_DETAIL_RESULTS],
            "vias_has_more": via_count > self.MAX_NET_DETAIL_RESULTS,
            "pad_count": pad_count,
            "pads": pads[: self.MAX_NET_DETAIL_RESULTS],
            "pads_has_more": pad_count > self.MAX_NET_DETAIL_RESULTS,
            "pour_count": pour_count,
            "pours": pours[: self.MAX_NET_DETAIL_RESULTS],
            "pours_has_more": pour_count > self.MAX_NET_DETAIL_RESULTS,
            "bbox_mil": {
                "minx_mil": bbox["a"],
                "miny_mil": bbox["b"],
                "maxx_mil": bbox["c"],
                "maxy_mil": bbox["d"],
            },
        }

    MAX_NEIGHBORS = 25

    def _copper_layers_in_stack_order(self) -> list[int]:
        return [
            row["v6_id"]
            for row in self.db.execute(
                "SELECT v6_id FROM layers "
                "WHERE kind = 'copper' AND v6_id IS NOT NULL "
                "ORDER BY stack_order"
            )
        ]

    def _adjacent_copper_layers(self, v6_id: int) -> list[int]:
        ordered_layers = self._copper_layers_in_stack_order()
        if v6_id not in ordered_layers:
            return []
        index = ordered_layers.index(v6_id)
        return [
            ordered_layers[neighbor_index]
            for neighbor_index in (index - 1, index + 1)
            if 0 <= neighbor_index < len(ordered_layers)
        ]

    def _primitive_layers(self, primitive) -> list[int]:
        """Return every copper layer occupied by a primitive."""
        ordered_layers = self._copper_layers_in_stack_order()
        layer = primitive["layer"]
        if primitive["kind"] == "via":
            layer_to = primitive["layer_to"]
            if layer in ordered_layers and layer_to in ordered_layers:
                start = ordered_layers.index(layer)
                end = ordered_layers.index(layer_to)
                low, high = sorted((start, end))
                return ordered_layers[low : high + 1]
        if primitive["kind"] == "pad" and (
            layer == 74
            or self.layer_name(layer).lower().replace("-", "")
            == "multilayer"
        ):
            return ordered_layers
        return [layer] if layer is not None else []

    def net_neighbors(
        self,
        name: str,
        distance: float,
        layer: int | None = None,
    ) -> dict | None:
        net_id = self.net_id(name)
        if net_id is None:
            return None
        targets = self.db.execute(
            "SELECT * FROM prims "
            "WHERE net_id = ? AND kind IN ('track','arc','via','pad')",
            (net_id,),
        ).fetchall()
        if layer is not None:
            targets = [
                target
                for target in targets
                if layer in self._primitive_layers(target)
            ]

        aggregates: dict[tuple[int, int], dict] = {}
        for target in targets:
            target_layers = self._primitive_layers(target)
            if layer is not None:
                target_layers = [layer]
            for target_layer in target_layers:
                bbox = (
                    target["minx"] - distance,
                    target["maxx"] + distance,
                    target["miny"] - distance,
                    target["maxy"] + distance,
                )
                if self._has_rtree:
                    candidates = self.db.execute(
                        "SELECT p.* FROM prims p "
                        "JOIN prims_rtree r ON r.id = p.id "
                        "WHERE p.net_id IS NOT NULL AND p.net_id != ? "
                        "AND p.kind IN ('track','arc','via','pad') "
                        "AND r.maxx >= ? AND r.minx <= ? "
                        "AND r.maxy >= ? AND r.miny <= ?",
                        (net_id, *bbox),
                    ).fetchall()
                else:
                    candidates = self.db.execute(
                        "SELECT * FROM prims "
                        "WHERE net_id IS NOT NULL AND net_id != ? "
                        "AND kind IN ('track','arc','via','pad') "
                        "AND maxx >= ? AND minx <= ? "
                        "AND maxy >= ? AND miny <= ?",
                        (net_id, *bbox),
                    ).fetchall()
                for candidate in candidates:
                    if target_layer not in self._primitive_layers(candidate):
                        continue
                    edge_distance = self._primitive_distance(
                        target,
                        candidate,
                    )
                    if edge_distance > distance:
                        continue
                    overlap = (
                        parallel_overlap(
                            target["x1"],
                            target["y1"],
                            target["x2"],
                            target["y2"],
                            candidate["x1"],
                            candidate["y1"],
                            candidate["x2"],
                            candidate["y2"],
                        )
                        if (
                            target["kind"] in {"track", "arc"}
                            and candidate["kind"] in {"track", "arc"}
                        )
                        else 0.0
                    )
                    key = (candidate["net_id"], target_layer)
                    aggregate = aggregates.setdefault(
                        key,
                        {
                            "min_edge": edge_distance,
                            "close_segments": 0,
                            "run": 0.0,
                        },
                    )
                    aggregate["min_edge"] = min(
                        aggregate["min_edge"],
                        edge_distance,
                    )
                    aggregate["close_segments"] += 1
                    aggregate["run"] += overlap

        neighbors = []
        for (other_net_id, on_layer), aggregate in aggregates.items():
            net_name = self.db.execute(
                "SELECT name FROM nets WHERE id = ?",
                (other_net_id,),
            ).fetchone()["name"]
            neighbors.append(
                {
                    "net": net_name,
                    "layer": self.layer_name(on_layer),
                    "min_edge_distance_mil": round(
                        aggregate["min_edge"],
                        2,
                    ),
                    "close_segments": aggregate["close_segments"],
                    "parallel_run_mil": round(aggregate["run"], 1),
                }
            )
        neighbors.sort(key=lambda neighbor: -neighbor["parallel_run_mil"])
        has_more = len(neighbors) > self.MAX_NEIGHBORS
        neighbors = neighbors[: self.MAX_NEIGHBORS]

        target_boxes: dict[int, dict[str, float]] = {}
        for target in targets:
            if (
                target["kind"] not in {"track", "arc"}
                or target["pour_id"] is not None
            ):
                continue
            for target_layer in self._primitive_layers(target):
                if layer is not None and target_layer != layer:
                    continue
                box = target_boxes.setdefault(
                    target_layer,
                    {
                        "minx": target["minx"],
                        "miny": target["miny"],
                        "maxx": target["maxx"],
                        "maxy": target["maxy"],
                    },
                )
                box["minx"] = min(box["minx"], target["minx"])
                box["miny"] = min(box["miny"], target["miny"])
                box["maxx"] = max(box["maxx"], target["maxx"])
                box["maxy"] = max(box["maxy"], target["maxy"])
        broadside: dict[tuple[str, str], None] = {}
        for target_layer, target_box in target_boxes.items():
            for adjacent_layer in self._adjacent_copper_layers(target_layer):
                rows = self.db.execute(
                    "SELECT DISTINCT n.name "
                    "FROM prims p JOIN nets n ON n.id = p.net_id "
                    "WHERE p.layer = ? AND p.net_id != ? "
                    "AND p.maxx >= ? AND p.minx <= ? "
                    "AND p.maxy >= ? AND p.miny <= ? "
                    "UNION "
                    "SELECT DISTINCT n.name "
                    "FROM pours po JOIN nets n ON n.id = po.net_id "
                    "WHERE po.layer = ? AND po.net_id != ? "
                    "AND po.maxx >= ? AND po.minx <= ? "
                    "AND po.maxy >= ? AND po.miny <= ?",
                    (
                        adjacent_layer,
                        net_id,
                        target_box["minx"],
                        target_box["maxx"],
                        target_box["miny"],
                        target_box["maxy"],
                        adjacent_layer,
                        net_id,
                        target_box["minx"],
                        target_box["maxx"],
                        target_box["miny"],
                        target_box["maxy"],
                    ),
                )
                for row in rows:
                    broadside[
                        (row["name"], self.layer_name(adjacent_layer))
                    ] = None
        broadside_entries = sorted(
            [
                {"net": net_name, "layer": layer_name}
                for net_name, layer_name in broadside
            ],
            key=lambda entry: (entry["layer"], entry["net"]),
        )
        broadside_count = len(broadside_entries)
        broadside_has_more = broadside_count > self.MAX_NEIGHBORS
        broadside_entries = broadside_entries[: self.MAX_NEIGHBORS]
        return {
            "net": self.db.execute(
                "SELECT name FROM nets WHERE id = ?",
                (net_id,),
            ).fetchone()["name"],
            "distance_mil": distance,
            "neighbors": neighbors,
            "has_more": has_more,
            "broadside_count": broadside_count,
            "broadside": broadside_entries,
            "broadside_has_more": broadside_has_more,
        }

    MAX_REGION_RESULTS = 25

    def region_query(
        self,
        x: float,
        y: float,
        radius: float,
        layer: int | None = None,
    ) -> dict:
        parameters: list = [
            x - radius,
            x + radius,
            y - radius,
            y + radius,
        ]
        if self._has_rtree:
            rows = self.db.execute(
                "SELECT p.* FROM prims p "
                "JOIN prims_rtree r ON r.id = p.id "
                "WHERE p.net_id IS NOT NULL "
                "AND r.maxx >= ? AND r.minx <= ? "
                "AND r.maxy >= ? AND r.miny <= ?",
                parameters,
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM prims "
                "WHERE net_id IS NOT NULL "
                "AND maxx >= ? AND minx <= ? "
                "AND maxy >= ? AND miny <= ?",
                parameters,
            ).fetchall()
        per_net: dict[int, dict] = {}
        for row in rows:
            occupied_layers = self._primitive_layers(row)
            if layer is not None:
                if layer not in occupied_layers:
                    continue
                occupied_layers = [layer]
            edge_distance = self._point_primitive_distance(x, y, row)
            if edge_distance > radius:
                continue
            entry = per_net.setdefault(
                row["net_id"],
                {
                    "min": edge_distance,
                    "kinds": set(),
                    "layers": set(),
                },
            )
            entry["min"] = min(entry["min"], edge_distance)
            entry["kinds"].add(row["kind"])
            entry["layers"].update(
                self.layer_name(occupied_layer)
                for occupied_layer in occupied_layers
            )
        nets = sorted(
            (
                {
                    "net": self.db.execute(
                        "SELECT name FROM nets WHERE id = ?",
                        (net_id,),
                    ).fetchone()["name"],
                    "min_distance_mil": round(entry["min"], 2),
                    "kinds": sorted(entry["kinds"]),
                    "layers": sorted(entry["layers"]),
                }
                for net_id, entry in per_net.items()
            ),
            key=lambda net: net["min_distance_mil"],
        )

        components = []
        component_rows = self.db.execute(
            "SELECT * FROM components "
            "WHERE maxx >= ? AND minx <= ? "
            "AND maxy >= ? AND miny <= ?",
            (
                x - radius,
                x + radius,
                y - radius,
                y + radius,
            ),
        )
        for row in component_rows:
            delta_x = max(row["minx"] - x, 0.0, x - row["maxx"])
            delta_y = max(row["miny"] - y, 0.0, y - row["maxy"])
            distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
            if distance <= radius:
                components.append(
                    {
                        "refdes": row["refdes"],
                        "sch_refdes": row["sch_refdes"],
                        "side": row["side"],
                        "distance_mil": round(distance, 2),
                    }
                )
        components.sort(key=lambda component: component["distance_mil"])

        pour_parameters = [
            x - radius,
            x + radius,
            y - radius,
            y + radius,
        ]
        if layer is not None:
            pour_parameters.append(layer)
        pours = []
        pour_rows = self.db.execute(
            "SELECT po.*, n.name AS net_name "
            "FROM pours po LEFT JOIN nets n ON n.id = po.net_id "
            "WHERE po.maxx >= ? AND po.minx <= ? "
            "AND po.maxy >= ? AND po.miny <= ?"
            + (" AND po.layer = ?" if layer is not None else ""),
            pour_parameters,
        )
        for row in pour_rows:
            vertices = json.loads(row["vertices"])
            if len(vertices) < 3:
                continue
            inside = point_in_polygon(x, y, vertices)
            if inside:
                distance = 0.0
            else:
                closed = vertices + [vertices[0]]
                distance = min(
                    point_seg_distance(x, y, x1, y1, x2, y2)
                    for (x1, y1), (x2, y2)
                    in zip(closed, closed[1:])
                )
            if distance > radius:
                continue
            pours.append(
                {
                    "net": row["net_name"],
                    "layer": self.layer_name(row["layer"]),
                    "inside_pour": inside,
                    "min_distance_mil": round(distance, 2),
                }
            )
        pours.sort(key=lambda pour: pour["min_distance_mil"])
        net_count = len(nets)
        component_count = len(components)
        pour_count = len(pours)
        return {
            "x_mil": x,
            "y_mil": y,
            "radius_mil": radius,
            "net_count": net_count,
            "nets": nets[: self.MAX_REGION_RESULTS],
            "nets_has_more": net_count > self.MAX_REGION_RESULTS,
            "component_count": component_count,
            "components": components[: self.MAX_REGION_RESULTS],
            "components_has_more": (
                component_count > self.MAX_REGION_RESULTS
            ),
            "pour_count": pour_count,
            "pours": pours[: self.MAX_REGION_RESULTS],
            "pours_has_more": pour_count > self.MAX_REGION_RESULTS,
        }

    NEAREST_COMPONENT_COUNT = 10

    def component_detail(self, refdes: str) -> list[dict]:
        instances = self.find_components(refdes)
        details = []
        for instance in instances:
            pins = [
                {
                    "pin": row["pad_name"],
                    "net": row["net_name"],
                    "x_mil": row["x1"],
                    "y_mil": row["y1"],
                    "layer": self.layer_name(row["layer"]),
                }
                for row in self.db.execute(
                    "SELECT p.*, n.name AS net_name "
                    "FROM prims p LEFT JOIN nets n ON n.id = p.net_id "
                    "WHERE p.component = ? AND p.kind = 'pad' "
                    "ORDER BY p.pad_name",
                    (instance["id"],),
                )
            ]
            nearest = []
            if instance["x"] is not None and instance["y"] is not None:
                rows = self.db.execute(
                    "SELECT refdes, sch_refdes, side, x, y, "
                    "((x - ?) * (x - ?) + (y - ?) * (y - ?)) AS d2 "
                    "FROM components "
                    "WHERE id != ? AND x IS NOT NULL AND y IS NOT NULL "
                    "ORDER BY d2 LIMIT ?",
                    (
                        instance["x"],
                        instance["x"],
                        instance["y"],
                        instance["y"],
                        instance["id"],
                        self.NEAREST_COMPONENT_COUNT,
                    ),
                )
                nearest = [
                    {
                        "refdes": row["refdes"],
                        "sch_refdes": row["sch_refdes"],
                        "side": row["side"],
                        "distance_mil": round(row["d2"] ** 0.5, 1),
                    }
                    for row in rows
                ]
            details.append(
                {
                    "refdes": instance["refdes"],
                    "sch_refdes": instance["sch_refdes"],
                    "channel_path": instance["channel_path"],
                    "x_mil": instance["x"],
                    "y_mil": instance["y"],
                    "rotation": instance["rotation"],
                    "side": instance["side"],
                    "bbox_mil": {
                        "minx_mil": instance["minx"],
                        "miny_mil": instance["miny"],
                        "maxx_mil": instance["maxx"],
                        "maxy_mil": instance["maxy"],
                    },
                    "pins": pins,
                    "nearest_components": nearest,
                }
            )
        return details
