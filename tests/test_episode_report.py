import numpy as np

from research.eval import episode_report


def test_score_counts_episodes_main_hits_h_hits_tops_and_coverage():
    p = np.arange(0, 1000, 5)
    alarm = np.zeros(len(p), dtype=bool)
    alarm[10:13] = True
    alarm[100:102] = True
    lo = np.full(len(p), np.nan)
    hi = np.full(len(p), np.nan)
    lo[10], hi[10] = 40, 60
    lo[100], hi[100] = 10, 40
    tops = np.array([120, 700])

    result = episode_report.score(p, alarm, lo, hi, tops)

    # Run starts are at 50 and 500: only the first top is within H=120 days.
    # With BUFFER=20, the first main window is [70, 130] and contains 120;
    # the second is [490, 560] and misses 700. Both tops are in-range, but
    # only 120 has an alarm in its prior H-day window.
    assert result == {
        "episodes": 2,
        "with_main": 2,
        "hit_main": 1,
        "hit_h": 1,
        "tops": 2,
        "covered": 1,
    }


def test_score_counts_episode_without_main_cluster_but_not_with_main():
    p = np.arange(0, 1000, 5)
    alarm = np.zeros(len(p), dtype=bool)
    alarm[10:13] = True
    lo = np.full(len(p), np.nan)
    hi = np.full(len(p), np.nan)

    result = episode_report.score(p, alarm, lo, hi, np.array([120]))

    # The run starts at 50 and the top at 120 is 70 days later, so it is an
    # episode, H hit, and covered top; lo is NaN, so it has no main cluster.
    assert result == {
        "episodes": 1,
        "with_main": 0,
        "hit_main": 0,
        "hit_h": 1,
        "tops": 1,
        "covered": 1,
    }
