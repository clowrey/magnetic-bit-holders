from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from tkinter import TRUE

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Cone,
    Cylinder,
    FontStyle,
    GeomType,
    Locations,
    Mode,
    Plane,
    Text,
    add,
    extrude,
    export_step,
    export_stl,
    chamfer,
    fillet,
)

# Build toggles
BUILD_SINGLE_10_BIT = True
BUILD_BATCH_10_TO_30 = False
BUILD_METRIC_LABELED = True
BUILD_ENGLISH_LABELED = True
BUILD_METRIC_DOUBLEBACK_LABELED = True
BUILD_ENGLISH_DOUBLEBACK_LABELED = True

BATCH_START = 10
BATCH_STOP = 30
BATCH_STEP = 2


@dataclass
class BitHolderParams:
    # Count and core hole geometry
    bit_count: int = 20
    bit_cavity_diameter: float = 7.6
    bit_cavity_depth: float = 13.0 # 13mm is max depth for some short bits that get wider after 13mm 

    # Magnet pocket geometry (for nominal 6x3 mm magnets)
    magnet_pocket_diameter: float = 6.1
    magnet_pocket_depth: float = 3.1
    magnet_bevel_depth: float = 0.8  # visible taper from 7.6 to 6.1

    # Floor thickness under magnet pocket (2 layers at 0.2 mm)
    bottom_floor_thickness: float = 0.4

    # Spacing and walls
    spacing_between_hole_ods: float = 1.6
    side_wall_thickness: float = 1.6
    end_wall_thickness: float = 1.6
    outer_edge_radius: float = 2.0
    bit_entry_bevel: float = 0.0
    side_label_font_size: float = 7.0
    side_label_depth: float = 0.45


def build_linear_bit_holder(params: BitHolderParams):
    if params.bit_count < 1:
        raise ValueError("bit_count must be >= 1")
    if params.magnet_bevel_depth < 0:
        raise ValueError("magnet_bevel_depth must be >= 0")
    if params.magnet_bevel_depth >= params.magnet_pocket_depth:
        raise ValueError("magnet_bevel_depth must be less than magnet_pocket_depth")

    center_spacing = params.bit_cavity_diameter + params.spacing_between_hole_ods

    body_length = (
        2 * params.end_wall_thickness
        + params.bit_count * params.bit_cavity_diameter
        + (params.bit_count - 1) * params.spacing_between_hole_ods
    )
    body_width = params.bit_cavity_diameter + 2 * params.side_wall_thickness
    body_height = (
        params.bit_cavity_depth + params.magnet_pocket_depth + params.bottom_floor_thickness
    )

    x_start = -0.5 * (params.bit_count - 1) * center_spacing
    top_z = body_height

    with BuildPart() as holder:
        Box(
            body_length,
            body_width,
            body_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )

        for i in range(params.bit_count):
            x = x_start + i * center_spacing

            # Main bit cavity from top face downward
            with Locations((x, 0, top_z)):
                Cylinder(
                    radius=0.5 * params.bit_cavity_diameter,
                    height=params.bit_cavity_depth,
                    align=(Align.CENTER, Align.CENTER, Align.MAX),
                    mode=Mode.SUBTRACT,
                )

            # Magnet pocket (straight section) from cavity floor downward
            magnet_cyl_depth = params.magnet_pocket_depth - params.magnet_bevel_depth
            with Locations((x, 0, top_z - params.bit_cavity_depth)):
                Cylinder(
                    radius=0.5 * params.magnet_pocket_diameter,
                    height=magnet_cyl_depth,
                    align=(Align.CENTER, Align.CENTER, Align.MAX),
                    mode=Mode.SUBTRACT,
                )

            # Beveled transition from bit cavity to magnet pocket
            if params.magnet_bevel_depth > 0:
                with Locations((x, 0, top_z - params.bit_cavity_depth)):
                    Cone(
                        top_radius=0.5 * params.bit_cavity_diameter,
                        bottom_radius=0.5 * params.magnet_pocket_diameter,
                        height=params.magnet_bevel_depth,
                        align=(Align.CENTER, Align.CENTER, Align.MAX),
                        mode=Mode.SUBTRACT,
                    )

        # Radius all external edges of the holder body.
        half_length = 0.5 * body_length
        half_width = 0.5 * body_width
        eps = 1e-6
        outer_edges = []
        for edge in holder.edges():
            c = edge.center()
            on_x_side = abs(abs(c.X) - half_length) < eps
            on_y_side = abs(abs(c.Y) - half_width) < eps
            on_bottom = abs(c.Z) < eps
            on_top = abs(c.Z - top_z) < eps

            if (on_x_side and on_y_side) or (on_x_side and (on_bottom or on_top)) or (
                on_y_side and (on_bottom or on_top)
            ):
                outer_edges.append(edge)

        if params.outer_edge_radius > 0 and outer_edges:
            try:
                fillet(outer_edges, params.outer_edge_radius)
            except ValueError as err:
                raise ValueError(
                    f"outer_edge_radius={params.outer_edge_radius} is too large for current geometry"
                ) from err

        # Bevel the top edge of each bit cavity after body edge fillets.
        # Select circular edges from the true top planar face(s) so the bevel
        # still applies even after large outer-edge fillets reshape nearby faces.
        top_planar_faces = [
            f
            for f in holder.faces()
            if f.geom_type == GeomType.PLANE and abs(f.center().Z - top_z) < eps
        ]
        top_hole_edges = []
        for face in top_planar_faces:
            top_hole_edges.extend(
                [e for e in face.edges() if e.geom_type == GeomType.CIRCLE]
            )
        if params.bit_entry_bevel > 0 and top_hole_edges:
            try:
                chamfer(top_hole_edges, params.bit_entry_bevel)
            except ValueError as err:
                raise ValueError(
                    f"bit_entry_bevel={params.bit_entry_bevel} is too large for current geometry"
                ) from err

    return holder.part


def _holder_dimensions(params: BitHolderParams) -> tuple[float, float, float, float]:
    center_spacing = params.bit_cavity_diameter + params.spacing_between_hole_ods
    body_length = (
        2 * params.end_wall_thickness
        + params.bit_count * params.bit_cavity_diameter
        + (params.bit_count - 1) * params.spacing_between_hole_ods
    )
    body_width = params.bit_cavity_diameter + 2 * params.side_wall_thickness
    body_height = (
        params.bit_cavity_depth + params.magnet_pocket_depth + params.bottom_floor_thickness
    )
    return center_spacing, body_length, body_width, body_height


def _measure_label_span(label: str, font_size: float) -> tuple[float, float]:
    """Measure rotated label span on the sketch plane (X, Y)."""
    with BuildSketch() as sketch:
        Text(
            txt=label,
            font_size=font_size,
            font_style=FontStyle.BOLD,
            align=(Align.CENTER, Align.CENTER),
            rotation=90,
        )
    bb = sketch.sketch.bounding_box()
    return bb.size.X, bb.size.Y


def _auto_fit_side_label_font_size(
    labels: list[str],
    requested_font_size: float,
    center_spacing: float,
    body_height: float,
) -> float:
    """
    Reduce side-label font size until it fits:
    - inside holder height (no top/bottom overlap)
    - within cavity pitch in X (no label-to-label overlap)
    """
    max_font = max(0.5, requested_font_size)
    min_font = 1.5
    step = 0.1
    avail_x = center_spacing - 0.6
    avail_y = body_height - 1.0

    steps = max(1, int(round((max_font - min_font) / step)))
    for i in range(steps + 1):
        size = max_font - i * step
        if size < min_font:
            break
        max_x = 0.0
        max_y = 0.0
        for label in labels:
            sx, sy = _measure_label_span(label, size)
            max_x = max(max_x, sx)
            max_y = max(max_y, sy)
        if max_x <= avail_x and max_y <= avail_y:
            return round(size, 2)
    return min_font


def add_side_debossed_labels(part, params: BitHolderParams, labels: list[str]):
    """Deboss text labels into the +Y side wall at each cavity center."""
    if len(labels) != params.bit_count:
        raise ValueError("labels count must match bit_count")
    if params.side_label_depth <= 0:
        raise ValueError("side_label_depth must be > 0")

    center_spacing, _, body_width, body_height = _holder_dimensions(params)
    x_start = -0.5 * (params.bit_count - 1) * center_spacing
    y_face = 0.5 * body_width
    z_text = 0.5 * body_height

    with BuildPart() as labeled:
        add(part)
        with BuildSketch(Plane.XZ.offset(y_face)):
            for i, label in enumerate(labels):
                x = x_start + i * center_spacing
                with Locations((x, z_text)):
                    Text(
                        txt=label,
                        font_size=params.side_label_font_size,
                        font_style=FontStyle.BOLD,
                        align=(Align.CENTER, Align.CENTER),
                        rotation=90,
                    )
        extrude(amount=-params.side_label_depth, mode=Mode.SUBTRACT)

    return labeled.part


def build_doubleback_bit_holder(
    params: BitHolderParams, columns: int = 6, rows: int = 2
):
    """Build a connected multi-row holder (double-back style)."""
    if columns < 1 or rows < 1:
        raise ValueError("columns and rows must be >= 1")

    center_spacing = params.bit_cavity_diameter + params.spacing_between_hole_ods
    body_length = (
        2 * params.end_wall_thickness
        + columns * params.bit_cavity_diameter
        + (columns - 1) * params.spacing_between_hole_ods
    )
    body_width = (
        2 * params.side_wall_thickness
        + rows * params.bit_cavity_diameter
        + (rows - 1) * params.spacing_between_hole_ods
    )
    body_height = (
        params.bit_cavity_depth + params.magnet_pocket_depth + params.bottom_floor_thickness
    )

    x_start = -0.5 * (columns - 1) * center_spacing
    y_start = -0.5 * (rows - 1) * center_spacing
    top_z = body_height

    with BuildPart() as holder:
        Box(
            body_length,
            body_width,
            body_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )

        for row in range(rows):
            y = y_start + row * center_spacing
            for col in range(columns):
                x = x_start + col * center_spacing

                with Locations((x, y, top_z)):
                    Cylinder(
                        radius=0.5 * params.bit_cavity_diameter,
                        height=params.bit_cavity_depth,
                        align=(Align.CENTER, Align.CENTER, Align.MAX),
                        mode=Mode.SUBTRACT,
                    )

                magnet_cyl_depth = params.magnet_pocket_depth - params.magnet_bevel_depth
                with Locations((x, y, top_z - params.bit_cavity_depth)):
                    Cylinder(
                        radius=0.5 * params.magnet_pocket_diameter,
                        height=magnet_cyl_depth,
                        align=(Align.CENTER, Align.CENTER, Align.MAX),
                        mode=Mode.SUBTRACT,
                    )

                if params.magnet_bevel_depth > 0:
                    with Locations((x, y, top_z - params.bit_cavity_depth)):
                        Cone(
                            top_radius=0.5 * params.bit_cavity_diameter,
                            bottom_radius=0.5 * params.magnet_pocket_diameter,
                            height=params.magnet_bevel_depth,
                            align=(Align.CENTER, Align.CENTER, Align.MAX),
                            mode=Mode.SUBTRACT,
                        )

        half_length = 0.5 * body_length
        half_width = 0.5 * body_width
        eps = 1e-6
        outer_edges = []
        for edge in holder.edges():
            c = edge.center()
            on_x_side = abs(abs(c.X) - half_length) < eps
            on_y_side = abs(abs(c.Y) - half_width) < eps
            on_bottom = abs(c.Z) < eps
            on_top = abs(c.Z - top_z) < eps
            if (on_x_side and on_y_side) or (on_x_side and (on_bottom or on_top)) or (
                on_y_side and (on_bottom or on_top)
            ):
                outer_edges.append(edge)

        if params.outer_edge_radius > 0 and outer_edges:
            fillet(outer_edges, params.outer_edge_radius)

        top_planar_faces = [
            f
            for f in holder.faces()
            if f.geom_type == GeomType.PLANE and abs(f.center().Z - top_z) < eps
        ]
        top_hole_edges = []
        for face in top_planar_faces:
            top_hole_edges.extend(
                [e for e in face.edges() if e.geom_type == GeomType.CIRCLE]
            )
        if params.bit_entry_bevel > 0 and top_hole_edges:
            chamfer(top_hole_edges, params.bit_entry_bevel)

    x_positions = [x_start + col * center_spacing for col in range(columns)]
    return holder.part, x_positions, body_width, body_height


def add_side_debossed_labels_on_edge(
    part,
    params: BitHolderParams,
    labels: list[str],
    x_positions: list[float],
    body_width: float,
    body_height: float,
    side: int,
):
    """Deboss labels on +Y or -Y long outer edge."""
    if side not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    if len(labels) != len(x_positions):
        raise ValueError("labels count must match x_positions count")

    y_face = side * 0.5 * body_width
    z_text = 0.5 * body_height

    with BuildPart() as labeled:
        add(part)
        with BuildSketch(Plane.XZ.offset(y_face)):
            for x, label in zip(x_positions, labels):
                with Locations((x, z_text)):
                    Text(
                        txt=label,
                        font_size=params.side_label_font_size,
                        font_style=FontStyle.BOLD,
                        align=(Align.CENTER, Align.CENTER),
                        rotation=90 if side > 0 else -90,
                    )
        extrude(amount=-side * params.side_label_depth, mode=Mode.SUBTRACT)

    return labeled.part


def export_cutaway_svg(params: BitHolderParams, out_path: str) -> None:
    """Export a 2D center cutaway (X-Z plane at Y=0) with basic dimensions."""
    center_spacing, body_length, body_width, body_height = _holder_dimensions(params)
    half_length = 0.5 * body_length
    top_z = body_height
    corner_r = min(params.outer_edge_radius, half_length, 0.5 * body_height)

    # mm -> px scaling and page margins
    scale = 8.0
    margin_x = 80.0
    margin_y = 70.0
    dim_pad = 120.0

    view_w = body_length * scale
    view_h = body_height * scale
    canvas_w = margin_x * 2 + view_w + 200
    canvas_h = margin_y * 2 + view_h + 170

    def sx(x_mm: float) -> float:
        return margin_x + (x_mm + half_length) * scale

    def sy(z_mm: float) -> float:
        return margin_y + (top_z - z_mm) * scale

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}">'
    )
    lines.append("<defs>")
    lines.append(
        '<marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
        '<path d="M0,0 L10,4 L0,8 z" fill="#1f2937"/></marker>'
    )
    lines.append("</defs>")

    # Body silhouette
    lines.append(
        f'<rect x="{sx(-half_length):.2f}" y="{sy(top_z):.2f}" width="{view_w:.2f}" '
        f'height="{view_h:.2f}" rx="{corner_r * scale:.2f}" ry="{corner_r * scale:.2f}" '
        f'fill="#d9dde3" stroke="#111827" stroke-width="1.5"/>'
    )

    # Cavity cutaways
    x_start = -0.5 * (params.bit_count - 1) * center_spacing
    r_bit = 0.5 * params.bit_cavity_diameter
    r_mag = 0.5 * params.magnet_pocket_diameter
    z_floor = top_z - params.bit_cavity_depth
    z_bevel_bottom = z_floor - params.magnet_bevel_depth
    z_mag_bottom = z_floor - params.magnet_pocket_depth

    for i in range(params.bit_count):
        x = x_start + i * center_spacing
        cavity_points = [
            (x - r_bit, top_z),
            (x + r_bit, top_z),
            (x + r_bit, z_floor),
            (x + r_mag, z_bevel_bottom),
            (x + r_mag, z_mag_bottom),
            (x - r_mag, z_mag_bottom),
            (x - r_mag, z_bevel_bottom),
            (x - r_bit, z_floor),
        ]
        points = " ".join(f"{sx(px):.2f},{sy(pz):.2f}" for px, pz in cavity_points)
        lines.append(
            f'<polygon points="{points}" fill="#ffffff" stroke="#111827" stroke-width="1.0"/>'
        )

    # Dimension: overall length
    x_l = sx(-half_length)
    x_r = sx(half_length)
    y_len = sy(0) + dim_pad
    lines.append(f'<line x1="{x_l:.2f}" y1="{y_len:.2f}" x2="{x_r:.2f}" y2="{y_len:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{x_l:.2f}" y1="{sy(0):.2f}" x2="{x_l:.2f}" y2="{y_len:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{x_r:.2f}" y1="{sy(0):.2f}" x2="{x_r:.2f}" y2="{y_len:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{0.5 * (x_l + x_r):.2f}" y="{y_len - 8:.2f}" text-anchor="middle" '
        f'font-size="13" fill="#111827">Overall length {body_length:.2f} mm</text>'
    )

    # Dimension: overall height
    x_h = sx(half_length) + 70
    y_b = sy(0)
    y_t = sy(top_z)
    lines.append(f'<line x1="{x_h:.2f}" y1="{y_b:.2f}" x2="{x_h:.2f}" y2="{y_t:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{sx(half_length):.2f}" y1="{y_b:.2f}" x2="{x_h:.2f}" y2="{y_b:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{sx(half_length):.2f}" y1="{y_t:.2f}" x2="{x_h:.2f}" y2="{y_t:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{x_h + 8:.2f}" y="{0.5 * (y_b + y_t):.2f}" font-size="13" fill="#111827">'
        f'Overall height {body_height:.2f} mm</text>'
    )

    # Dimension: bit cavity diameter on first cavity
    x0 = x_start
    mid_i = max(0, (params.bit_count // 2) - 1)
    x_mid = x_start + mid_i * center_spacing
    x_d1 = sx(x0 - r_bit)
    x_d2 = sx(x0 + r_bit)
    y_d = sy(top_z) - 28
    lines.append(f'<line x1="{x_d1:.2f}" y1="{y_d:.2f}" x2="{x_d2:.2f}" y2="{y_d:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{x_d1:.2f}" y1="{y_d:.2f}" x2="{x_d1:.2f}" y2="{sy(top_z):.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{x_d2:.2f}" y1="{y_d:.2f}" x2="{x_d2:.2f}" y2="{sy(top_z):.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{0.5 * (x_d1 + x_d2):.2f}" y="{y_d - 8:.2f}" text-anchor="middle" '
        f'font-size="13" fill="#111827">Bit cavity OD {params.bit_cavity_diameter:.2f} mm</text>'
    )

    # Dimension: thickness between adjacent cavities (hole OD to hole OD gap), centered.
    x1 = x_mid + center_spacing
    x_gap_l = sx(x_mid + r_bit)
    x_gap_r = sx(x1 - r_bit)
    y_gap = sy(top_z) - 84
    lines.append(f'<line x1="{x_gap_l:.2f}" y1="{y_gap:.2f}" x2="{x_gap_r:.2f}" y2="{y_gap:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{x_gap_l:.2f}" y1="{y_gap:.2f}" x2="{x_gap_l:.2f}" y2="{sy(top_z):.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{x_gap_r:.2f}" y1="{y_gap:.2f}" x2="{x_gap_r:.2f}" y2="{sy(top_z):.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{0.5 * (x_gap_l + x_gap_r):.2f}" y="{y_gap - 8:.2f}" text-anchor="middle" '
        f'font-size="13" fill="#111827">Between cavities {params.spacing_between_hole_ods:.2f} mm</text>'
    )

    # Dimension: bit cavity depth on first cavity
    x_dep = sx(x0 - r_bit) - 28
    y_top = sy(top_z)
    y_floor = sy(z_floor)
    lines.append(f'<line x1="{x_dep:.2f}" y1="{y_top:.2f}" x2="{x_dep:.2f}" y2="{y_floor:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{x_dep:.2f}" y1="{y_top:.2f}" x2="{sx(x0 - r_bit):.2f}" y2="{y_top:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{x_dep:.2f}" y1="{y_floor:.2f}" x2="{sx(x0 - r_bit):.2f}" y2="{y_floor:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(
        f'<text x="{x_dep - 6:.2f}" y="{0.5 * (y_top + y_floor):.2f}" text-anchor="end" '
        f'font-size="13" fill="#111827">Bit depth {params.bit_cavity_depth:.2f} mm</text>'
    )

    # Dimension: magnet hole diameter on middle cavity
    x_m1 = sx(x_mid - r_mag)
    x_m2 = sx(x_mid + r_mag)
    y_m = sy(z_bevel_bottom) + 18
    lines.append(f'<line x1="{x_m1:.2f}" y1="{y_m:.2f}" x2="{x_m2:.2f}" y2="{y_m:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{x_m1:.2f}" y1="{y_m:.2f}" x2="{x_m1:.2f}" y2="{sy(z_bevel_bottom):.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{x_m2:.2f}" y1="{y_m:.2f}" x2="{x_m2:.2f}" y2="{sy(z_bevel_bottom):.2f}" stroke="#6b7280" stroke-width="1"/>')
    x_m_label = sx(x_mid - r_bit) - 170
    y_m_label = sy(0) + 64
    lines.append(
        f'<line x1="{x_m_label + 130:.2f}" y1="{y_m_label - 4:.2f}" '
        f'x2="{0.5 * (x_m1 + x_m2):.2f}" y2="{y_m:.2f}" '
        'stroke="#1f2937" stroke-width="1.2" marker-end="url(#arrow)"/>'
    )
    lines.append(
        f'<text x="{x_m_label:.2f}" y="{y_m_label:.2f}" '
        f'font-size="13" fill="#111827">Magnet hole OD {params.magnet_pocket_diameter:.2f} mm</text>'
    )

    # Dimension: magnet hole depth on middle cavity
    x_mdep = sx(x_mid + r_mag) + 24
    y_mtop = sy(z_bevel_bottom)
    y_mbot = sy(z_mag_bottom)
    lines.append(f'<line x1="{x_mdep:.2f}" y1="{y_mtop:.2f}" x2="{x_mdep:.2f}" y2="{y_mbot:.2f}" '
                 'stroke="#1f2937" stroke-width="1.2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    lines.append(f'<line x1="{sx(x_mid + r_mag):.2f}" y1="{y_mtop:.2f}" x2="{x_mdep:.2f}" y2="{y_mtop:.2f}" stroke="#6b7280" stroke-width="1"/>')
    lines.append(f'<line x1="{sx(x_mid + r_mag):.2f}" y1="{y_mbot:.2f}" x2="{x_mdep:.2f}" y2="{y_mbot:.2f}" stroke="#6b7280" stroke-width="1"/>')
    x_md_label = sx(x_mid + r_bit) - 190
    y_md_label = sy(0) + 86
    lines.append(
        f'<line x1="{x_md_label + 125:.2f}" y1="{y_md_label - 4:.2f}" '
        f'x2="{x_mdep:.2f}" y2="{0.5 * (y_mtop + y_mbot):.2f}" '
        'stroke="#1f2937" stroke-width="1.2" marker-end="url(#arrow)"/>'
    )
    lines.append(
        f'<text x="{x_md_label:.2f}" y="{y_md_label:.2f}" '
        f'font-size="13" fill="#111827">Magnet depth {params.magnet_pocket_depth - params.magnet_bevel_depth:.2f} mm</text>'
    )

    # Dimension: outer edge radius leader
    if corner_r > 0:
        arc_point_x = half_length - corner_r * 0.35
        arc_point_z = top_z - corner_r * 0.05
        label_x = sx(half_length) + 18
        label_y = sy(top_z) - 28
        lines.append(
            f'<line x1="{label_x:.2f}" y1="{label_y + 4:.2f}" '
            f'x2="{sx(arc_point_x):.2f}" y2="{sy(arc_point_z):.2f}" '
            'stroke="#1f2937" stroke-width="1.2" marker-end="url(#arrow)"/>'
        )
        lines.append(
            f'<text x="{label_x:.2f}" y="{label_y:.2f}" font-size="13" fill="#111827">'
            f'Outer edge radius R{corner_r:.2f} mm</text>'
        )

    lines.append("</svg>")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def export_cutaway_jpg(svg_path: str, jpg_path: str) -> None:
    """Render cutaway SVG to JPG for easy preview."""
    try:
        import cairosvg
        from PIL import Image
    except ImportError as err:
        raise RuntimeError(
            "JPG export requires cairosvg and Pillow packages"
        ) from err

    with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_png = Path(tmp.name)

    try:
        # Render at higher scale for a sharper JPG.
        cairosvg.svg2png(url=svg_path, write_to=str(tmp_png), scale=3.0)
        with Image.open(tmp_png) as img:
            # Force solid white background (no transparency).
            rgba = img.convert("RGBA")
            white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
            white_bg.paste(rgba, mask=rgba.getchannel("A"))
            white_bg.save(jpg_path, format="JPEG", quality=96, subsampling=0)
    finally:
        if tmp_png.exists():
            tmp_png.unlink()


if __name__ == "__main__":
    output_dir = Path("exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    def out_path(filename: str) -> str:
        return str(output_dir / filename)

    base = BitHolderParams()
    standard_counts: list[int] = []
    if BUILD_SINGLE_10_BIT:
        standard_counts.append(10)
    if BUILD_BATCH_10_TO_30:
        standard_counts.extend(range(BATCH_START, BATCH_STOP + 1, BATCH_STEP))

    for bit_count in sorted(set(standard_counts)):
        p = replace(base, bit_count=bit_count)
        part = build_linear_bit_holder(p)
        stem = f"linear_bit_holder_{bit_count}bit"
        stl_path = out_path(f"{stem}.stl")
        step_path = out_path(f"{stem}.step")
        svg_path = out_path(f"{stem}_cutaway.svg")
        jpg_path = out_path(f"{stem}_cutaway.jpg")

        export_stl(part, stl_path)
        export_step(part, step_path)
        export_cutaway_svg(p, svg_path)
        export_cutaway_jpg(svg_path, jpg_path)

        center_spacing = p.bit_cavity_diameter + p.spacing_between_hole_ods
        length = (
            2 * p.end_wall_thickness
            + p.bit_count * p.bit_cavity_diameter
            + (p.bit_count - 1) * p.spacing_between_hole_ods
        )
        width = p.bit_cavity_diameter + 2 * p.side_wall_thickness
        height = p.bit_cavity_depth + p.magnet_pocket_depth + p.bottom_floor_thickness

        print("Linear bit holder generated:")
        print(f"- bit_count: {p.bit_count}")
        print(f"- center_spacing: {center_spacing:.3f} mm")
        print(f"- overall L x W x H: {length:.3f} x {width:.3f} x {height:.3f} mm")
        print(f"- STL exported to: {stl_path}")
        print(f"- STEP exported to: {step_path}")
        print(f"- 2D cutaway exported to: {svg_path}")
        print(f"- 2D cutaway exported to: {jpg_path}")

    metric_hex_labels = [
        "1.5",
        "2",
        "2.5",
        "3",
        "3.5",
        "4",
        "5",
        "5.5",
        "6",
        "7",
        "8",
    ]
    if BUILD_METRIC_LABELED:
        metric_params = replace(base, bit_count=len(metric_hex_labels))
        metric_part = build_linear_bit_holder(metric_params)
        metric_labeled = add_side_debossed_labels(metric_part, metric_params, metric_hex_labels)
        metric_stem = "linear_bit_holder_11bit_metric_hex_labeled"
        metric_stl = out_path(f"{metric_stem}.stl")
        metric_step = out_path(f"{metric_stem}.step")
        export_stl(metric_labeled, metric_stl)
        export_step(metric_labeled, metric_step)
        print("Metric labeled variant generated:")
        print(f"- bit_count: {metric_params.bit_count}")
        print(f"- side labels: {', '.join(metric_hex_labels)}")
        print(f"- STL exported to: {metric_stl}")
        print(f"- STEP exported to: {metric_step}")

    english_hex_labels = [
        "5/64",
        "3/32",
        "7/64",
        "1/8",
        "9/64",
        "5/32",
        "3/16",
        "7/32",
        "1/4",
        "5/16",
    ]
    if BUILD_ENGLISH_LABELED:
        english_params = replace(base, bit_count=len(english_hex_labels))
        english_center_spacing, _, _, english_height = _holder_dimensions(english_params)
        fitted_english_font = _auto_fit_side_label_font_size(
            english_hex_labels,
            english_params.side_label_font_size,
            english_center_spacing,
            english_height,
        )
        english_params = replace(english_params, side_label_font_size=fitted_english_font)
        english_part = build_linear_bit_holder(english_params)
        english_labeled = add_side_debossed_labels(
            english_part, english_params, english_hex_labels
        )
        english_stem = "linear_bit_holder_10bit_english_hex_labeled"
        english_stl = out_path(f"{english_stem}.stl")
        english_step = out_path(f"{english_stem}.step")
        export_stl(english_labeled, english_stl)
        export_step(english_labeled, english_step)
        print("English labeled variant generated:")
        print(f"- bit_count: {english_params.bit_count}")
        print(f"- fitted label font size: {english_params.side_label_font_size}")
        print(f"- side labels: {', '.join(english_hex_labels)}")
        print(f"- STL exported to: {english_stl}")
        print(f"- STEP exported to: {english_step}")

    if BUILD_METRIC_DOUBLEBACK_LABELED:
        # Assumes common metric progression and adds 10 mm as the 12th size.
        doubleback_labels = [
            "1.5",
            "2",
            "2.5",
            "3",
            "3.5",
            "4",
            "5",
            "5.5",
            "6",
            "7",
            "8",
            "10",
        ]
        doubleback_params = replace(base, bit_count=len(doubleback_labels))
        doubleback_part, x_positions, db_width, db_height = build_doubleback_bit_holder(
            doubleback_params, columns=6, rows=2
        )
        side_a_labels = doubleback_labels[0::2]
        side_b_labels = doubleback_labels[1::2]
        doubleback_labeled = add_side_debossed_labels_on_edge(
            doubleback_part,
            doubleback_params,
            side_a_labels,
            x_positions,
            db_width,
            db_height,
            side=1,
        )
        doubleback_labeled = add_side_debossed_labels_on_edge(
            doubleback_labeled,
            doubleback_params,
            side_b_labels,
            x_positions,
            db_width,
            db_height,
            side=-1,
        )
        doubleback_stem = "linear_bit_holder_12bit_metric_hex_doubleback_labeled"
        doubleback_stl = out_path(f"{doubleback_stem}.stl")
        doubleback_step = out_path(f"{doubleback_stem}.step")
        export_stl(doubleback_labeled, doubleback_stl)
        export_step(doubleback_labeled, doubleback_step)
        print("Metric double-back labeled variant generated:")
        print("- layout: 2 rows x 6 columns (12 total)")
        print(f"- +Y side labels: {', '.join(side_a_labels)}")
        print(f"- -Y side labels: {', '.join(side_b_labels)}")
        print(f"- STL exported to: {doubleback_stl}")
        print(f"- STEP exported to: {doubleback_step}")

    if BUILD_ENGLISH_DOUBLEBACK_LABELED:
        english_doubleback_labels = [
            "5/64",
            "3/32",
            "7/64",
            "1/8",
            "9/64",
            "5/32",
            "3/16",
            "7/32",
            "1/4",
            "5/16",
        ]
        english_db_params = replace(base, bit_count=len(english_doubleback_labels))
        english_db_part, english_x_positions, english_db_width, english_db_height = (
            build_doubleback_bit_holder(english_db_params, columns=5, rows=2)
        )
        english_db_center_spacing = (
            english_db_params.bit_cavity_diameter + english_db_params.spacing_between_hole_ods
        )
        fitted_english_db_font = _auto_fit_side_label_font_size(
            english_doubleback_labels,
            english_db_params.side_label_font_size,
            english_db_center_spacing,
            english_db_height,
        )
        english_db_params = replace(
            english_db_params, side_label_font_size=fitted_english_db_font
        )
        side_a_labels = english_doubleback_labels[0::2]
        side_b_labels = english_doubleback_labels[1::2]
        english_db_labeled = add_side_debossed_labels_on_edge(
            english_db_part,
            english_db_params,
            side_a_labels,
            english_x_positions,
            english_db_width,
            english_db_height,
            side=1,
        )
        english_db_labeled = add_side_debossed_labels_on_edge(
            english_db_labeled,
            english_db_params,
            side_b_labels,
            english_x_positions,
            english_db_width,
            english_db_height,
            side=-1,
        )
        english_db_stem = "linear_bit_holder_10bit_english_hex_doubleback_labeled"
        english_db_stl = out_path(f"{english_db_stem}.stl")
        english_db_step = out_path(f"{english_db_stem}.step")
        export_stl(english_db_labeled, english_db_stl)
        export_step(english_db_labeled, english_db_step)
        print("English double-back labeled variant generated:")
        print("- layout: 2 rows x 5 columns (10 total)")
        print(f"- fitted label font size: {english_db_params.side_label_font_size}")
        print(f"- +Y side labels: {', '.join(side_a_labels)}")
        print(f"- -Y side labels: {', '.join(side_b_labels)}")
        print(f"- STL exported to: {english_db_stl}")
        print(f"- STEP exported to: {english_db_step}")
