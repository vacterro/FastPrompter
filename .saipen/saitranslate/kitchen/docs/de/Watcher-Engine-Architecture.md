# Watcher-Engine-Architektur

## Übersicht

Prompt-Ableitungs- + Zielautomatisierungs-Subsystem. Reiht Prompts ein, überwacht den Ziel-App-Zustand (Electron/Web/jedes Win32-Fenster), sendet automatisch, wenn das Ziel im Leerlauf ist.

---

## Hochlevel-Architektur

```
+------------------------------------------------------------------+
|                        Watcher Engine (engine.py)                  |
|  +------------------+    +------------------+   +--------------+  |
|  | State Machine    | -> | Probes & Hooks   | ->| SendIntent   |  |
|  | DISARMED→ARMED→  |    | (Win32 + CDP)    |   | Generator    |  |
|  | WATCHING→SENDING |    +------------------+   +--------------+  |
|  +------------------+                                          |
+------------------------------------------------------------------+
                              v
+------------------------------------------------------------------+
|  Queue (queue.py)           |    Sender (sender.py)              |
|  - Per-target queue_key     |    - CDP Runtime.evaluate          |
|  - FIFO item backlog        |    - Win32 key injection           |
|  - Pinned queue_key on arm  |    - Read-back verify              |
+------------------------------------------------------------------+
```

---

## 1. Zustandsmaschine (`engine.py`)

```
[DISARMED] ← (error/panic/max_sends)
    |
    | arm(target, queue_key)
    v
[ARMED] —→ (agent seen busy) —→ [WATCHING]
    ^                               |
    |     (send completed)          | (agent idle + settle_ms)
    +———————— <— [SENDING] ————————+
```

### Zustände
1. **DISARMED** — inaktiv, keine Probe-Polls, keine Item-Verarbeitung
2. **ARMED** — an Zielfenster + queue_key gebunden. Wartet auf Zielaktivität.
3. **WATCHING** — Ziel als beschäftigt beobachtet (LLM generiert). Wartet auf Leerlauf + settle.
4. **SENDING** — SendIntent ausgelöst. Wartet auf Injektionsbestätigung.

---

## 2. Chrome-CDP (`cdp.py`)

Warum CDP: Electron-Apps (VS Code, Claude Desktop, ChatGPT, Obsidian) verarbeiten keine Win32-Nachrichten. Chromiums IPC ignoriert `PostMessageW` — Zeichen fallen still weg.

### Operationen
- `discover()` — `http://127.0.0.1:<port>/json/list` nach Seiten-Targets abfragen
- WebSocket-JSON-RPC-Verbindung pro Seite
- `Runtime.evaluate` + `Input.dispatchKeyEvent` für Texteingabe
- **Read-back-Verifizierung** — Text einfügen, Feldwert per DOM-Abfrage lesen, nur bei Übereinstimmung Submit
- Nicht blockierende Timeouts (3 s Standard)

---

## 3. Win32-Probes (`win32.py`, `probes.py`)

Für Nicht-Electron-Ziel-Apps.

- `GetForegroundWindow()` + Titel-Regex-Match → Zielerkennung
- Caret- + Fokus-Überwachung → Injektion nur bei aktivem Eingabefeld
- `combine()` — Multi-Probe-Zustände zu einzelnen Bool-Werten aggregieren (is_target_active, is_target_busy, is_blocked)

---

## 4. Queue-Modell (`queue.py`)

### QueueItem
- `id` — UUID
- `text` — Prompt-Text
- `skill` — Wrapper-Skill-Name
- `line` — Quellzeilennummer (für Live-Text-Tracking)

### SendIntent
- `item_id`, `text`, `queue_key`, `skill` — für den Sender gekapselt

### Lebenszyklus
1. **Pending** — im Backlog
2. **In-Flight** — SendIntent an Sender ausgelöst
3. **Sent** — vom Sender bestätigt, aus Queue entfernt
4. **Failed** — erhöht consecutive_failures, erneut bis max_failures (3) versuchen

### Queue-Pinning
Beim `arm(target, queue_key)` wird der Schlüssel gepinnt. Projekt/Silo mitten in der Sitzung wechseln → Watcher leert trotzdem die richtige Queue.

---

## 5. Sicherheits-Guards

| Parameter | Standard | Zweck |
|---|---|---|
| `settle_ms` | 2500 | Ruhezeit nach Ziel-Leerlauf vor dem Senden |
| `min_gap_ms` | 4000 | Mindestverzögerung zwischen aufeinanderfolgenden Sendungen |
| `max_sends` | 25 | Max. Prompts pro scharfgeschalteter Sitzung (Auto-Disarm) |
| `max_failures` | 3 | Aufeinanderfolgende Fehler → Disarm mit Fehler |
| `panic()` | — | Not-Stopp: Disarm + alle In-Flight abbrechen |

---

## 6. Skill-System (`skills.py`)

Prompt-Wrapper, die vor dem Dispatch angewendet werden.

```python
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review:\n\n{text}",
}
```

Variablen: `{text}`, `{timestamp}`, `{project}`.

---

## 7. Skills & Watcher-Dialog

- `Alt+C` — aktuelle Editor-Zeile in Queue (blockverankert)
- `Alt+Shift+C` — Queue Master (Übersicht aller Silos)
- Standard-Skill in Einstellungen festlegen
- Watcher-Dialog: scharf/entschärfen, Ziel wählen, Probes konfigurieren
