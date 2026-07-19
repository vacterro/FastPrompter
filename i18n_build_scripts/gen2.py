"""Generate complete Spanish translation file."""
from __future__ import annotations
import ast, re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/en.py', 'r', encoding='utf-8') as f:
    en_d = ast.literal_eval(re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', f.read(), re.DOTALL).group(1))

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/spa.py', 'r', encoding='utf-8') as f:
    spa_d = ast.literal_eval(re.search(r'TRANSLATIONS: dict\[str, str\] = (\{.*\})', f.read(), re.DOTALL).group(1))

# For each EN key not in SPA, we need Spanish translation
# Strategy: for format/technical keys, keep same; for text, translate
NEW: dict[str, str] = {}

for k, v in en_d.items():
    if k in spa_d:
        continue
    NEW[k] = v  # default: same as EN (will override below)

# ── now override with proper Spanish translations ──
# We match by the exact EN key string (from en_d dict)

def T(en_val: str, es_val: str) -> None:
    """Find key by its EN value and set Spanish translation."""
    # Find the key in en_d whose value matches
    for k in list(NEW.keys()):
        if en_d.get(k) == en_val:
            NEW[k] = es_val
            return
    # Try matching key directly
    if en_val in NEW:
        NEW[en_val] = es_val
        return
    print(f"WARN: could not find key for EN value: {en_val!r}")

# Markers / section headers
T("--- APP HOTKEYS (only when window active) ---", "--- TECLAS DE APP (solo con ventana activa) ---")
T("--- GLOBAL HOTKEYS (work anywhere) ---", "--- TECLAS GLOBALES (funcionan en cualquier lado) ---")

# Scale / UI descriptions
T("50\u2013150% whole-UI scaling with readable minimums", "50\u2013150% escala total de IU con m\u00ednimos legibles")
T("Fine-tune the UI scale", "Ajustar finamente la escala de IU")
T("Click sound volume (1-10)", "Volumen de clic (1-10)")
T("Silo Gap Height", "Altura del espacio entre silos")
T("Splitter Handle Width", "Ancho del divisor")
T("UI Gaps:", "Espacios de IU:")

# Drop zones
T("A grid of drop zones appear: insert as text, link in text, copy to silo Files, or link in silo Files", "Aparece cuadr\u00edcula de zonas: insertar como texto, enlazar en texto, copiar a Archivos del silo, o enlazar en Archivos del silo")
T("Customize Drop Zones", "Personalizar zonas de soltar")
T("Drop Zones", "Zonas de soltar")
T("Drop Zones Configuration", "Configuraci\u00f3n de zonas de soltar")
T("Bottom Left Zone", "Zona inferior izquierda")
T("Bottom Left:", "Inf. izq.:")
T("Bottom Right Zone", "Zona inferior derecha")
T("Bottom Right:", "Inf. der.:")
T("Top Left Zone", "Zona superior izquierda")
T("Top Left:", "Sup. izq.:")
T("Top Right Zone", "Zona superior derecha")
T("Top Right:", "Sup. der.:")

# File operations
T("Add .url links instead of copies", "Agregar enlaces .url en lugar de copias")
T("Add Link to Files\u2026", "Agregar enlace a Archivos\u2026")
T("Add dropped file", "Agregar archivo soltado")
T("All Files (*.*)", "Todos los archivos (*.*)")
T("All files (*.*)", "Todos los archivos (*.*)")
T("Clipboard \u2192 File\tCtrl+V", "Portapapeles \u2192 Archivo\tCtrl+V")
T("Clip\u2192File\nSave the clipboard text into this folder as a .txt file", "Clip\u2192Archivo\nGuardar texto del portapapeles en esta carpeta como .txt")
T("Copy Path\tCtrl+Shift+C", "Copiar ruta\tCtrl+Shift+C")
T("Copy that code block to the clipboard", "Copiar ese bloque de c\u00f3digo al portapapeles")
T("Create these folders in the current silo", "Crear estas carpetas en el silo actual")
T("Delete files", "Eliminar archivos")
T("Drop files here \u2014 copied into a plain folder you own. ", "Suelta archivos aqu\u00ed \u2014 copiados a una carpeta tuya. ")
T("Drop files here \u2014 copied into a plain folder you own. Hold Alt while dropping to add links instead of copies.", "Suelta archivos aqu\u00ed \u2014 copiados a una carpeta tuya. Mant\u00e9n Alt para agregar enlaces en lugar de copias.")
T("Enter filename (without .txt):", "Nombre de archivo (sin .txt):")
T("Export all files to\u2026", "Exportar todos los archivos a\u2026")
T("Export the current silo to a .txt/.md file", "Exportar el silo actual a un archivo .txt/.md")
T("Export to\u2026", "Exportar a\u2026")
T("File container", "Contenedor de archivos")
T("Files Folder...", "Carpeta archivos...")
T("Files \u2014 {}", "Archivos \u2014 {}")
T("Files: drop/drag/preview assets for this silo", "Archivos: soltar/arrastrar/previsualizar activos de este silo")
T("Files: drop/drag/preview assets for this silo\n\n{}", "Archivos: soltar/arrastrar/previsualizar activos de este silo\n\n{}")
T("Files\u2014asset drawer for the active silo (drop in / drag out /\npreview / export; plain folder in data/files)\n\n", "Archivos\u2014caj\u00f3n de activos del silo activo (soltar / arrastrar /\nprevisualizar / exportar; carpeta simple en data/files)\n\n")
T("Find / Find &amp; Replace", "Buscar / Buscar y reemplazar")
T("Folder Tpl:", "Plantilla carpeta:")
T("Folder name:", "Nombre de carpeta:")
T("Folder template (e.g. src, docs, assets)", "Plantilla de carpeta (ej. src, docs, assets)")
T("Import Files...\nCopy files into this silo's folder\n(or just drop files anywhere on this window)", "Importar archivos...\nCopiar archivos a la carpeta de este silo\n(o simplemente suelta archivos en cualquier lado de esta ventana)")
T("Import Files\u2026", "Importar archivos\u2026")
T("Import Folder...\nCopy an entire folder into this silo's folder", "Importar carpeta...\nCopiar una carpeta entera a la carpeta de este silo")
T("Import Folder\u2026", "Importar carpeta\u2026")
T("Import folder", "Importar carpeta")
T("Link to files (no copy)", "Enlazar a archivos (sin copia)")
T("Loaded: {}", "Cargado: {}")
T("Markdown Files (*.md)", "Archivos Markdown (*.md)")
T("Merge files", "Fusionar archivos")
T("Name:", "Nombre:")
T("New name:", "Nuevo nombre:")
T("Open Folder\nOpen this silo's folder in Explorer", "Abrir carpeta\nAbrir la carpeta de este silo en el Explorador")
T("Plain folders under", "Carpetas simples en")
T("Save Clipboard", "Guardar portapapeles")
T("Select Export Directory", "Seleccionar directorio de exportaci\u00f3n")
T("Text Files (*.txt)", "Archivos de texto (*.txt)")
T("~50 text formats load as plain text", "~50 formatos de texto se cargan como texto plano")
T("{} file(s)", "{} archivo(s)")
T("{} item(s) \u00b7 {}", "{} elemento(s) \u00b7 {}")
T("add shortcut in container", "agregar acceso directo en contenedor")
T("clipboard has no text", "el portapapeles no tiene texto")
T("fully readable outside FastPrompter", "completamente legible fuera de FastPrompter")
T("insert content into silo", "insertar contenido en silo")
T("insert markdown link at cursor", "insertar enlace markdown en el cursor")
T("location configurable in settings", "ubicaci\u00f3n configurable en ajustes")
T("one click stores the current silo or snippet", "un clic guarda el silo o snippet actual")
T("path copied", "ruta copiada")
T("per-silo asset drawer: drop ANY files in, drag them out, preview images, open, export, link (.url), save clipboard as file. Explorer-style Icons / List / Details views", "caj\u00f3n de activos por silo: suelta CUALQUIER archivo, arrastra, previsualiza im\u00e1genes, abre, exporta, enlaza (.url), guarda portapapeles como archivo. Vistas Iconos / Lista / Detalles")
T("store in silo's container", "guardar en el contenedor del silo")

# Snippet operations
T("Enter snippet number (1-{}):", "N\u00famero de snippet (1-{}):")
T("Overwrite Snippet", "Sobrescribir snippet")
T("Rename Snippet", "Renombrar snippet")
T("Save Snippet", "Guardar snippet")
T("Snippet #{} already exists. Overwrite?", "El snippet #{} ya existe. \u00bfSobrescribir?")
T("Snippet Number", "N\u00famero de snippet")
T("Copy + Clear current silo", "Copiar + limpiar silo actual")
T("Delete Silo", "Eliminar silo")
T("Delete Snippet", "Eliminar snippet")
T("Export/Save Silo to File", "Exportar/guardar silo a archivo")
T("Save current silo as file in its own folder:", "Guardar silo actual como archivo en su propia carpeta:")
T("Save text as snippet / update the edited snippet", "Guardar texto como snippet / actualizar el snippet editado")
T("Silo successfully saved to:\n{}", "Silo guardado exitosamente en:\n{}")
T("Silos exported to:\n{}", "Silos exportados a:\n{}")

# Silos
T("Backup Silo", "Respaldar silo")
T("Collapse / expand its children", "Contraer / expandir sus hijos")
T("Nest it as a child (1 level; its files can merge into the parent)", "Anidar como hijo (1 nivel; sus archivos pueden fusionarse al padre)")
T("New empty silo at the top (max 5 blanks)", "Nuevo silo vac\u00edo arriba (m\u00e1x 5 vac\u00edos)")
T("Reorder \u2014 dragging a child out promotes it back to top level", "Reordenar \u2014 arrastrar un hijo lo promueve de vuelta al nivel superior")
T("Move it to the trash (text + files land in data/files/_trash)", "Mover a la papelera (texto+archivos van a data/files/_trash)")
T("clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed", "limpiar o tirar un silo escribe su texto a data/files/_trash/ y mueve sus archivos all\u00ed; nada se destruye")

# Tabs / Projects
T("Maximum of 5 tabs/projects. Remove one first.", "M\u00e1ximo 5 pesta\u00f1as/proyectos. Elimina uno primero.")
T("Projects \u2014 mouse wheel switches tabs", "Proyectos \u2014 la rueda del rat\u00f3n cambia pesta\u00f1as")
T("Switch project", "Cambiar proyecto")
T("Transfer to project, replace from, move to bottom&hellip;", "Transferir a proyecto, reemplazar desde, mover al fondo&hellip;")
T("up to 5 tabs, each with its own silos, snippets, archive", "hasta 5 pesta\u00f1as, cada una con sus propios silos, snippets, archivo")

# Auto-bullet / formatting
T("Auto-Bullet (Right-Click): {}\nLeft-Click: Convert selected lines between dashes and bullets.", "Auto-vi\u00f1eta (clic der.): {}\nClic izq.: Convertir l\u00edneas entre guiones y vi\u00f1etas.")
T("Auto-Bullet:", "Auto-vi\u00f1eta:")
T("Insert a spaced --- divider and start a fresh bullet", "Insertar divisor --- espaciado y empezar una vi\u00f1eta nueva")
T("Lines after --- (before the fresh bullet)", "L\u00edneas despu\u00e9s de --- (antes de la vi\u00f1eta nueva)")
T("Lines before ---", "L\u00edneas antes de ---")

# Backup / Export
T("Backup & Export Settings", "Respaldar y exportar ajustes")
T("Backup Database (.db)", "Respaldar base de datos (.db)")
T("Backup Full Database", "Respaldar BD completa")
T("Creates an exact copy of the local_data_v15.db file containing all settings, silos, and snippets.", "Crea una copia exacta del archivo local_data_v15.db con todos los ajustes, silos y snippets.")
T("Database backed up to:\n{}", "BD respaldada en:\n{}")
T("Export All Silos", "Exportar todos los silos")
T("Export All...\nCopy every file here to a folder you pick", "Exportar todo...\nCopiar cada archivo aqu\u00ed a una carpeta que elijas")
T("Export Silos & Text", "Exportar silos y texto")
T("Export all Silo contents to readable text formats.", "Exportar contenido de todos los silos a formatos de texto legibles.")
T("Failed to backup:\n{}", "Error al respaldar:\n{}")
T("Failed to export:\n{}", "Error al exportar:\n{}")
T("Failed to load font: {}", "Error al cargar fuente: {}")
T("Failed to restore backup:\n{}", "Error al restaurar respaldo:\n{}")
T("Failed to save backup:\n{}", "Error al guardar respaldo:\n{}")
T("Failed to save file:\n{}", "Error al guardar archivo:\n{}")
T("Save && Apply", "Guardar && aplicar")

# Window / UI state
T("Always on Top \u2014 keep the window above all others", "Siempre visible \u2014 mantener la ventana sobre todas las dem\u00e1s")
T("App will restart. Proceed?", "La app se reiniciar\u00e1. \u00bfContinuar?")
T("Lock / unlock window size & position", "Bloquear / desbloquear tama\u00f1o y posici\u00f3n de ventana")
T("Show / hide FastPrompter from anywhere", "Mostrar / ocultar FastPrompter desde cualquier lugar")
T("Show / hide the line-number gutter\n(click the gutter to place colored margin marks)", "Mostrar / ocultar n\u00fameros de l\u00ednea\n(clic en el margen para marcas de color)")
T("Show window + toggle the sidebar", "Mostrar ventana + alternar barra lateral")
T("Snap the window through screen corners", "Ajustar la ventana a las esquinas de la pantalla")
T("Source and destination are the same file.", "Origen y destino son el mismo archivo.")
T("Toggle Hide on Click-Out", "Ocultar al hacer clic fuera")
T("Toggle always-on-top", "Alternar siempre visible")
T("Toggle [ ] checkboxes on the line / selection", "Alternar casillas [ ] en la l\u00ednea / selecci\u00f3n")
T("Zen / focus mode (hide all chrome)", "Modo zen / enfoque (ocultar todo el chrome)")

# Confirmation dialogs
T("Are you sure you want to delete this silo and its content?", "\u00bfSeguro que quieres eliminar este silo y su contenido?")
T("Are you sure you want to delete this snippet?", "\u00bfSeguro que quieres eliminar este snippet?")
T("Clear all custom fonts and reset to defaults?", "\u00bfLimpiar fuentes personalizadas y restablecer valores?")
T("Delete from this silo's folder?\n\n{}\n", "\u00bfEliminar de la carpeta de este silo?\n\n{}\n")
T("Delete this snippet?", "\u00bfEliminar este snippet?")
T("How should '{}' be added?", "\u00bfC\u00f3mo agregar '{}'?")
T("Nuke '{}' and all snippets?", "\u00bfEliminar '{}' y todos sus snippets?")
T("Remove all custom fonts from the font selector?", "\u00bfEliminar todas las fuentes personalizadas del selector?")
T("The nested silo owns {} file(s).\nMerge them into the parent silo's Files?\n(collisions get ' (2)' names \u2014 nothing is overwritten)", "El silo anidado tiene {} archivo(s).\n\u00bfFusionarlos en Archivos del silo padre?\n(las colisiones obtienen ' (2)' \u2014 nada se sobrescribe)")

# Font
T("Font loaded but no font families found.", "Fuente cargada pero no se encontraron familias de fuente.")

# Help / keyboard shortcuts
T("Close search bar; press again to hide &amp; save", "Cerrar barra de b\u00fasqueda; presiona de nuevo para ocultar y guardar")
T("Fold (collapse) the section; right-click editor &rarr; Expand All Folds", "Plegar (contraer) la secci\u00f3n; clic der. &rarr; Expandir todos los pliegues")
T("Header the line: # + bold + underline + timestamp, then jump 2 lines down onto a fresh &bull; bullet", "Titular la l\u00ednea: # + negrita + subrayado + timestamp, luego saltar 2 l\u00edneas a una vi\u00f1eta &bull; nueva")
T("Insert Divider Line\tCtrl+W", "Insertar l\u00ednea divisoria\tCtrl+W")
T("Insert Kanban", "Insertar Kanban")
T("Open\tEnter", "Abrir\tIntro")
T("Source View: Plain text editor\nLive Preview: Editor with live markdown highlights (default)\nReading: Read-only rendered markdown view", "Vista fuente: Editor de texto plano\nVista previa: Editor con resaltado markdown en vivo (predet.)\nLectura: Vista markdown renderizada s\u00f3lo lectura")
T("Strikethrough (Ctrl+T)\nCross out selected text.", "Tachado (Ctrl+T)\nTachar texto seleccionado.")
T("Undo / redo \u2014 text <i>and</i> silo actions (clear, delete, move, pin, archive, tabs)", "Deshacer / rehacer \u2014 texto <i>y</i> acciones de silo (limpiar, eliminar, mover, fijar, archivar, pesta\u00f1as)")
T("View\nCycle view: Icons \u2192 List \u2192 Details (like Explorer)", "Vista\nCiclo: Iconos \u2192 Lista \u2192 Detalles (como el Explorador)")
T("View ({})", "Vista ({})")
T("View ({})\nCycle view: Icons \u2192 List \u2192 Details (like Explorer)", "Vista ({})\nCiclo: Iconos \u2192 Lista \u2192 Detalles (como el Explorador)")
T("Zoom the editor font", "Zoom de la fuente del editor")
T("``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line", "``` vallas renderizan monospace con tintes de sintaxis, n\u00fameros de l\u00ednea auto y bot\u00f3n de copia en la l\u00ednea de valla")
T("collapse code blocks and # header sections with the fold box; right-click &rarr; Expand All Folds", "contraer bloques de c\u00f3digo y secciones # con el cuadro de pliegue; clic der. &rarr; Expandir todos los pliegues")
T("Flip pages", "Voltear p\u00e1ginas")
T("live highlighting, clickable links &amp; checkboxes, auto-bullets (- + space, Enter continues), zebra stripes, line numbers", "resaltado en vivo, enlaces y casillas cliqueables, auto-vi\u00f1etas (- + espacio, Enter contin\u00faa), rayas de cebra, n\u00fameros de l\u00ednea")
T("named text blocks per project tab; instant paste", "bloques de texto nombrados por pesta\u00f1a de proyecto; pegado instant\u00e1neo")
T("Paste snippet 1&ndash;10 into the active app", "Pegar snippet 1&ndash;10 en la app activa")
T("Paste snippet 1&ndash;10 into the editor", "Pegar snippet 1&ndash;10 en el editor")
T("Quick List pie menu at the cursor", "Men\u00fa circular de lista r\u00e1pida en el cursor")
T("Select previous / next silo", "Seleccionar silo anterior / siguiente")
T("Settings &rarr; Header Fmt: {text}, {time}, {state} (Morning/Day/Evening/Night) \u2014 bold markers are yours to keep or drop", "Ajustes &rarr; Formato encabezado: {text}, {time}, {state} (Ma\u00f1ana/D\u00eda/Tarde/Noche) \u2014 marcadores negrita t\u00fayos para conservar o quitar")
T("Settings &rarr; Header Fmt: {{text}}, {{time}}, {{state}} (Morning/Day/Evening/Night) \u2014 bold markers are yours to keep or drop", "Ajustes &rarr; Formato encabezado: {{text}}, {{time}}, {{state}} (Ma\u00f1ana/D\u00eda/Tarde/Noche) \u2014 marcadores negrita t\u00fayos para conservar o quitar")
T("Swap their places", "Intercambiar sus lugares")
T("Template for the Ctrl+E header.\n{text} \u2014 the line's text\n{time} \u2014 timestamp\n{state} \u2014 Morning / Day / Evening / Night\nMarkdown markers (** __ etc.) are yours to add or drop.", "Plantilla para el encabezado Ctrl+E.\n{text} \u2014 texto de la l\u00ednea\n{time} \u2014 timestamp\n{state} \u2014 Ma\u00f1ana / D\u00eda / Tarde / Noche\nMarcadores Markdown (** __ etc.) tuyos para agregar o quitar.")
T("Up/Down arrows: Previous / next silo", "Flechas arriba/abajo: Silo anterior / siguiente")

# Bold / Italic / Underline formatting
T("Bold ({})\nMake selected text bold.", "Negrita ({})\nPoner texto seleccionado en negrita.")
T("Bold / Italic / Underline", "Negrita / Cursiva / Subrayado")
T("Clear Format\nRemove all explicit font styling from text.", "Limpiar formato\nEliminar todo estilo de fuente expl\u00edcito del texto.")
T("Clear Formatting", "Limpiar formato")
T("Italic ({})\nMake selected text italic.", "Cursiva ({})\nPoner texto seleccionado en cursiva.")
T("Underline ({})\nMake selected text underlined.", "Subrayado ({})\nSubrayar texto seleccionado.")

# Date / time
T("date + time with seconds, day word and an optional mini analog clock, all toggleable", "fecha + hora con segundos, palabra del d\u00eda y un mini reloj anal\u00f3gico opcional, todo alternable")

# Header
T("Header (Ctrl+E)\nTitle the line: # + bold + underline + timestamp,\nthen land 2 lines below on a fresh bullet.", "Encabezado (Ctrl+E)\nTitular la l\u00ednea: # + negrita + subrayado + timestamp,\nluego saltar 2 l\u00edneas a una vi\u00f1eta nueva.")
T("Format:", "Formato:")

# Markdown
T("Mark it done \u2014 the tick stays until clicked again", "Marcar como hecho \u2014 la marca queda hasta hacer clic de nuevo")
T("optional UI clicks and typewriter effect", "clics de IU opcionales y efecto de m\u00e1quina de escribir")

# Navigation
T("Jump to silo 1&ndash;10", "Saltar a silo 1&ndash;10")
T("Next archive page", "Siguiente p\u00e1gina de archivo")
T("Next silo page", "Siguiente p\u00e1gina de silos")
T("Next snippet page", "Siguiente p\u00e1gina de snippets")
T("Open with the cursor at start / end", "Abrir con el cursor al inicio / final")
T("Previous / next silo", "Silo anterior / siguiente")
T("Previous archive page", "P\u00e1gina de archivo anterior")
T("Previous silo page", "P\u00e1gina de silos anterior")
T("Previous snippet page", "P\u00e1gina de snippets anterior")

# ON/OFF
T("OFF", "APAG")
T("ON", "ENC")

# Window actions
T("Esc : Hide Window & Auto-save", "Esc : Ocultar ventana y autoguardar")
T("Quit completely", "Salir completamente")

# Ctrl+ shortcuts
T("Ctrl+Alt+Shift+Q : Quit Application Completely", "Ctrl+Alt+Shift+Q : Salir completamente de la app")
T("Ctrl+D : Toggle Focus Mode", "Ctrl+D : Modo enfoque")
T("Ctrl+F : Find Text", "Ctrl+F : Buscar texto")
T("Ctrl+H : Replace Text", "Ctrl+H : Reemplazar texto")
T("Ctrl+N : New Empty Snippet", "Ctrl+N : Nuevo snippet vac\u00edo")
T("Ctrl+Q : Cycle Snap Corners (move across screens)", "Ctrl+Q : Ciclo esquinas (mover entre pantallas)")
T("Ctrl+S : Save Snippet", "Ctrl+S : Guardar snippet")
T("Ctrl+Shift+S : Export/Save Silo to File", "Ctrl+Shift+S : Exportar/guardar silo a archivo")
T("Ctrl+Z : Undo Text Change", "Ctrl+Z : Deshacer cambio de texto")
T("Cycle Snap Corners (move across screens)", "Ciclo esquinas (mover entre pantallas)")
T("Expand All Folds", "Expandir todos los pliegues")
T("F1 - F10 : Execute Snippet 1-10", "F1 - F10 : Ejecutar snippet 1-10")
T("New Folder\tCtrl+N", "Nueva carpeta\tCtrl+N")
T("Rename\u2026\tF2", "Renombrar\u2026\tF2")
T("Delete\u2026\tDel", "Eliminar\u2026\tSupr")

# Misc status
T("Error", "Error")
T("Success", "\u00c9xito")

# Sound
T("Play a typewriter tick for every typed character.\nPlace 'type1.wav' in the 'sound' folder to use your own typing sound.", "Sonido de m\u00e1quina de escribir por cada car\u00e1cter.\nPon 'type1.wav' en 'sound' para tu propio sonido.")
T("Play click sounds for buttons and actions.\nYou can place your own .wav files in the 'sound' folder to override:\n\u2022 newbutton1.wav (New button)\n\u2022 savebutton1.wav (Save button)\n\u2022 button1.wav (Click/Silo)\n\u2022 button2.wav (Snippet)\n\u2022 tickbox1.wav (Checkbox)\n\u2022 delete1.wav (Delete)\n\u2022 clear1.wav (Clear)", "Sonidos de clic para botones y acciones.\nPon tus archivos .wav en la carpeta 'sound' :\n\u2022 newbutton1.wav (Nuevo)\n\u2022 savebutton1.wav (Guardar)\n\u2022 button1.wav (Clic/Silo)\n\u2022 button2.wav (Snippet)\n\u2022 tickbox1.wav (Casilla)\n\u2022 delete1.wav (Eliminar)\n\u2022 clear1.wav (Limpiar)")

# Last edited
T("Last Edited < 1 day", "\u00daltima edici\u00f3n < 1 d\u00eda")
T("Last Edited < 1 hr", "\u00daltima edici\u00f3n < 1 h")
T("Last Edited < 1 min", "\u00daltima edici\u00f3n < 1 min")
T("Last Edited < 49 days", "\u00daltima edici\u00f3n < 49 d\u00edas")

# Files descriptions
T("Files\nAsset drawer for the active silo: drop any files in,\ndrag them out, preview, export. Stored as a plain folder\nin data/files \u2014 readable outside FastPrompter.", "Archivos\nCaj\u00f3n de activos del silo activo: suelta archivos,\narrastra, previsualiza, exporta. Carpeta simple\nen data/files \u2014 legible fuera de FastPrompter.")
T("SQLite next to the app; daily Markdown backups in Documents; crash log next to the EXE", "SQLite junto a la app; respaldos Markdown diarios en Documents; registro de errores junto al EXE")
T("up to 100 auto-saved scratchpads per project; pins, recency color tints, line counters, drag to reorder", "hasta 100 blocas autoguardados por proyecto; fijados, tintes de color por reciente, contadores de l\u00ednea, arrastrar para reordenar")

# Emoji / icon keys
T("\u279b Transfer to Snippet", "\u279b Transferir a Snippet")
T("\U0001f4be Save as Snippet #\u2026", "\U0001f4be Guardar como Snippet #\u2026")
T("\U0001f4be Save text as Snippet", "\U0001f4be Guardar texto como Snippet")
T("\U0001f4c1 Files\u2026", "\U0001f4c1 Archivos\u2026")
T("\U0001f4c1{}", "\U0001f4c1{}")
T("\U0001f4c4 Drop as Text", "\U0001f4c4 Soltar como texto")
T("\U0001f4c4 Insert as Text", "\U0001f4c4 Insertar como texto")
T("\U0001f4dd Drop as Text", "\U0001f4dd Soltar como texto")
T("\U0001f4e5 Copy to Files \U0001f4c1", "\U0001f4e5 Copiar a Archivos \U0001f4c1")
T("\U0001f4e5 Copy to Silo Files \U0001f4c1", "\U0001f4e5 Copiar a Archivos del silo \U0001f4c1")
T("\U0001f517 Link in Files \U0001f4c1", "\U0001f517 Enlazar en Archivos \U0001f4c1")
T("\U0001f517 Link in Silo Files \U0001f4c1", "\U0001f517 Enlazar en Archivos del silo \U0001f4c1")
T("\U0001f517 Link in Text", "\U0001f517 Enlazar en texto")
T("\U0001f5c2 Open Trash Folder", "\U0001f5c2 Abrir carpeta de papelera")

T("Build Template", "Crear plantilla")
T("Build Template Folders", "Crear carpetas de plantilla")
T("Replace with...", "Reemplazar con...")
T("Replaced {} occurrences.", "{} ocurrencias reemplazadas.")

# ── Build complete output ──
complete = {}
for k in en_d:
    complete[k] = spa_d[k] if k in spa_d else NEW[k]

# Verify
assert len(complete) == len(en_d), f"Missing keys: {len(en_d)} vs {len(complete)}"

# Write file
out_lines = [
    '"""Traducciones al español (Spanish) — todas las claves."""',
    '',
    'from __future__ import annotations',
    '',
    'TRANSLATIONS: dict[str, str] = {',
]

keys_sorted = sorted(complete.keys())
for i, key in enumerate(keys_sorted):
    val = complete[key]
    ek = key.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
    ev = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
    out_lines.append(f'    "{ek}": "{ev}",')

out_lines.append('}')
out_lines.append('')

output = '\n'.join(out_lines)

with open('V:/_TEMP_/opencode/spa_full.py', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Written {len(complete)} translations to spa_full.py")
print(f"File size: {len(output.encode('utf-8'))} bytes")
