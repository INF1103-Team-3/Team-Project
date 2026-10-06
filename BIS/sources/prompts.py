"""Shared CLI text and the temporary AI prompt template."""

import json

from sources.profile_schema import (
    CUISINES, OTHER_PREFERENCES, PREFERENCE_FIELDS,
)

QUESTIONS = {
    "location": (
        "Which locations would you like to search around? "
        "(comma-separated areas)"
    ),
    "max_distance_km": "How far are you willing to walk? (in km or mins)",
    "max_travel_time_minutes": "How long are you willing to walk? (in mins)",
    "budget_per_person": "What is your budget per person? (in SGD)",
    "dietary_requirements": (
        "Do you require halal or vegetarian options? "
        "(halal, vegetarian, both, or none)"
    ),
    "liked_cuisines": (
        "Which cuisines do you like? (describe/list cuisines, or none)"
    ),
    "disliked_cuisines": (
        "Which cuisines do you avoid? (describe/list cuisines, or none)"
    ),
    OTHER_PREFERENCES: (
        "Any other preferences? List them with commas "
        "(spicy food, quiet cafes; or none)"
    ),
}

LABELS = {
    "location": "Locations",
    "max_distance_km": "Max walking distance",
    "max_travel_time_minutes": "Max walking time",
    "budget_per_person": "Budget per person",
    "dietary_requirements": "Dietary requirements",
    "liked_cuisines": "Likes",
    "disliked_cuisines": "Avoids",
    OTHER_PREFERENCES: "Other preferences",
}

COMMANDS = {
    "/profile": "show_profile", "/help": "help", "/reset": "reset_profile",
    "/search": "search",
    "/logout": "logout", "/quit": "exit", "/exit": "exit",
}

INTENTS = {"profile_update", "show_profile", "reset_profile", "search", "help",
           "exit", "logout", "unknown"}

SYSTEM_PROMPT = (
    "You assist BiteFinder profile collection, not recommendations. "
    "Return only JSON: {intent, profile_updates, location_action}. "
    "Intent is one of " + ", ".join(sorted(INTENTS)) + ". "
    "profile_updates is a dictionary using only these exact keys: "
    + json.dumps(list(PREFERENCE_FIELDS)) + ". "
    "Never output account fields, name, username, allergies, "
    "spice_preference, or dining_preferences. "
    "location is a list of areas. location_action is add by default, "
    "replace only for an explicit replacement, remove only for removal. "
    "dietary_requirements is a list containing halal and/or vegetarian; "
    "[] means explicitly no restrictions. Unknown restrictions such as "
    "dkdk must not be mapped to a known category or to none. "
    "Cuisine lists contain only: " + ", ".join(CUISINES) + ". "
    "Only extract user-supported facts. Null means unmentioned/unclear. "
    "Numbers must be numeric, budget in SGD (0.01–1000), walking distance "
    "in km (0.01–100), walking time in minutes (0.1–2000). "
    "Convert hours/metres as needed. "
    "For a travel answer, return only the explicitly provided quantities; "
    "Python supplies the approximate counterpart. "
    "other_preferences is a list of short preference strings; [] means "
    "explicitly none. Never return a single string for it. "
    "Leave unclear answers unanswered; never invent preferences. "
    "Cuisine interpretations and extra preferences require user confirmation. "
    "Never treat general instructions as preferences. 'Log out' means "
    "logout; 'quit' means exit. Utility intents have no profile updates."
)


EDIT_ALIASES = {
    "budget": "budget_per_person", "travel": "max_distance_km",
    "diet": "dietary_requirements", "likes": "liked_cuisines",
    "dislikes": "disliked_cuisines", "other": OTHER_PREFERENCES,
}


HELP_TEXT = """What would you like to do?
/profile — View your saved profile.
/search — Choose today's location, travel, cuisine, budget, and preferences.
/edit — See how to change an answer, such as your budget.
/add-location — Add an area to your saved locations.
/remove-location — Remove an area from your saved locations.
/reset — Clear all preferences. Keep your account and username.
/logout — Save and switch to another account.
/quit — Save and close the chatbot.

Use /help [command] for more detailed info."""

EDIT_HINT = """Choose what you want to change. For example, type:
/edit budget
I'll then ask for your new budget. Enter the answer when prompted.
For all editing options and examples, type /help edit."""

EDIT_HELP = """To change an answer:
1. Type a command below, such as /edit budget.
2. Answer the question that appears, such as 10 for a SGD 10 budget.
3. Confirm any suggestions if asked. Valid answers are saved automatically.

Command           What it changes            Example answer
/edit username    Your display name          John
/edit location    Your entire location list  Punggol, Tampines
/edit budget      Budget per person          10
/edit travel      Maximum walking distance   1 km or 20 mins
/edit diet        Dietary requirements       halal, vegetarian, both, or none
/edit likes       Cuisines you like          Chinese and Japanese
/edit dislikes    Cuisines you avoid         Indian, or none
/edit other       Other preferences          Quiet cafes, spicy food

Enter only the command first, then your answer when asked.
Editing replaces the selected answer and keeps your other answers.
Use /add-location to add areas without replacing your location list.
Use /remove-location to remove areas; at least one must remain.
Use /profile to check your saved answers."""


EDIT_HELP += "\nAccepted cuisine values: " + ", ".join(CUISINES) + ".\n"

EDIT_HELP += """

Accepted values when answering:
username: 1–50 characters after trimming spaces.
location: Comma-separated areas; each 1–100 characters with a letter.
          At least one area is required.
budget: 0.01–1000 SGD, entered as a number (up to two decimal places).
travel: 0.01–100 km walking or 0.1–2000 mins walking (up to two decimal places).
        Include units; distance and time use approximately 20 mins per km.
diet: halal, vegetarian, both, or none.
likes/dislikes: Supported cuisine names, or none. Natural phrases are accepted;
               typo suggestions require confirmation.
other: Comma-separated preferences (each up to 100 characters), or none.
"""

COMMAND_HELP = {
    "edit": EDIT_HELP,
    "profile": """/profile — View your saved profile.
Accepted values: None; type the command on its own.
Example: /profile
This only displays your profile; it does not change your answers.""",
    "search": """/search — Set up a restaurant search using your saved profile.
It starts automatically once when a profile becomes complete, or on the next
resume if it was already complete. Run /search again for new choices. You will
confirm your current location,
then choose walk/drive, maximum distance, one cuisine, today's budget, and
other preferences. Today's choices do not change your saved profile.
Restaurant recommendations will be added when BRNS is connected.
Example: /search""",
    "add-location": """/add-location — Add areas to your saved locations.
Accepted values: No value after the command. When prompted, enter areas
separated by commas; each must be 1–100 characters and contain a letter.
Example:
You: /add-location
When asked for locations: Punggol, Tampines
Existing areas are kept and duplicates are ignored.""",
    "remove-location": """/remove-location — Remove saved areas.
Accepted values: No value after the command. When prompted, enter one or
more existing location names separated by commas. At least one must remain.
Example (if Punggol and Tampines are saved):
You: /remove-location
When asked for locations: Tampines
Punggol remains in your saved locations.""",
    "reset": """/reset — Clear all your preference answers.
Accepted values: None; type the command on its own.
Example: /reset
This clears preferences immediately, without a confirmation question.
Your account, email, and username are kept. You can answer the questions again.
To change just one answer instead, use /edit followed by its name.""",
    "logout": """/logout — Save and return to the account menu.
Accepted values: None; type the command on its own.
Example: /logout
You can then resume another account by email or sign up.""",
    "quit": """/quit — Save your preferences and close the chatbot.
Accepted values: None; type the command on its own. /exit also works.
Example: /quit
You can resume your saved account by email the next time you start.""",
    "help": """/help — Show commands or explain one command.
Accepted values: No value for the overview, or one command name:
profile, search, edit, add-location, remove-location, reset, logout, quit,
exit, help.
Example: /help edit explains editing options and accepted answers.
Example: /help logout explains how to switch accounts.
A leading slash on the command name is optional: /help /logout also works.
Help only displays instructions; it never changes your profile.""",
}
COMMAND_HELP["exit"] = COMMAND_HELP["quit"]
