-- PlasmaColorizer preset: system stats (CPU, memory, disk, network)
-- Colors follow wallpaper palette via {{token}} substitution.
-- Semi-opaque panel (ARGB) avoids broken transparency when windows cross the Conky region.

conky.config = {
    alignment = 'top_left',
    gap_x = 24,
    gap_y = 48,
    minimum_width = 220,
    own_window = true,
    own_window_type = 'desktop',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
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
${color1}CPU${alignr}${cpu cpu0}%
${color1}Load${alignr}${loadavg 1}
${color1}RAM${alignr}${mem} / ${memmax}
${color1}RAM %${alignr}${memperc}%
${color1}Root free${alignr}${fs_free /}
${color1}Root used${alignr}${fs_used /} / ${fs_size /}
${color1}Net${font sans:size=8}${color2}${hr 1}${font}
${if_up wlo1}${color3}wlan${alignr}${downspeed wlo1}↓ ${upspeed wlo1}↑${endif}
${if_up wlan0}${color3}wlan${alignr}${downspeed wlan0}↓ ${upspeed wlan0}↑${endif}
${if_up eth0}${color3}eth${alignr}${downspeed eth0}↓ ${upspeed eth0}↑${endif}
]]
