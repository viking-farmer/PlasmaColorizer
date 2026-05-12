-- PlasmaColorizer preset: system stats (CPU, memory, disk, network)
-- Colors follow wallpaper palette via {{token}} substitution.
-- Opaque dock panel; “opacity” is blended RGB (no ARGB — avoids KWin blur ghosts after overlaps).

conky.config = {
    alignment = '{{conky_alignment}}',
    gap_x = 24,
    gap_y = 48,
    minimum_width = {{system_min_width}},
    own_window = true,
    own_window_type = 'dock',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = false,
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_title = 'PlasmaColorizer_system',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = 'sans:size=10',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    color3 = '{{tertiary}}',
    update_interval = 2,
}

conky.text = [[
${color1}System${font sans:size=8}${color2}${hr 1}${font}
{{system_stats_body}}
${color1}Root free${alignr}${fs_free /}
${color1}Root used${alignr}${fs_used /} / ${fs_size /}
${color1}Net${font sans:size=8}${color2}${hr 1}${font}
${if_up wlo1}${color3}wlan${alignr}${downspeed wlo1}↓ ${upspeed wlo1}↑${endif}
${if_up wlan0}${color3}wlan${alignr}${downspeed wlan0}↓ ${upspeed wlan0}↑${endif}
${if_up eth0}${color3}eth${alignr}${downspeed eth0}↓ ${upspeed eth0}↑${endif}
]]
