from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    Cone,
    Cylinder,
    GeomType,
    Locations,
    Mode,
    export_step,
    export_stl,
    chamfer,
    fillet,
)


@dataclass
class BitHolderParams:
    # Count and core hole geometry
    bit_count: int = 10
    bit_cavity_diameter: float = 7.6
    bit_cavity_depth: float = 16.0

    # Magnet pocket geometry (for nominal 6x3 mm magnets)
    magnet_pocket_diameter: float = 6.1
    magnet_pocket_depth: float = 3.6
    magnet_bevel_depth: float = 0.8  # visible taper from 7.6 to 6.1

    # Floor thickness under magnet pocket (2 layers at 0.2 mm)
    bottom_floor_thickness: float = 0.4

    # Spacing and walls
    spacing_between_hole_ods: float = 1.6
    side_wall_thickness: float = 1.6
    end_wall_thickness: float = 1.6
    outer_edge_radius: float = 2.0
    bit_entry_bevel: float = 0.0


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
    y_mtop = sy(z_floor)
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
        f'font-size="13" fill="#111827">Magnet depth {params.magnet_pocket_depth:.2f} mm</text>'
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
    p = BitHolderParams()
    part = build_linear_bit_holder(p)
    export_stl(part, "linear_bit_holder_10bit.stl")
    export_step(part, "linear_bit_holder_10bit.step")
    export_cutaway_svg(p, "linear_bit_holder_10bit_cutaway.svg")
    export_cutaway_jpg(
        "linear_bit_holder_10bit_cutaway.svg",
        "linear_bit_holder_10bit_cutaway.jpg",
    )

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
    print("- STL exported to: linear_bit_holder_10bit.stl")
    print("- STEP exported to: linear_bit_holder_10bit.step")
    print("- 2D cutaway exported to: linear_bit_holder_10bit_cutaway.svg")
    print("- 2D cutaway exported to: linear_bit_holder_10bit_cutaway.jpg")
