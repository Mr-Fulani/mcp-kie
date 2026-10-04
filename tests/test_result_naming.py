from pathlib import Path

import pytest

from kie_mcp.ledger import GuardError
from kie_mcp.storage import result_folder, save_result

PNG = b"\x89PNG\r\n\x1a\nfixture"
CREATED = 1791072000000


def test_readable_saves_leave_existing_folders_untouched(tmp_path):
    old = Path(save_result(tmp_path, "task_1", PNG))
    kwargs = {"model": "google/nano-banana-edit", "created_at": CREATED, "label": "Студийное фото"}
    one = Path(save_result(tmp_path, "task_1", PNG, **kwargs))
    two = Path(save_result(tmp_path, "task_1", PNG, **kwargs))
    assert one.parent.name == "2026-10-04__Студийное-фото__image__google-nano-banana-edit__task_1"
    assert one.parent == two.parent and one != two
    assert old.read_bytes() == one.read_bytes() == two.read_bytes() == PNG
    assert old.parent == tmp_path / "task_1"


@pytest.mark.parametrize("label", ["../escape", "a/b", "a\\b", "", "a\n", "я" * 25, "x" * 49])
def test_label_cannot_supply_paths_or_exceed_byte_limit(label):
    with pytest.raises(GuardError):
        result_folder("task", "image/png", "google/model", CREATED, label)


def test_folder_retains_full_id_and_bounds_model_slug():
    task_id = "a" * 128
    folder = result_folder(task_id, "video/mp4", "a" * 200, CREATED, "я" * 24)
    assert folder.endswith("__" + task_id)
    assert len(folder.encode()) <= 255
    assert "__video__" in folder


@pytest.mark.parametrize("model", ["../escape", "a/b/c", None, 3])
def test_model_cannot_supply_path(model):
    with pytest.raises(GuardError):
        result_folder("task", "image/png", model, CREATED)


def test_descriptive_folder_symlink_escape_blocked(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    folder = result_folder("task", "image/png", "fixture/image", CREATED)
    (root / folder).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        save_result(root, "task", PNG, model="fixture/image", created_at=CREATED)
    assert not list(tmp_path.glob("*.png"))
