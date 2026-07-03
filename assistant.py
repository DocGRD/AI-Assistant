#!/usr/bin/env python
"""Back-compat entry point.

The service now lives in the ``assistant_core`` package. Prefer
``python -m assistant_core``; this shim keeps ``python assistant.py`` working
(and any existing systemd unit that calls it).
"""

from assistant_core.app import main

if __name__ == "__main__":
    main()
