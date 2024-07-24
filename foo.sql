WITH picked AS (
    SELECT
        DATE_TRUNC('sec', updated at time zone 'UTC') AS created,
        entrypoint,
        'picked' as slab,
        status::text,
        count(*) as count
    FROM
        pgqueuer
    WHERE
        status = 'picked'
    GROUP BY
        DATE_TRUNC('sec', updated at time zone 'UTC'), 
        entrypoint,
        slab,
        status
), done AS (
    SELECT
        DATE_TRUNC('sec', created at time zone 'UTC') AS created,
        entrypoint,
        'done' as slab,
        status::text,
        count
    FROM
        pgqueuer_statistics
), combined AS (
    SELECT * FROM picked
    UNION ALL
    SELECT * FROM done
)
SELECT * FROM combined ORDER BY created;

