from aut.suite import run_combination


def test_push_pull(suite, ctx, combo):
    fmt, repo_type = combo
    run_combination(ctx, suite.adapters[fmt], repo_type)
