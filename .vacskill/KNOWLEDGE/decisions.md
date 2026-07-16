## File container (v0.4.0)
Silo assets live in real folders: data/files/<category-slug>/<silo-title-slug>/.
Keyed by title slug, not slot index — survives reorders; retitle detaches folder (by design).
No DB/sidecar: folder is truth. Same-title silos share a folder. Empty title -> untitled.
## File container (v0.4.0)
Silo assets live in real folders: data/files/<category-slug>/<silo-title-slug>/.
Keyed by title slug (silo_slug in ui/file_container.py), NOT slot index - folders survive silo reorders but a retitled silo detaches from its old folder (by design, folder stays readable).
No database, no sidecar metadata: the folder is the source of truth; panel is a thin window over os.listdir.
Same-title silos share one folder. Empty title -> untitled.
