"""Dollar cost of Claude usage, shared by the API spend caps and the eval."""

# Claude Opus 5.5 list prices, $ per million tokens (5-minute cache writes are 1.25x input).
PRICE = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}


def usage_cost(usage: list[dict]) -> float:
    total = 0.0
    for u in usage:
        total += (u.get("input_tokens", 0) * PRICE["input"] + u.get("output_tokens", 0) * PRICE["output"]
                  + u.get("cache_read_input_tokens", 0) * PRICE["cache_read"]
                  + u.get("cache_creation_input_tokens", 0) * PRICE["cache_write"]) / 1e6
    return round(total, 5)
