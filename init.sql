INSTALL ducklake;
INSTALL postgres;

CREATE OR REPLACE SECRET s3_secret (
    TYPE s3,
    PROVIDER config,
    ENDPOINT getenv('S3_ENDPOINT'),
    KEY_ID getenv('S3_ACCESS_KEY'),
    SECRET getenv('S3_SECRET_KEY'),
    REGION getenv('S3_REGION'),
    URL_STYLE 'path',
    USE_SSL CAST(getenv('S3_USE_SSL') AS BOOLEAN)
);

CREATE OR REPLACE SECRET postgres_secret (
    TYPE postgres,
    HOST getenv('POSTGRES_HOST'),
    PORT 5432,
    DATABASE ducklake_catalog,
    USER 'ducklake',
    PASSWORD getenv('POSTGRES_DB_PASSWORD')
);

CREATE SECRET ducklake_secret (
    TYPE ducklake,
    METADATA_PATH '',
    DATA_PATH getenv('S3_DATA_PATH'),
    METADATA_PARAMETERS MAP {'TYPE': 'postgres', 'SECRET': 'postgres_secret'}
);

ATTACH 'ducklake:ducklake_secret' AS ducklake;
USE ducklake;
SELECT 'DuckLake is ready' as status;
