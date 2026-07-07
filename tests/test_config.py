import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings, load_env_file


class ConfigTests(unittest.TestCase):
    def test_load_env_file_sets_missing_values_without_overriding_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "GITHUB_APP_PRIVATE_KEY_PATH='/tmp/private-key.pem'",
                        "PUBLIC_BASE_URL=https://coverage.example",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://existing.example"}, clear=True):
                load_env_file(env_path)
                settings = Settings()

        self.assertEqual(settings.github_private_key_path, "/tmp/private-key.pem")
        self.assertEqual(settings.public_base_url, "https://existing.example")


if __name__ == "__main__":
    unittest.main()
