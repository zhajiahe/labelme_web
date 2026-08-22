# The annotator is a local web service, not a Qt desktop window

`labelme` starts a FastAPI process, serves a browser SPA from `labelme/_web/`,
and reads/writes the existing Annotation File format. PySide6/Qt widgets are
removed. This reopens the UI layer described in ADR-0001 (Window State via
QSettings) and ADR-0005 (Qt Fusion color scheme / QIcon tinting): those
mechanisms no longer exist. Settings still live in `~/.labelmerc`; chrome
theming is CSS (`color_theme`). Window geometry is not persisted.

## Considered options

- **Keep Qt as a fallback** — rejected: two UIs would fork the session and
  canvas logic. The conversion deletes the Qt stack.
- **FastAPI + static SPA** — chosen: fits the Python packaging model, keeps
  the Annotation codec and AI Assist sessions in-process, and needs no Node
  build.

## Consequences

- CLI flags (`--labels`, `--flags`, `--config`, `--output`, …) still configure
  the session; `--host` / `--port` / `--no-browser` bind the service.
- GUI QA drives a browser at localhost, not a QMainWindow.
- The web UI ships English chrome. Qt `.ts`/`.qm` catalogs and the Language
  setting are not used.
