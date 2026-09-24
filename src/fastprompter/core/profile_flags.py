"""One fallback for "True"/"False" profile flags: DEFAULT_PROFILE.

A literal fallback at each read site (``data.get("date_emoji", "True")``)
lets two surfaces disagree about a key the profile never stored -- the
settings checkbox said one thing, the profile-switch resync another. Every
reader goes through here so the shipped default is the single truth.
"""

from fastprompter.core.default_profile import DEFAULT_PROFILE


def profile_default(key, fallback="False"):
    """The shipped default for ``key`` as the profile stores it."""
    return DEFAULT_PROFILE.get(key, fallback)


def profile_flag(data, key, fallback="False"):
    """``data[key] == "True"``, a missing key reading its shipped default."""
    return str(data.get(key, profile_default(key, fallback))) == "True"
