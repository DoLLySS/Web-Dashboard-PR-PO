"""ทดสอบการบันทึกไฟล์ในเครื่อง (utils/local_storage.py): เขียนพร้อมกันไม่ทับกัน และลบสำเนา Desktop เฉพาะใต้โฟลเดอร์ของมัน"""

import threading
from pathlib import Path

import pytest

import utils.local_storage as local_storage
from utils.local_storage import save_document_locally

FOLDER = ["2026", "Mar", "19", "งานพร้อมกัน"]


def test_same_name_saved_at_the_same_moment_keeps_every_file(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ทุกเธรดเลือกชื่อว่างเดียวกันก่อนใครเขียน (บังคับด้วย barrier) ไฟล์ต้องไม่ทับกัน"""
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    original_pick = local_storage._pick_free_file_name

    def pick_then_wait(directory: Path, name: str) -> str:
        chosen = original_pick(directory, name)
        barrier.wait(timeout=10)  # ทุกเธรดเลือกชื่อเสร็จก่อน จึงเลือกชื่อเดียวกันหมด
        return chosen

    monkeypatch.setattr(local_storage, "_pick_free_file_name", pick_then_wait)
    contents = [f"เนื้อหา {index}".encode() for index in range(thread_count)]
    paths: list[str] = []
    errors: list[BaseException] = []

    def save(data: bytes) -> None:
        try:
            paths.append(save_document_locally(data, "PR.pdf", FOLDER))
        except BaseException as error:  # noqa: BLE001 - เก็บไว้ตรวจในเธรดหลัก
            errors.append(error)

    threads = [threading.Thread(target=save, args=(data,)) for data in contents]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(set(paths)) == thread_count
    stored = sorted(path.read_bytes() for path in isolated_storage.joinpath(*FOLDER).iterdir())
    assert stored == sorted(contents)


def test_identical_content_still_reuses_the_existing_file(isolated_storage: Path) -> None:
    first = save_document_locally(b"same", "a.pdf", FOLDER)
    second = save_document_locally(b"same", "a.pdf", FOLDER)

    assert first == second and len(list(isolated_storage.joinpath(*FOLDER).iterdir())) == 1


def test_different_content_gets_a_numbered_name(isolated_storage: Path) -> None:
    save_document_locally(b"one", "a.pdf", FOLDER)
    second = save_document_locally(b"two", "a.pdf", FOLDER)

    assert second.endswith("/a_1.pdf")


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Desktop"
    root.mkdir()
    monkeypatch.setattr(local_storage, "DESKTOP_EXPORT_ENABLED", True)
    monkeypatch.setattr(local_storage, "get_desktop_directory", lambda: root)
    return root


def test_desktop_copy_of_a_row_folder_is_removed(desktop: Path) -> None:
    folder = desktop.joinpath(*FOLDER)
    folder.mkdir(parents=True)
    (folder / "a.pdf").write_bytes(b"x")

    local_storage.remove_desktop_copy(FOLDER)

    assert not folder.exists() and desktop.is_dir()


@pytest.mark.parametrize("parts", [["."], ["2026", "Mar", ".", "x"], [".", ".", ".", "."], ["2026", "..", "x"], []])
def test_desktop_copy_removal_refuses_dot_parts_and_changes_nothing(desktop: Path, parts: list[str]) -> None:
    day = desktop / "2026" / "Mar" / "19"
    day.mkdir(parents=True)
    (day / "keep.pdf").write_bytes(b"x")

    with pytest.raises(OSError):
        local_storage.remove_desktop_copy(parts)

    assert (day / "keep.pdf").exists()


def test_desktop_copy_removal_never_leaves_the_desktop_folder(desktop: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("x")

    with pytest.raises(OSError):
        local_storage.remove_desktop_copy([str(outside)])  # path เต็ม: joinpath จะทิ้ง Desktop แล้วชี้ไปที่ outside

    assert (outside / "precious.txt").exists()
