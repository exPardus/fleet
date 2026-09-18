# `bench-template/` is a deliberately broken task: its tests are meant to FAIL
# until a finger model fixes the three planted bugs, so the repository's own
# pytest run must never collect them. `bench-out/` holds one regenerable copy
# per benchmarked model and is ignored by git for the same reason.
collect_ignore_glob = ["bench-template/*", "bench-out/*"]
