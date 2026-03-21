from __future__ import annotations

from typing import Any

READ_ACTIONS = ["s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject"]
WRITE_ACTIONS = ["s3:PutObject", "s3:DeleteObject"]


def build_principal(access_key: str, project_id: str) -> str:
    return f"arn:aws:iam:::user/p{project_id}:{access_key}"


def build_policy(
    grants: list[dict[str, str]],
    users: dict[str, dict[str, str]],
    bucket: str,
) -> dict[str, Any]:
    if not grants:
        return {"Version": "2012-10-17", "Statement": []}

    user_grants: dict[str, list[dict[str, str]]] = {}
    for g in grants:
        user_grants.setdefault(g["user_name"], []).append(g)

    statements: list[dict[str, Any]] = []

    for user_name in sorted(user_grants):
        user_info = users[user_name]
        principal = user_info["principal_arn"]
        user_table_grants = user_grants[user_name]

        all_prefixes = sorted(f"main/{g['table_name']}/*" for g in user_table_grants)
        write_prefixes = sorted(
            f"main/{g['table_name']}/*"
            for g in user_table_grants
            if g["permission"] == "read_write"
        )

        bucket_arn = f"arn:aws:s3:::{bucket}"

        statements.append(
            {
                "Sid": f"AllowGetBucketLocation-{user_name}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetBucketLocation",
                "Resource": bucket_arn,
            }
        )

        statements.append(
            {
                "Sid": f"AllowListPrefix-{user_name}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:ListBucket",
                "Resource": bucket_arn,
                "Condition": {
                    "StringLike": {"s3:prefix": all_prefixes},
                },
            }
        )

        statements.append(
            {
                "Sid": f"AllowGetObject-{user_name}",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "s3:GetObject",
                "Resource": [f"{bucket_arn}/{p}" for p in all_prefixes],
            }
        )

        if write_prefixes:
            statements.append(
                {
                    "Sid": f"AllowPutObject-{user_name}",
                    "Effect": "Allow",
                    "Principal": {"AWS": principal},
                    "Action": "s3:PutObject",
                    "Resource": [f"{bucket_arn}/{p}" for p in write_prefixes],
                }
            )

            statements.append(
                {
                    "Sid": f"AllowDeleteObject-{user_name}",
                    "Effect": "Allow",
                    "Principal": {"AWS": principal},
                    "Action": "s3:DeleteObject",
                    "Resource": [f"{bucket_arn}/{p}" for p in write_prefixes],
                }
            )

    return {"Version": "2012-10-17", "Statement": statements}


def normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    statements = []
    for stmt in policy.get("Statement", []):
        normalized = dict(stmt)
        for key in ("Resource", "Action"):
            if key in normalized and isinstance(normalized[key], list):
                normalized[key] = sorted(normalized[key])
        if "Condition" in normalized:
            cond = normalized["Condition"]
            for op in cond:
                for ck in cond[op]:
                    if isinstance(cond[op][ck], list):
                        cond[op][ck] = sorted(cond[op][ck])
        statements.append(normalized)
    statements.sort(key=lambda s: s.get("Sid", ""))
    return {"Version": policy.get("Version", "2012-10-17"), "Statement": statements}
