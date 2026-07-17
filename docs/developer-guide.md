[← Documentation index](../README.md#documentation)

# Developer guide

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (`xlsform_studio/tests/`) covers the naming, classification,
logic, constraint and calculation engines, the builders/exporter, the
validators (including static path analysis and choice-list auditing), the
interview simulator, every parser, the end-to-end workflow, and the optional
AI layer (fully mocked at the network boundary — no API key or internet
connection is needed to run the suite).

---

---

## Packaging as a Windows application

See [`packaging/README.md`](../packaging/README.md). In short:

```bat
pip install -r requirements-dev.txt
pyinstaller packaging\xlsform_studio_cli.spec     :: -> dist\xlsform-studio.exe
```

The CLI packages into a single standalone `.exe` (no Python needed on the
target). The Streamlit UI ships as a small virtual-environment launcher.

---
