-- PlasmaColorizer preset: weather via Open-Meteo (no API key)
-- Set city or lat/lon in PlasmaColorizer Conky settings.
-- Semi-opaque panel (ARGB) avoids broken transparency when windows cross the Conky region.

conky.config = {
    alignment = 'bottom_right',
    gap_x = 24,
    gap_y = 64,
    minimum_width = 240,
    own_window = true,
    own_window_type = 'desktop',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_title = 'PlasmaColorizer_weather',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = 'sans:size=10',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 120,
}

conky.text = [[
${color1}Weather${color2}${hr 1}
${execi 1800 {{python_exec}} -m plasmacolorizer.conky.fetch weather}
]]
