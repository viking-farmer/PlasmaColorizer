-- PlasmaColorizer preset: static KDE-oriented shortcuts (edit via the Conky tab)
-- Non-interactive reference only.
-- Uses ``desktop`` window type so the panel sits on the wallpaper layer under
-- KWin / Plasma Wayland. ``normal``+``below`` caused plasmashell instability
-- with multiple ARGB Conky windows on XWayland; prefer the safer desktop role.
-- ARGB alpha is driven by the transparency slider (0 = fully transparent, 255 = solid).

conky.config = {
    -- Force X11/XWayland. Conky 1.22+ may pick Wayland on KDE and leave panels
    -- unmapped or invisible; X11 is the reliable path for PlasmaColorizer.
    out_to_wayland = false,
    out_to_x = true,
    alignment = '{{conky_alignment}}',
    gap_x = 24,
    gap_y = 48,
    minimum_width = 260,
    own_window = true,
    own_window_type = '{{conky_window_type}}',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = '{{conky_window_hints}}',
    own_window_class = 'PlasmaColorizerConky',
    own_window_title = 'PlasmaColorizer_shortcuts',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = '{{theme_font_body}}',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 60,
}

conky.text = [[
${color1}{{theme_title_open}}Shortcuts{{theme_title_close}}${color2}{{theme_section_divider}}
{{shortcuts_body}}
]]
