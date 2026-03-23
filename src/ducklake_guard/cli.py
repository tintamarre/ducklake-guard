from __future__ import annotations

import functools
import subprocess

import click
import psycopg
from psycopg.rows import dict_row

from ducklake_guard.adapter.hetzner import create_s3_client
from ducklake_guard.catalog import create_catalog_role, drop_catalog_role
from ducklake_guard.config import Config
from ducklake_guard.db import create_user as db_create_user
from ducklake_guard.db import delete_grant, get_user, upsert_grant
from ducklake_guard.sync import sync as do_sync
from ducklake_guard.templates import (
    ENV_TEMPLATE,
    INIT_SQL,
    PG_HBA_LINE,
    PG_HBA_PATH,
    SERVER_INIT_SQL,
)
from ducklake_guard.transaction import apply_with_policy_sync


def _connect(config: Config, dbname: str, **kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host=config.postgres_host,
        dbname=dbname,
        user="ducklake",
        password=config.postgres_db_password,
        autocommit=True,
        **kwargs,
    )


def _guard_conn(config: Config) -> psycopg.Connection:
    return _connect(config, "ducklake_guard", row_factory=dict_row)


def _catalog_conn(config: Config) -> psycopg.Connection:
    return _connect(config, "ducklake_catalog")


def _with_resources(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        config = Config.from_env()
        guard = _guard_conn(config)
        catalog = _catalog_conn(config)
        s3 = create_s3_client(config)
        try:
            return f(guard, catalog, s3, config, *args, **kwargs)
        finally:
            guard.close()
            catalog.close()

    return wrapper


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)


@cli.command()
@click.option(
    "--ssh-host",
    envvar="POSTGRES_HOST",
    required=True,
    help="SSH host for remote psql (needs passwordless sudo to postgres)",
)
@click.pass_context
def init(ctx: click.Context, ssh_host: str) -> None:
    def _ssh(cmd: str, stdin: str | None = None) -> str:
        r = subprocess.run(  # noqa: S603
            ["ssh", ssh_host, cmd],  # noqa: S607
            input=stdin,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise click.ClickException(f"ssh command failed:\n{r.stderr.strip()}")
        return r.stdout.strip()

    out = _ssh("sudo -u postgres psql", stdin=SERVER_INIT_SQL)
    click.echo(out)

    hba_check = _ssh(
        f"sudo grep -qF 'ducklake_guard' {PG_HBA_PATH} && echo exists || echo missing"
    )
    if "missing" in hba_check:
        _ssh(f"echo '{PG_HBA_LINE}' | sudo tee -a {PG_HBA_PATH} > /dev/null")
        _ssh("sudo systemctl reload postgresql")
        click.echo("Added pg_hba.conf entry and reloaded PostgreSQL")
    else:
        click.echo("pg_hba.conf entry already present")

    click.echo("Init complete")


@cli.command()
def env() -> None:
    click.echo(ENV_TEMPLATE, nl=False)


@cli.group()
@click.pass_context
def user(ctx: click.Context) -> None:
    pass


@user.command("create")
@click.argument("name")
@click.option("--access-key", required=True, help="Hetzner S3 access key for the user")
@click.option("--project-id", required=True, help="Hetzner project ID for the user")
@_with_resources
def create_user(
    guard,
    catalog,
    s3,
    config: Config,
    name: str,
    access_key: str,
    project_id: str,
) -> None:
    password = create_catalog_role(catalog, name)

    def mutate(cur):
        db_create_user(cur, name, access_key, project_id)
        return {"action": "create", "user_name": name}

    apply_with_policy_sync(guard, catalog, s3, config.s3_bucket_name, mutate)

    init_path = _write_init_sql(name)

    click.echo(click.style(f"Created user '{name}'", fg="green"))
    click.echo(f"  Principal ARN: arn:aws:iam:::user/p{project_id}:{access_key}")
    click.echo(f"  Catalog role: dga_{name}")
    click.echo(
        f"  Catalog password: {click.style(password, fg='bright_white', bold=True)}"
    )
    click.echo("")
    click.echo(
        click.style(
            "  !! Save this password now — it cannot be retrieved later.",
            fg="yellow",
            bold=True,
        )
    )
    click.echo("")
    click.echo(f"  Init file: {init_path}")
    click.echo("  The init file uses getenv() for all secrets.")
    click.echo(
        f"  Set {click.style('S3_ACCESS_KEY', bold=True)}, "
        f"{click.style('S3_SECRET_KEY', bold=True)}, and "
        f"{click.style('DGA_CATALOG_PASSWORD', bold=True)}"
    )
    click.echo("  in the user's environment before connecting.")


def _write_init_sql(name: str) -> str:
    from pathlib import Path

    content = INIT_SQL.substitute(name=name)
    path = Path(f"init-{name}.sql")
    path.write_text(content)
    return str(path)


@user.command("delete")
@click.argument("name")
@_with_resources
def delete_user(guard, catalog, s3, config: Config, name: str) -> None:
    with guard.transaction():
        cur = guard.cursor()
        existing = get_user(cur, name)

    if existing is None:
        raise click.ClickException(f"User '{name}' not found")

    def mutate(cur):
        cur.execute("DELETE FROM grants WHERE user_name = %s", [name])
        cur.execute("DELETE FROM users WHERE name = %s", [name])
        return {"action": "delete", "user_name": name}

    apply_with_policy_sync(guard, catalog, s3, config.s3_bucket_name, mutate)
    drop_catalog_role(catalog, name)

    click.echo(click.style(f"Deleted user '{name}'", fg="green"))
    click.echo(
        click.style(
            "  Remember to delete the S3 credential in the Hetzner Console.",
            fg="yellow",
            bold=True,
        )
    )


@cli.command()
@click.argument("user_name")
@click.option("--table", required=True, help="Table name to grant access to")
@click.option(
    "--read-only", "permission", flag_value="read_only", help="Grant read-only access"
)
@click.option(
    "--read-write",
    "permission",
    flag_value="read_write",
    help="Grant read-write access",
)
@_with_resources
def allow(
    guard,
    catalog,
    s3,
    config: Config,
    user_name: str,
    table: str,
    permission: str | None,
) -> None:
    if permission is None:
        raise click.ClickException("Specify --read-only or --read-write")

    def mutate(cur):
        if get_user(cur, user_name) is None:
            raise click.ClickException(f"User '{user_name}' not found")
        upsert_grant(cur, user_name, table, permission)
        return {
            "action": "allow",
            "user_name": user_name,
            "detail": {"table": table, "permission": permission},
        }

    apply_with_policy_sync(guard, catalog, s3, config.s3_bucket_name, mutate)
    click.echo(
        click.style(f"Granted {permission} on '{table}' to '{user_name}'", fg="green")
    )


@cli.command()
@click.argument("user_name")
@click.option("--table", required=True, help="Table name to revoke access from")
@_with_resources
def deny(guard, catalog, s3, config: Config, user_name: str, table: str) -> None:
    def mutate(cur):
        if get_user(cur, user_name) is None:
            raise click.ClickException(f"User '{user_name}' not found")
        rows = delete_grant(cur, user_name, table)
        if rows == 0:
            raise click.ClickException(f"No grant for '{user_name}' on '{table}'")
        return {
            "action": "deny",
            "user_name": user_name,
            "detail": {"table": table},
        }

    apply_with_policy_sync(guard, catalog, s3, config.s3_bucket_name, mutate)
    click.echo(
        click.style(f"Revoked access on '{table}' from '{user_name}'", fg="green")
    )


@cli.command()
@_with_resources
def sync(guard, catalog, s3, config: Config) -> None:
    result = do_sync(guard, catalog, s3, config.s3_bucket_name)
    if result["s3_changed"]:
        click.echo("S3 policy updated")
    else:
        click.echo("S3 policy already in sync")

    if result["rls_changed"]:
        click.echo("RLS policies updated")
    else:
        click.echo("RLS policies already in sync")
