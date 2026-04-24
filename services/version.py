"""Version stamp for the running container.

Populated at image build time via Docker build args promoted to ENV.
When no build args are passed (e.g. local `docker compose up --build`
without overrides, or `pytest` outside Docker), every field reads
"unknown" — that is acceptable and not an error.
"""

import os


def get_version() -> dict[str, str]:
    return {
        "git_sha": os.environ.get("FTL_GIT_SHA", "unknown"),
        "built_at": os.environ.get("FTL_BUILT_AT", "unknown"),
        "image_tag": os.environ.get("FTL_IMAGE_TAG", "unknown"),
    }
