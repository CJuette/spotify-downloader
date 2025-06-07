import logging
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from yt_dlp import YoutubeDL

from spotdl.types.result import Result
from spotdl.types.song import Song
from spotdl.utils.config import get_temp_path
from spotdl.utils.formatter import (
    args_to_ytdlp_options,
    create_search_query,
    create_song_title,
)
from spotdl.utils.matching import artists_match_fixup1, artists_match_fixup2, artists_match_fixup3, calc_album_match, calc_artists_match, calc_main_artist_match, calc_name_match, calc_time_match, check_common_word, check_forbidden_words, get_best_matches
from spotdl.utils.logging import MATCH

logger = logging.getLogger(__name__)

def debug(song_id: str, result_id: str, message: str) -> None:
    """
    Log a message with MATCH level

    ### Arguments
    - message: message to log
    """

    logger.log(MATCH, "[%s|%s] %s", song_id, result_id, message)


class Matcher:
    """
    Base class for implementing different algorithms to find the best result
    for a song.
    """

    def __init__(self):
        pass

    def get_best_result(self, results: Dict[Result, float]) -> Tuple[Result, float]:
        # not implemented in base class
        raise NotImplementedError
    
    def order_results(
        self,
        results: List[Result],
        song: Song,
        search_query: Optional[str] = None,
    ) -> Dict[Result, float]:
        """
        Order results.

        ### Arguments
        - results: The results to order.
        - song: The song to order for.
        - search_query: The search query.

        ### Returns
        - The ordered results, with scores.
        """
        # not implemented in base class
        raise NotImplementedError

class StandardMatcher(Matcher):
    """
    Standard implementation of the result discriminator.
    This is the default implementation.
    """

    def __init__(self):
        super().__init__()

    def get_best_result(self, results: Dict[Result, float]) -> Tuple[Result, float]:
        """
        Get the best match from the results
        using views and average match

        ### Arguments
        - results: A dictionary of results and their scores

        ### Returns
        - The best match URL and its score
        """

        best_results = get_best_matches(results, 8)

        # If we have only one result, return it
        if len(best_results) == 1:
            return best_results[0][0], best_results[0][1]

        # Initial best result based on the average match
        best_result = best_results[0]

        # If the best result has a score higher than 80%
        # and it's a isrc search, return it
        if best_result[1] > 80 and best_result[0].isrc_search:
            return best_result[0], best_result[1]

        # If we have more than one result,
        # return the one with the highest score
        # and most views
        if len(best_results) > 1:
            views: List[int] = []
            for best_result in best_results:
                if best_result[0].views:
                    views.append(best_result[0].views)

            highest_views = max(views)
            lowest_views = min(views)

            if highest_views in (0, lowest_views):
                return best_result[0], best_result[1]

            weighted_results: List[Tuple[Result, float]] = []
            for index, best_result in enumerate(best_results):
                result_views = views[index]
                views_score = (
                    (result_views - lowest_views) / (highest_views - lowest_views)
                ) * 15
                score = min(best_result[1] + views_score, 100)
                weighted_results.append((best_result[0], score))

            # Now we return the result with the highest score
            return max(weighted_results, key=lambda x: x[1])

        return best_result[0], best_result[1]
    
    def order_results(
        self,
        results: List[Result],
        song: Song,
        search_query: Optional[str] = None,
    ) -> Dict[Result, float]:
        """
        Order results.

        ### Arguments
        - results: The results to order.
        - song: The song to order for.
        - search_query: The search query.

        ### Returns
        - The ordered results, with scores.
        """

        # Assign an overall avg match value to each result
        links_with_match_value = {}

        # Iterate over all results
        for result in results:
            debug(
                song.song_id,
                result.result_id,
                f"Calculating match value for {result.url} - {result.json}",
            )

            # skip results that have no common words in their name
            if not check_common_word(song, result):
                debug(
                    song.song_id, result.result_id, "Skipping result due to no common words"
                )

                continue

            # Calculate match value for main artist
            artists_match = calc_main_artist_match(song, result)
            debug(song.song_id, result.result_id, f"Main artist match: {artists_match}")

            # Calculate match value for all artists
            other_artists_match = calc_artists_match(song, result)
            debug(
                song.song_id,
                result.result_id,
                f"Other artists match: {other_artists_match}",
            )

            artists_match += other_artists_match

            # Calculate initial artist match value
            debug(song.song_id, result.result_id, f"Initial artists match: {artists_match}")
            artists_match = artists_match / (2 if len(song.artists) > 1 else 1)
            debug(song.song_id, result.result_id, f"First artists match: {artists_match}")

            # First attempt to fix artist match
            artists_match = artists_match_fixup1(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup1: {artists_match}",
            )

            # Second attempt to fix artist match
            artists_match = artists_match_fixup2(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup2: {artists_match}",
            )

            # Third attempt to fix artist match
            artists_match = artists_match_fixup3(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup3: {artists_match}",
            )

            debug(song.song_id, result.result_id, f"Final artists match: {artists_match}")

            # Calculate name match
            name_match = calc_name_match(song, result, search_query)
            debug(song.song_id, result.result_id, f"Initial name match: {name_match}")

            # Check if result contains forbidden words
            contains_fwords, found_fwords = check_forbidden_words(song, result)
            if contains_fwords:
                for _ in found_fwords:
                    name_match -= 15

            debug(
                song.song_id,
                result.result_id,
                f"Contains forbidden words: {contains_fwords}, {found_fwords}",
            )
            debug(song.song_id, result.result_id, f"Final name match: {name_match}")

            # Calculate album match
            album_match = calc_album_match(song, result)
            debug(song.song_id, result.result_id, f"Final album match: {album_match}")

            # Calculate time match
            time_match = calc_time_match(song, result)
            debug(song.song_id, result.result_id, f"Final time match: {time_match}")

            # Ignore results with name match lower than 60%
            if name_match <= 60:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to name match lower than 60%",
                )
                continue

            # Ignore results with artists match lower than 70%
            if artists_match < 70 and result.source != "slider.kz":
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to artists match lower than 70%",
                )
                continue

            # Calculate total match
            average_match = (artists_match + name_match) / 2
            debug(song.song_id, result.result_id, f"Average match: {average_match}")

            if (
                result.verified
                and not result.isrc_search
                and result.album
                and album_match <= 80
            ):
                # we are almost certain that this is the correct result
                # so we add the album match to the average match
                average_match = (average_match + album_match) / 2
                debug(
                    song.song_id,
                    result.result_id,
                    f"Average match /w album match: {average_match}",
                )

            # Skip results with time match lower than 25%
            if time_match < 25:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to time match lower than 25%",
                )
                continue

            # If the time match is lower than 50%
            # and the average match is lower than 75%
            # we skip the result
            if time_match < 50 and average_match < 75:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to time match < 50% and average match < 75%",
                )
                continue

            if (
                (not result.isrc_search and average_match <= 85)
                or result.source == "slider.kz"
                or time_match < 0
            ):
                # Don't add time to avg match if average match is not the best
                # (lower than 85%), always include time match if result is from
                # slider.kz or if time match is lower than 0
                average_match = (average_match + time_match) / 2

                debug(
                    song.song_id,
                    result.result_id,
                    f"Average match /w time match: {average_match}",
                )

                if (result.explicit is not None and song.explicit is not None) and (
                    result.explicit != song.explicit
                ):
                    debug(
                        song.song_id,
                        result.result_id,
                        "Lowering average match due to explicit mismatch",
                    )

                    average_match -= 5

            average_match = min(average_match, 100)
            debug(song.song_id, result.result_id, f"Final average match: {average_match}")

            # the results along with the avg Match
            links_with_match_value[result] = average_match

        return links_with_match_value
    
class ExtendedMixMatcher(StandardMatcher):
    """
    Extended Mix implementation of the result discriminator.
    This is the default implementation.
    """

    def __init__(self):
        super().__init__()

    def order_results(
        self,
        results: List[Result],
        song: Song,
        search_query: Optional[str] = None,
    ) -> Dict[Result, float]:
        """
        Order results.

        ### Arguments
        - results: The results to order.
        - song: The song to order for.
        - search_query: The search query.

        ### Returns
        - The ordered results, with scores.
        """

        # Assign an overall avg match value to each result
        links_with_match_value = {}

        # Iterate over all results
        for result in results:
            debug(
                song.song_id,
                result.result_id,
                f"Calculating match value for {result.url} - {result.json}",
            )

            # skip results that have no common words in their name
            if not check_common_word(song, result):
                debug(
                    song.song_id, result.result_id, "Skipping result due to no common words"
                )

                continue

            # Calculate match value for main artist
            artists_match = calc_main_artist_match(song, result)
            debug(song.song_id, result.result_id, f"Main artist match: {artists_match}")

            # Calculate match value for all artists
            other_artists_match = calc_artists_match(song, result)
            debug(
                song.song_id,
                result.result_id,
                f"Other artists match: {other_artists_match}",
            )

            artists_match += other_artists_match

            # Calculate initial artist match value
            debug(song.song_id, result.result_id, f"Initial artists match: {artists_match}")
            artists_match = artists_match / (2 if len(song.artists) > 1 else 1)
            debug(song.song_id, result.result_id, f"First artists match: {artists_match}")

            # First attempt to fix artist match
            artists_match = artists_match_fixup1(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup1: {artists_match}",
            )

            # Second attempt to fix artist match
            artists_match = artists_match_fixup2(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup2: {artists_match}",
            )

            # Third attempt to fix artist match
            artists_match = artists_match_fixup3(song, result, artists_match)
            debug(
                song.song_id,
                result.result_id,
                f"Artists match after fixup3: {artists_match}",
            )

            debug(song.song_id, result.result_id, f"Final artists match: {artists_match}")

            # Calculate name match
            name_match = calc_name_match(song, result, search_query)
            debug(song.song_id, result.result_id, f"Initial name match: {name_match}")

            # Check if result contains forbidden words
            contains_fwords, found_fwords = check_forbidden_words(song, result)
            if contains_fwords:
                for _ in found_fwords:
                    name_match -= 15

            debug(
                song.song_id,
                result.result_id,
                f"Contains forbidden words: {contains_fwords}, {found_fwords}",
            )
            debug(song.song_id, result.result_id, f"Final name match: {name_match}")

            # Calculate album match
            album_match = calc_album_match(song, result)
            debug(song.song_id, result.result_id, f"Final album match: {album_match}")

            # Calculate time match
            time_match = calc_time_match(song, result)
            debug(song.song_id, result.result_id, f"Final time match: {time_match}")

            # Ignore results with name match lower than 60%
            if name_match <= 60:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to name match lower than 60%",
                )
                continue

            # Ignore results with artists match lower than 70%
            if artists_match < 70 and result.source != "slider.kz":
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to artists match lower than 70%",
                )
                continue

            # Calculate total match
            average_match = (artists_match + name_match) / 2
            debug(song.song_id, result.result_id, f"Average match: {average_match}")

            if (
                result.verified
                and not result.isrc_search
                and result.album
                and album_match <= 80
            ):
                # we are almost certain that this is the correct result
                # so we add the album match to the average match
                average_match = (average_match + album_match) / 2
                debug(
                    song.song_id,
                    result.result_id,
                    f"Average match /w album match: {average_match}",
                )

            # Skip results with time match lower than 25%
            if time_match < 25:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to time match lower than 25%",
                )
                continue

            # If the time match is lower than 50%
            # and the average match is lower than 75%
            # we skip the result
            if time_match < 50 and average_match < 75:
                debug(
                    song.song_id,
                    result.result_id,
                    "Skipping result due to time match < 50% and average match < 75%",
                )
                continue

            if (
                (not result.isrc_search and average_match <= 85)
                or result.source == "slider.kz"
                or time_match < 0
            ):
                # Don't add time to avg match if average match is not the best
                # (lower than 85%), always include time match if result is from
                # slider.kz or if time match is lower than 0
                average_match = (average_match + time_match) / 2

                debug(
                    song.song_id,
                    result.result_id,
                    f"Average match /w time match: {average_match}",
                )

                if (result.explicit is not None and song.explicit is not None) and (
                    result.explicit != song.explicit
                ):
                    debug(
                        song.song_id,
                        result.result_id,
                        "Lowering average match due to explicit mismatch",
                    )

                    average_match -= 5

            average_match = min(average_match, 100)
            debug(song.song_id, result.result_id, f"Final average match: {average_match}")

            # the results along with the avg Match
            links_with_match_value[result] = average_match

        self.compare_with_standard(links_with_match_value, song, search_query)
        return links_with_match_value
    
    
    def compare_with_standard(self, results_extended: Dict[Result, float], song: Song, search_query: Optional[str] = None):
        """
        Compares the best result from ExtendedMixMatcher and StandardMatcher get_best_result.
        Prints a message if the best result is different.
        """
        # Get ordered results from both matchers
        extended_results = results_extended
        standard_results = super().order_results(list(results_extended.keys()), song, search_query)

        # Use get_best_result to get the best result and score from each matcher
        best_extended, score_extended = self.get_best_result(extended_results) if extended_results else (None, None)
        best_standard, score_standard = super().get_best_result(standard_results) if standard_results else (None, None)

        if best_extended != best_standard:
            logging.info(f"[ExtendedMixMatcher] Best result differs from StandardMatcher:\n"
                  f"  ExtendedMixMatcher: artist={getattr(best_extended, 'artist', None)}, name={getattr(best_extended, 'name', None)} (score: {score_extended})\n"
                  f"  StandardMatcher: artist={getattr(best_standard, 'artist', None)}, name={getattr(best_standard, 'name', None)} (score: {score_standard})")