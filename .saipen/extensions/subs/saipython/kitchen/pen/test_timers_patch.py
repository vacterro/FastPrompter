def test_from_dict_corrupt_entries_skipped():
    from fastprompter.core.timers import load_timers

    t_healthy = {
        "target": "2026-08-19T10:00:00",
        "name": "Healthy",
        "description": "A healthy timer",
    }
    t_numeric_name = {
        "target": "2026-08-19T10:00:00",
        "name": 123,
        "description": "Numeric name",
    }
    t_numeric_desc = {
        "target": "2026-08-19T10:00:00",
        "name": "Numeric desc",
        "description": 123,
    }
    t_aware_target = {
        "target": "2026-08-19T10:00:00+03:00",
        "name": "Aware target",
        "description": "Timezone aware",
    }

    timers = load_timers([
        t_healthy,
        t_numeric_name,
        t_numeric_desc,
        t_aware_target,
    ])

    assert len(timers) == 1
    assert timers[0].name == "Healthy"
