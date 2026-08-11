# FastPrompter für Dummies (Opa erklärt's)

> Setz dich, hol dir einen Tee. Kurz und knapp, ohne Geschwafel.

## Was es ist

Ein Notizblock mit einer Taste. Drück `Alt+X` — ein Fenster ploppt am
Cursor auf. Drück `Esc` — weg. Wie ein Kuckuck, nur nützlicher. Drin:
hundert nummerierte Notizfächer ("Silos") für Text, fertige Snippets auf
`F1`–`F10`, Projekt-Tabs, eine Datei-Schublade pro Notiz, ein Archiv,
ein Papierkorb. Es ist eine portable Windows-App — keine Installation,
keine Admin-Rechte.

## Wofür es gut ist

Damit du den Gedanken nicht verlierst, während du nach einem Notizblock
kramst. Ein Prompt für die KI, ein Code-Schnipsel, eine Einkaufsliste,
ein E-Mail-Entwurf — tippst du, versteckt sich das Fenster von selbst,
der Text ist schon gespeichert. Es gibt keinen "Speichern"-Knopf: in dem
Moment, wo du aufhörst zu tippen, liegt es schon auf der Platte. Strom
weg mitten im Satz — das Silo überlebt.

## Warum nicht einfach die Cloud

Weil dein Notiztext niemanden etwas angeht. Alles lebt in einem `data/`-
Ordner neben dem Programm: kein Konto, keine Cloud, keine Telemetrie.
Kopier den Ordner auf einen USB-Stick — das ist dein Backup und die
ganze Installation in einem Rutsch.

## Wo was liegt

- `data/local_data_v15.db` — die Datenbank, in Echtzeit geschrieben.
- `data/files/<Projekt>/<Silo>/` — die Anhänge jeder Notiz, ganz normale
  Ordner, öffne sie im Explorer wann immer du willst.
- `data/files/_trash/` — wohin ein mittelgeklicktes Silo wandert: hier
  brennt nichts, du kannst es jederzeit zurückholen.
- `Documents\.fastprompter\` — ein täglicher Markdown-Spiegel von allem,
  falls die App selbst mal nicht startet — der Text liest sich trotzdem
  in jedem Editor.

## So benutzt man es wirklich (Kurzfassung)

- `Alt+X` — Fenster von überall holen/verstecken.
- `F1`–`F10` / `Ctrl+Shift+1`–`9` — Snippet 1-10 einfügen.
- `Ctrl+1`–`Ctrl+0` — zu Silo 1-10 springen.
- `Ctrl+N` — ein frisches leeres Silo; `Alt+Up`/`Alt+Down` — zwischen
  ihnen wandern.
- `Ctrl+W` — einen abgesetzten --- Trenner einfügen.
- `Alt+W` — einen abgesetzten --- Trenner einfügen und einen frischen
  Bullet starten.
- `Ctrl+E` — Zeile zum Header machen: # + fett + unterstrichen + Zeitstempel.
- `Ctrl+Return` — [ ] Checkboxen umschalten.
- `Ctrl+B` / `Ctrl+I` / `Ctrl+U` / `Ctrl+T` — fett, kursiv, unterstrichen, durchgestrichen.
- `Alt+Backspace` — das vorherige Wort löschen.
- `Ctrl+S` — Snippet speichern.
- `Ctrl+D` — Zen-Modus.
- `Ctrl+Q` — Fenster an Ecken andocken.
- Mittelklick auf ein Silo — in den Papierkorb (nicht für immer weg).
- Mit der Maus über ein Silo fahren — Knöpfe erscheinen: Haken ✅, Dateien 📁, Pin 📌, Archiv 📥.
- Rechtsklick auf die Projekt-Dropdown — Tabs hinzufügen, umbenennen oder löschen.

Die komplette Feature-Liste, Screenshots und eine Erklärung jedes Knopfs
stehen in [README.md](README.md) und im
[Wiki](https://github.com/vacterro/FastPrompter/wiki/User-Guide). Die
Opas-Stimme-Erklärung ist dieses Guide selbst.

## Fazit

Eine Taste — `Alt+X` — und dein ganzes Durcheinander aus Gedanken, Code
und Links lebt an einem Ort, läuft nicht weg und meldet sich bei
niemandem. Opa ist zufrieden.
