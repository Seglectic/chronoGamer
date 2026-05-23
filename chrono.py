#!/usr/bin/env python3
"""chronoGamer development server and packager."""

from __future__ import annotations

import argparse
import base64
import mimetypes
import shutil
import subprocess
import sys
import tempfile
import zipapp
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_NAME = "chronoGamer"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1337
ROOT_DIR = Path(__file__).resolve().parent
CLIENT_DIR = ROOT_DIR / "client"
BIN_DIR = ROOT_DIR / "bin"
SOURCE_FILE = Path(__file__).resolve()
EMBEDDED_RESOURCES = None


def decode_embedded_resources() -> dict[str, bytes]:
    if not EMBEDDED_RESOURCES:
        return {}

    return {
        route: base64.b64decode(encoded)
        for route, encoded in EMBEDDED_RESOURCES.items()
    }


def collect_client_resources() -> dict[str, str]:
    payload: dict[str, str] = {}
    for path in sorted(CLIENT_DIR.rglob("*")):
        if path.is_file():
            route = "/" + path.relative_to(CLIENT_DIR).as_posix()
            payload[route] = base64.b64encode(path.read_bytes()).decode("ascii")
    return payload


def load_route_bytes(route: str) -> tuple[bytes | None, str]:
    embedded = decode_embedded_resources()
    if route in embedded:
        mime_type = mimetypes.guess_type(route)[0] or "application/octet-stream"
        return embedded[route], mime_type

    file_path = (CLIENT_DIR / route.lstrip("/")).resolve()
    try:
        file_path.relative_to(CLIENT_DIR.resolve())
    except ValueError:
        return None, "text/plain; charset=utf-8"

    if not file_path.is_file():
        return None, "text/plain; charset=utf-8"

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return file_path.read_bytes(), mime_type


class ChronoHandler(BaseHTTPRequestHandler):
    def serve_route(self, include_body: bool) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/":
            route = "/index.html"

        body, mime_type = load_route_bytes(route)
        if body is None:
            self.send_error(404, "Not Found")
            return

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self.serve_route(include_body=True)

    def do_HEAD(self) -> None:
        self.serve_route(include_body=False)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write(f"[chronoGamer] {self.address_string()} - {fmt % args}\n")


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), ChronoHandler)
    print(f"Serving {APP_NAME} on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


def build_source_text() -> str:
    marker = "EMBEDDED_RESOURCES = None"
    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    if marker not in source_text:
        raise RuntimeError(f"Could not find marker: {marker}")

    payload = collect_client_resources()
    embedded_block = f"EMBEDDED_RESOURCES = {payload!r}"
    return source_text.replace(marker, embedded_block, 1)


def ensure_output_path(mode: str, output: str | None) -> Path:
    suffix = {
        "py": ".py",
        "pyz": ".pyz",
        "exe": ".exe",
    }[mode]

    if output:
        candidate = Path(output)
        if not candidate.is_absolute() and candidate.parent == Path("."):
            candidate = BIN_DIR / candidate
    else:
        candidate = BIN_DIR / f"chronoGamer{suffix}"

    if candidate.suffix.lower() != suffix:
        candidate = candidate.with_suffix(suffix)

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def build_python_file(output_path: Path) -> Path:
    output_path.write_text(build_source_text(), encoding="utf-8")
    return output_path


def build_zipapp(output_path: Path) -> Path:
    source_text = build_source_text()
    with tempfile.TemporaryDirectory(prefix="chronogamer-pyz-") as temp_dir:
        temp_path = Path(temp_dir)
        main_file = temp_path / "__main__.py"
        main_file.write_text(source_text, encoding="utf-8")
        zipapp.create_archive(
            temp_path,
            target=output_path,
            interpreter="/usr/bin/env python3",
        )
    return output_path


def build_windows_exe(output_path: Path) -> Path:
    if sys.platform != "win32":
        raise RuntimeError(
            "Windows .exe builds must be run on Windows. "
            "Use `uv run chrono.py build --mode py` or `--mode pyz` on Linux/macOS."
        )

    if shutil.which("pyinstaller") is None:
        try:
            import PyInstaller  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "PyInstaller is required for --mode exe. Install it with "
                "`uv sync`, then run the build on Windows with `uv run spawn.py build --mode exe`."
            ) from exc

    source_text = build_source_text()
    with tempfile.TemporaryDirectory(prefix="chronogamer-exe-") as temp_dir:
        temp_path = Path(temp_dir)
        source_file = temp_path / "chronogamer_embedded.py"
        work_dir = temp_path / "build"
        spec_dir = temp_path / "spec"
        dist_dir = output_path.parent
        source_file.write_text(source_text, encoding="utf-8")

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--name",
            output_path.stem,
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            "--specpath",
            str(spec_dir),
            str(source_file),
        ]
        subprocess.run(command, check=True)

    return output_path


def build_artifact(mode: str, output: str | None) -> Path:
    output_path = ensure_output_path(mode, output)
    if mode == "py":
        return build_python_file(output_path)
    if mode == "pyz":
        return build_zipapp(output_path)
    if mode == "exe":
        return build_windows_exe(output_path)
    raise ValueError(f"Unsupported build mode: {mode}")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="chronoGamer development server and build tool.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the local dev server.")
    serve_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind.")
    serve_parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=int,
        help="Port to listen on.",
    )

    build_parser = subparsers.add_parser("build", help="Create a packaged artifact.")
    build_parser.add_argument(
        "--mode",
        choices=("py", "pyz", "exe"),
        default="py",
        help="Build target type.",
    )
    build_parser.add_argument(
        "--output",
        help="Output filename or path. Bare filenames are written into bin/.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        if args.command in (None, "serve"):
            run_server(
                host=getattr(args, "host", DEFAULT_HOST),
                port=getattr(args, "port", DEFAULT_PORT),
            )
            return 0

        if args.command == "build":
            output_path = build_artifact(args.mode, args.output)
            print(f"Built {output_path}")
            return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
