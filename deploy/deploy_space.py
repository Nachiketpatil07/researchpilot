"""Publish the backend to a Hugging Face Space (Docker SDK) in one commit.

    hf auth login                                  # once, with a token that can write
    python deploy/deploy_space.py researchpilot-api

Uploads only what the image needs: Dockerfile, requirements.txt, app/**.py, the latest
evaluation report, and the Space README. Never uploads .env. Add GROQ_API_KEY yourself
as a Space secret (Settings -> Variables and secrets).
"""

import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def files_to_upload() -> list[tuple[Path, str]]:
    files = [
        (BACKEND / "Dockerfile", "Dockerfile"),
        (BACKEND / "requirements.txt", "requirements.txt"),
        (BACKEND / "eval" / "results" / "latest.json", "eval/results/latest.json"),
        (ROOT / "deploy" / "hf-space-README.md", "README.md"),
    ]
    for py in sorted((BACKEND / "app").rglob("*.py")):
        files.append((py, py.relative_to(BACKEND).as_posix()))
    for local, remote in files:
        assert local.name != ".env" and ".env" not in remote.split("/"), "refusing to upload .env"
    return files


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python deploy/deploy_space.py <space-name or owner/space-name>")
    api = HfApi()
    user = api.whoami()["name"]
    space_id = sys.argv[1] if "/" in sys.argv[1] else f"{user}/{sys.argv[1]}"

    api.create_repo(space_id, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    ops = [CommitOperationAdd(path_in_repo=remote, path_or_fileobj=str(local)) for local, remote in files_to_upload()]
    info = api.create_commit(space_id, repo_type="space", operations=ops,
                             commit_message="Deploy ResearchPilot API")
    owner, name = space_id.split("/")
    print(f"Uploaded {len(ops)} files: {info.commit_url}")
    print(f"Space:  https://huggingface.co/spaces/{space_id}")
    print(f"API:    https://{owner.lower()}-{name.lower().replace('_', '-').replace('.', '-')}.hf.space")


if __name__ == "__main__":
    main()
