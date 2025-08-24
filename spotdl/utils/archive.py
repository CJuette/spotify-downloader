"""
Module for archiving sets of data
"""

import json
from pathlib import Path
from typing import Dict, Optional, Set, Union

__all__ = ["Archive"]


class Archive(Set):
    """
    Archive class.
    A file-persistable set that can store both URLs and their corresponding filenames.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dictionary to store URL -> filename mapping
        self._filename_map: Dict[str, str] = {}

    def add_with_filename(self, url: str, filename: Optional[str] = None) -> None:
        """
        Add a URL to the archive with its corresponding filename.

        ### Arguments
        - url: The URL to add
        - filename: The filename where the URL was downloaded (optional)
        """
        self.add(url)
        if filename:
            self._filename_map[url] = str(filename)

    def get_filename(self, url: str) -> Optional[str]:
        """
        Get the filename for a given URL.

        ### Arguments
        - url: The URL to look up

        ### Returns
        - The filename if found, None otherwise
        """
        return self._filename_map.get(url)

    def has_file(self, filename: str) -> bool:
        """
        Check if a filename exists in the archive.

        ### Arguments
        - filename: The filename to check

        ### Returns
        - True if the filename exists in the archive
        """
        return filename in self._filename_map.values()

    def get_url_by_filename(self, filename: str) -> Optional[str]:
        """
        Get the URL for a given filename.

        ### Arguments
        - filename: The filename to look up

        ### Returns
        - The URL if found, None otherwise
        """
        for url, stored_filename in self._filename_map.items():
            if stored_filename == filename:
                return url
        return None

    def load(self, file: str) -> bool:
        """
        Imports the archive from the file.

        ### Arguments
        - file: the file name of the archive

        ### Returns
        - if the file exists
        """

        if not Path(file).exists():
            return False

        try:
            with open(file, "r", encoding="utf-8") as archive_file:
                content = archive_file.read().strip()

                # Try to load as JSON first (new format)
                if content.startswith("{"):
                    data = json.loads(content)
                    self.clear()
                    self._filename_map.clear()

                    # Load URLs
                    if "urls" in data:
                        self.update(data["urls"])

                    # Load filename mappings
                    if "filename_map" in data:
                        self._filename_map.update(data["filename_map"])
                else:
                    # Fallback to old format (plain text URLs)
                    self.clear()
                    self._filename_map.clear()
                    self.update([line.strip() for line in content.split("\n") if line.strip()])

        except (json.JSONDecodeError, Exception):
            # Fallback to old format if JSON parsing fails
            with open(file, "r", encoding="utf-8") as archive_file:
                self.clear()
                self._filename_map.clear()
                self.update([line.strip() for line in archive_file if line.strip()])

        return True

    def save(self, file: str) -> bool:
        """
        Exports the current archive to the file.

        ### Arguments
        - file: the file name of the archive
        """

        # Save in new JSON format
        data = {
            "urls": sorted(list(self)),
            "filename_map": self._filename_map,
        }

        with open(file, "w", encoding="utf-8") as archive_file:
            json.dump(data, archive_file, indent=2, ensure_ascii=False)

        return True
