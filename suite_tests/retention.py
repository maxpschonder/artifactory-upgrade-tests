from aut.suite import verify_entry


def test_old_artifact(suite, ctx, old_entry):
    verify_entry(ctx, suite.adapters[old_entry["format"]], old_entry)
