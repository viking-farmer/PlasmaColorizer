-- PlasmaColorizer preset: system stats (CPU, memory, disk, network)
-- Colors follow wallpaper palette via {{token}} substitution.
-- Uses ``normal`` window type pinned ``below`` everything else: KWin then tracks
-- damage/expose events properly so translucent ARGB panels repaint cleanly when
-- other windows overlap (no more blur/contrast ghosting on the desktop layer).
-- ``skip_taskbar``/``skip_pager``/``sticky``/``undecorated`` keep it out of
-- task switchers and pinned across virtual desktops.
-- ARGB alpha is driven by the transparency slider (0 = fully transparent, 255 = solid).

conky.config = {
    alignment = '{{conky_alignment}}',
    gap_x = 24,
    gap_y = 48,
    minimum_width = {{system_min_width}},
    own_window = true,
    own_window_type = 'normal',
    own_window_transparent = false,
    own_window_colour = '{{panel_bg_hex6}}',
    own_window_argb_visual = true,
    own_window_argb_value = {{conky_window_alpha}},
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_class = 'PlasmaColorizerConky',
    own_window_title = 'PlasmaColorizer_system',
    double_buffer = true,
    draw_shades = false,
    draw_outline = false,
    use_xft = true,
    font = '{{theme_font_body}}',
    default_color = '{{on_surface}}',
    color1 = '{{primary}}',
    color2 = '{{secondary}}',
    color3 = '{{tertiary}}',
    update_interval = 2,
}

conky.text = [[
${color1}{{theme_title_open}}System{{theme_title_close}}${color2}{{theme_section_divider}}
{{system_stats_body}}
${color1}Root free${alignr}${fs_free /}
${color1}Root used${alignr}${fs_used /} / ${fs_size /}
${color1}{{theme_title_open}}Net{{theme_title_close}}${color2}{{theme_section_divider}}
${if_up wlo1}${color3}wlan${alignr}${downspeed wlo1}↓ ${upspeed wlo1}↑${endif}
${if_up wlan0}${color3}wlan${alignr}${downspeed wlan0}↓ ${upspeed wlan0}↑${endif}
${if_up eth0}${color3}eth${alignr}${downspeed eth0}↓ ${upspeed eth0}↑${endif}
]]
