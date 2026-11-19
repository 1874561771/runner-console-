from app.db.migrate import discover_migrations, split_statements


def test_migrations_are_unique_and_ordered():
    migrations = discover_migrations()
    versions = [version for version, _name, _path in migrations]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[-1] >= 3


def test_split_statements_ignores_comment_only_chunks():
    sql = """
    -- comment
    CREATE TABLE example (id INT);
    -- another comment
    INSERT INTO example (id) VALUES (1);
    """

    statements = split_statements(sql)

    assert len(statements) == 2
    assert "CREATE TABLE example" in statements[0]
    assert "INSERT INTO example" in statements[1]
