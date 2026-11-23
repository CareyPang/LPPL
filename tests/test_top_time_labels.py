"""Label semantics and data-cutoff tests, independent of LPPL predictions."""

from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal
from random import Random

import pytest

from research.eval.top_time.contracts import Protocol, TopEvent
from research.eval.top_time.labels import _assign_families, build_labels


def _calendar(n):
    # A deliberately synthetic explicit session calendar, not an exchange claim.
    return tuple((date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(n))


def _small(**changes):
    config = Protocol(
        short_left=2,
        short_right=2,
        stage_left=4,
        stage_right=3,
        merge_gap=1,
        trough_left=2,
        trough_right=2,
        rise_min=3,
        rise_max=12,
        require_stage_rise=False,
    )
    return replace(config, **changes)


def _plateau():
    return list(range(10)) + [20] * 16 + list(range(19, 3, -1))


def _event(book, scale, peak):
    return next(
        (event for event in book.events if event.scale == scale and event.peak_session == peak),
        None,
    )


def test_long_plateau_uses_first_candidate_and_waits_for_final_group_closure():
    prices = _plateau()
    sessions = _calendar(len(prices))
    before = build_labels("toy", sessions, prices, config=_small(), asof_session=28)
    assert _event(before, "short", 10).end_session == 25
    assert _event(before, "stage", 10) is None
    assert before.known["stage"][10] is False

    closed = build_labels("toy", sessions, prices, config=_small(), asof_session=29)
    short = _event(closed, "short", 10)
    stage = _event(closed, "stage", 10)
    assert short.candidate_sessions == stage.candidate_sessions == tuple(range(10, 26))
    assert short.support_end == 28
    assert stage.support_end == stage.available_session == 29
    assert stage.family_id == short.family_id
    assert not stage.family_ambiguous
    assert all(closed.known["stage"][i] for i in range(10, 26))
    assert len([event for event in closed.events if event.scale == "stage"]) == 1


def test_equal_price_gapped_candidates_merge_but_no_epsilon_is_applied():
    prices = [0, 1, 2, 3, 4, 5, 10, 8, 10, 7, 6, 5, 4, 3, 2, 1]
    config = _small(merge_gap=2)
    book = build_labels("toy", _calendar(len(prices)), prices, config=config)
    assert _event(book, "short", 6).candidate_sessions == (6, 8)
    assert _event(book, "short", 6).end_session == 8
    changed = list(prices)
    changed[8] = Decimal("10.000000000000000001")
    revised = build_labels("toy", _calendar(len(prices)), changed, config=config)
    assert _event(revised, "short", 6) is None
    assert _event(revised, "short", 8).candidate_sessions == (8,)


def test_same_price_peaks_outside_gap_are_separate_events():
    prices = [0, 1, 2, 3, 10, 7, 6, 7, 10, 7, 6, 5, 4, 3, 2]
    book = build_labels("toy", _calendar(len(prices)), prices, config=_small())
    assert _event(book, "short", 4) is not None
    assert _event(book, "short", 8) is not None
    assert _event(book, "short", 4).family_id != _event(book, "short", 8).family_id


def test_missing_sessions_are_unknown_and_never_compressed_or_zero_filled():
    prices = _plateau()
    prices[15] = None
    book = build_labels("toy", _calendar(len(prices)), prices, config=_small())
    assert len(book.sessions) == len(prices)
    assert _event(book, "stage", 10) is None
    assert book.known["stage"][10] is False
    assert any("MISSING" in item["reason"] for item in book.pending)
    # Splitting a damaged plateau must not fabricate a new peak after the gap.
    assert not [event for event in book.events if event.scale == "stage"]


@pytest.mark.parametrize("missing", [None, float("nan"), Decimal("NaN"), float("inf")])
def test_missing_closure_price_keeps_label_pending(missing):
    prices = _plateau()
    prices[29] = missing
    book = build_labels("toy", _calendar(len(prices)), prices, config=_small())
    assert _event(book, "short", 10) is not None
    assert _event(book, "stage", 10) is None
    assert book.known["stage"][10] is False


def test_delayed_input_changes_available_time_without_moving_peak_or_calendar():
    prices = _plateau()
    availability = list(range(len(prices)))
    availability[29] = 32
    before = build_labels(
        "toy", _calendar(len(prices)), prices, config=_small(),
        asof_session=31, available_sessions=availability,
    )
    assert _event(before, "stage", 10) is None
    assert before.known["stage"][10] is False
    after = build_labels(
        "toy", _calendar(len(prices)), prices, config=_small(),
        asof_session=32, available_sessions=availability,
    )
    event = _event(after, "stage", 10)
    assert event.support_end == 29
    assert event.available_session == 32
    assert after.metadata["known_support"]["stage"][10]["available_session"] == 32


def test_asof_ignores_future_values_and_agrees_with_physically_truncated_input():
    prices = _plateau()
    sessions = _calendar(len(prices))
    cutoff = 29
    full = build_labels("toy", sessions, prices, config=_small(), asof_session=cutoff)
    changed = prices[: cutoff + 1] + ["unread future"] * (len(prices) - cutoff - 1)
    hidden = build_labels("toy", sessions, changed, config=_small(), asof_session=cutoff)
    prefix = build_labels("toy", sessions[: cutoff + 1], prices[: cutoff + 1], config=_small())
    assert [asdict(event) for event in full.events] == [asdict(event) for event in hidden.events]
    assert [asdict(event) for event in full.events] == [asdict(event) for event in prefix.events]
    for scale in ("short", "stage"):
        assert full.known[scale] == hidden.known[scale]
        assert full.known[scale][: cutoff + 1] == prefix.known[scale]
        assert not any(full.known[scale][cutoff + 1 :])


def test_delayed_prices_are_not_inspected_before_their_available_session():
    prices = _plateau()
    availability = list(range(len(prices)))
    availability[29] = 35
    prices[29] = "not available yet"
    book = build_labels(
        "toy", _calendar(len(prices)), prices, config=_small(),
        asof_session=32, available_sessions=availability,
    )
    assert _event(book, "stage", 10) is None
    assert any(item["reason"] == "DELAYED_DATA" for item in book.pending)


def test_flat_and_monotone_series_do_not_create_events_and_tail_is_unknown():
    for prices in ([7] * 40, list(range(40)), list(range(40, 0, -1))):
        book = build_labels("toy", _calendar(len(prices)), prices, config=_small())
        assert not book.events
        assert not any(book.known["stage"][:4])
        assert not any(book.known["stage"][-4:])
    increasing = build_labels("toy", _calendar(40), list(range(40)), config=_small())
    assert increasing.known["stage"][20] is True  # Resolved absence, unlike the tail.


def _nearest_trough_example():
    # Candidate troughs: i=8 at 5, i=15 at 8, i=18 at 7.  For peak i=20,
    # rise_min=3 excludes i=18; i=15 is selected, then breached.  Older i=8
    # would pass, and must not be substituted after seeing that failure.
    return [14, 13, 12, 11, 10, 9, 8, 7, 5, 6, 7, 8, 9, 10, 9, 8,
            9, 10, 7, 11, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]


def test_rise_selects_nearest_before_validation_and_never_falls_back():
    prices = _nearest_trough_example()
    book = build_labels(
        "toy", _calendar(len(prices)), prices, config=_small(require_stage_rise=True)
    )
    assert _event(book, "short", 20) is not None
    assert _event(book, "stage", 20) is None
    assert book.known["stage"][20] is True
    audit = next(item for item in book.metadata["rise_audit"] if item["peak_session"] == 20)
    assert audit["rise_start"] == 15
    assert audit["reason"] == "RISE_TROUGH_BREACHED"
    assert audit["breach_sessions"] == (18,)
    assert len(audit["eligible_trough_ids"]) == 2


def test_unresolved_trough_search_range_is_not_a_negative_rise_label():
    prices = _nearest_trough_example()
    prices[6] = None  # Damages an older part of the fixed search range.
    book = build_labels(
        "toy", _calendar(len(prices)), prices, config=_small(require_stage_rise=True)
    )
    assert any(item["peak_session"] == 20 for item in book.metadata["stage_structure_events"])
    assert _event(book, "stage", 20) is None
    assert book.known["stage"][20] is False
    assert any(item["reason"] == "RISE_SEARCH_UNRESOLVED" for item in book.pending)


def test_missing_gap_in_combined_support_does_not_become_a_negative_or_crash():
    prices = list(range(21)) + list(range(19, 8, -1))
    prices[14] = None
    config = _small(require_stage_rise=True, rise_min=10, rise_max=12)
    book = build_labels("toy", _calendar(len(prices)), prices, config=config)
    assert any(item["peak_session"] == 20 for item in book.metadata["stage_structure_events"])
    assert book.known["stage"][20] is False
    assert any(item["reason"] == "RISE_MISSING_PRICE" for item in book.pending)


def test_monotone_price_transformation_preserves_labels_and_rise_decisions():
    prices = _nearest_trough_example()
    config = _small(require_stage_rise=True)
    first = build_labels("toy", _calendar(len(prices)), prices, config=config)
    second = build_labels(
        "toy", _calendar(len(prices)), [Decimal(p) ** 3 + 17 for p in prices], config=config
    )
    def shape(book):
        return [
            (event.scale, event.peak_session, event.end_session, event.rise_start)
            for event in book.events
        ]
    assert shape(first) == shape(second)
    assert first.known == second.known
    assert [item["reason"] for item in first.excluded] == [item["reason"] for item in second.excluded]


def test_closed_labels_and_resolved_negative_anchors_survive_later_prices():
    # Discrete prices deliberately create repeated equal-price candidates.
    random = Random(20261106)
    prices = [random.randrange(1, 9) for _ in range(100)]
    sessions = _calendar(len(prices))
    config = _small(merge_gap=2)
    final = build_labels("toy", sessions, prices, config=config)
    final_events = {event.event_id: event for event in final.events}
    for cutoff in (20, 39, 57, 80):
        earlier = build_labels("toy", sessions, prices, config=config, asof_session=cutoff)
        for event in earlier.events:
            assert event.event_id in final_events
            later = final_events[event.event_id]
            assert (event.peak_session, event.end_session, event.available_session) == (
                later.peak_session, later.end_session, later.available_session
            )
        for scale in ("short", "stage"):
            old_anchors = {event.peak_session for event in earlier.events if event.scale == scale}
            new_anchors = {event.peak_session for event in final.events if event.scale == scale}
            for anchor, known in enumerate(earlier.known[scale]):
                if known:
                    assert final.known[scale][anchor]
                    assert (anchor in old_anchors) == (anchor in new_anchors)


def test_family_linker_preserves_many_to_one_ambiguity_without_collapsing_events():
    def event(name, scale, candidates):
        return TopEvent(name, "toy", scale, candidates[0], candidates[-1], candidates,
                        "10", 0, 20, 20)

    events = [event("s", "short", (10, 11, 12)),
              event("a", "stage", (10,)), event("b", "stage", (12,))]
    links = _assign_families(events)
    assert len(events) == 3 and len(links) == 2
    assert len({item.family_id for item in events}) == 1
    assert all(item.family_ambiguous for item in events)


def test_metadata_keeps_research_defaults_and_assumed_availability_explicit():
    book = build_labels("toy", _calendar(10), list(range(10)))
    assert book.metadata["config"]["stage_right"] == 42
    assert book.metadata["config"]["parameter_status"] == "RESEARCH_DEFAULT_NOT_FROZEN"
    assert book.metadata["provenance"]["availability_basis"] == "ASSUMED_SAME_SESSION_NON_PIT"
    assert book.metadata["provenance"]["historical_publication"] == "NOT_ESTABLISHED"
    assert book.metadata["provenance"]["input_status"] == "UNVERIFIED"
    assert book.metadata["rise_search_policy"] == "ENTIRE_FIXED_ENDPOINT_RANGE_RESOLVED_NO_FALLBACK"


def test_input_validation_and_empty_cutoff():
    with pytest.raises(ValueError, match="equal length"):
        build_labels("toy", _calendar(3), [1, 2])
    with pytest.raises(ValueError, match="unique"):
        build_labels("toy", ["2024-01-01"] * 2, [1, 2])
    with pytest.raises(ValueError, match="no earlier"):
        build_labels("toy", _calendar(3), [1, 2, 3], available_sessions=[0, 0, 2])
    book = build_labels("toy", _calendar(3), ["unread"] * 3, asof_session=-1)
    assert not book.events and not any(book.known["short"])
    assert build_labels("toy", [], []).asof_session == -1


# Small immutable extract from frozen/v20261104/sh000001_qfq.parquet.
# Observed dates are retained exactly; they are not an independently verified
# exchange calendar.  Close prices only; no LPPL or future-return selection.
_SHANGHAI_CLOSE = """
2023-07-03:3243.98 2023-07-04:3245.35 2023-07-05:3222.95 2023-07-06:3205.57
2023-07-07:3196.61 2023-07-10:3203.7 2023-07-11:3221.37 2023-07-12:3196.13
2023-07-13:3236.48 2023-07-14:3237.7 2023-07-17:3209.63 2023-07-18:3197.82
2023-07-19:3198.84 2023-07-20:3169.52 2023-07-21:3167.75 2023-07-24:3164.16
2023-07-25:3231.52 2023-07-26:3223.03 2023-07-27:3216.67 2023-07-28:3275.93
2023-07-31:3291.04 2023-08-01:3290.95 2023-08-02:3261.69 2023-08-03:3280.46
2023-08-04:3288.08 2023-08-07:3268.83 2023-08-08:3260.62 2023-08-09:3244.49
2023-08-10:3254.56 2023-08-11:3189.25 2023-08-14:3178.43 2023-08-15:3176.18
2023-08-16:3150.13 2023-08-17:3163.74 2023-08-18:3131.95 2023-08-21:3092.98
2023-08-22:3120.33 2023-08-23:3078.4 2023-08-24:3082.24 2023-08-25:3064.07
2023-08-28:3098.64 2023-08-29:3135.89 2023-08-30:3137.14 2023-08-31:3119.88
2023-09-01:3133.25 2023-09-04:3177.06 2023-09-05:3154.37 2023-09-06:3158.08
2023-09-07:3122.35 2023-09-08:3116.72 2023-09-11:3142.78 2023-09-12:3137.06
2023-09-13:3123.07 2023-09-14:3126.55 2023-09-15:3117.74 2023-09-18:3125.93
2023-09-19:3124.96 2023-09-20:3108.57 2023-09-21:3084.7 2023-09-22:3132.43
2023-09-25:3115.61 2023-09-26:3102.27 2023-09-27:3107.32 2023-09-28:3110.48
2023-10-09:3096.92 2023-10-10:3075.24 2023-10-11:3078.96 2023-10-12:3107.9
2023-10-13:3088.1 2023-10-16:3073.81 2023-10-17:3083.5 2023-10-18:3058.71
2023-10-19:3005.39 2023-10-20:2983.06 2023-10-23:2939.29 2023-10-24:2962.24
2023-10-25:2974.11 2023-10-26:2988.3 2023-10-27:3017.78 2023-10-30:3021.55
2023-10-31:3018.77 2023-11-01:3023.08 2023-11-02:3009.41 2023-11-03:3030.8
2023-11-06:3058.41 2023-11-07:3057.27 2023-11-08:3052.37 2023-11-09:3053.28
2023-11-10:3038.97 2023-11-13:3046.53 2023-11-14:3056.07 2023-11-15:3072.83
2023-11-16:3050.93 2023-11-17:3054.37 2023-11-20:3068.32 2023-11-21:3067.93
2023-11-22:3043.61 2023-11-23:3061.86 2023-11-24:3040.97 2023-11-27:3031.7
2023-11-28:3038.55 2023-11-29:3021.69 2023-11-30:3029.67 2023-12-01:3031.64
2023-12-04:3022.91 2023-12-05:2972.3 2023-12-06:2968.93 2023-12-07:2966.21
2023-12-08:2969.56 2023-12-11:2991.44 2023-12-12:3003.44 2023-12-13:2968.76
2023-12-14:2958.99 2023-12-15:2942.56 2023-12-18:2930.8 2023-12-19:2932.39
2023-12-20:2902.11 2023-12-21:2918.71 2023-12-22:2914.78 2023-12-25:2918.81
2023-12-26:2898.88 2023-12-27:2914.61 2023-12-28:2954.7 2023-12-29:2974.93
2024-01-02:2962.28 2024-01-03:2967.25 2024-01-04:2954.35 2024-01-05:2929.18
2024-01-08:2887.54 2024-01-09:2893.25 2024-01-10:2877.7 2024-01-11:2886.65
2024-01-12:2881.98 2024-01-15:2886.29 2024-01-16:2893.99 2024-01-17:2833.62
2024-01-18:2845.78 2024-01-19:2832.28 2024-01-22:2756.34 2024-01-23:2770.98
2024-01-24:2820.77 2024-01-25:2906.11 2024-01-26:2910.22 2024-01-29:2883.36
2024-01-30:2830.53 2024-01-31:2788.55 2024-02-01:2770.74 2024-02-02:2730.15
2024-02-05:2702.19 2024-02-06:2789.49 2024-02-07:2829.7 2024-02-08:2865.9
2024-02-19:2910.54 2024-02-20:2922.73 2024-02-21:2950.96 2024-02-22:2988.36
2024-02-23:3004.88 2024-02-26:2977.02 2024-02-27:3015.48 2024-02-28:2957.85
2024-02-29:3015.17 2024-03-01:3027.02 2024-03-04:3039.31 2024-03-05:3047.79
2024-03-06:3039.93 2024-03-07:3027.4 2024-03-08:3046.02 2024-03-11:3068.46
2024-03-12:3055.94 2024-03-13:3043.83 2024-03-14:3038.23 2024-03-15:3054.64
2024-03-18:3084.93 2024-03-19:3062.76 2024-03-20:3079.69 2024-03-21:3077.11
2024-03-22:3048.03 2024-03-25:3026.31 2024-03-26:3031.48 2024-03-27:2993.14
2024-03-28:3010.66 2024-03-29:3041.17 2024-04-01:3077.38 2024-04-02:3074.96
2024-04-03:3069.3 2024-04-08:3047.05 2024-04-09:3048.54 2024-04-10:3027.33
2024-04-11:3034.25 2024-04-12:3019.47 2024-04-15:3057.38 2024-04-16:3007.07
2024-04-17:3071.38 2024-04-18:3074.22 2024-04-19:3065.26 2024-04-22:3044.6
2024-04-23:3021.98 2024-04-24:3044.82 2024-04-25:3052.9 2024-04-26:3088.64
2024-04-29:3113.04 2024-04-30:3104.82 2024-05-06:3140.72 2024-05-07:3147.74
2024-05-08:3128.48 2024-05-09:3154.32 2024-05-10:3154.55 2024-05-13:3148.02
2024-05-14:3145.77 2024-05-15:3119.9 2024-05-16:3122.4 2024-05-17:3154.03
2024-05-20:3171.15 2024-05-21:3157.97 2024-05-22:3158.54 2024-05-23:3116.39
2024-05-24:3088.87 2024-05-27:3124.04 2024-05-28:3109.57 2024-05-29:3111.02
2024-05-30:3091.68 2024-05-31:3086.81 2024-06-03:3078.49 2024-06-04:3091.2
2024-06-05:3065.4 2024-06-06:3048.79 2024-06-07:3051.28 2024-06-11:3028.05
2024-06-12:3037.47 2024-06-13:3028.92 2024-06-14:3032.63 2024-06-17:3015.89
2024-06-18:3030.25 2024-06-19:3018.05 2024-06-20:3005.44 2024-06-21:2998.14
2024-06-24:2963.1 2024-06-25:2950.0 2024-06-26:2972.53 2024-06-27:2945.85
2024-06-28:2967.4 2024-07-01:2994.73 2024-07-02:2997.01 2024-07-03:2982.38
2024-07-04:2957.57 2024-07-05:2949.93 2024-07-08:2922.45 2024-07-09:2959.37
2024-07-10:2939.36 2024-07-11:2970.39 2024-07-12:2971.3 2024-07-15:2974.01
2024-07-16:2976.3 2024-07-17:2962.85 2024-07-18:2977.13 2024-07-19:2982.31
2024-07-22:2964.22 2024-07-23:2915.37 2024-07-24:2901.95 2024-07-25:2886.74
2024-07-26:2890.9 2024-07-29:2891.85 2024-07-30:2879.3 2024-07-31:2938.75
"""


def _shanghai():
    rows = [token.split(":") for token in _SHANGHAI_CLOSE.split()]
    return tuple(row[0] for row in rows), tuple(Decimal(row[1]) for row in rows)


def test_real_casebook_r21_and_r42_change_stage_semantics_not_short_label():
    sessions, prices = _shanghai()
    march, may, trough = (sessions.index(day) for day in
                          ("2024-03-18", "2024-05-20", "2024-02-05"))
    r21 = build_labels("sh000001", sessions, prices, config=Protocol(stage_right=21))
    r42 = build_labels("sh000001", sessions, prices, config=Protocol())
    assert _event(r21, "short", march) is not None
    assert _event(r42, "short", march) is not None
    assert _event(r21, "stage", march).rise_start == trough
    assert march - trough == 24  # The old peak-time-mature trough rule lost this case.
    assert _event(r42, "stage", march) is None
    assert r42.known["stage"][march] is True
    assert _event(r21, "stage", may).rise_start == trough
    assert _event(r42, "stage", may).rise_start == trough
    assert may - trough == 64
    assert sessions[_event(r21, "stage", march).support_end] == "2024-04-25"
    assert sessions[_event(r21, "stage", may).support_end] == "2024-06-26"
    assert sessions[_event(r42, "stage", may).support_end] == "2024-07-25"


@pytest.mark.parametrize("right, support_day", [(21, "2024-06-26"), (42, "2024-07-25")])
def test_real_casebook_peak_is_pending_until_its_exact_support_end(right, support_day):
    sessions, prices = _shanghai()
    peak, support = sessions.index("2024-05-20"), sessions.index(support_day)
    config = Protocol(stage_right=right)
    before = build_labels("sh000001", sessions, prices, config=config, asof_session=support - 1)
    at = build_labels("sh000001", sessions, prices, config=config, asof_session=support)
    assert _event(before, "stage", peak) is None
    assert before.known["stage"][peak] is False
    assert _event(at, "stage", peak).available_session == support
    assert at.known["stage"][peak] is True
