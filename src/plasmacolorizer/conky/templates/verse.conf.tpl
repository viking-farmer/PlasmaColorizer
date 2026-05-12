-- PlasmaColorizer preset: ESV Bible text (Crossway API; non-commercial use per API terms)
-- Set API key in PlasmaColorizer Conky settings. Refreshes periodically.
-- Semi-opaque panel (ARGB) avoids broken transparency when windows cross the Conky region.

conky.config = {
    alignment = 'bottom_left',
    gap_x = 24,
    gap_y = 64,
    maximum_width = 420,
    own_window = true,
    own_window_type = 'desktop',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_title = 'PlasmaColorizer_verse',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = 'sans:size=9',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 300,
}

conky.text = [[
${color1}Verse (ESV)${color2}${hr 1}
${execi 3600 {{python_exec}} -m plasmacolorizer.conky.fetch esv}
]]
