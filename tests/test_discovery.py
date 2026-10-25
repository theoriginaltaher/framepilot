from framepilot.services import discover_raw_files


def test_recursive_case_insensitive_discovery(tmp_path):
    nested = tmp_path / "card"; nested.mkdir()
    (nested / "A.CR3").write_bytes(b"a")
    (nested / "B.nef").write_bytes(b"b")
    (nested / "notes.txt").write_text("ignore")
    photos = discover_raw_files(tmp_path)
    assert {p.path.suffix.lower() for p in photos} == {".cr3", ".nef"}
