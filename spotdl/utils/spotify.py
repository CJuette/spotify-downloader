"""
Module for interacting with Spotify API.
To use this module, you must have a Spotify API key and Spotify API secret.

```python
import spotdl.utils.spotify
spotify.Spotify.init(client_id, client_secret)
```
"""

import json
import logging
from typing import Any, Dict, Optional

import requests
from spotipy import Spotify
from spotipy.cache_handler import CacheFileHandler, MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from SpotipyFree import Spotify as FreeSpotify

from spotdl.utils.config import get_cache_path, get_spotify_cache_path

__all__ = [
    "SpotifyError",
    "SpotifyClient",
    "save_spotify_cache",
]

logger = logging.getLogger(__name__)

OFFICIAL_API_ONLY_OPTIONS = {
    "auth_token": "--auth-token",
    "user_auth": "--user-auth",
    "use_cache_file": "--use-cache-file",
}


class SpotifyError(Exception):
    """
    Base class for all exceptions related to SpotifyClient.
    """


class _OfficialSpotifyClient(Spotify):
    """
    Spotipy-backed Spotify client used when the official API is requested.
    """

    cache: Dict[str, Optional[Dict]] = {}

    @classmethod
    def init(
        cls,
        client_id: str,
        client_secret: str,
        user_auth: bool = False,
        no_cache: bool = False,
        headless: bool = False,
        max_retries: int = 3,
        use_cache_file: bool = False,
        auth_token: Optional[str] = None,
        cache_path: Optional[str] = None,
    ) -> "_OfficialSpotifyClient":
        """
        Initializes the official SpotifyClient implementation.
        """

        credential_manager = None

        cache_handler = (
            CacheFileHandler(cache_path or get_cache_path())
            if not no_cache
            else MemoryCacheHandler()
        )
        if user_auth:
            credential_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="http://127.0.0.1:9900/",
                scope="user-library-read,user-follow-read,playlist-read-private,playlist-read-collaborative",
                cache_handler=cache_handler,
                open_browser=not headless,
            )
        else:
            credential_manager = SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
                cache_handler=cache_handler,
            )

        if auth_token is not None:
            credential_manager = None

        client = cls(
            auth=auth_token,
            auth_manager=credential_manager,
            status_forcelist=(429, 500, 502, 503, 504, 404),
        )
        client.user_auth = user_auth
        client.no_cache = no_cache
        client.max_retries = max_retries
        client.use_cache_file = use_cache_file

        cache_file_loc = get_spotify_cache_path()
        if use_cache_file and cache_file_loc.exists():
            with open(cache_file_loc, "r", encoding="utf-8") as cache_file:
                client.cache = json.load(cache_file)
        elif use_cache_file:
            with open(cache_file_loc, "w", encoding="utf-8") as cache_file:
                json.dump(client.cache, cache_file)

        return client

    def playlist_items(  # type: ignore[override]
        self,
        playlist_id,
        fields=None,
        limit=100,
        offset=0,
        market=None,
        additional_types=("track", "episode"),
    ):
        """Get items of a playlist.

        Spotify deprecated the legacy endpoint `GET /playlists/{id}/tracks` in early 2026 and
        introduced `GET /playlists/{id}/items`. Newer Spotify API behavior may return 403/404
        for the legacy endpoint, even when the playlist is otherwise accessible.

        This override prefers the new `/items` endpoint and falls back to Spotipy's
        implementation if needed.
        """
        plid = self._get_id("playlist", playlist_id)

        # Spotipy accepts additional_types as list/tuple, but the request param is a comma-separated string.
        if isinstance(additional_types, (list, tuple, set)):
            additional_types_param = ",".join(additional_types)
        else:
            additional_types_param = additional_types

        try:
            return self._get(
                f"playlists/{plid}/items",
                limit=limit,
                offset=offset,
                fields=fields,
                market=market,
                additional_types=additional_types_param,
            )
        except Exception:
            # Fall back to spotipy's (legacy) playlist_items which may still work
            return super().playlist_items(
                playlist_id,
                fields=fields,
                limit=limit,
                offset=offset,
                market=market,
                additional_types=additional_types,
            )

    def playlist(  # type: ignore[override]
        self,
        playlist_id,
        fields=None,
        market=None,
        additional_types=None,
    ):
        """Get full details of a playlist.

        As of Spotify Web API changes in early 2026, some clients saw 404/403 issues when passing
        `additional_types` to the playlist metadata endpoint. The playlist items are retrieved via
        `playlist_items` (which uses the newer `/items` endpoint), so we intentionally omit
        `additional_types` here.
        
        This method always fetches fresh data to check snapshot_id for cache invalidation.
        """

        plid = self._get_id("playlist", playlist_id)
        # Always fetch fresh playlist metadata (never cached) to get current snapshot_id
        response = self._get(f"playlists/{plid}", fields=fields, market=market, force_fresh=True)
        
        # Update snapshot_id tracking for cache invalidation
        if response and response.get("snapshot_id"):
            snapshot_key = f"__snapshot__{plid}"
            old_snapshot = self.cache.get(snapshot_key)
            new_snapshot = response["snapshot_id"]
            
            if old_snapshot and old_snapshot != new_snapshot:
                # Playlist changed - invalidate cached playlist items
                logger.info(
                    "Playlist %s changed (snapshot %s -> %s), invalidating items cache",
                    plid, old_snapshot[:8], new_snapshot[:8]
                )
                self._invalidate_playlist_items_cache(plid)
            
            # Update snapshot tracking in cache
            self.cache[snapshot_key] = new_snapshot
        
        return response
    
    def _invalidate_playlist_items_cache(self, playlist_id: str):
        """
        Invalidate all cached playlist_items responses for a given playlist.
        
        ### Arguments
        - playlist_id: The Spotify playlist ID
        """
        keys_to_delete = []
        for cache_key in self.cache.keys():
            # Parse cache key to check if it's for this playlist's items
            try:
                key_obj = json.loads(cache_key)
                if key_obj.get("url", "").startswith(f"playlists/{playlist_id}/items"):
                    keys_to_delete.append(cache_key)
            except (json.JSONDecodeError, AttributeError):
                continue
        
        for key in keys_to_delete:
            logger.debug("Invalidating cache key: %s", key[:100])
            del self.cache[key]

    def _get(self, url, args=None, payload=None, **kwargs):
        """
        Overrides the get method of the SpotifyClient.
        Allows us to cache requests
        
        ### Arguments
        - url: The API endpoint URL
        - args: Additional arguments (merged with kwargs)
        - payload: Request payload
        - force_fresh: If True, bypass cache and fetch fresh data (used for playlist metadata)
        - **kwargs: Query parameters
        """

        use_cache = not self.no_cache  # type: ignore # pylint: disable=E1101
        force_fresh = kwargs.pop("force_fresh", False)  # Extract force_fresh flag

        if args:
            kwargs.update(args)

        cache_key = None
        if use_cache and not force_fresh:
            key_obj = dict(kwargs)
            key_obj["url"] = url
            key_obj["data"] = json.dumps(payload)
            cache_key = json.dumps(key_obj)
            if cache_key is None:
                cache_key = url
            if self.cache.get(cache_key) is not None:
                logger.debug("Cache HIT: %s", url)
                return self.cache[cache_key]
            else:
                logger.debug("Cache MISS: %s", url)

        response = None
        retries = self.max_retries  # type: ignore # pylint: disable=E1101
        while response is None:
            try:
                response = self._internal_call("GET", url, payload, kwargs)
            except (requests.exceptions.Timeout, requests.ConnectionError) as exc:
                retries -= 1
                if retries <= 0:
                    raise exc

        # Only cache successful responses (not None, not errors)
        # This prevents caching temporary failures (404, rate limits, etc.)
        if use_cache and cache_key is not None and not force_fresh and response is not None:
            self.cache[cache_key] = response

        return response


def _init_official_spotify_client(**kwargs) -> _OfficialSpotifyClient:
    """
    Initialize the official Spotipy client.
    """

    return _OfficialSpotifyClient.init(**kwargs)


def _init_free_spotify_client(**kwargs) -> Any:
    """
    Initialize the default SpotipyFree client.
    """

    return FreeSpotify(**kwargs)


class SpotifyClient:
    """
    Runtime-selected Spotify client facade.
    """

    _instance: Optional[Any] = None
    _use_official_api = False

    def __new__(cls):
        """
        Return the initialized Spotify client implementation.
        """

        if cls._instance is None:
            raise SpotifyError(
                "Spotify client not created. Call SpotifyClient.init"
                "("
                "client_id, client_secret, user_auth=False, no_cache=False, "
                "headless=False, max_retries=3, use_cache_file=False, "
                "use_official_api=False, auth_token=None, cache_path=None"
                ") first."
            )

        return cls._instance

    def __getattr__(self, name: str) -> Any:
        """
        The selected backend provides Spotify API methods at runtime.
        """

        raise AttributeError(name)

    @classmethod
    def is_using_official_api(cls) -> bool:
        """
        Returns whether the active client uses the official Spotify Web API.
        """

        return cls._use_official_api

    @classmethod
    def init(
        cls,
        client_id: str,
        client_secret: str,
        user_auth: bool = False,
        no_cache: bool = False,
        headless: bool = False,
        max_retries: int = 3,
        use_cache_file: bool = False,
        use_official_api: bool = False,
        auth_token: Optional[str] = None,
        cache_path: Optional[str] = None,
    ) -> Any:
        """
        Initializes the selected SpotifyClient implementation.
        """

        if cls._instance is not None:
            raise SpotifyError("A spotify client has already been initialized")

        kwargs = {
            "client_id": client_id,
            "client_secret": client_secret,
            "user_auth": user_auth,
            "no_cache": no_cache,
            "headless": headless,
            "max_retries": max_retries,
            "use_cache_file": use_cache_file,
            "auth_token": auth_token,
            "cache_path": cache_path,
        }

        official_only_options = [
            option for key, option in OFFICIAL_API_ONLY_OPTIONS.items() if kwargs[key]
        ]
        if official_only_options and not use_official_api:
            logger.info(
                "Using the official Spotify Web API because %s %s requested.",
                ", ".join(official_only_options),
                "was" if len(official_only_options) == 1 else "were",
            )
            use_official_api = True

        if use_official_api:
            cls._instance = _init_official_spotify_client(**kwargs)
        else:
            cls._instance = _init_free_spotify_client(**kwargs)

        cls._use_official_api = use_official_api

        return cls._instance


def save_spotify_cache(cache: Dict[str, Optional[Dict]]):
    """
    Saves the Spotify cache to a file when the official API client is active.
    
    Caches all Spotify API responses except playlist metadata (which is always fetched fresh
    to check snapshot_id for changes). Playlist items ARE cached and invalidated when
    snapshot_id changes. Playlist snapshots are stored in the cache with special keys
    prefixed with __snapshot__.

    ### Arguments
    - cache: The cache dictionary to save
    """

    if not SpotifyClient.is_using_official_api():
        return

    cache_file_loc = get_spotify_cache_path()

    logger.debug("Saving Spotify cache to %s", cache_file_loc)

    # Cache everything except playlist metadata (we need fresh data for snapshot_id checking)
    # We cache:
    # - tracks/* (individual track details)
    # - albums/* (album metadata)
    # - artists/* (artist metadata) 
    # - playlists/*/items (playlist contents - invalidated by snapshot_id)
    # - __snapshot__* (snapshot_id tracking for playlists)
    # We do NOT cache:
    # - playlists/* (without /items) - always fetch fresh for snapshot_id
    filtered_cache = {}
    snapshot_count = 0
    
    for key, value in cache.items():
        if value is None:
            continue
        
        # Always keep snapshot tracking keys
        if key.startswith("__snapshot__"):
            filtered_cache[key] = value
            snapshot_count += 1
            continue
        
        # Check if this is a playlist metadata call (not items)
        try:
            key_obj = json.loads(key)
            url = key_obj.get("url", "")
            
            # Skip playlist metadata (always fetch fresh), but keep playlist items
            if url.startswith("playlists/") and "/items" not in url:
                continue
                
            filtered_cache[key] = value
        except (json.JSONDecodeError, AttributeError):
            # If we can't parse the key, include it to be safe
            filtered_cache[key] = value

    with open(cache_file_loc, "w", encoding="utf-8") as cache_file:
        json.dump(filtered_cache, cache_file, indent=2)
    
    logger.info(
        "Saved Spotify cache: %d entries, %d playlist snapshots",
        len(filtered_cache) - snapshot_count,
        snapshot_count
    )
