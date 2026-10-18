"""Dollar cost of model usage, shared by the API spend caps and the eval."""

# $ per million tokens: input, output, cache read, 5-minute cache write (1.25x input).
# Haiku 5.5 cache prices are assumed at the usual 0.1x / 1.25x of input.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
PRICE = PRICES["claude-opus-5-5"]  # default when a usage row doesn't name a known model


def usage_cost(usage: list[dict]) -> float:
    total = 0.0
    for u in usage:
        if u.get("provider") == "ollama":  # local models cost nothing per token
            continue
        p = PRICES.get(u.get("model", ""), PRICE)
        total += (u.get("input_tokens", 0) * p["input"] + u.get("output_tokens", 0) * p["output"]
                  + u.get("cache_read_input_tokens", 0) * p["cache_read"]
                  + u.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1e6
    return round(total, 5)
