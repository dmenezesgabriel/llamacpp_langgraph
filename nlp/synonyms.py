"""
Domain synonym map: user vocabulary → canonical schema term.
Keys are lower-cased query words; values are exact column or table names.
"""

SYNONYMS: dict[str, str] = {
    # nyc_taxi
    "fare": "fare_amount",
    "tip": "tip_amount",
    "toll": "tolls_amount",
    "total": "total_amount",
    "payment": "payment_type",
    "pickup": "tpep_pickup_datetime",
    "dropoff": "tpep_dropoff_datetime",
    "distance": "trip_distance",
    "mile": "trip_distance",
    "passenger": "passenger_count",
    "vendor": "VendorID",
    "taxi": "nyc_taxi",
    "trip": "nyc_taxi",
    "ride": "nyc_taxi",
    # seattle_weather
    "rain": "weather",
    "rainy": "weather",
    "temperature": "temp_max",
    "temp": "temp_max",
    "precipitation": "precipitation",
    "wind": "wind",
    "seattle": "seattle_weather",
    "weather": "seattle_weather",
    # movies
    "movie": "movies",
    "film": "movies",
    "rating": "IMDB Rating",
    "imdb": "IMDB Rating",
    "gross": "Worldwide Gross",
    "budget": "Production Budget",
    "genre": "Major Genre",
    "director": "Director",
    "score": "Rotten Tomatoes Rating",
    # cars
    "car": "cars",
    "vehicle": "cars",
    "mpg": "Miles_per_Gallon",
    "horsepower": "Horsepower",
    "cylinder": "Cylinders",
    "origin": "Origin",
    "hp": "Horsepower",
}
