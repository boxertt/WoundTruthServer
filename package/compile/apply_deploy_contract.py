"""Patch a copied backend so the compiled program matches the deploy layout.

The release checkout itself is not modified. This runs only against the build copy.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{path.name} 里找不到{label}，发布分支的入口变了，需要更新编译补丁")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    root = Path(sys.argv[1])
    main_py = root / "app" / "main.py"
    service_py = root / "app" / "sam2_service.py"
    _replace_once(
        main_py,
        'FRONTEND_DIST = Path(__file__).parents[2] / "frontend" / "dist"',
        "\n".join(
            [
                '_static_dir = os.environ.get("WOUNDTRUTH_STATIC_DIR", "").strip()',
                'FRONTEND_DIST = Path(_static_dir) if _static_dir else Path(__file__).parents[2] / "frontend" / "dist"',
            ]
        ),
        "网页目录",
    )
    _replace_once(
        service_py,
        "\n".join(
            [
                '        self.python = Path(os.environ.get("WOUNDTRUTH_SAM2_PYTHON", ""))',
                '        self.model = Path(os.environ.get("WOUNDTRUTH_SAM2_MODEL", ""))',
                '        self.worker_module = "app.sam2_worker"',
            ]
        ),
        "\n".join(
            [
                '        self.python = Path(os.environ.get("WOUNDTRUTH_SAM2_PYTHON", ""))',
                '        self.model = Path(os.environ.get("WOUNDTRUTH_SAM2_MODEL", ""))',
                '        self.worker_executable = Path(os.environ.get("WOUNDTRUTH_SAM2_WORKER", ""))',
                '        self.worker_module = "app.sam2_worker"',
            ]
        ),
        "SAM2 工人配置",
    )
    _replace_once(
        main_py,
        'allow_origins=["http://localhost:4173", "http://127.0.0.1:4173", "http://192.168.1.25:4173"],',
        'allow_origins=["http://localhost:4173", "http://127.0.0.1:4173"],',
        "跨域来源",
    )
    _replace_once(
        service_py,
        '        command = [str(self.python), "-m", self.worker_module, "--serve", "--model", str(self.model)]',
        "\n".join(
            [
                "        if self.worker_executable.is_file() and os.access(self.worker_executable, os.X_OK):",
                '            command = [str(self.worker_executable), "--serve", "--model", str(self.model)]',
                "        else:",
                '            command = [str(self.python), "-m", self.worker_module, "--serve", "--model", str(self.model)]',
            ]
        ),
        "SAM2 启动命令",
    )


if __name__ == "__main__":
    main()
