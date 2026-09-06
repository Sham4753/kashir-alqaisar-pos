# CAESAR POS Production v1

This release is sanitized for first-run setup: transactional records, demo users, demo menu data, tables, counters, logs, caches, and temporary files are empty or removed.

`CAESAR_POS.exe` must be generated on Windows by running `Setup_CAESAR_OneFile.bat`, because PyInstaller produces Windows executables and this staging environment is Linux. The build script supports local wheels, installed packages, or an internet fallback.
