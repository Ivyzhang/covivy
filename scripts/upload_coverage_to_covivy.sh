#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Upload a coverage report to covivy.

Required:
  COVIVY_UPLOAD_TOKEN or COVERAGE_UPLOAD_TOKEN

Common environment:
  COVIVY_BASE_URL       Defaults to COVERAGE_SERVICE_URL or http://127.0.0.1:8000
  GITHUB_REPOSITORY     owner/repo
  GITHUB_EVENT_NAME     pull_request or push
  GITHUB_EVENT_PATH     path to GitHub event JSON
  GITHUB_SHA            fallback commit sha
  GITHUB_REF_NAME       fallback branch

Options:
  --coverage-file PATH  Defaults to coverage.xml
  --format NAME         Defaults to cobertura
  --base-url URL        Overrides COVIVY_BASE_URL
  --repository OWNER/REPO
  --commit-sha SHA
  --branch NAME
  --base-sha SHA
  --base-branch NAME
  --pr-number NUMBER
  --uploader NAME       Defaults to github-actions
  --dry-run             Print resolved fields instead of uploading
  -h, --help
USAGE
}

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 2
  fi
}

json_value() {
  local path=$1
  local default=${2:-}
  if [[ -n "${GITHUB_EVENT_PATH:-}" && -f "${GITHUB_EVENT_PATH}" ]]; then
    jq -r "${path} // \"${default}\"" "${GITHUB_EVENT_PATH}"
  else
    printf '%s\n' "${default}"
  fi
}

coverage_file="coverage.xml"
format_name="cobertura"
base_url="${COVIVY_BASE_URL:-${COVERAGE_SERVICE_URL:-http://127.0.0.1:8000}}"
repository="${GITHUB_REPOSITORY:-}"
commit_sha=""
branch=""
base_sha=""
base_branch=""
pr_number=""
uploader="github-actions"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --coverage-file)
      coverage_file="$2"
      shift 2
      ;;
    --format)
      format_name="$2"
      shift 2
      ;;
    --base-url)
      base_url="$2"
      shift 2
      ;;
    --repository)
      repository="$2"
      shift 2
      ;;
    --commit-sha)
      commit_sha="$2"
      shift 2
      ;;
    --branch)
      branch="$2"
      shift 2
      ;;
    --base-sha)
      base_sha="$2"
      shift 2
      ;;
    --base-branch)
      base_branch="$2"
      shift 2
      ;;
    --pr-number)
      pr_number="$2"
      shift 2
      ;;
    --uploader)
      uploader="$2"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

need curl
need jq

base_url="${base_url%/}"

if [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]]; then
  pr_number="${pr_number:-$(json_value '.number')}"
  commit_sha="${commit_sha:-$(json_value '.pull_request.head.sha')}"
  branch="${branch:-$(json_value '.pull_request.head.ref')}"
  base_sha="${base_sha:-$(json_value '.pull_request.base.sha')}"
  base_branch="${base_branch:-$(json_value '.pull_request.base.ref')}"
fi

commit_sha="${commit_sha:-${GITHUB_SHA:-}}"
branch="${branch:-${GITHUB_REF_NAME:-}}"

upload_token="${COVIVY_UPLOAD_TOKEN:-${COVERAGE_UPLOAD_TOKEN:-}}"

if [[ -z "${upload_token}" ]]; then
  echo "COVIVY_UPLOAD_TOKEN or COVERAGE_UPLOAD_TOKEN is required" >&2
  exit 2
fi
if [[ -z "${repository}" ]]; then
  echo "repository is required via --repository or GITHUB_REPOSITORY" >&2
  exit 2
fi
if [[ -z "${commit_sha}" ]]; then
  echo "commit sha is required via --commit-sha, GITHUB_SHA, or pull_request event JSON" >&2
  exit 2
fi
if [[ -z "${branch}" ]]; then
  echo "branch is required via --branch, GITHUB_REF_NAME, or pull_request event JSON" >&2
  exit 2
fi
if [[ ! -f "${coverage_file}" ]]; then
  echo "coverage file not found: ${coverage_file}" >&2
  exit 2
fi

if [[ "${dry_run}" == "true" ]]; then
  cat <<EOF
base_url=${base_url}
repository=${repository}
commit_sha=${commit_sha}
branch=${branch}
base_sha=${base_sha}
base_branch=${base_branch}
pr_number=${pr_number}
format=${format_name}
uploader=${uploader}
coverage_file=${coverage_file}
EOF
  exit 0
fi

curl -fS -X POST "${base_url}/api/v1/uploads" \
  -H "Authorization: Bearer ${upload_token}" \
  -F "repository=${repository}" \
  -F "commit_sha=${commit_sha}" \
  -F "branch=${branch}" \
  -F "base_sha=${base_sha}" \
  -F "base_branch=${base_branch}" \
  -F "pr_number=${pr_number}" \
  -F "format=${format_name}" \
  -F "uploader=${uploader}" \
  -F "file=@${coverage_file}"
