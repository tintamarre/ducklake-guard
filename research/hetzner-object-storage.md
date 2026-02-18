# Hetzner Object Storage

https://docs.hetzner.com/storage/object-storage/overview/

## Limits

| Resource                          | Limit              |
| --------------------------------- | ------------------ |
| Metadata per object               | 8 kB               |
| Single PUT upload                 | 5 GB               |
| Multi-part upload (per part)      | 5 GB               |
| Multi-part upload (max parts)     | 10,000             |
| Object size                       | 5 TB               |
| Parallel TCP sessions per IP      | 256                |
| Requests per second per IP        | 750                |
| Requests per second per bucket    | 750                |
| Bandwidth per bucket              | 10 Gbit/s          |
| Storage per bucket                | 100 TB             |
| Objects per bucket                | 50,000,000         |
| S3 credentials (across projects)  | 200                |
| Buckets (across projects)         | 100                |

## Access control

Each S3 key pair has full access to every bucket in the same project by default.
To restrict a key, use bucket policies — see [research/s3-access-control.md](s3-access-control.md).
