import unittest

from scripts.local_e2e_upload import build_multipart, normalize_base_url


class LocalE2EUploadScriptTests(unittest.TestCase):
    def test_normalize_base_url_removes_trailing_slash(self):
        self.assertEqual(normalize_base_url("http://localhost:8000/"), "http://localhost:8000")

    def test_build_multipart_includes_fields_and_file(self):
        body, content_type = build_multipart(
            {
                "repository": "octo/demo",
                "commit_sha": "abc123",
                "format": "lcov",
            },
            "coverage.info",
            b"SF:src/api.py\nDA:1,1\nend_of_record\n",
            boundary="test-boundary",
        )

        self.assertEqual(content_type, "multipart/form-data; boundary=test-boundary")
        self.assertIn(b'name="repository"\r\n\r\nocto/demo', body)
        self.assertIn(b'name="file"; filename="coverage.info"', body)
        self.assertIn(b"SF:src/api.py\nDA:1,1\nend_of_record\n", body)
        self.assertTrue(body.endswith(b"--test-boundary--\r\n"))


if __name__ == "__main__":
    unittest.main()
