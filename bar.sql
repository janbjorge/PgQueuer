WITH MovingAverageStatistics AS (
    SELECT 
        AVG(count) AS avg_throughput
    FROM 
        pgqueuer_statistics
    WHERE 
        created >= NOW() - INTERVAL '1 hour'
),
MovingAveragePicked AS (
    SELECT 
        COUNT(*) AS avg_throughput -- Assuming the interval is 1 hour and you want to convert it to minutes.
    FROM 
        pgqueuer
    WHERE 
        status = 'picked' AND updated >= NOW() - INTERVAL '1 hour'
)
SELECT 
    s.avg_throughput AS statistics_throughput,
    p.avg_throughput AS picked_throughput
FROM 
    MovingAverageStatistics s,
    MovingAveragePicked p;
