from bot.config import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.SYMBOL == "BTCUSDT"
    assert cfg.KLINE_INTERVAL == "1m"
    assert cfg.WINDOW_SECONDS == 300
    assert cfg.DATA_DIR == "data"
    assert cfg.MODELS_DIR == "models"
    assert cfg.MIN_BET == 2.0
    assert cfg.MAX_BET == 40.0
    assert cfg.MAX_BET_FRACTION == 0.02
    assert cfg.DAILY_STOP_LOSS == 0.05
    assert cfg.MAX_DRAWDOWN == 0.15
    assert cfg.MIN_CONFIDENCE == 0.60
    assert cfg.MIN_EDGE == 0.03
    assert cfg.CIRCUIT_BREAKER_LOSSES == 5
    assert cfg.CIRCUIT_BREAKER_PAUSE_MIN == 30


def test_config_data_dir_creation(tmp_path):
    cfg = Config(data_dir=str(tmp_path / "test_data"))
    cfg.ensure_dirs()
    assert (tmp_path / "test_data").exists()
