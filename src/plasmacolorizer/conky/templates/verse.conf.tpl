-- PlasmaColorizer preset: ESV Bible text (Crossway API; non-commercial use per API terms)
-- Set API key in PlasmaColorizer Conky settings. Refreshes periodically.
-- Opaque ``desktop`` panel that stays *below* normal windows (no ARGB → no KWin blur ghosts).

conky.config = {
    alignment = '{{conky_alignment}}',
    gap_x = 24,
    gap_y = 64,
    maximum_width = 420,
    -- Default text_buffer_size silently truncates long ``execi`` output (~256 B).
    text_buffer_size = 2048,
    own_window = true,
    own_window_type = 'desktop',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = false,
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_title = 'PlasmaColorizer_verse',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = '{{theme_font_body}}',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 300,
}

conky.text = [[
${color1}{{theme_title_open}}Verse (ESV){{theme_title_close}}${color2}{{theme_section_divider}}
${execi 3600 {{python_exec}} -m plasmacolorizer.conky.fetch esv}
]]
