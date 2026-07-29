"""Point the test suite at the dedicated test database before src.core.config loads."""

import os

os.environ.setdefault("DB_NAME", "fastapi_di_test")
