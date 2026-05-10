from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core.palette import MaterialPalette, apply_green_bias


def test_render_template_basic() -> None:
    out = render_template("x {{primary}} y {{on_surface}}", {"primary": "#aabbcc", "on_surface": "#112233"})
    assert out == "x #aabbcc y #112233"


def test_green_bias_limits() -> None:
    mid = 0xFF5555AA
    assert apply_green_bias(mid, 0.0) == mid
    a = apply_green_bias(mid, 1.0)
    b = apply_green_bias(mid, 1.0)
    assert a == b


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
