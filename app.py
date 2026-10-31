import streamlit as st
import pandas as pd
import mysql.connector
import plotly.express as px

# =====================================================
# 1. PAGE CONFIGURATION AND THEME
# =====================================================

st.set_page_config(
    page_title="TMDB Reel Insights",
    page_icon="🎬",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background-color: #0E111B;
}
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1500px;
}
[data-testid="stSidebar"] {
    background-color: #191D2B;
}
[data-testid="stMetric"] {
    background-color: #191D2B;
    border: 1px solid #292D40;
    padding: 16px;
    border-radius: 12px;
}
[data-testid="stMetricLabel"] {
    color: #B8BBD0;
}
[data-testid="stMetricValue"] {
    color: #FFFFFF;
    font-weight: 700;
}
h1, h2, h3 {
    color: #FFFFFF !important;
}
.stButton > button {
    border-radius: 8px;
    min-height: 52px;
}
</style>
""", unsafe_allow_html=True)


# =====================================================
# 2. HEADER
# =====================================================

st.markdown(
    "<h1 style='color:#784BFF;'>🎬 TMDB REEL INSIGHTS</h1>",
    unsafe_allow_html=True
)
st.caption("Explore • Analyse • Discover Movie Industry Insights")


# =====================================================
# 3. DATABASE HELPERS
# =====================================================

def get_connection():
    """Create a MySQL connection using .streamlit/secrets.toml."""
    return mysql.connector.connect(
        host=st.secrets["mysql"]["host"],
        user=st.secrets["mysql"]["user"],
        password=st.secrets["mysql"]["password"],
        database=st.secrets["mysql"]["database"]
    )


def read_sql(query, params=None):
    """Run a SELECT query and always close its database connection."""
    connection = get_connection()
    try:
        return pd.read_sql(query, connection, params=params)
    finally:
        connection.close()


def fetch_one(query, params=None):
    """Run a query that returns one row and close its connection."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(query, params or [])
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


# =====================================================
# 4. FILTER OPTION FUNCTIONS
# =====================================================

def get_genres():
    df = read_sql(
        "SELECT genre_name FROM genres ORDER BY genre_name"
    )
    return df["genre_name"].dropna().tolist()


def get_year_range():
    result = fetch_one("""
        SELECT MIN(YEAR(release_date)), MAX(YEAR(release_date))
        FROM movies
        WHERE release_date IS NOT NULL
    """)
    if not result or result[0] is None or result[1] is None:
        return 1900, 2030
    return int(result[0]), int(result[1])


def get_languages():
    df = read_sql("""
        SELECT DISTINCT original_language
        FROM movies
        WHERE original_language IS NOT NULL
        ORDER BY original_language
    """)
    return df["original_language"].dropna().tolist()


# =====================================================
# 5. COMMON FILTER BUILDER
# =====================================================

def build_filter_query(alias="m"):
    conditions = [
        f"YEAR({alias}.release_date) BETWEEN %s AND %s",
        f"{alias}.vote_average >= %s"
    ]
    params = [
        selected_years[0],
        selected_years[1],
        minimum_rating
    ]

    if selected_language != "All":
        conditions.append(f"{alias}.original_language = %s")
        params.append(selected_language)

    if selected_genres:
        placeholders = ",".join(["%s"] * len(selected_genres))
        conditions.append(f"""
            EXISTS (
                SELECT 1
                FROM movie_genres mg_filter
                INNER JOIN genres g_filter
                    ON mg_filter.genre_id = g_filter.genre_id
                WHERE mg_filter.movie_id = {alias}.movie_id
                  AND g_filter.genre_name IN ({placeholders})
            )
        """)
        params.extend(selected_genres)

    return " AND ".join(conditions), params


# =====================================================
# 6. FILTERED KPI AND MOVIE COUNT
# =====================================================

def get_filtered_kpis():
    where_clause, params = build_filter_query("m")
    query = f"""
        WITH filtered_movies AS (
            SELECT m.*
            FROM movies m
            WHERE {where_clause}
        )
        SELECT
            (SELECT COUNT(*) FROM filtered_movies),
            (SELECT COUNT(DISTINCT mg.genre_id)
             FROM movie_genres mg
             INNER JOIN filtered_movies fm
                ON fm.movie_id = mg.movie_id),
            (SELECT COUNT(DISTINCT c.actor_name)
             FROM `cast` c
             INNER JOIN filtered_movies fm
                ON fm.movie_id = c.movie_id
             WHERE c.actor_name IS NOT NULL),
            (SELECT ROUND(AVG(vote_average), 2)
             FROM filtered_movies
             WHERE vote_count > 0)
    """
    return fetch_one(query, params)


def get_filtered_movie_count():
    where_clause, params = build_filter_query("m")
    result = fetch_one(
        f"SELECT COUNT(DISTINCT m.movie_id) FROM movies m WHERE {where_clause}",
        params
    )
    return result[0] if result else 0

def get_filtered_movies():

    where_clause, params = build_filter_query("m")

    query = f"""
        SELECT
            m.title,
            YEAR(m.release_date) AS release_year,
            m.vote_average AS rating,
            m.original_language AS language
        FROM movies m
        WHERE {where_clause}
        ORDER BY m.vote_average DESC
    """

    return read_sql(query, params)


# =====================================================
# 7. VISUALIZATION DATA FUNCTIONS
# =====================================================

def get_movies_by_year():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT YEAR(m.release_date) AS release_year,
               COUNT(*) AS movie_count
        FROM movies m
        WHERE {where_clause}
        GROUP BY YEAR(m.release_date)
        ORDER BY release_year
    """, params)


def get_genre_distribution():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT g.genre_name,
               COUNT(DISTINCT m.movie_id) AS movie_count
        FROM movies m
        INNER JOIN movie_genres mg ON m.movie_id = mg.movie_id
        INNER JOIN genres g ON mg.genre_id = g.genre_id
        WHERE {where_clause}
        GROUP BY g.genre_id, g.genre_name
        ORDER BY movie_count DESC
    """, params)


def get_average_revenue_by_genre():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT g.genre_name,
               ROUND(AVG(NULLIF(m.revenue, 0)), 2) AS avg_revenue
        FROM movies m
        INNER JOIN movie_genres mg ON m.movie_id = mg.movie_id
        INNER JOIN genres g ON mg.genre_id = g.genre_id
        WHERE {where_clause}
        GROUP BY g.genre_id, g.genre_name
        HAVING COUNT(DISTINCT CASE WHEN m.revenue > 0
                                   THEN m.movie_id END) > 0
        ORDER BY avg_revenue DESC
    """, params)


def get_budget_revenue():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.title, m.budget, m.revenue, m.vote_average
        FROM movies m
        WHERE {where_clause}
          AND m.budget > 0
          AND m.revenue > 0
    """, params)


def get_top_revenue_movies():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.title, m.revenue
        FROM movies m
        WHERE {where_clause}
          AND m.revenue > 0
        ORDER BY m.revenue DESC
        LIMIT 10
    """, params)


def get_top_actors():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT c.actor_name,
               COUNT(DISTINCT m.movie_id) AS movie_count
        FROM movies m
        INNER JOIN `cast` c ON m.movie_id = c.movie_id
        WHERE {where_clause}
          AND c.actor_name IS NOT NULL
        GROUP BY c.actor_name
        ORDER BY movie_count DESC
        LIMIT 10
    """, params)


def get_ratings_distribution():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.vote_average
        FROM movies m
        WHERE {where_clause}
          AND m.vote_count > 0
    """, params)


def get_runtime_distribution():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.runtime
        FROM movies m
        WHERE {where_clause}
          AND m.runtime > 0
    """, params)


def get_popularity_vote_data():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.title, m.popularity, m.vote_count, m.vote_average
        FROM movies m
        WHERE {where_clause}
          AND m.popularity > 0
          AND m.vote_count > 0
    """, params)


def get_top_profitable_movies():
    where_clause, params = build_filter_query("m")
    return read_sql(f"""
        SELECT m.title,
               m.budget,
               m.revenue,
               (m.revenue - m.budget) AS profit
        FROM movies m
        WHERE {where_clause}
          AND m.budget > 0
          AND m.revenue > 0
        ORDER BY profit DESC
        LIMIT 10
    """, params)


# =====================================================
# 8. SIDEBAR FILTERS
# =====================================================

st.sidebar.title("🎬 Movie Filters")

try:
    genres = get_genres()
    min_year, max_year = get_year_range()
    languages = get_languages()
except Exception as error:
    st.error(f"Could not load filter options from MySQL: {error}")
    st.stop()

selected_genres = st.sidebar.multiselect(
    "Select Genre",
    options=genres,
    key="selected_genres"
)

selected_years = st.sidebar.slider(
    "Release Year Range",
    min_value=min_year,
    max_value=max_year,
    value=(min_year, max_year),
    key="selected_years"
)

minimum_rating = st.sidebar.slider(
    "Minimum Rating",
    min_value=0.0,
    max_value=10.0,
    value=0.0,
    step=0.5,
    key="minimum_rating"
)

selected_language = st.sidebar.selectbox(
    "Select Language",
    options=["All"] + languages,
    key="selected_language"
)

try:
    filtered_count = get_filtered_movie_count()
    st.sidebar.divider()
    st.sidebar.metric("Matching Movies", f"{filtered_count:,}")
except Exception as error:
    st.sidebar.error(f"Could not calculate matching movies: {error}")


# =====================================================
# 9. NAVIGATION
# =====================================================

overview_tab, revenue_tab, query_tab = st.tabs([
    "🎬 Dashboard",
    "📈 Visuals",
    "💻 Query Explorer"
])


# =====================================================
# 10. OVERVIEW TAB
# =====================================================

with overview_tab:
    st.subheader("📊 Movie Analytics Overview")

    try:
        kpis = get_filtered_kpis()
        total_movies, total_genres, total_actors, average_rating = kpis

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Movies", f"{total_movies:,}")

        with col2:
            st.metric("Total Genres", f"{total_genres:,}")

        with col3:
            st.metric("Total Actors", f"{total_actors:,}")

        with col4:
            st.metric(
                "Average Rating",
                f"{average_rating}/10" if average_rating is not None else "N/A"
            )

                # Matching Movies
        st.markdown("### 🎬 Movies Matching Selected Filters")

        movie_list = get_filtered_movies()

        if not movie_list.empty:

            st.dataframe(
                movie_list,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "title": "Movie Name",
                    "release_year": "Release Year",
                    "rating": st.column_config.NumberColumn(
                        "Rating",
                        format="%.2f / 10"
                    ),
                    "language": "Language"
                }
            )

        else:
            st.info("No movies found for the selected filters.")

        st.divider()

        left_chart, right_chart = st.columns(2)

        with left_chart:
            st.markdown("### 📈 Movies Released Per Year")
            yearly_movies = get_movies_by_year()
            if not yearly_movies.empty:
                fig = px.line(
                    yearly_movies,
                    x="release_year",
                    y="movie_count",
                    markers=True,
                    template="plotly_dark"
                )
                fig.update_traces(line_color="#784BFF", line_width=3)
                fig.update_layout(
                    paper_bgcolor="#191D2B",
                    plot_bgcolor="#191D2B",
                    margin=dict(l=15, r=15, t=35, b=15)
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No yearly movie data for these filters.")

        with right_chart:
            st.markdown("### 🎭 Genre Distribution")
            genre_data = get_genre_distribution()
            if not genre_data.empty:
                fig = px.pie(
                    genre_data,
                    names="genre_name",
                    values="movie_count",
                    hole=0.45,
                    template="plotly_dark"
                )
                fig.update_layout(
                    paper_bgcolor="#191D2B",
                    margin=dict(l=15, r=15, t=35, b=15)
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No genre data for these filters.")

    except Exception as error:
        st.error(f"Overview could not be loaded: {error}")


# =====================================================
# 11. REVENUE TAB - COMPACT VISUALIZATION GALLERY
# =====================================================

with revenue_tab:
    st.subheader("📊 Visualization Explorer")
    st.caption("Choose a compact card on the left to display its chart on the right.")

    visualizations = [
        ("01", "Movies Released Per Year"),
        ("02", "Genre Distribution"),
        ("03", "Average Revenue by Genre"),
        ("04", "Budget vs Revenue"),
        ("05", "Top 10 Highest Grossing Movies"),
        ("06", "Top 10 Actors by Appearances"),
        ("07", "Ratings Distribution"),
        ("08", "Runtime Distribution"),
        ("09", "Popularity vs Vote Count"),
        ("10", "Top 10 Profitable Movies")
    ]

    if "selected_visualization" not in st.session_state:
        st.session_state.selected_visualization = "01"

    gallery_col, preview_col = st.columns([1.05, 2.2], gap="medium")

    with gallery_col:
        st.markdown("### Choose Chart")

        for i in range(0, len(visualizations), 2):
            card_col1, card_col2 = st.columns(2)

            for col, item in zip(
                [card_col1, card_col2],
                visualizations[i:i + 2]
            ):
                number, title = item
                with col:
                    is_selected = (
                        st.session_state.selected_visualization == number
                    )
                    if st.button(
                        f"{'✓ ' if is_selected else ''}{number}\n{title}",
                        key=f"viz_{number}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary"
                    ):
                        st.session_state.selected_visualization = number
                        st.rerun()

    with preview_col:
        selected = st.session_state.selected_visualization
        selected_title = next(
            title for number, title in visualizations if number == selected
        )
        st.markdown(f"### 📈 {selected_title}")

        try:
            # 01 - Movies Released Per Year
            if selected == "01":
                df = get_movies_by_year()
                if not df.empty:
                    fig = px.line(
                        df, x="release_year", y="movie_count",
                        markers=True, template="plotly_dark",
                        title="Movies Released Per Year"
                    )
                    fig.update_traces(line_color="#784BFF", line_width=3)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No yearly movie data for these filters.")

            # 02 - Genre Distribution
            elif selected == "02":
                df = get_genre_distribution()
                if not df.empty:
                    fig = px.pie(
                        df, names="genre_name", values="movie_count",
                        hole=0.45, template="plotly_dark",
                        title="Movie Distribution by Genre"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No genre data for these filters.")

            # 03 - Average Revenue by Genre
            elif selected == "03":
                df = get_average_revenue_by_genre()
                if not df.empty:
                    fig = px.bar(
                        df.sort_values("avg_revenue"),
                        x="avg_revenue", y="genre_name",
                        orientation="h", template="plotly_dark",
                        title="Average Revenue by Genre",
                        color_discrete_sequence=["#784BFF"]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No revenue data for these filters.")

            # 04 - Budget vs Revenue
            elif selected == "04":
                df = get_budget_revenue()
                if not df.empty:
                    fig = px.scatter(
                        df, x="budget", y="revenue",
                        hover_name="title", color="vote_average",
                        color_continuous_scale="Purples",
                        template="plotly_dark",
                        title="Movie Budget vs Revenue"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No valid budget and revenue data.")

            # 05 - Top 10 Highest Grossing Movies
            elif selected == "05":
                df = get_top_revenue_movies()
                if not df.empty:
                    fig = px.bar(
                        df.sort_values("revenue"),
                        x="revenue", y="title", orientation="h",
                        template="plotly_dark",
                        title="Top 10 Highest Grossing Movies",
                        color_discrete_sequence=["#784BFF"]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No revenue data for these filters.")

            # 06 - Top 10 Actors by Appearances
            elif selected == "06":
                df = get_top_actors()
                if not df.empty:
                    fig = px.bar(
                        df.sort_values("movie_count"),
                        x="movie_count", y="actor_name",
                        orientation="h", template="plotly_dark",
                        title="Top 10 Actors by Movie Appearances",
                        color_discrete_sequence=["#784BFF"]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No actor data for these filters.")

            # 07 - Ratings Distribution
            elif selected == "07":
                df = get_ratings_distribution()
                if not df.empty:
                    fig = px.histogram(
                        df, x="vote_average", nbins=20,
                        template="plotly_dark",
                        title="Movie Ratings Distribution",
                        color_discrete_sequence=["#784BFF"]
                    )
                    fig.update_traces(
                        marker_line_color="white",
                        marker_line_width=1
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No rating data for these filters.")

            # 08 - Runtime Distribution
            elif selected == "08":
                df = get_runtime_distribution()
                if not df.empty:
                    fig = px.histogram(
                        df, x="runtime", nbins=20,
                        template="plotly_dark",
                        title="Movie Runtime Distribution",
                        color_discrete_sequence=["#784BFF"]
                    )
                    fig.update_traces(
                        marker_line_color="white",
                        marker_line_width=1
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No runtime data for these filters.")

            # 09 - Popularity vs Vote Count
            elif selected == "09":
                df = get_popularity_vote_data()
                if not df.empty:
                    fig = px.scatter(
                        df, x="vote_count", y="popularity",
                        hover_name="title", color="vote_average",
                        color_continuous_scale="Purples",
                        template="plotly_dark",
                        title="Popularity vs Vote Count"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No popularity data for these filters.")

            # 10 - Top 10 Profitable Movies
            elif selected == "10":
                df = get_top_profitable_movies()
                if not df.empty:
                    fig = px.bar(
                        df.sort_values("profit"),
                        x="profit", y="title", orientation="h",
                        template="plotly_dark",
                        title="Top 10 Profitable Movies",
                        color_discrete_sequence=["#784BFF"]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No profit data for these filters.")

            st.caption("Chart reflects the currently selected sidebar filters.")

        except Exception as error:
            st.error(f"Could not load this visualization: {error}")


# =====================================================
# 12. QUERY EXPLORER
# =====================================================

with query_tab:
    st.subheader("🔎 SQL Query Explorer")
    st.write("Select a business question and execute its SQL analysis.")

    sql_queries = {
        "Q1 - Action Movies After 2015": """
            SELECT DISTINCT m.title, m.release_date
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            WHERE g.genre_name = 'Action'
              AND YEAR(m.release_date) > 2015
            ORDER BY m.release_date DESC
        """,

        "Q2 - Top 10 Highest Grossing Movies": """
            SELECT m.title, m.revenue,
                   GROUP_CONCAT(DISTINCT g.genre_name) AS genres
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            WHERE m.revenue > 0
            GROUP BY m.movie_id, m.title, m.revenue
            ORDER BY m.revenue DESC
            LIMIT 10
        """,

        "Q3 - Average Budget and Revenue by Genre": """
            SELECT g.genre_name,
                   ROUND(AVG(NULLIF(m.budget, 0)), 2) AS avg_budget,
                   ROUND(AVG(NULLIF(m.revenue, 0)), 2) AS avg_revenue
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            GROUP BY g.genre_id, g.genre_name
            ORDER BY avg_revenue DESC
        """,

        "Q4 - Top 10 Actors by Movie Appearances": """
            SELECT actor_name,
                   COUNT(DISTINCT movie_id) AS movie_count
            FROM `cast`
            WHERE actor_name IS NOT NULL
            GROUP BY actor_name
            ORDER BY movie_count DESC
            LIMIT 10
        """,

        "Q5 - Directors with More Than 3 Movies": """
            SELECT person_name AS director_name,
                   COUNT(DISTINCT movie_id) AS movie_count
            FROM crew
            WHERE job = 'Director'
            GROUP BY person_name
            HAVING COUNT(DISTINCT movie_id) > 3
            ORDER BY movie_count DESC
        """,

        "Q6 - Top 10 Most Used Keywords": """
            SELECT keyword_name,
                   COUNT(DISTINCT movie_id) AS usage_count
            FROM movie_keywords
            GROUP BY keyword_id, keyword_name
            ORDER BY usage_count DESC
            LIMIT 10
        """,

        "Q7 - Above Average Budget and Below Average Revenue": """
            SELECT title, budget, revenue
            FROM movies
            WHERE budget > 0
              AND revenue > 0
              AND budget > (
                  SELECT AVG(budget) FROM movies WHERE budget > 0
              )
              AND revenue < (
                  SELECT AVG(revenue) FROM movies WHERE revenue > 0
              )
            ORDER BY budget DESC
        """,

        "Q8 - Actors in Christopher Nolan Movies": """
            SELECT DISTINCT c.actor_name, m.title
            FROM `cast` c
            JOIN movies m ON c.movie_id = m.movie_id
            JOIN crew cr ON cr.movie_id = m.movie_id
            WHERE cr.person_name = 'Christopher Nolan'
              AND cr.job = 'Director'
            ORDER BY m.title, c.actor_name
        """,

        "Q9 - Highest Rated Genre (Minimum 20 Movies)": """
            SELECT g.genre_name,
                   ROUND(AVG(m.vote_average), 2) AS avg_rating,
                   COUNT(DISTINCT m.movie_id) AS movie_count
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            WHERE m.vote_count > 0
            GROUP BY g.genre_id, g.genre_name
            HAVING COUNT(DISTINCT m.movie_id) >= 20
            ORDER BY avg_rating DESC
        """,

        "Q10 - Top 10 Movies with Most Keywords": """
            SELECT m.title,
                   COUNT(DISTINCT mk.keyword_id) AS total_keywords
            FROM movies m
            JOIN movie_keywords mk ON m.movie_id = mk.movie_id
            GROUP BY m.movie_id, m.title
            ORDER BY total_keywords DESC
            LIMIT 10
        """
    }

    chart_settings = {
        "Q2 - Top 10 Highest Grossing Movies":
            ("title", "revenue"),

        "Q3 - Average Budget and Revenue by Genre":
            ("genre_name", "avg_revenue"),

        "Q4 - Top 10 Actors by Movie Appearances":
            ("actor_name", "movie_count"),

        "Q5 - Directors with More Than 3 Movies":
            ("director_name", "movie_count"),

        "Q6 - Top 10 Most Used Keywords":
            ("keyword_name", "usage_count"),

        "Q9 - Highest Rated Genre (Minimum 20 Movies)":
            ("genre_name", "avg_rating"),

        "Q10 - Top 10 Movies with Most Keywords":
            ("title", "total_keywords")
    }

    query_options = ["-- Select a Query --"] + list(sql_queries.keys())

    selected_query = st.selectbox(
        "Choose Analysis Question",
        options=query_options,
        index=0
    )

    if st.button("▶ Execute Query", type="primary"):
        if selected_query == "-- Select a Query --":
            st.warning("Please select a query before executing.")
        else:
            try:
                result_df = read_sql(sql_queries[selected_query])

                st.success(
                    f"Query executed successfully! {len(result_df)} records found."
                )

                st.markdown("### 📋 Query Results")
                st.dataframe(
                    result_df,
                    use_container_width=True,
                    hide_index=True
                )

                # -------------------------------------------------
                # QUERY EXPLORER VISUALIZATIONS
                # -------------------------------------------------
                if result_df.empty:
                    st.info("No records were found for this analysis.")
                else:
                    st.markdown("### 📊 Visual Analysis")

                    # Q1 - Action Movies After 2015
                    if selected_query == "Q1 - Action Movies After 2015":
                        chart_df = result_df.copy()
                        chart_df["release_year"] = pd.to_datetime(
                            chart_df["release_date"], errors="coerce"
                        ).dt.year
                        chart_df = (
                            chart_df.dropna(subset=["release_year"])
                            .groupby("release_year")
                            .size()
                            .reset_index(name="movie_count")
                            .sort_values("release_year")
                        )

                        if not chart_df.empty:
                            fig = px.bar(
                                chart_df,
                                x="release_year",
                                y="movie_count",
                                text="movie_count",
                                template="plotly_dark",
                                title="Action Movies Released After 2015",
                                color_discrete_sequence=["#784BFF"]
                            )
                            fig.update_layout(
                                paper_bgcolor="#191D2B",
                                plot_bgcolor="#191D2B",
                                xaxis_title="Release Year",
                                yaxis_title="Number of Movies"
                            )
                            fig.update_xaxes(dtick=1)
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.info("No valid release-year data available to chart.")

                    # Q7 - Above Average Budget and Below Average Revenue
                    elif selected_query == "Q7 - Above Average Budget and Below Average Revenue":
                        fig = px.scatter(
                            result_df,
                            x="budget",
                            y="revenue",
                            hover_name="title",
                            template="plotly_dark",
                            title="Above Average Budget vs Below Average Revenue",
                            color_discrete_sequence=["#784BFF"]
                        )
                        fig.update_layout(
                            paper_bgcolor="#191D2B",
                            plot_bgcolor="#191D2B",
                            xaxis_title="Budget (USD)",
                            yaxis_title="Revenue (USD)"
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    # Q8 - Actors in Christopher Nolan Movies
                    elif selected_query == "Q8 - Actors in Christopher Nolan Movies":
                        actor_data = (
                            result_df.groupby("actor_name")["title"]
                            .nunique()
                            .reset_index(name="movie_count")
                            .sort_values("movie_count", ascending=True)
                        )

                        fig = px.bar(
                            actor_data,
                            x="movie_count",
                            y="actor_name",
                            orientation="h",
                            template="plotly_dark",
                            title="Actors in Christopher Nolan Movies",
                            color_discrete_sequence=["#784BFF"]
                        )
                        fig.update_layout(
                            paper_bgcolor="#191D2B",
                            plot_bgcolor="#191D2B",
                            xaxis_title="Number of Nolan Movies",
                            yaxis_title="Actor"
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    # Q2, Q3, Q4, Q5, Q6, Q9 and Q10
                    elif selected_query in chart_settings:
                        x_column, y_column = chart_settings[selected_query]

                        chart_df = result_df.sort_values(
                            by=y_column,
                            ascending=True
                        )

                        fig = px.bar(
                            chart_df,
                            x=y_column,
                            y=x_column,
                            orientation="h",
                            template="plotly_dark",
                            title=selected_query,
                            color_discrete_sequence=["#784BFF"]
                        )
                        fig.update_layout(
                            paper_bgcolor="#191D2B",
                            plot_bgcolor="#191D2B"
                        )
                        st.plotly_chart(fig, use_container_width=True)

            except Exception as error:
                st.error(f"Query execution or visualization failed: {error}")
