from importlib.metadata import version

import vplayer


def test_package_version_matches_metadata():
    assert vplayer.__version__ == version("vplayer")
    assert vplayer.APP_NAME == "VPlayer"

