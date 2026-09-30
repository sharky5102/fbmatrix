#!/usr/bin/env python3
"""Generate and evaluate a collectively self-framing LED ID codebook.

All LEDs emit fixed-length binary codes in the same global phase. Hard
constraints are aligned Hamming distance, cyclic run length, and balance.
Individual codes need not be rotation-separated; instead, the population is
checked for wrong-global-phase confusion. No third-party packages are needed.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import random
from collections import Counter
from pathlib import Path


def rotate_right(value: int, amount: int, width: int) -> int:
    amount %= width
    mask = (1 << width) - 1
    return ((value >> amount) | (value << (width - amount))) & mask


def bits(value: int, width: int) -> str:
    return f"{value:0{width}b}"


def cyclic_max_run(value: int, width: int) -> int:
    sequence = bits(value, width)
    if sequence.count(sequence[0]) == width:
        return width
    start = next(i for i in range(width) if sequence[i] != sequence[i - 1])
    best = run = 1
    previous = sequence[start]
    for step in range(1, width):
        current = sequence[(start + step) % width]
        if current == previous:
            run += 1
            best = max(best, run)
        else:
            run = 1
            previous = current
    return best


def cyclic_transitions(value: int, width: int) -> int:
    return (value ^ rotate_right(value, 1, width)).bit_count()


def cyclic_window(value: int, start: int, length: int, width: int) -> int:
    result = 0
    for offset in range(length):
        bit_position = width - 1 - ((start + offset) % width)
        result = (result << 1) | ((value >> bit_position) & 1)
    return result


def window_distance(a: int, b: int, start: int, length: int, width: int) -> int:
    return (
        cyclic_window(a, start, length, width)
        ^ cyclic_window(b, start, length, width)
    ).bit_count()


def minimum_window_distance(a: int, b: int, length: int, width: int) -> int:
    return min(window_distance(a, b, phase, length, width) for phase in range(width))


def enumerate_candidates(
    width: int, min_weight: int, max_weight: int, max_run: int
) -> list[int]:
    return [
        value
        for value in range(1 << width)
        if min_weight <= value.bit_count() <= max_weight
        and cyclic_max_run(value, width) <= max_run
    ]


def forbid_hamming_ball(forbidden: bytearray, value: int, width: int, radius: int) -> None:
    """Mark every word within Hamming radius 0..2 of value."""
    forbidden[value] = 1
    if radius == 0:
        return
    for i in range(width):
        forbidden[value ^ (1 << i)] = 1
    if radius == 1:
        return
    if radius != 2:
        raise ValueError("this generator supports minimum distance up to 3")
    for i in range(width):
        for j in range(i + 1, width):
            forbidden[value ^ (1 << i) ^ (1 << j)] = 1


def select_distance_code(
    candidates: list[int], count: int, width: int, minimum_distance: int, seed: int
) -> list[int]:
    """Randomized greedy selection with an exact aligned-distance guarantee."""
    if minimum_distance not in (1, 2, 3):
        raise ValueError("--min-distance must be 1, 2, or 3")
    order = candidates.copy()
    random.Random(seed).shuffle(order)
    forbidden = bytearray(1 << width)
    selected: list[int] = []
    radius = minimum_distance - 1
    for value in order:
        if forbidden[value]:
            continue
        selected.append(value)
        forbid_hamming_ball(forbidden, value, width, radius)
        if len(selected) == count:
            return selected
    raise RuntimeError(
        f"greedy search found only {len(selected):,}/{count:,} codes; "
        "try another --seed, larger --width, or looser constraints"
    )


def order_physical_ids(codes: list[int], width: int, window: int, pool: int) -> list[int]:
    """Heuristically separate consecutive physical IDs in every short window."""
    result = codes.copy()
    for index in range(len(result) - 1):
        stop = min(len(result), index + 1 + pool)

        def score(candidate_index: int) -> tuple[int, int]:
            candidate = result[candidate_index]
            return (
                minimum_window_distance(result[index], candidate, window, width),
                (result[index] ^ candidate).bit_count(),
            )

        best_index = max(range(index + 1, stop), key=score)
        result[index + 1], result[best_index] = result[best_index], result[index + 1]
    return result


def repair_physical_order(
    codes: list[int],
    width: int,
    window: int,
    target: int,
    iterations: int,
    seed: int,
) -> tuple[list[int], int, int]:
    """Repair weak adjacent pairs using cheap random swaps.

    Each proposal touches at most four edges. A swap is kept only when the
    lexicographic objective (bad edges, total deficit, window score, full-code
    score) improves over those affected edges.
    """
    result = codes.copy()
    rng = random.Random(seed ^ 0x5A9A5A9A)
    cache: dict[tuple[int, int], tuple[int, int]] = {}

    def score(a: int, b: int) -> tuple[int, int]:
        key = (a, b) if a < b else (b, a)
        cached = cache.get(key)
        if cached is None:
            cached = (
                minimum_window_distance(a, b, window, width),
                (a ^ b).bit_count(),
            )
            cache[key] = cached
        return cached

    edge_scores = [score(result[i], result[i + 1]) for i in range(len(result) - 1)]
    heap = [(edge_scores[i][0], i) for i in range(len(edge_scores)) if edge_scores[i][0] < target]
    heapq.heapify(heap)

    def objective(selected: list[tuple[int, int]]) -> tuple[int, int, int, int]:
        bad = sum(window_score < target for window_score, _ in selected)
        deficit = sum(max(0, target - window_score) for window_score, _ in selected)
        return (
            bad,
            deficit,
            -sum(window_score for window_score, _ in selected),
            -sum(full_score for _, full_score in selected),
        )

    attempts = 0
    accepted = 0
    while attempts < iterations:
        while heap:
            heap_score, bad_edge = heapq.heappop(heap)
            if edge_scores[bad_edge][0] == heap_score and heap_score < target:
                break
        else:
            break

        swap_position = bad_edge + rng.randrange(2)
        other_position = rng.randrange(len(result))
        attempts += 1
        if other_position == swap_position:
            heapq.heappush(heap, (edge_scores[bad_edge][0], bad_edge))
            continue

        affected = {
            edge
            for position in (swap_position, other_position)
            for edge in (position - 1, position)
            if 0 <= edge < len(edge_scores)
        }
        old_objective = objective([edge_scores[edge] for edge in affected])
        result[swap_position], result[other_position] = result[other_position], result[swap_position]
        proposed = {
            edge: score(result[edge], result[edge + 1])
            for edge in affected
        }
        if objective(list(proposed.values())) < old_objective:
            accepted += 1
            for edge, edge_score in proposed.items():
                edge_scores[edge] = edge_score
                if edge_score[0] < target:
                    heapq.heappush(heap, (edge_score[0], edge))
        else:
            result[swap_position], result[other_position] = result[other_position], result[swap_position]
            heapq.heappush(heap, (edge_scores[bad_edge][0], bad_edge))

    remaining_bad = sum(window_score < target for window_score, _ in edge_scores)
    return result, accepted, remaining_bad


def short_window_stats(
    codes: list[int], width: int, window: int
) -> list[tuple[int, int, int]]:
    result = []
    for phase in range(width):
        counts = Counter(cyclic_window(code, phase, window, width) for code in codes)
        unique = sum(count == 1 for count in counts.values())
        ambiguous = sum(count for count in counts.values() if count > 1)
        result.append((unique, max(counts.values()), ambiguous))
    return result


def transition_rates(codes: list[int], width: int) -> list[float]:
    rates = []
    for phase in range(width):
        previous = (phase - 1) % width
        changed = 0
        for code in codes:
            a = (code >> (width - 1 - previous)) & 1
            b = (code >> (width - 1 - phase)) & 1
            changed += a != b
        rates.append(changed / len(codes))
    return rates


def wrong_phase_exact_rates(codes: list[int], width: int) -> list[float]:
    """Fraction of the codebook still valid after each global rotation."""
    code_set = set(codes)
    return [
        sum(rotate_right(code, shift, width) in code_set for code in codes) / len(codes)
        for shift in range(1, width)
    ]


def sampled_aligned_distances(codes: list[int], samples: int, seed: int) -> Counter[int]:
    rng = random.Random(seed ^ 0xC011EC71)
    result: Counter[int] = Counter()
    for _ in range(samples):
        i = rng.randrange(len(codes))
        j = rng.randrange(len(codes) - 1)
        if j >= i:
            j += 1
        result[(codes[i] ^ codes[j]).bit_count()] += 1
    return result


def write_csv(path: Path, codes: list[int], width: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("led_id", "hex", "bits"))
        for led_id, code in enumerate(codes):
            writer.writerow((led_id, f"0x{code:0{(width + 3) // 4}x}", bits(code, width)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=21)
    parser.add_argument("--count", type=int, default=8192)
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--max-run", type=int, default=3)
    parser.add_argument("--min-weight", type=int)
    parser.add_argument("--max-weight", type=int)
    parser.add_argument("--min-distance", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ordering-pool", type=int, default=32)
    parser.add_argument("--repair-target", type=int, default=5)
    parser.add_argument("--repair-iterations", type=int, default=200_000)
    parser.add_argument("--distance-samples", type=int, default=100_000)
    parser.add_argument("--show", type=int, default=8)
    parser.add_argument("--output", type=Path, help="optional generated codebook CSV")
    args = parser.parse_args()

    if not 1 <= args.window <= args.width:
        parser.error("--window must be between 1 and --width")
    if args.width > 24:
        parser.error("exhaustive enumeration is intentionally limited to width <= 24")

    min_weight = args.min_weight if args.min_weight is not None else args.width * 2 // 5
    max_weight = args.max_weight if args.max_weight is not None else args.width - min_weight

    print(f"Enumerating constrained {args.width}-bit words...")
    candidates = enumerate_candidates(args.width, min_weight, max_weight, args.max_run)
    print(f"Candidates:              {len(candidates):,}")
    print(f"Selecting distance-{args.min_distance} code with seed {args.seed}...")
    codes = select_distance_code(
        candidates, args.count, args.width, args.min_distance, args.seed
    )
    codes = order_physical_ids(codes, args.width, args.window, args.ordering_pool)
    before_repair = min(
        minimum_window_distance(codes[i], codes[i + 1], args.window, args.width)
        for i in range(len(codes) - 1)
    )
    codes, accepted_swaps, remaining_bad = repair_physical_order(
        codes,
        args.width,
        args.window,
        args.repair_target,
        args.repair_iterations,
        args.seed,
    )
    print(
        f"Order repair:           min {before_repair}, accepted {accepted_swaps:,}, "
        f"remaining below {args.repair_target}: {remaining_bad:,}"
    )

    weights = [code.bit_count() for code in codes]
    runs = [cyclic_max_run(code, args.width) for code in codes]
    transitions = [cyclic_transitions(code, args.width) for code in codes]
    print(f"Selected codes:          {len(codes):,}")
    print(f"Weight range:            {min(weights)}..{max(weights)}")
    print(f"Cyclic max-run range:    {min(runs)}..{max(runs)}")
    print(f"Per-code transitions:    {min(transitions)}..{max(transitions)}")

    adjacent_aligned = [(codes[i] ^ codes[i + 1]).bit_count() for i in range(len(codes) - 1)]
    adjacent_windows = [
        minimum_window_distance(codes[i], codes[i + 1], args.window, args.width)
        for i in range(len(codes) - 1)
    ]
    print(f"Adjacent-ID aligned distance:       {min(adjacent_aligned)}..{max(adjacent_aligned)}")
    print(
        f"Adjacent-ID min {args.window}-window distance: "
        f"{min(adjacent_windows)}..{max(adjacent_windows)}"
    )

    window_stats = short_window_stats(codes, args.width, args.window)
    print(f"{args.window}-bit window largest bucket:       {max(x[1] for x in window_stats)}")
    print(
        f"{args.window}-bit window ambiguous IDs:        "
        f"{min(x[2] for x in window_stats):,}..{max(x[2] for x in window_stats):,}"
    )
    rates = transition_rates(codes, args.width)
    print(f"Population transition rate:         {min(rates):.3f}..{max(rates):.3f}")
    wrong_phase = wrong_phase_exact_rates(codes, args.width)
    print(
        f"Wrong-phase exact-valid fraction:   "
        f"{min(wrong_phase):.4f}..{max(wrong_phase):.4f}"
    )

    histogram = sampled_aligned_distances(codes, args.distance_samples, args.seed)
    print("Sampled aligned-distance histogram:")
    for distance in sorted(histogram):
        print(f"  {distance:2d}: {histogram[distance]:,}")
    print("Example codes:")
    for led_id, code in enumerate(codes[: args.show]):
        print(f"  {led_id:4d}: {bits(code, args.width)}")

    assert len(codes) == len(set(codes)) == args.count
    assert all(cyclic_max_run(code, args.width) <= args.max_run for code in codes)
    assert all(min_weight <= code.bit_count() <= max_weight for code in codes)
    assert min(adjacent_aligned) >= args.min_distance
    print("Hard-constraint sanity checks: PASS")
    if args.output:
        write_csv(args.output, codes, args.width)
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
