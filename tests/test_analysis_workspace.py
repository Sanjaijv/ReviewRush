import io
import tarfile
from pathlib import Path

import pytest

from app.analysis.workspace import _safe_extract


def _make_tar(tmp_path: Path, members: dict[str, bytes | None]) -> Path:
    """Build a tarball at tmp_path/archive.tar.gz. A None value creates a
    symlink member instead of a regular file (name is the link target).
    """
    tar_path = tmp_path / "archive.tar.gz"
    with tarfile.open(tar_path, mode="w:gz") as tar:
        for name, content in members.items():
            if content is None:
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
                continue
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return tar_path


def test_strips_single_top_level_directory(tmp_path: Path) -> None:
    tar_path = _make_tar(
        tmp_path,
        {
            "acme-widgets-abc123/README.md": b"hello",
            "acme-widgets-abc123/src/main.py": b"print(1)",
        },
    )
    dest = tmp_path / "out"
    dest.mkdir()

    _safe_extract(tar_path, dest)

    assert (dest / "README.md").read_bytes() == b"hello"
    assert (dest / "src" / "main.py").read_bytes() == b"print(1)"


def test_rejects_path_traversal_member(tmp_path: Path) -> None:
    tar_path = _make_tar(
        tmp_path,
        {"acme-widgets-abc123/../../etc/passwd": b"pwned"},
    )
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(ValueError):
        _safe_extract(tar_path, dest)


def test_skips_symlink_members(tmp_path: Path) -> None:
    tar_path = _make_tar(
        tmp_path,
        {
            "acme-widgets-abc123/README.md": b"hello",
            "acme-widgets-abc123/evil-link": None,
        },
    )
    dest = tmp_path / "out"
    dest.mkdir()

    _safe_extract(tar_path, dest)

    assert (dest / "README.md").read_bytes() == b"hello"
    assert not (dest / "evil-link").exists()
