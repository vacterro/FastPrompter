"""Settings control for choosing which discovered quota accounts are drawn."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


def hidden_account_keys(data: dict) -> set[str]:
    """Return persisted hidden keys, tolerating pre-codec/string profiles."""
    raw = data.get("limit_gauges_hidden_accounts", [])
    if isinstance(raw, (list, tuple, set)):
        return {str(key) for key in raw if key}
    return set()


def account_order(data: dict) -> list[str]:
    """Persisted draw order as a list of stable account keys."""
    raw = (data or {}).get("limit_gauges_account_order", [])
    if not isinstance(raw, (list, tuple)):
        return []
    seen = set()
    order = []
    for key in raw:
        key = str(key)
        if key and key not in seen:
            seen.add(key)
            order.append(key)
    return order


def ordered_accounts(accounts, data: dict | None = None):
    """Accounts in the user's draw order, unranked ones keeping discovery order.

    A key the order list does not mention is NOT dropped: it is appended after
    the ranked accounts. An allow-list here would make a newly discovered
    account invisible until the user happened to open the settings dialog.
    """
    ranked = account_order(data or {})
    if not ranked:
        return list(accounts)
    position = {key: index for index, key in enumerate(ranked)}
    tail = len(position)
    return sorted(
        accounts,
        key=lambda a: (position.get(a.key, tail),))


def _setting_map(data: dict, key: str) -> dict[str, str]:
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k}


def default_account_label(account) -> str:
    """Detected compact label used until the user explicitly overrides it."""
    if account.provider_id == "claude":
        return "CL"
    if account.provider_id == "antigravity":
        return "AG"
    if account.provider_id == "zcode":
        return "ZC"
    if account.provider_id == "codex":
        suffix = account.display_name.removeprefix("Codex").strip()
        return f"C{suffix or '1'}"
    return account.provider_id[:2].upper() or "AI"


def short_account_label(account, data: dict | None = None) -> str:
    """User badge (including an intentionally blank one), or detected label."""
    labels = _setting_map(data or {}, "limit_gauges_account_labels")
    if account.key in labels:
        return labels[account.key].strip()
    return default_account_label(account)


def account_display_name(account, data: dict | None = None) -> str:
    """User-facing alias for tooltips; identity remains the stable key."""
    names = _setting_map(data or {}, "limit_gauges_account_names")
    return names.get(account.key, "").strip() or account.display_name


class LimitAccountSelector(QWidget):
    """Dynamic checkbox grid backed by stable ``provider:stable_id`` keys."""

    def __init__(self, main_win, service):
        super().__init__(main_win)
        self.main_win = main_win
        self._service = service
        self._signature = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(1)
        self.sync(force=True)

    def sync(self, force=False):
        accounts = ordered_accounts(
            self._service.state_copy.accounts, self.main_win.data)
        hidden = hidden_account_keys(self.main_win.data)
        signature = tuple((a.key, a.display_name, a.source_path,
                           a.key in hidden) for a in accounts)
        if not force and signature == self._signature:
            return
        self._signature = signature
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not accounts:
            self._grid.addWidget(QLabel("No AI accounts detected"), 0, 0)
            return
        name_map = _setting_map(
            self.main_win.data, "limit_gauges_account_names")
        label_map = _setting_map(
            self.main_win.data, "limit_gauges_account_labels")
        self._grid.addWidget(QLabel("Show"), 0, 0)
        self._grid.addWidget(QLabel("Detected"), 0, 1)
        self._grid.addWidget(QLabel("Your name"), 0, 2)
        self._grid.addWidget(QLabel("Header"), 0, 3)
        self._grid.addWidget(QLabel("Order"), 0, 4, 1, 2)
        last = len(accounts) - 1
        for index, account in enumerate(accounts):
            row = index + 1
            cb = QCheckBox()
            cb.setChecked(account.key not in hidden)
            cb.setToolTip(f"{account.provider_id}: {account.source_path}")
            cb.toggled.connect(
                lambda checked, key=account.key: self._set_visible(key, checked)
            )
            self._grid.addWidget(cb, row, 0)

            detected = QLabel(account.display_name)
            detected.setToolTip(account.source_path)
            self._grid.addWidget(detected, row, 1)

            name_edit = QLineEdit()
            name_edit.setMaxLength(40)
            name_edit.setPlaceholderText(account.display_name)
            name_edit.setText(name_map.get(account.key, ""))
            name_edit.setToolTip(
                "Optional account name used in limit details and hover")
            name_edit.textEdited.connect(
                lambda text, key=account.key: self._set_name(key, text))
            self._grid.addWidget(name_edit, row, 2)

            badge_edit = QLineEdit()
            badge_edit.setMaxLength(8)
            badge_edit.setMaximumWidth(48)
            badge_edit.setText(label_map.get(
                account.key, default_account_label(account)))
            badge_edit.setToolTip(
                "Short header badge. Leave empty for no badge on this account.")
            badge_edit.textEdited.connect(
                lambda text, key=account.key: self._set_badge(key, text))
            self._grid.addWidget(badge_edit, row, 3)

            move_up = QPushButton("▲")
            move_up.setFixedWidth(22)
            move_up.setEnabled(index > 0)
            move_up.setToolTip("Draw this account earlier in the header")
            move_up.clicked.connect(
                lambda _checked=False, key=account.key: self._move(key, -1))
            self._grid.addWidget(move_up, row, 4)

            move_down = QPushButton("▼")
            move_down.setFixedWidth(22)
            move_down.setEnabled(index < last)
            move_down.setToolTip("Draw this account later in the header")
            move_down.clicked.connect(
                lambda _checked=False, key=account.key: self._move(key, 1))
            self._grid.addWidget(move_down, row, 5)

    def _move(self, key: str, delta: int):
        """Shift one account up/down in the persisted draw order.

        The order is rewritten from the CURRENT full account list, not from the
        stored list: a stored order predating a discovery has no slot for the
        new account, and swapping inside it would silently drop the newcomer to
        the end on the next save.
        """
        accounts = ordered_accounts(
            self._service.state_copy.accounts, self.main_win.data)
        keys = [a.key for a in accounts]
        if key not in keys:
            return
        index = keys.index(key)
        target = index + delta
        if not 0 <= target < len(keys):
            return
        keys[index], keys[target] = keys[target], keys[index]
        self.main_win.data["limit_gauges_account_order"] = keys
        self._changed()
        self.sync(force=True)
        update_status = getattr(self.main_win, "_update_limit_status", None)
        if callable(update_status):
            update_status()

    def _set_visible(self, key: str, visible: bool):
        hidden = hidden_account_keys(self.main_win.data)
        if visible:
            hidden.discard(key)
        else:
            hidden.add(key)
        self.main_win.data["limit_gauges_hidden_accounts"] = sorted(hidden)
        self.main_win.mark_dirty()
        gauges = getattr(self.main_win, "limit_gauges", None)
        if gauges is not None:
            gauges.refresh_view()
        update_status = getattr(self.main_win, "_update_limit_status", None)
        if callable(update_status):
            update_status()

    def _set_name(self, key: str, value: str):
        names = _setting_map(
            self.main_win.data, "limit_gauges_account_names")
        value = value.strip()
        if value:
            names[key] = value
        else:
            names.pop(key, None)
        self.main_win.data["limit_gauges_account_names"] = names
        self._changed()

    def _set_badge(self, key: str, value: str):
        labels = _setting_map(
            self.main_win.data, "limit_gauges_account_labels")
        # Keep an empty string: unlike an empty full name it is an explicit
        # per-account request to draw no header badge.
        labels[key] = value.strip()
        self.main_win.data["limit_gauges_account_labels"] = labels
        self._changed()

    def _changed(self):
        self.main_win.mark_dirty()
        gauges = getattr(self.main_win, "limit_gauges", None)
        if gauges is not None:
            gauges.refresh_view()
