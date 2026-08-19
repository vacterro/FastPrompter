def test_t1015_toast_sentinel_palette():
    import fastprompter.ui.timer_toast
    from fastprompter.core.timers import Timer
    from PyQt6.QtWidgets import QApplication
    import datetime
    qapp = QApplication.instance() or QApplication([])

    class MockMainWin:
        def __init__(self):
            self._theme_cache = {
                "raw_colors": {
                    "notif_bg": "#111111",
                    "notif_title": "#222222",
                    "notif_accent": "#333333",
                    "notif_text": "#444444",
                    "notif_info": "#555555",
                    "border": "#666666",
                    "border_dark": "#777777",
                    "btn_bg": "#888888",
                    "btn_text": "#999999",
                    "btn_pressed": "#aaaaaa"
                }
            }
            self._current_lang = "EN"

    app = MockMainWin()

    t = Timer("Toast", target=datetime.datetime.now())
    t.color = "#666666"

    toast = fastprompter.ui.timer_toast.TimerToast(app, t)
    qss = toast.styleSheet()
    assert "#222222" in qss, "notif_title should be used for TitleLbl"
    assert "#333333" in qss, "notif_accent should be used for InfoLbl"
    
    title_lbl = toast.findChild(fastprompter.ui.timer_toast.QLabel, "TitleLbl")
    assert title_lbl is not None
