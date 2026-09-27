"""Line counts for recorded unified diffs."""


def count_diff_lines(diff: str) -> tuple[int, int]:
    """Count changed lines, excluding unified-diff file headers."""
    additions = 0
    deletions = 0
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("@@ "):
            in_hunk = True
            continue
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        if not in_hunk and (line.startswith("+++ ") or line.startswith("--- ")):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions
