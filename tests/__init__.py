import os

# Tests run against the code's defaults, whatever a local .env says: an empty value means
# "default" (see bot/config.py), and the environment wins over .env
for name in ("BRAND", "MODEL_PATTERN", "MIN_YEAR", "MIN_RANK", "LIMIT_JPY", "TOP_RANK", "TOP_LIMIT_JPY",
             "EXPECT_RATIO", "NEAR_RATIO", "FRAMES", "SCAN_EVERY_MIN", "ALERT_AFTER_MIN"):
    os.environ[name] = ""
