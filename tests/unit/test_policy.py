from __future__ import annotations

from ducklake_guard.policy import build_policy, build_principal, normalize_policy

BUCKET = "test-bucket"


def _users(*names: str) -> dict[str, dict[str, str]]:
    return {
        n: {
            "name": n,
            "access_key": f"key-{n}",
            "project_id": f"proj-{n}",
            "principal_arn": f"arn:aws:iam:::user/pproj-{n}:key-{n}",
        }
        for n in names
    }


def _grant(user: str, table: str, perm: str = "read_only") -> dict[str, str]:
    return {"user_name": user, "table_name": table, "permission": perm}


class TestBuildPrincipal:
    def test_arn_format(self):
        result = build_principal("AKID123", "abc-def")
        assert result == "arn:aws:iam:::user/pabc-def:AKID123"


class TestBuildPolicyEmpty:
    def test_empty_grants_returns_empty_statements(self):
        policy = build_policy([], {}, BUCKET)
        assert policy == {"Version": "2012-10-17", "Statement": []}


class TestBuildPolicySingleUserReadOnly:
    def test_read_only_produces_three_statements(self):
        grants = [_grant("alice", "orders")]
        users = _users("alice")
        policy = build_policy(grants, users, BUCKET)

        stmts = policy["Statement"]
        assert len(stmts) == 3

        sids = [s["Sid"] for s in stmts]
        assert "AllowGetBucketLocation-alice" in sids
        assert "AllowListPrefix-alice" in sids
        assert "AllowGetObject-alice" in sids

    def test_read_only_get_object_resource(self):
        grants = [_grant("alice", "orders")]
        users = _users("alice")
        policy = build_policy(grants, users, BUCKET)

        get_obj = [s for s in policy["Statement"] if "GetObject" in s["Sid"]][0]
        assert get_obj["Resource"] == [f"arn:aws:s3:::{BUCKET}/main/orders/*"]

    def test_read_only_principal(self):
        grants = [_grant("alice", "orders")]
        users = _users("alice")
        policy = build_policy(grants, users, BUCKET)

        for stmt in policy["Statement"]:
            assert stmt["Principal"]["AWS"] == users["alice"]["principal_arn"]


class TestBuildPolicySingleUserReadWrite:
    def test_read_write_produces_five_statements(self):
        grants = [_grant("bob", "events", "read_write")]
        users = _users("bob")
        policy = build_policy(grants, users, BUCKET)

        stmts = policy["Statement"]
        assert len(stmts) == 5

        sids = [s["Sid"] for s in stmts]
        assert "AllowPutObject-bob" in sids
        assert "AllowDeleteObject-bob" in sids

    def test_write_resources_match_table(self):
        grants = [_grant("bob", "events", "read_write")]
        users = _users("bob")
        policy = build_policy(grants, users, BUCKET)

        put = [s for s in policy["Statement"] if "PutObject" in s["Sid"]][0]
        delete = [s for s in policy["Statement"] if "DeleteObject" in s["Sid"]][0]
        expected = [f"arn:aws:s3:::{BUCKET}/main/events/*"]
        assert put["Resource"] == expected
        assert delete["Resource"] == expected


class TestBuildPolicyMixedPermissions:
    def test_mixed_permissions_bundling(self):
        grants = [
            _grant("carol", "orders", "read_only"),
            _grant("carol", "events", "read_write"),
        ]
        users = _users("carol")
        policy = build_policy(grants, users, BUCKET)

        get_obj = [s for s in policy["Statement"] if "GetObject" in s["Sid"]][0]
        assert len(get_obj["Resource"]) == 2
        assert f"arn:aws:s3:::{BUCKET}/main/events/*" in get_obj["Resource"]
        assert f"arn:aws:s3:::{BUCKET}/main/orders/*" in get_obj["Resource"]

        put = [s for s in policy["Statement"] if "PutObject" in s["Sid"]][0]
        assert put["Resource"] == [f"arn:aws:s3:::{BUCKET}/main/events/*"]

    def test_list_prefix_contains_all_tables(self):
        grants = [
            _grant("carol", "orders", "read_only"),
            _grant("carol", "events", "read_write"),
        ]
        users = _users("carol")
        policy = build_policy(grants, users, BUCKET)

        list_stmt = [s for s in policy["Statement"] if "ListPrefix" in s["Sid"]][0]
        prefixes = list_stmt["Condition"]["StringLike"]["s3:prefix"]
        assert "main/events/*" in prefixes
        assert "main/orders/*" in prefixes


class TestBuildPolicyMultipleUsers:
    def test_statements_sorted_by_user(self):
        grants = [
            _grant("zara", "t1"),
            _grant("alice", "t2"),
        ]
        users = _users("zara", "alice")
        policy = build_policy(grants, users, BUCKET)

        sids = [s["Sid"] for s in policy["Statement"]]
        alice_idx = next(i for i, s in enumerate(sids) if "alice" in s)
        zara_idx = next(i for i, s in enumerate(sids) if "zara" in s)
        assert alice_idx < zara_idx

    def test_correct_principals_per_user(self):
        grants = [
            _grant("alice", "t1"),
            _grant("bob", "t2"),
        ]
        users = _users("alice", "bob")
        policy = build_policy(grants, users, BUCKET)

        for stmt in policy["Statement"]:
            if "alice" in stmt["Sid"]:
                assert stmt["Principal"]["AWS"] == users["alice"]["principal_arn"]
            elif "bob" in stmt["Sid"]:
                assert stmt["Principal"]["AWS"] == users["bob"]["principal_arn"]


class TestUpsertSemantics:
    def test_last_grant_wins_for_same_user_table(self):
        grants = [
            _grant("alice", "orders", "read_only"),
            _grant("alice", "orders", "read_write"),
        ]
        users = _users("alice")

        deduped: dict[tuple[str, str], dict[str, str]] = {}
        for g in grants:
            deduped[(g["user_name"], g["table_name"])] = g
        final_grants = list(deduped.values())

        policy = build_policy(final_grants, users, BUCKET)
        assert len(policy["Statement"]) == 5


class TestSidPattern:
    def test_sid_follows_pattern(self):
        grants = [_grant("alice", "t", "read_write")]
        users = _users("alice")
        policy = build_policy(grants, users, BUCKET)

        expected_sids = {
            "AllowGetBucketLocation-alice",
            "AllowListPrefix-alice",
            "AllowGetObject-alice",
            "AllowPutObject-alice",
            "AllowDeleteObject-alice",
        }
        actual_sids = {s["Sid"] for s in policy["Statement"]}
        assert actual_sids == expected_sids


class TestNormalizePolicy:
    def test_sorts_statements_by_sid(self):
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Sid": "Z-stmt", "Action": "s3:GetObject"},
                {"Sid": "A-stmt", "Action": "s3:PutObject"},
            ],
        }
        result = normalize_policy(policy)
        assert result["Statement"][0]["Sid"] == "A-stmt"
        assert result["Statement"][1]["Sid"] == "Z-stmt"

    def test_sorts_resource_list(self):
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Sid": "s1", "Resource": ["arn:z", "arn:a", "arn:m"]},
            ],
        }
        result = normalize_policy(policy)
        assert result["Statement"][0]["Resource"] == ["arn:a", "arn:m", "arn:z"]

    def test_sorts_action_list(self):
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Sid": "s1", "Action": ["s3:PutObject", "s3:GetObject"]},
            ],
        }
        result = normalize_policy(policy)
        assert result["Statement"][0]["Action"] == ["s3:GetObject", "s3:PutObject"]

    def test_sorts_condition_arrays(self):
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "s1",
                    "Condition": {
                        "StringLike": {"s3:prefix": ["z/*", "a/*"]},
                    },
                },
            ],
        }
        result = normalize_policy(policy)
        prefixes = result["Statement"][0]["Condition"]["StringLike"]["s3:prefix"]
        assert prefixes == ["a/*", "z/*"]

    def test_preserves_version(self):
        policy = {"Version": "custom-ver", "Statement": []}
        result = normalize_policy(policy)
        assert result["Version"] == "custom-ver"

    def test_default_version_when_missing(self):
        policy = {"Statement": []}
        result = normalize_policy(policy)
        assert result["Version"] == "2012-10-17"
