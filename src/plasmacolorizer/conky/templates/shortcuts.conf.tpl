-- PlasmaColorizer preset: static KDE-oriented shortcuts (edit template to taste)
-- Non-interactive reference only.
-- Semi-opaque panel (ARGB) avoids broken transparency when windows cross the Conky region.

conky.config = {
    alignment = 'top_right',
    gap_x = 24,
    gap_y = 48,
    minimum_width = 260,
    own_window = true,
    own_window_type = 'desktop',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_title = 'PlasmaColorizer_shortcuts',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = 'sans:size=9',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    update_interval = 60,
}

conky.text = [[
${color1}Shortcuts${color2}${hr 1}
${color1}Launcher${alignr}Meta
${color1}Overview${alignr}Meta+W
${color1}Clipboard${alignr}Meta+V
${color1}Screenshot${alignr}Meta+Print
${color1}Lock${alignr}Meta+L
${color1}Konsole${alignr}Meta+T
${color1}Settings${alignr}Meta+,
${color1}Close window${alignr}Meta+Shift+W
]]
