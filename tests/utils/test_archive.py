import pytest

from spotdl.utils.archive import Archive


def test_load_archive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive1 = Archive(["a", "b", "c"])
    # Test adding with filename
    archive1.add_with_filename("d", "/path/to/file.mp3")
    assert archive1.save("archive.txt") is True
    assert (tmp_path / "archive.txt").is_file() is True
    archive2 = Archive()
    assert archive2.load("archive.txt") is True
    assert len(archive2) == len(archive1)
    diff = archive2 ^ archive1
    assert len(diff) == 0
    # Test filename functionality
    assert archive2.get_filename("d") == "/path/to/file.mp3"
    assert archive2.has_file("/path/to/file.mp3") is True
    assert archive2.get_url_by_filename("/path/to/file.mp3") == "d"


def test_archive_filename_features():
    """Test the new filename-related features of the Archive class."""
    archive = Archive()

    # Test add_with_filename
    archive.add_with_filename("https://spotify.com/track/1", "/music/Song.mp3")
    archive.add_with_filename("https://spotify.com/track/2", "/music/Song (Extended Mix).mp3")
    archive.add("https://spotify.com/track/3")  # URL only

    # Test get_filename
    assert archive.get_filename("https://spotify.com/track/1") == "/music/Song.mp3"
    assert archive.get_filename("https://spotify.com/track/2") == "/music/Song (Extended Mix).mp3"
    assert archive.get_filename("https://spotify.com/track/3") is None
    assert archive.get_filename("nonexistent") is None

    # Test has_file
    assert archive.has_file("/music/Song.mp3") is True
    assert archive.has_file("/music/Song (Extended Mix).mp3") is True
    assert archive.has_file("/music/nonexistent.mp3") is False

    # Test get_url_by_filename
    assert archive.get_url_by_filename("/music/Song.mp3") == "https://spotify.com/track/1"
    assert archive.get_url_by_filename("/music/Song (Extended Mix).mp3") == "https://spotify.com/track/2"
    assert archive.get_url_by_filename("/music/nonexistent.mp3") is None


def test_archive_backward_compatibility(tmpdir, monkeypatch):
    """Test that the new archive format is backward compatible with old text format."""
    monkeypatch.chdir(tmpdir)

    # Create old format archive file
    with open("old_archive.txt", "w", encoding="utf-8") as f:
        f.write("https://spotify.com/track/1\n")
        f.write("https://spotify.com/track/2\n")
        f.write("https://spotify.com/track/3\n")

    # Load old format
    archive = Archive()
    assert archive.load("old_archive.txt") is True
    assert len(archive) == 3
    assert "https://spotify.com/track/1" in archive
    assert "https://spotify.com/track/2" in archive
    assert "https://spotify.com/track/3" in archive

    # All filename mappings should be empty for old format
    assert archive.get_filename("https://spotify.com/track/1") is None
