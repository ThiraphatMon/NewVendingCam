"""tests ขั้น E: เตือนค่าใน .env ที่ไม่มีผลกับโหมดที่รัน"""

import config


def test_no_warning_for_clean_redis_env():
    env = {"CONTROL_MODE": "redis", "REDIS_HOST": "127.0.0.1", "CLOUD_ENABLED": "0", "CAMERA_INDEX": "0"}
    assert config.inactive_warnings(env) == []


def test_warns_order_only_and_cloud_only_keys():
    env = {"CLOUD_ENABLED": "0", "WS_URL": "ws://x/ws", "ORDER_WINDOW": "30", "CLOUD_API_URL": "http://x"}
    w = config.inactive_warnings(env)
    assert len(w) == 2
    assert "WS_URL, ORDER_WINDOW" in w[0] and "CLOUD_API_URL" in w[1]


def test_cloud_keys_ok_when_cloud_enabled_and_empty_values_ignored():
    env = {"CLOUD_ENABLED": "1", "CLOUD_API_URL": "http://x", "API_KEY": "", "WS_URL": " "}
    assert config.inactive_warnings(env) == []


def test_redis_keys_warned_in_keyboard_mode():
    w = config.inactive_warnings({"CONTROL_MODE": "keyboard", "REDIS_PORT": "6379"})
    assert w and "REDIS_PORT" in w[0] and "CONTROL_MODE=redis" in w[0]
