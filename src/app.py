"""MM.AI desktop UI entry point.

Run::

    python -m src.app
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.theme import apply_theme
from .workspace_window import create_workspace_window


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("MM.AI")
    app.setOrganizationName("MM.AI")
    apply_theme(app)
    window, _controller = create_workspace_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
