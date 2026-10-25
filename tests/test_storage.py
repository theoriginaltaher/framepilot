from pathlib import Path

from framepilot.models import AnalysisResult, CullStatus, DevelopSettings, PhotoRecord
from framepilot.storage import ProjectDatabase


def test_project_persists_photo_state(tmp_path):
    raw = tmp_path / "capture.CR3"
    raw.write_bytes(b"not a real raw fixture")
    stat = raw.stat()
    project = ProjectDatabase(tmp_path / "event.fp-project")
    photo = PhotoRecord(raw, stat.st_size, stat.st_mtime_ns, rating=4,
        cull_status=CullStatus.KEEP, settings=DevelopSettings(exposure=0.75, clarity=12),
        analysis=AnalysisResult(sharpness=81.5, explanation="synthetic"))
    project.upsert_photo(photo)
    project.save_photo(photo)
    project.close()

    reopened = ProjectDatabase(tmp_path / "event.fp-project")
    loaded = reopened.load_photos()
    reopened.close()
    assert len(loaded) == 1
    assert loaded[0].rating == 4
    assert loaded[0].cull_status is CullStatus.KEEP
    assert loaded[0].settings.exposure == 0.75
    assert loaded[0].analysis.sharpness == 81.5


def test_reimport_does_not_overwrite_edits(tmp_path):
    raw = tmp_path / "capture.NEF"; raw.write_bytes(b"raw")
    stat = raw.stat(); project = ProjectDatabase(tmp_path / "test.fp-project")
    first = PhotoRecord(raw, stat.st_size, stat.st_mtime_ns, rating=5)
    project.upsert_photo(first); project.save_photo(first)
    duplicate = PhotoRecord(raw, stat.st_size, stat.st_mtime_ns)
    project.upsert_photo(duplicate)
    assert project.load_photos()[0].rating == 5
    project.close()

