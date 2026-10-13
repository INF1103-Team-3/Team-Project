# BiteFinder: Project Scope - Team 3

Repo Link: [https://github.com/INF1103-Team-3/Team-Project](https://github.com/INF1103-Team-3/Team-Project)

1. Problem Statement and Target Users

What real-world problem does your application aim to solve?

Choosing a suitable restaurant is difficult when users must compare Halal or vegetarian requirements, budget, preferred and disliked cuisines, opening hours, ratings and travel limits. Restaurant facts, MUIS certification, prices, reviews and routes are spread across services. BiteFinder combines them into one Singapore search, explains matches and exclusions, and provides clear, usable directions without manual comparisons.

Who are the intended users of the application?

BiteFinder serves the general public, especially people choosing food quickly or following dietary preferences. Users include students, educational staff, office workers, Halal or vegetarian diners, budget-conscious diners, tourists, public-transport users, and anyone wanting suggestions supported by current restaurant and route facts.

2. User Inputs

What information or data will users provide to BiteFinder?

BiteFinder collects information needed to create an account, save reusable preferences, and perform today's search. Inputs include:

- Account details - a username and email address verified using a six-digit email code
- Saved locations - Singapore areas, addresses, landmarks or postal codes
- Travel preference - a maximum distance or journey time for walking, driving or public transit
- Traffic preference - whether a driving-time search should use current traffic
- Budget - the maximum expected amount per person
- Dietary requirements - Halal, vegetarian, both or none
- Cuisine preferences - liked cuisines, disliked cuisines, or no specific cuisine for today's search
- Current search location - a saved place, postal code, address, landmark or latitude and longitude
- Optional special request - natural-language wishes such as “spicy chicken rice”, “minimum 4.5 stars”, or “only Korean food”
- Result action - view details, sort by rating or distance, show a route, repeat the search, or email a Google Maps link

3. Use of AI

How will AI be utilized within the application?

AI connects BIS, BRNS and BRC. BIS interprets natural language, proposes spelling corrections for confirmation, finds equivalent saved requests, and converts confirmed searches into validated JSON. BRNS ranks Google Places and Routes candidates using controlled reason codes. BRC cleans MUIS records, tags cuisines and proposes certification matches before deterministic rules verify identity. Invalid AI schemas are rejected, fallback models are tried, and confirmed choices and restaurant facts cannot be overwritten.

What outputs, insights, or recommendations will the AI generate from the user inputs?

The AI generates a ranked set of restaurant candidate identifiers and reasons based on cuisine, budget, dietary needs, travel limits, ratings, review counts, and special requests. Results show the restaurant name, address, cuisine, estimated price range, Google rating and review count, today's opening hours, dietary status, and verified route distance or duration when available.

Each recommendation separates factual matches, suitability reasons, and cautions. If no restaurant satisfies every requirement, BiteFinder reports that clearly and offers alternatives instead of presenting them as exact matches. Users can then adjust today's choices or repeat the same search for unseen candidates. For Halal searches, BRC marks matched MUIS outlets as officially certified; Google-indicated results remain clearly labelled unofficial when official checking is unavailable.

4. Business Rules

What business rules, validations, or decision-making logic will be applied to the AI-generated outputs?

The recommendation process follows rules that protect confirmed user choices and ensure that AI output is supported by restaurant data:

- BIS validates account, location, travel, cuisine, dietary and budget values before creating search JSON. Invalid values are rejected; AI corrections require confirmation.
- Words such as “only” and “at least” become hard requirements after confirmation. They must match, although budget and travel may be relaxed for labelled alternatives.
- BRNS accepts only current Places candidate identifiers and supported reason codes. Duplicate, unknown or malformed AI values are rejected.
- Restaurants must be open at the current Singapore day and time. Closed places or unknown live opening hours are excluded.
- Route limits use Google Routes distance or duration for walking, driving and transit. Driving may use traffic; missing transit routes are not estimated.
- Budget uses the known price range. Ranking considers both Google rating and review count.
- Disliked cuisines and confirmed cuisine or rating limits are enforced. Soft preferences influence ranking without becoming guaranteed facts.
- BRC marks MUIS matches official. Google Halal evidence is an unofficial fallback if BRC fails. Vegetarian claims require supporting facts.
- If no exact match exists, BiteFinder explains exclusions and offers alternatives without silently changing dietary or hard requirements.
- Search summaries, restaurant facts and geocodes are stored as JSON. Logs record stages, attempts and trace identifiers without API keys or raw responses.
