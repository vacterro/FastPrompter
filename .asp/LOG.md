# ASP Log

- 17.07.26 03:37 [INIT] RUN: Init ASP state and board -> PASS
- 17.07.26 03:38 [HUNT] RUN: Update ASP state to HUNT -> PASS
- 17.07.26 03:39 [PLAN] RUN: Added T-004 to T-006 for failing smoke tests -> PASS
- 17.07.26 03:43 [HUNT] RUN: Fixed tests and topbar shrinking for T-004 to T-006 -> PASS
- 17.07.26 06:15 [T-101] RUN: slug игнорит таймштампы + sync в switch/archive paths -> 66 PASS; папка больше не хоронится при рестампе
- 17.07.26 06:40 [T-102] RUN: modal guard (топмост прятал confirm), Del/F2/Enter/Ctrl+Shift+C/Ctrl+N в панели -> 67 PASS
- 17.07.26 06:41 [T-103] H: dense-pack мерил шрифт до полиша темы -> re-pack after setStyleSheet, conf med (GUI глазами)
- 17.07.26 06:42 [T-104] H: скрытый search_bar со старым текстом фильтровал снипеты -> _snippet_query() игнорит скрытый бар
- 17.07.26 06:55 [T-105] RUN: TS_STAMP_LINE_RE один на всех, знает 17 Jul + секунды -> глиф не пропадёт
- 17.07.26 06:56 [T-115] RUN: {state} в шаблоне Ctrl+E + тултип; свой дубль поля снёс, у Antigravity уже было
