from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core.palette import (
    MaterialPalette,
    apply_primary_bias,
    build_palette,
    rgb_tuple_to_argb_u,
)


def test_render_template_basic() -> None:
    out = render_template("x {{primary}} y {{on_surface}}", {"primary": "#aabbcc", "on_surface": "#112233"})
    assert out == "x #aabbcc y #112233"


def test_rgb_tuple_to_argb_u() -> None:
    assert rgb_tuple_to_argb_u((0, 0, 0)) == 0xFF000000
    assert rgb_tuple_to_argb_u((255, 255, 255)) == 0xFFFFFFFF
    assert rgb_tuple_to_argb_u((10, 20, 30)) == 0xFF0A141E


def test_primary_bias_limits() -> None:
    mid = 0xFF5555AA
    assert apply_primary_bias(mid, 0.0, dark=True) == mid
    a = apply_primary_bias(mid, 1.0, dark=True)
    b = apply_primary_bias(mid, 1.0, dark=True)
    assert a == b


def test_primary_bias_moves_toward_scheme_primary() -> None:
    seed = 0xFF5533AA
    biased = apply_primary_bias(seed, 1.0, dark=True)
    pal = build_palette(seed, dark=True)
    target = rgb_tuple_to_argb_u(pal.colors["primary"])
    assert biased == target


def test_context_from_palette_has_snake_case() -> None:
    pal = MaterialPalette(
        is_dark=True,
        colors={
            "primary": (10, 20, 30),
            "onSurface": (200, 200, 200),
        },
    )
    ctx = context_from_palette(pal)
    assert ctx["onSurface"].startswith("#")
    assert ctx["on_surface"].startswith("#")
