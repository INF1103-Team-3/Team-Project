from __future__ import annotations

import streamlit as st

from database.database import (
    fetch_restaurants,
    initialise_database,
    load_profile,
    record_history,
    save_profile,
)
from database.seed_data import seed_database
from recommendation.recommender import recommend


APP_TITLE = "BiteFinder"

CUISINES = [
    "Chinese",
    "Fusion",
    "Healthy",
    "Indian",
    "Italian",
    "Japanese",
    "Korean",
    "Malay",
    "Mediterranean",
    "Thai",
    "Western",
]

DIETS = [
    "No dietary restriction",
    "Vegetarian",
    "Vegan",
    "Halal",
]

COMMON_ALLERGENS = [
    "dairy",
    "egg",
    "gluten",
    "nuts",
    "peanuts",
    "sesame",
    "shellfish",
    "soy",
]


def bootstrap() -> None:
    initialise_database()
    seed_database()


def apply_loaded_profile(profile: dict) -> None:
    st.session_state["profile_id"] = profile["user_id"]
    st.session_state["profile_name_input"] = profile["name"]
    st.session_state["budget"] = float(profile["budget"])
    st.session_state["max_distance"] = float(profile["maximum_distance"])
    st.session_state["diet"] = profile["diet"]
    st.session_state["allergies"] = profile["allergies"]
    st.session_state["cuisines"] = profile["cuisines"]


def sidebar_profile() -> None:
    st.sidebar.header("Saved profile")
    st.sidebar.caption("Optional: save or reload your basic preferences.")

    profile_name = st.sidebar.text_input(
        "Profile name",
        key="profile_name_input",
        placeholder="e.g. Alex",
    )

    col1, col2 = st.sidebar.columns(2)

    with col1:
        if st.button("Load", use_container_width=True):
            if not profile_name.strip():
                st.sidebar.error("Enter a profile name first.")
            else:
                profile = load_profile(profile_name)
                if profile:
                    apply_loaded_profile(profile)
                    st.rerun()
                else:
                    st.sidebar.warning("No saved profile found.")

    with col2:
        if st.button("Save", use_container_width=True):
            if not profile_name.strip():
                st.sidebar.error("Enter a profile name first.")
            else:
                user_id = save_profile(
                    name=profile_name,
                    budget=float(st.session_state.get("budget", 20)),
                    maximum_distance=float(
                        st.session_state.get("max_distance", 2)
                    ),
                    diet=st.session_state.get(
                        "diet", "No dietary restriction"
                    ),
                    allergies=st.session_state.get("allergies", []),
                    cuisines=st.session_state.get("cuisines", []),
                )
                st.session_state["profile_id"] = user_id
                st.sidebar.success("Profile saved.")


def preference_form() -> dict | None:
    st.subheader("What are you looking for?")

    st.caption(
        "The default location is only sample MVP data. Replace it with your "
        "chosen coordinates or later connect a geocoding/map API."
    )

    with st.form("preferences"):
        col1, col2 = st.columns(2)

        with col1:
            diet = st.selectbox(
                "Dietary requirement",
                DIETS,
                key="diet",
            )

            allergies = st.multiselect(
                "Allergies / ingredients to exclude",
                COMMON_ALLERGENS,
                key="allergies",
            )

            budget = st.number_input(
                "Maximum meal budget ($)",
                min_value=1.0,
                max_value=200.0,
                value=float(st.session_state.get("budget", 20.0)),
                step=1.0,
                key="budget",
            )

            cuisines = st.multiselect(
                "Preferred cuisine",
                CUISINES,
                key="cuisines",
            )

        with col2:
            latitude = st.number_input(
                "Latitude",
                value=1.3521,
                format="%.6f",
            )
            longitude = st.number_input(
                "Longitude",
                value=103.8198,
                format="%.6f",
            )

            max_distance = st.slider(
                "Maximum distance (km)",
                min_value=0.2,
                max_value=5.0,
                value=float(st.session_state.get("max_distance", 2.0)),
                step=0.1,
                key="max_distance",
            )

            open_now_only = st.checkbox(
                "Show only restaurants currently open",
                value=False,
            )

            result_limit = st.slider(
                "Number of recommendations",
                min_value=1,
                max_value=10,
                value=5,
            )

        submitted = st.form_submit_button(
            "Find food",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return None

    return {
        "diet": diet,
        "allergies": allergies,
        "budget": budget,
        "preferred_cuisines": cuisines,
        "latitude": latitude,
        "longitude": longitude,
        "max_distance_km": max_distance,
        "open_now_only": open_now_only,
        "result_limit": result_limit,
    }


def render_recommendations(user: dict) -> None:
    restaurants = fetch_restaurants()
    recommendations, exclusions = recommend(
        user,
        restaurants,
        limit=user["result_limit"],
    )

    st.divider()
    st.subheader("Recommendations")

    total_excluded = sum(exclusions.values())
    st.caption(
        f"Checked {len(restaurants)} restaurants. "
        f"Filtered out {total_excluded} that did not meet mandatory requirements."
    )

    with st.expander("See filter summary"):
        st.write(
            {
                "Allergy conflicts": exclusions["allergy"],
                "Diet mismatch": exclusions["diet"],
                "Over budget": exclusions["budget"],
                "Too far": exclusions["distance"],
                "Closed": exclusions["closed"],
            }
        )

    if not recommendations:
        st.warning(
            "No restaurants matched every hard requirement. "
            "Try increasing the budget/distance or changing a non-safety preference."
        )
        return

    for index, restaurant in enumerate(recommendations, start=1):
        with st.container(border=True):
            top_left, top_right = st.columns([4, 1])

            with top_left:
                st.markdown(f"### {index}. {restaurant['name']}")
                st.write(
                    f"**{restaurant['cuisine']}** · "
                    f"${restaurant['average_price']:.0f} average · "
                    f"{restaurant['distance_km']:.2f} km away"
                )

            with top_right:
                st.metric("Match", f"{restaurant['score']:.0f}%")

            for reason in restaurant["explanation"]:
                st.write(f"✓ {reason}")

            if st.button(
                "Select this restaurant",
                key=f"select_{restaurant['restaurant_id']}",
            ):
                record_history(
                    restaurant_id=restaurant["restaurant_id"],
                    action="selected",
                    user_id=st.session_state.get("profile_id"),
                )
                st.success(f"Saved selection: {restaurant['name']}")


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🍜",
        layout="wide",
    )

    bootstrap()

    st.title("🍜 BiteFinder")
    st.write(
        "Filter out restaurants you cannot accept, then rank the remaining "
        "options by your preferences."
    )

    st.info(
        "Allergy notice: this MVP filters using stored restaurant data only. "
        "Always confirm allergy and cross-contamination information directly "
        "with the restaurant before eating."
    )

    sidebar_profile()

    user = preference_form()
    if user:
        render_recommendations(user)


if __name__ == "__main__":
    main()
