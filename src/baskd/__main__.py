"""``python -m baskd``: run the API locally with uvicorn (settings from ``.env``/env)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("baskd.app:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
