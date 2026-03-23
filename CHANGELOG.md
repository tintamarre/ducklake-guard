# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - 2026-03-23

### Added

- `dga init` — create guard database, schema, pg_hba entry, enable RLS
- `dga user create` / `dga user delete` — register and remove users with S3 credentials and catalog roles
- `dga allow` / `dga deny` — grant and revoke per-table read-only or read-write access
- `dga sync` — converge S3 bucket policies and RLS to match grant state
- `dga env` — generate a `.env` template for configuration
- Hetzner Object Storage adapter
- Audit log for all policy changes

[0.1.0]: https://github.com/berndsen-io/ducklake-guard/releases/tag/v0.1.0
