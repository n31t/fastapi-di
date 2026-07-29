"""Force the test suite onto the dedicated test database before src.core.config loads."""

import os

os.environ["DB_NAME"] = "fastapi_di_test"
