"""Shipped defaults — the baked "current configuration" (T-695, T-696).

Generated once from a live profile (E-1169, scratchpad gen_defaults.py) and
then hand-maintained; regenerate from a live database if the shipped look is
ever re-frozen.

This map is merged into `FastPrompterState.reset_data()`, which means it is
BOTH the fresh-install configuration and the fallback an existing database
falls back to for keys it has never stored. Adding a key here therefore
changes what an upgrading user sees for any setting they never touched --
that is intended (it is what "make the current state the default" means), but
it is the reason no key with user CONTENT in it may ever be added: silos,
timers, window geometry and the editor text are excluded on purpose.
"""

DEFAULT_PROFILE = {
    "altw_blanks_after": 1,
    "altw_blanks_before": 0,
    "altw_bullet_char": "•",
    "altw_s1_after": 2,
    "altw_s1_before": 2,
    "altw_s1_bullet": "True",
    "altw_s1_divider": "False",
    "altw_s2_after": 2,
    "altw_s2_before": 2,
    "altw_s2_bullet": "True",
    "altw_s2_divider": "True",
    "altw_s3_after": 1,
    "altw_s3_before": 0,
    "altw_s3_bullet": "False",
    "altw_s3_divider": "True",
    "altw_s4_after": 2,
    "altw_s4_before": 2,
    "altw_s4_bullet": "True",
    "altw_s4_divider": "False",
    "altw_s5_after": 3,
    "altw_s5_before": 3,
    "altw_s5_bullet": "True",
    "altw_s5_divider": "True",
    "altw_s6_action": "remove",
    "always_on_top": "False",
    "always_on_top_hotkey": "Alt+S",
    "always_on_top_hotkey_alt": "",
    "analog_clock": "True",
    "auto_bullet": "True",
    "bold_hash_titles": "True",
    "bullet_double_line": "True",
    "button_scale": 0.7,
    "close_on_focus_loss": "False",
    "code_monospace": "False",
    "ctrl_c_closes": "False",
    "ctrl_e_align": "center",
    "ctrl_e_align_bullet": "left",
    "ctrl_e_align_rule": "center",
    "ctrl_e_bullet": "True",
    "ctrl_e_bullet_char": "•",
    "ctrl_e_center": "True",
    "ctrl_e_format": "{text} ({time})",
    "ctrl_e_gap_after": 1,
    "ctrl_e_gap_below": 1,
    "ctrl_e_gap_bottom": 1,
    "ctrl_e_rule": "True",
    "ctrl_e_rule_below": "False",
    "ctrl_e_stamp_every": "False",
    "ctrlw_blanks_after": 3,
    "ctrlw_blanks_before": 2,
    "ctrlw_bullet_char": "•",
    "ctrlw_s1_after": 2,
    "ctrlw_s1_before": 2,
    "ctrlw_s1_bullet": "True",
    "ctrlw_s1_divider": "False",
    "ctrlw_s2_after": 2,
    "ctrlw_s2_before": 2,
    "ctrlw_s2_bullet": "True",
    "ctrlw_s2_divider": "True",
    "ctrlw_s3_after": 2,
    "ctrlw_s3_before": 2,
    "ctrlw_s3_bullet": "False",
    "ctrlw_s3_divider": "True",
    "ctrlw_s4_after": 3,
    "ctrlw_s4_before": 0,
    "ctrlw_s4_bullet": "True",
    "ctrlw_s4_divider": "False",
    "ctrlw_s5_after": 1,
    "ctrlw_s5_before": 0,
    "ctrlw_s5_bullet": "True",
    "ctrlw_s5_divider": "False",
    "ctrlw_s6_action": "remove",
    "ctrlw_split_behavior": "bullet",
    "cursor_blink_ms": 1000,
    "custom_colors": {
        "edit_bg": "#2a3330",
        "overlay_new": "#6a5555",
        "overlay_recent": "#6a5a40",
        "overlay_day": "#5a5a30",
        "overlay_old": "#40506a"
    },
    "custom_cursors": "True",
    "customize_toolbar": "False",
    "date_ampm": "False",
    "date_daypart": "True",
    "date_emoji": "False",
    "date_seconds": "True",
    "date_text_month": "True",
    "passed_alert_enabled": "True",
    "passed_event_color": "#e05555",
    "divider_lines_after": 2,
    "drop_bot_left": "files",
    "drop_bot_right": "files_link",
    "drop_top_left": "text",
    "drop_top_right": "editor_link",
    "fancyzones_fast": "True",
    "fancyzones_fast_idx": 0,
    "fancyzones_layout": "Presets",
    "file_panel_docked": "True",
    "file_panel_view": "Icons",
    "files_dock_open": "False",
    "files_dock_width": 185,
    "font_family": "Verdana",
    "font_size": 13,
    "global_hotkey": "Alt+X",
    "global_hotkey_alt": "F15",
    "header_position": "top",
    "hide_extra": "False",
    "hide_on_clickout_hotkey": "Alt+A",
    "hide_on_clickout_hotkey_alt": "",
    "hide_shortkeys": "False",
    "hk_bold": "Ctrl+B",
    "hk_divider": "Ctrl+W",
    "hk_export_silo": "Ctrl+Shift+S",
    "hk_find": "Ctrl+F",
    "hk_focus": "Ctrl+D",
    "hk_header": "Ctrl+E",
    "hk_new_snippet": "Ctrl+N",
    "hk_quit": "Ctrl+Alt+Shift+Q",
    "hk_replace": "Ctrl+H",
    "hk_save_snippet": "Ctrl+S",
    "hk_snap": "Ctrl+Q",
    "hk_undo": "Ctrl+Z",
    "hover_line": "True",
    "hover_line_color": "#0059ff",
    "hover_line_opacity": 5,
    "hr_visual_line": "True",
    "language": "EN",
    "last_save_format": "txt",
    "line_heat": "True",
    "line_heat_palette": "accent",
    "line_heat_strength": 5,
    "line_marks": "True",
    "live_preview_conceal": "True",
    "lock_to_cursor": "False",
    "lock_window_hotkey": "Alt+E",
    "lock_window_hotkey_alt": "",
    "normal_window": "False",
    "numbox_tabs": "True",
    "paste_mode": "Plain",
    "pie_menu_hotkey": "Shift+Alt+X",
    "pie_menu_hotkey_alt": "Shift+F15",
    "portable_backup_enabled": "True",
    "preview_mode": "Live Preview",
    "quote_italic": "True",
    "saved_sidebar_size": 236,
    "search_visible": "True",
    "settings_width": 426,
    "show_date_rect": "True",
    "show_line_numbers": "False",
    "show_titlebar": "False",
    "show_token_count": "False",
    "sidebar_right": "True",
    "silo_0_hotkey": "Alt+Shift+Numpad1",
    "silo_0_hotkey_alt": "",
    "silo_1_hotkey": "Alt+Shift+Numpad2",
    "silo_1_hotkey_alt": "",
    "silo_2_hotkey": "Alt+Shift+Numpad3",
    "silo_2_hotkey_alt": "",
    "silo_3_hotkey": "Alt+Shift+Numpad4",
    "silo_3_hotkey_alt": "",
    "silo_4_hotkey": "Alt+Shift+Numpad5",
    "silo_4_hotkey_alt": "",
    "silo_color_box": "True",
    "silo_gap_height": 12,
    "silo_home": "True",
    "silo_pinned_gap": "True",
    "silo_ticks_enabled": "True",
    "snippet_0_hotkey": "Ctrl+Shift+Numpad1",
    "snippet_0_hotkey_alt": "",
    "snippet_1_hotkey": "Ctrl+Shift+Numpad2",
    "snippet_1_hotkey_alt": "",
    "snippet_2_hotkey": "Ctrl+Shift+Numpad3",
    "snippet_2_hotkey_alt": "",
    "snippet_3_hotkey": "Ctrl+Shift+Numpad4",
    "snippet_3_hotkey_alt": "",
    "snippet_4_hotkey": "Ctrl+Shift+Numpad5",
    "snippet_4_hotkey_alt": "",
    "snippet_5_hotkey": "Ctrl+Shift+Numpad6",
    "snippet_6_hotkey": "Ctrl+Shift+Numpad7",
    "snippet_7_hotkey": "Ctrl+Shift+Numpad8",
    "snippet_8_hotkey": "Ctrl+Shift+Numpad9",
    "snippet_9_hotkey": "Ctrl+Shift+Numpad0",
    "snippet_arrows": "False",
    "snippets_hidden": "False",
    "snippets_visible": "False",
    "numbox_btn_size": 22,
    "numbox_per_row": 10,
    "fkey_action": "projects",
    "sound_typewriter": "True",
    "sound_ui": "True",
    "sound_volume": "1",
    "sound_quick_bar": [
        "file:NEWDAY.wav",
        "file:NEWMONTH.wav",
        "file:NEWWEEK.wav",
        "file:NOMAD.wav",
        "file:OBELISK.wav",
        "file:GENIE.wav",
        "file:PICKUP01.wav",
        "file:PICKUP03.wav",
        "file:GAZEBO.wav",
        "file:ROGUE.wav"
    ],
    "sound_events": {
        "new": {
            "file": "ui_new.wav",
            "enabled": "True",
            "volume": ""
        },
        "save": {
            "file": "ui_save.wav",
            "enabled": "True",
            "volume": ""
        },
        "silo": {
            "file": "button1.wav",
            "enabled": "True",
            "volume": ""
        },
        "snippet": {
            "file": "click_double.wav",
            "enabled": "True",
            "volume": ""
        },
        "tick": {
            "file": "tick_on.wav",
            "enabled": "True",
            "volume": ""
        },
        "untick": {
            "file": "step_stone3.wav",
            "enabled": "True",
            "volume": ""
        },
        "delete": {
            "file": "ui_clear.wav",
            "enabled": "True",
            "volume": ""
        },
        "clear": {
            "file": "warp_teleport08.wav",
            "enabled": "True",
            "volume": ""
        },
        "type": {
            "file": "type_key_1.wav",
            "enabled": "True",
            "volume": ""
        },
        "backspace": {
            "file": "type_key_3.wav",
            "enabled": "True",
            "volume": ""
        },
        "click": {
            "file": "button1.wav",
            "enabled": "True",
            "volume": ""
        },
        "hover": {
            "file": "cs_style/buttonrollover.wav",
            "enabled": "True",
            "volume": ""
        },
        "button_click": {
            "file": "cs_style/buttonclick.wav",
            "enabled": "True",
            "volume": ""
        },
        "button_release": {
            "file": "cs_style/buttonclickrelease.wav",
            "enabled": "True",
            "volume": ""
        },
        "chest_open": {
            "file": "chest_open.wav",
            "enabled": "True",
            "volume": ""
        },
        "chest_close": {
            "file": "chest_closed.wav",
            "enabled": "True",
            "volume": ""
        },
        "notify": {
            "file": "notify.wav",
            "enabled": "True",
            "volume": ""
        },
        "error": {
            "file": "record_scratch_stop.wav",
            "enabled": "True",
            "volume": ""
        },
        "success": {
            "file": "success_levelup.wav",
            "enabled": "True",
            "volume": ""
        },
        "timer": {
            "file": "success_scored.wav",
            "enabled": "True",
            "volume": ""
        },
        "undo": {
            "file": "blip_bow.wav",
            "enabled": "True",
            "volume": ""
        },
        "redo": {
            "file": "blip_bruh.wav",
            "enabled": "True",
            "volume": ""
        },
        "select_all": {
            "file": "reload1.wav",
            "enabled": "True",
            "volume": ""
        },
        "settings": {
            "file": "notify_notification1.wav",
            "enabled": "True",
            "volume": ""
        },
        "help": {
            "file": "notify_notification2.wav",
            "enabled": "True",
            "volume": ""
        },
        "hotkey": {
            "file": "menu_mnu_click.wav",
            "enabled": "True",
            "volume": ""
        },
        "bold": {
            "file": "chat_display_text.wav",
            "enabled": "True",
            "volume": ""
        },
        "italic": {
            "file": "click_cornrclk.wav",
            "enabled": "True",
            "volume": ""
        },
        "underline": {
            "file": "click_hint.wav",
            "enabled": "True",
            "volume": ""
        },
        "strike": {
            "file": "click_tmp_1.wav",
            "enabled": "True",
            "volume": ""
        },
        "header": {
            "file": "click_hint.wav",
            "enabled": "True",
            "volume": ""
        },
        "divider": {
            "file": "menu_mnu_next.wav",
            "enabled": "True",
            "volume": ""
        },
        "snap": {
            "file": "pickup_weapon_02.wav",
            "enabled": "True",
            "volume": ""
        },
        "find": {
            "file": "menu_launch_select1.wav",
            "enabled": "True",
            "volume": ""
        },
        "replace": {
            "file": "menu3.wav",
            "enabled": "True",
            "volume": ""
        },
        "focus": {
            "file": "panel_open.wav",
            "enabled": "True",
            "volume": ""
        },
        "export": {
            "file": "ui_save.wav",
            "enabled": "True",
            "volume": ""
        },
        "quit": {
            "file": "menu_mnu_disa.wav",
            "enabled": "True",
            "volume": ""
        },
        "archive": {
            "file": "chest_open.wav",
            "enabled": "True",
            "volume": ""
        },
        "snippets_toggle": {
            "file": "menu_mnu_next.wav",
            "enabled": "True",
            "volume": ""
        },
        "transform": {
            "file": "click_double.wav",
            "enabled": "True",
            "volume": ""
        },
        "sidebar": {
            "file": "record_scratch_stop.wav",
            "enabled": "True",
            "volume": ""
        },
        "lock": {
            "file": "click_tactile_click.wav",
            "enabled": "True",
            "volume": ""
        },
        "copy": {
            "file": "pop_cartoon_pop.wav",
            "enabled": "True",
            "volume": ""
        },
        "paste": {
            "file": "pop_up_02.wav",
            "enabled": "True",
            "volume": ""
        },
        "cut": {
            "file": "menu_launch_deny1.wav",
            "enabled": "True",
            "volume": ""
        },
        "zoom_in": {
            "file": "knife_slash1.wav",
            "enabled": "True",
            "volume": ""
        },
        "zoom_out": {
            "file": "blip1.wav",
            "enabled": "True",
            "volume": ""
        },
        "escape": {
            "file": "menu_mnu_next.wav",
            "enabled": "True",
            "volume": ""
        },
        "search": {
            "file": "menu_launch_select1.wav",
            "enabled": "True",
            "volume": ""
        },
        "backup": {
            "file": "ui_save.wav",
            "enabled": "True",
            "volume": ""
        },
        "restore": {
            "file": "menu_mnu_empt.wav",
            "enabled": "True",
            "volume": ""
        },
        "reset": {
            "file": "ui_clear.wav",
            "enabled": "True",
            "volume": ""
        },
        "timer_start": {
            "file": "tick_stickybomblauncher_det.wav",
            "enabled": "True",
            "volume": ""
        },
        "profile": {
            "file": "panel_open.wav",
            "enabled": "True",
            "volume": ""
        },
        "watcher": {
            "file": "notify.wav",
            "enabled": "True",
            "volume": ""
        }
    },
    "saved_sound_mappings": {
        "hover": "cs_style/buttonrollover.wav",
        "click": "button1.wav",
        "button_release": "cs_style/buttonclickrelease.wav",
        "button_click": "cs_style/buttonclick.wav"
    },
    "cs_style": "False",
    "splitter_sizes": [
        178,
        1257
    ],
    "splitter_sizes_left": [
        187,
        898,
        0
    ],
    "splitter_sizes_right": [
        0,
        717,
        236
    ],
    "splitter_width": 3,
    "sync_mode": "Off",
    "sync_exclude": "node_modules, .git, .hg, .svn, .idea, .vscode, .vs, __pycache__, .venv, venv, dist, build, out, target, bin, obj, .next, .nuxt, .gradle, .terraform, .pytest_cache, .mypy_cache, .ruff_cache, .cache, coverage, .tox, .eggs, site-packages, Pods, vendor, .DS_Store, Thumbs.db, desktop.ini, *.pyc, *.exe, *.dll, *.so, *.dylib, *.png, *.jpg, *.jpeg, *.gif, *.bmp, *.ico, *.webp, *.mp3, *.mp4, *.wav, *.zip, *.rar, *.7z, *.tar, *.gz, *.min.js, *.min.css, *.map, *.woff, *.woff2, *.ttf, *.otf, *.pdf, *.doc, *.docx, *.xls, *.xlsx, *.ppt, *.pptx",
    "sync_include": ".txt .md .markdown .rst .py .pyw .js .mjs .cjs .ts .jsx .tsx .json .yaml .yml .toml .ini .cfg .conf .csv .tsv .html .htm .css .scss .less .xml .svg .log .sh .bash .zsh .bat .cmd .ps1 .sql .r .rb .go .rs .java .kt .kts .c .h .cpp .hpp .cc .hh .cs .php .swift .lua .pl .pm .vim .env .properties .gradle .dockerfile .dockerignore .gitignore .editorconfig .makefile",
    "sync_live_watch": "True",
    "sync_max_kb": "512",
    "sync_recursive": "True",
    "tab_overflow_mode": "Shrink",
    "text_align": "left",
    "theme": "Golden Default",
    "timer_show_minutes": "True",
    "toggle_sidebar_hotkey": "Alt+D",
    "tray_click_activates": "True",
    "toggle_sidebar_hotkey_alt": "",
    "typo_check_enabled": "False",
    "typo_color": "#e05555",
    "typo_user_words": [],
    "token_mode": "chars",
    "token_weight": 4.0,
    "toolbar_hidden": "",
    "toolbar_order": "",
    "trash_vision": "False",
    "tray_visible": "True",
    "two_sided_buttons": "True",
    "ui_scale": 0.7,
    "window_locked": "False",
    "window_presets": [
        {
            "name": "Preset 1",
            "x": 0.3338541666666667,
            "y": 0.31851851851851853,
            "w": 0.5,
            "h": 0.6287037037037037,
            "state": "normal"
        },
        {
            "name": "Preset 2",
            "x": 0.3338541666666667,
            "y": 0.31851851851851853,
            "w": 0.3338541666666667,
            "h": 0.6287037037037037,
            "state": "normal"
        },
        {
            "name": "Preset 3",
            "x": 0.2916666666666667,
            "y": 0.0,
            "w": 0.4166666666666667,
            "h": 1.0,
            "state": "normal"
        }
    ],
    "window_presets_enabled": "True",
    "window_presets_capture_state": "True",
    "word_wrap": "True",
    "zebra_lines": "True",
    "zebra_stripes": "False",
    "project_sync_all": {},
    "project_sync_map_all": {},
    "temp_timer_settings": {
        "name": "Temp Timer",
        "description": "",
        "increment_minutes": 15,
        "delete_after_fire": False,
        "sound": "tick",
        "volume": 0.0,
        "color_mode": "temperature",
        "show_notification": True,
        "show_in_top_bar": True,
        "sound_mode": "single",
        "sound_rules": []
    },
    "productivity_timer": {
        "work_seconds": 2730,
        "break_seconds": 930,
        "breaks_enabled": True,
        "repeat_alarm": True,
        "completed_cycles": 0,
        "work_sound": "file:QUEST.wav",
        "break_sound": "file:NEWDAY.wav",
        "volume": 0.05,
        "sound_enabled": True
    },
    "interval_notifs": [
        {
            "id": "interval_default_noon",
            "name": "Noon (12:00)",
            "minutes": 60,
            "enabled": True,
            "sound": "file:GENIE.wav",
            "volume": 1.0,
            "show_notification": True,
            "show_in_top_bar": False,
            "align_mode": "clock",
            "all_day": False,
            "start_minute": 720,
            "end_minute": 779
        },
        {
            "id": "interval_default_morning",
            "name": "Morning (07:00 - 11:00)",
            "minutes": 60,
            "enabled": True,
            "sound": "file:newday.wav",
            "volume": 1.0,
            "show_notification": True,
            "show_in_top_bar": False,
            "align_mode": "clock",
            "all_day": False,
            "start_minute": 420,
            "end_minute": 719
        },
        {
            "id": "interval_default_day",
            "name": "Day & Evening (13:00 - 21:00)",
            "minutes": 60,
            "enabled": True,
            "sound": "file:newday.wav",
            "volume": 1.0,
            "show_notification": True,
            "show_in_top_bar": False,
            "align_mode": "clock",
            "all_day": False,
            "start_minute": 780,
            "end_minute": 1319
        },
        {
            "id": "interval_default_night",
            "name": "Night (22:00 - 06:00)",
            "minutes": 60,
            "enabled": True,
            "sound": "file:alert_owl2.wav",
            "volume": 1.0,
            "show_notification": True,
            "show_in_top_bar": False,
            "align_mode": "clock",
            "all_day": False,
            "start_minute": 1320,
            "end_minute": 419
        }
    ],
    "project_sync": {},
    "project_sync_map": {},
    "silo_links": {},
    "silo_links_all": {},
}
