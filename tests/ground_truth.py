"""
Ground truth validation script.
Loads all datasets and runs the exact SQL queries we expect the agent to answer,
producing authoritative reference answers to compare against agent outputs.
"""

from __future__ import annotations

import json
import sys
from db.loader import get_connection

conn = get_connection()

GROUND_TRUTH_QUERIES = [
    # ── Q1: table listing ───────────────────────────────────────────────────
    {
        "id": "Q1",
        "question": "What datasets / tables do you have available?",
        "sql": "SHOW TABLES",
        "description": "List all tables",
    },
    # ── Q2: nyc_taxi schema ─────────────────────────────────────────────────
    {
        "id": "Q2",
        "question": "What columns are in the nyc_taxi table?",
        "sql": "DESCRIBE nyc_taxi",
        "description": "Schema of nyc_taxi",
    },
    # ── Q3: 7-day rolling average of daily trips ────────────────────────────
    {
        "id": "Q3",
        "question": "Calculate the 7-day rolling average of daily trips in the NYC taxi dataset. Return the pickup date and the rolling average.",
        "sql": """
            WITH daily AS (
                SELECT CAST(pickup_at AS DATE) as date, COUNT(*) as daily_trips
                FROM nyc_taxi
                GROUP BY 1
            )
            SELECT 
                date, 
                ROUND(AVG(daily_trips) OVER (
                    ORDER BY date 
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ), 2) as rolling_avg_7d
            FROM daily
            ORDER BY date
            LIMIT 10
        """,
        "description": "7-day rolling average (Window Function)",
    },
    # ── Q4: Anomaly Detection - Tip > Fare ──────────────────────────────────
    {
        "id": "Q4",
        "question": "Identify the percentage of trips in the NYC taxi dataset where the tip amount is strictly greater than the fare amount.",
        "sql": """
            SELECT 
                ROUND(100.0 * SUM(CASE WHEN tip_amount > fare_amount THEN 1 ELSE 0 END) / COUNT(*), 4) as anomaly_pct
            FROM nyc_taxi
        """,
        "description": "Anomaly Detection (Tip > Fare)",
    },
    # ── Q5: Tipping behavior by distance decile ─────────────────────────────
    {
        "id": "Q5",
        "question": "Bucket the NYC taxi trips into deciles by trip_distance. For each decile, calculate the average tip percentage (tip_amount / fare_amount). Exclude trips with zero fare.",
        "sql": """
            WITH deciles AS (
                SELECT 
                    tip_amount,
                    fare_amount,
                    NTILE(10) OVER (ORDER BY trip_distance) as distance_decile
                FROM nyc_taxi
                WHERE fare_amount > 0
            )
            SELECT 
                distance_decile, 
                ROUND(AVG(tip_amount / fare_amount) * 100, 2) as avg_tip_pct
            FROM deciles
            GROUP BY 1
            ORDER BY 1
        """,
        "description": "Cohorts/Deciles Analysis",
    },
    # ── Q6: YoY Growth in Movie Gross ───────────────────────────────────────
    {
        "id": "Q6",
        "question": "Using the movies dataset, calculate the Year-over-Year growth in total 'Worldwide Gross'. Show the year, total gross, and the percentage growth from the previous year. Ignore rows where Release Date or Worldwide Gross is null.",
        "sql": """
            WITH yearly AS (
                SELECT 
                    EXTRACT(YEAR FROM CAST(strptime(regexp_extract("Release Date", '^[A-Za-z]+ \d{2} \d{4}'), '%b %d %Y') AS DATE)) as release_year,
                    SUM("Worldwide Gross") as total_gross
                FROM movies
                WHERE "Release Date" IS NOT NULL AND "Worldwide Gross" IS NOT NULL
                GROUP BY 1
            )
            SELECT 
                release_year,
                total_gross,
                ROUND(100.0 * (total_gross - LAG(total_gross) OVER (ORDER BY release_year)) / LAG(total_gross) OVER (ORDER BY release_year), 2) as yoy_growth_pct
            FROM yearly
            ORDER BY 1
            LIMIT 10
        """,
        "description": "YoY Growth (Window function + Date parsing)",
    },
    # ── Q7: Visualization Data Gathering ────────────────────────────────────
    {
        "id": "Q7",
        "question": "Create a time-series dataset of daily average maximum temperature and total precipitation from the seattle_weather dataset, formatted to be used in a dual-axis chart. Order by date.",
        "sql": """
            SELECT 
                date, 
                ROUND(AVG(temp_max), 2) as avg_temp_max, 
                ROUND(SUM(precipitation), 2) as total_precip
            FROM seattle_weather
            GROUP BY 1
            ORDER BY 1
            LIMIT 10
        """,
        "description": "Data gathering for Dual-axis Time-Series Visualization",
    },
    # ── Q8: Director with highest average IMDB rating ───────────────────────
    {
        "id": "Q8",
        "question": "Find the movie director who has the highest average 'IMDB Rating' among directors who have directed at least 3 movies.",
        "sql": """
            SELECT Director, ROUND(AVG("IMDB Rating"), 2) as avg_rating
            FROM movies
            WHERE Director IS NOT NULL AND "IMDB Rating" IS NOT NULL
            GROUP BY Director
            HAVING COUNT(*) >= 3
            ORDER BY avg_rating DESC
            LIMIT 1
        """,
        "description": "Aggregation with HAVING clause",
    },
    # ── Q9: 90th percentile of fare amount by payment type ──────────────────
    {
        "id": "Q9",
        "question": "Calculate the 90th percentile of fare amounts for each payment type in the NYC taxi data.",
        "sql": """
            SELECT 
                payment_type, 
                ROUND(QUANTILE_CONT(fare_amount, 0.90), 2) as fare_p90
            FROM nyc_taxi
            GROUP BY 1
            ORDER BY 1
        """,
        "description": "Percentiles Calculation",
    },
    # ── Q10: Distribution of Horsepower ─────────────────────────────────────
    {
        "id": "Q10",
        "question": "Calculate the distribution of cars by Horsepower ranges: 0-100, 101-150, 151-200, 201+. Return the range name and the count of cars.",
        "sql": """
            SELECT 
                CASE 
                    WHEN Horsepower <= 100 THEN '0-100'
                    WHEN Horsepower <= 150 THEN '101-150'
                    WHEN Horsepower <= 200 THEN '151-200'
                    ELSE '201+' 
                END as hp_range,
                COUNT(*) as car_count
            FROM cars
            WHERE Horsepower IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """,
        "description": "Custom Binning / Bucketing using CASE",
    },
    # ── Q11: Monthly Retention/Active Days (Proxy) ──────────────────────────
    {
        "id": "Q11",
        "question": "For the seattle_weather dataset, calculate the percentage of days in each month where there was at least some rain (precipitation > 0).",
        "sql": """
            SELECT 
                EXTRACT(YEAR FROM date) as year,
                EXTRACT(MONTH FROM date) as month,
                ROUND(100.0 * SUM(CASE WHEN precipitation > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) as rainy_day_pct
            FROM seattle_weather
            GROUP BY 1, 2
            ORDER BY 1, 2
            LIMIT 10
        """,
        "description": "Monthly Percentage calculation",
    },
    # ── Q12: Longest gap between movies for a director ──────────────────────
    {
        "id": "Q12",
        "question": "Find the director who had the longest gap (in days) between releasing two consecutive movies. Ignore null dates or directors.",
        "sql": """
            WITH dated_movies AS (
                SELECT 
                    Director,
                    CAST(strptime(regexp_extract("Release Date", '^[A-Za-z]+ \d{2} \d{4}'), '%b %d %Y') AS DATE) as release_date
                FROM movies
                WHERE Director IS NOT NULL AND "Release Date" IS NOT NULL
            ),
            gaps AS (
                SELECT 
                    Director, 
                    release_date - LAG(release_date) OVER (PARTITION BY Director ORDER BY release_date) as days_gap
                FROM dated_movies
            )
            SELECT Director, MAX(days_gap) as max_gap
            FROM gaps
            GROUP BY 1
            ORDER BY max_gap DESC NULLS LAST
            LIMIT 1
        """,
        "description": "Complex Window Function (LAG with PARTITION)",
    },
    # ── Q13: Cumulative Sum ─────────────────────────────────────────────────
    {
        "id": "Q13",
        "question": "Calculate the cumulative sum of trips over time (by date) in the NYC taxi dataset.",
        "sql": """
            WITH daily AS (
                SELECT CAST(pickup_at AS DATE) as date, COUNT(*) as daily_trips
                FROM nyc_taxi
                GROUP BY 1
            )
            SELECT 
                date,
                daily_trips,
                SUM(daily_trips) OVER (ORDER BY date) as cumulative_trips
            FROM daily
            ORDER BY 1
            LIMIT 10
        """,
        "description": "Cumulative Sum (Running Total)",
    },
    # ── Q14: Anomalous tip ratios ───────────────────────────────────────────
    {
        "id": "Q14",
        "question": "Identify pickup locations in the NYC taxi dataset where the average tip percentage (tip_amount/fare_amount) is more than 2 standard deviations above the overall average tip percentage. Exclude zero fare trips.",
        "sql": """
            WITH trip_pct AS (
                SELECT pickup_location_id, (tip_amount / fare_amount) as tip_pct
                FROM nyc_taxi
                WHERE fare_amount > 0
            ),
            overall_stats AS (
                SELECT AVG(tip_pct) as overall_avg, STDDEV(tip_pct) as overall_stddev
                FROM trip_pct
            )
            SELECT 
                t.pickup_location_id, 
                AVG(t.tip_pct) as loc_avg_tip_pct
            FROM trip_pct t, overall_stats s
            GROUP BY 1, s.overall_avg, s.overall_stddev
            HAVING AVG(t.tip_pct) > (s.overall_avg + 2 * s.overall_stddev)
            ORDER BY loc_avg_tip_pct DESC
            LIMIT 10
        """,
        "description": "Statistical Anomalies (Z-score proxy)",
    },
    # ── Q15: Complex Join-like (Self Join proxy) ────────────────────────────
    {
        "id": "Q15",
        "question": "In the seattle_weather dataset, find instances where it rained heavily (precipitation > 10) and the very next day had a maximum temperature at least 5 degrees warmer.",
        "sql": """
            WITH daily AS (
                SELECT 
                    date, 
                    precipitation, 
                    temp_max,
                    LEAD(temp_max) OVER (ORDER BY date) as next_day_temp,
                    LEAD(date) OVER (ORDER BY date) as next_day
                FROM seattle_weather
            )
            SELECT date, next_day, precipitation, temp_max, next_day_temp
            FROM daily
            WHERE precipitation > 10 AND next_day_temp >= temp_max + 5
            ORDER BY date
            LIMIT 10
        """,
        "description": "Sequential comparison using LEAD",
    },
]


def run_all() -> None:
    results = []

    print("=" * 70)
    print("  GROUND TRUTH — Direct DuckDB Queries")
    print("=" * 70)

    for q in GROUND_TRUTH_QUERIES:
        print(f"\n{'─'*70}")
        print(f"[{q['id']}] {q['description']}")
        print(f"SQL: {q['sql'].strip()}")
        print("Result:")
        try:
            rel = conn.execute(q["sql"])
            cols = [d[0] for d in rel.description] if rel.description else []
            rows = rel.fetchall()
            results.append({
                "id": q["id"],
                "question": q["question"],
                "sql": q["sql"].strip(),
                "columns": cols,
                "rows": [list(r) for r in rows],
                "error": None,
            })
            # Print table
            if not rows:
                print("  (no rows)")
            else:
                col_w = [len(c) for c in cols]
                for row in rows:
                    for i, v in enumerate(row):
                        col_w[i] = max(col_w[i], len(str(v)))
                header = " | ".join(c.ljust(col_w[i]) for i, c in enumerate(cols))
                sep = "-+-".join("-" * w for w in col_w)
                print(f"  {header}")
                print(f"  {sep}")
                for row in rows:
                    print("  " + " | ".join(str(v).ljust(col_w[i]) for i, v in enumerate(row)))
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "id": q["id"],
                "question": q["question"],
                "sql": q["sql"].strip(),
                "columns": [],
                "rows": [],
                "error": str(e),
            })

    # Save ground truth to JSON for comparison
    import os, json
    out_path = os.path.join(os.path.dirname(__file__), "ground_truth.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\n✅  Ground truth saved to: {out_path}")


if __name__ == "__main__":
    run_all()
