def solve(start, target, must_contain, forbidden):
    N = start
    f = [0] * (N + 1)  # пути, избегающие forbidden
    g = [0] * (N + 1)  # пути, избегающие forbidden И must_contain
    f[target] = 1
    g[target] = 1

    for v in range(target + 1, N + 1):
        if v == forbidden:
            continue  # остаётся 0
        children = (v - 1, v // 3, v // 4)
        for c in children:
            if c == forbidden or c < target:
                continue
            f[v] += f[c]
        if v == must_contain:
            g[v] = 0  # траектория, проходящая 250, исключается в g
            continue
        for c in children:
            if c == forbidden or c == must_contain or c < target:
                continue
            g[v] += g[c]

    return f[start] - g[start]


if __name__ == "__main__":
    ans = solve(start=2025, target=25, must_contain=250, forbidden=42)
    print(ans)