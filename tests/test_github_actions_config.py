import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GitHubActionsConfigTests(unittest.TestCase):
    def test_upload_action_wraps_shell_uploader(self):
        action = ROOT / "upload-action" / "action.yml"
        self.assertTrue(action.exists(), "upload-action/action.yml should exist")
        text = action.read_text()

        self.assertIn("using: composite", text)
        self.assertIn("COVIVY_UPLOAD_TOKEN: ${{ inputs.token }}", text)
        self.assertIn("COVIVY_BASE_URL: ${{ inputs.base-url }}", text)
        self.assertIn("scripts/upload_coverage_to_covivy.sh", text)
        self.assertIn("--coverage-file", text)
        self.assertIn("--format", text)

    def test_ci_workflow_runs_lint_tests_coverage_and_covivy_upload(self):
        workflow = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(workflow.exists(), ".github/workflows/ci.yml should exist")
        text = workflow.read_text()

        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertIn('name: "Static Check: Lint"', text)
        self.assertIn("name: Test with Coverage", text)
        self.assertIn("name: Generate Coverage Report", text)
        self.assertIn("name: Covivy Coverage", text)
        self.assertIn("needs: test-with-coverage", text)
        self.assertIn("needs: generate-coverage-report", text)
        self.assertIn("python -m ruff check", text)
        self.assertIn(
            "python -m coverage run --data-file coverage-data/coverage.db "
            "-m unittest discover -s tests",
            text,
        )
        self.assertIn("path: coverage-data/coverage.db", text)
        self.assertIn("python -m coverage xml --data-file coverage-data/coverage.db", text)
        self.assertIn("path: coverage.xml", text)
        self.assertIn("uses: ./upload-action", text)
        self.assertIn(
            "if: (github.event_name == 'pull_request' || github.event_name == 'push')",
            text,
        )
        self.assertIn("COVIVY_BASE_URL", text)
        self.assertIn("COVIVY_UPLOAD_TOKEN", text)
        self.assertIn("coverage.xml", text)


if __name__ == "__main__":
    unittest.main()
