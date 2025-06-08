import requests
from spotdl.types.song import Song
from typing import List, Dict, Any, TypedDict, Optional
import logging
import time

logger = logging.getLogger(__name__)

class ISRCResult(TypedDict):
    duration: Optional[str]
    recordingVersion: Optional[str]
    isValidIsrc: Optional[str]
    recordingYear: Optional[str]
    recordingArtistName: Optional[str]
    isrcFailureCode: Optional[str]
    isExplicit: Optional[str]
    isrc: Optional[str]
    recordingTitle: Optional[str]
    id: Optional[str]

def isrcresult_from_api_dict(rec: dict) -> ISRCResult:
    """Create an ISRCResult from an API dictionary."""
    return ISRCResult(
        duration=rec.get("duration"),
        recordingVersion=rec.get("recordingVersion"),
        isValidIsrc=rec.get("isValidIsrc"),
        recordingYear=rec.get("recordingYear"),
        recordingArtistName=rec.get("recordingArtistName"),
        isrcFailureCode=rec.get("isrcFailureCode"),
        isExplicit=rec.get("isExplicit"),
        isrc=rec.get("isrc"),
        recordingTitle=rec.get("recordingTitle"),
        id=rec.get("id"),
    )


def find_isrc_alternatives(song: Song, number: int = 10) -> List[ISRCResult]:
    """
    Find possible alternative ISRCs for a song using the SoundExchange ISRC API.

    Args:
        song (Song): The Song object to search for.
        number (int): Number of results to return (default 10).

    Returns:
        List[ISRCResult]: List of ISRC result dicts from the API.
    """
    url = "https://isrc-api.soundexchange.com/api/ext/recordings"
    payload = {
        "searchFields": {
            "recordingArtistName": {"value": song.artist},
            "recordingTitle": {"value": song.name},
            "releaseName": {"value": ""},
        },
        "start": 0,
        "number": number,
        "showReleases": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Token 548fa8b24c6e44f4106b380f1882f0502c9ef4ab",
    }

    for attempt in range(10):
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            break
        else:
            logger.warning(f"Attempt {attempt + 1}: Received HTTP {response.status_code}. Retrying in 5 seconds...")
            time.sleep(5)
    else:
        logger.error("Failed to fetch data from ISRC API after 10 attempts.")
        raise ConnectionError("Failed to fetch data from ISRC API after 10 attempts.")

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        logger.error("Failed to decode JSON response from ISRC API.")
        raise ValueError("Invalid JSON response from ISRC API")

    results = data.get("recordings", [])
    # Convert each result to ISRCResult type (dict with correct keys)
    typed_results: List[ISRCResult] = [isrcresult_from_api_dict(rec) for rec in results]
    return typed_results
