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
from typing import Dict, Optional

import requests
from spotipy import Spotify
from spotipy.cache_handler import CacheFileHandler, MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from spotdl.utils.config import get_cache_path, get_spotify_cache_path

__all__ = [
    "SpotifyError",
    "SpotifyClient",
    "save_spotify_cache",
]

logger = logging.getLogger(__name__)


class SpotifyError(Exception):
    """
    Base class for all exceptions related to SpotifyClient.
    """


class Singleton(type):
    """
    Singleton metaclass for SpotifyClient. Ensures that SpotifyClient is not
    instantiated without prior initialization. Every other instantiation of
    SpotifyClient will return the same instance.
    """

    _instance = None

    def __call__(self):  # pylint: disable=bad-mcs-method-argument
        """
        Call method for Singleton metaclass.

        ### Returns
        - The instance of the SpotifyClient.
        """

        if self._instance is None:
            raise SpotifyError(
                "Spotify client not created. Call SpotifyClient.init"
                "(client_id, client_secret, user_auth, cache_path, no_cache, open_browser) first."
            )
        return self._instance

    def init(  # pylint: disable=bad-mcs-method-argument
        self,
        client_id: str,
        client_secret: str,
        user_auth: bool = False,
        no_cache: bool = False,
        headless: bool = False,
        max_retries: int = 3,
        use_cache_file: bool = False,
        auth_token: Optional[str] = None,
        cache_path: Optional[str] = None,
    ) -> "Singleton":
        """
        Initializes the SpotifyClient.

        ### Arguments
        - client_id: The client ID of the application.
        - client_secret: The client secret of the application.
        - auth_token: The access token to use.
        - user_auth: Whether or not to use user authentication.
        - cache_path: The path to the cache file.
        - no_cache: Whether or not to use the cache.
        - open_browser: Whether or not to open the browser.

        ### Returns
        - The instance of the SpotifyClient.
        """

        # check if initialization has been completed, if yes, raise an Exception
        if isinstance(self._instance, self):
            raise SpotifyError("A spotify client has already been initialized")

        credential_manager = None

        cache_handler = (
            CacheFileHandler(cache_path or get_cache_path())
            if not no_cache
            else MemoryCacheHandler()
        )
        # Use SpotifyOAuth as auth manager
        if user_auth:
            credential_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="http://127.0.0.1:9900/",
                scope="user-library-read,user-follow-read,playlist-read-private,playlist-read-collaborative",
                cache_handler=cache_handler,
                open_browser=not headless,
            )
        # Use SpotifyClientCredentials as auth manager
        else:
            credential_manager = SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
                cache_handler=cache_handler,
            )
        if auth_token is not None:
            credential_manager = None

        self.user_auth = user_auth
        self.no_cache = no_cache
        self.max_retries = max_retries
        self.use_cache_file = use_cache_file

        # Create instance
        self._instance = super().__call__(
            auth=auth_token,
            auth_manager=credential_manager,
            status_forcelist=(429, 500, 502, 503, 504, 404),
        )

        # Return instance
        return self._instance


class SpotifyClient(Spotify, metaclass=Singleton):
    """
    This is the Spotify client meant to be used in the app.
    Has to be initialized first by calling
    `SpotifyClient.init(client_id, client_secret, user_auth, cache_path, no_cache, open_browser)`.
    """

    _initialized = False
    cache: Dict[str, Optional[Dict]] = {}

    def __init__(self, *args, **kwargs):
        """
        Initializes the SpotifyClient.

        ### Arguments
        - auth: The access token to use.
        - auth_manager: The auth manager to use.
        """

        super().__init__(*args, **kwargs)
        self._initialized = True

        use_cache_file: bool = self.use_cache_file  # type: ignore # pylint: disable=E1101
        cache_file_loc = get_spotify_cache_path()

        if use_cache_file and cache_file_loc.exists():
            with open(cache_file_loc, "r", encoding="utf-8") as cache_file:
                self.cache = json.load(cache_file)
        elif use_cache_file:
            with open(cache_file_loc, "w", encoding="utf-8") as cache_file:
                json.dump(self.cache, cache_file)

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

        # Wrap in a try-except and retry up to `retries` times.
        response = None
        retries = self.max_retries  # type: ignore # pylint: disable=E1101
        while response is None:
            try:
                response = self._internal_call("GET", url, payload, kwargs)
            except (requests.exceptions.Timeout, requests.ConnectionError) as exc:
                retries -= 1
                if retries <= 0:
                    raise exc

        if use_cache and cache_key is not None and not force_fresh:
            self.cache[cache_key] = response

        return response


def save_spotify_cache(cache: Dict[str, Optional[Dict]]):
    """
    Saves the Spotify cache to a file.
    
    Caches all Spotify API responses except playlist metadata (which is always fetched fresh
    to check snapshot_id for changes). Playlist items ARE cached and invalidated when
    snapshot_id changes. Playlist snapshots are stored in the cache with special keys
    prefixed with __snapshot__.

    ### Arguments
    - cache: The cache dictionary to save
    """

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
