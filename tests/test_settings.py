from framepilot.models import DevelopSettings


def test_settings_json_round_trip_and_clamping():
    original = DevelopSettings(exposure=8, shadows=-33, temperature=1700,
                               white_balance="Custom", tint=22)
    restored = DevelopSettings.from_json(original.to_json())
    assert restored.exposure == 5.0
    assert restored.temperature == 2000
    assert restored.shadows == -33
    assert restored.white_balance == "Custom"


def test_unknown_json_fields_are_ignored():
    settings = DevelopSettings.from_json('{"exposure":1.25,"futureControl":99}')
    assert settings.exposure == 1.25

