from kdp_pipeline.core.ids import new_id


def test_ids_are_prefixed_and_unique():
    ids = {new_id("AST") for _ in range(100)}
    assert len(ids) == 100
    assert all(value.startswith("AST-") for value in ids)
