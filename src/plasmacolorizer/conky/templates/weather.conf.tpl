-- PlasmaColorizer preset: weather via Open-Meteo (no API key)
-- Set city or lat/lon in PlasmaColorizer Conky settings.
-- Uses ``normal`` window type pinned ``below`` everything else: KWin then tracks
-- damage/expose events properly so translucent ARGB panels repaint cleanly when
-- other windows overlap (no more blur/contrast ghosting on the desktop layer).
-- ARGB alpha is driven by the transparency slider (0 = fully transparent, 255 = solid).

conky.config = {
    alignment = '{{conky_alignment}}',
    gap_x = 24,
    gap_y = 64,
    minimum_width = 240,
    own_window = true,
    own_window_type = 'normal',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_class = 'PlasmaColorizerConky',
    own_window_title = 'PlasmaColorizer_weather',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = '{{theme_font_body}}',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 120,
}

conky.text = [[
${color1}{{theme_title_open}}Weather{{theme_title_close}}${color2}{{theme_section_divider}}
${execi 1800 {{python_exec}} -m plasmacolorizer.conky.fetch weather}
]]
