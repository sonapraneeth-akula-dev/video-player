import math

import pytest

from vplayer.sync import fps_match


@pytest.mark.parametrize(("a", "b"), [(29.97, 30000 / 1001), (25, 25), (24, 24.0009)])
def test_matching_frame_rates(a, b):
    assert fps_match(a, b)
    assert fps_match(b, a)


@pytest.mark.parametrize(("a", "b"), [(29.97, 30), (24, 25), (60, 59.94), (24, 24.001)])
def test_mismatched_rates_show_both_values(a, b):
    with pytest.raises(ValueError, match=f"{a:g} fps vs {b:g} fps"):
        fps_match(a, b)


@pytest.mark.parametrize("unknown", [None, 0, -1, True, math.inf, math.nan, "25"])
def test_unknown_rates_refuse_compare(unknown):
    with pytest.raises(ValueError, match="Frame rate unknown"):
        fps_match(unknown, 25)
    with pytest.raises(ValueError, match="Frame rate unknown"):
        fps_match(25, unknown)
