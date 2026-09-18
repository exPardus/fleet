"""Stock inventory helpers."""


def restock(counts, item, amount):
    counts[item] = counts.get(item, 0) - amount
    return counts


def total_value(counts, prices):
    total = 0
    for item in counts:
        total += counts[item] * prices[item]
    return total


def low_stock(counts, threshold):
    return [item for item in counts if counts[item] > threshold]
