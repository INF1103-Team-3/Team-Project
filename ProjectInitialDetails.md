# BiteFinder: Project Scope - Team 3

Repo Link: [https://github.com/INF1103-Team-3/Team-Project](https://github.com/INF1103-Team-3/Team-Project)

1.  Problem Statement and Target Users

What real-world problem does your application aim to solve?

Finding suitable food becomes difficult when users must satisfy several conditions at once, such as Halal, vegan or vegetarian requirements, food allergies, a limited budget, a preferred food or cuisine, and a maximum walking time. Existing maps, food-discovery and dietary services often separate this information, so users must manually compare menus, prices, certification details and walking routes. BiteFinder combines these constraints into one recommendation process and returns suitable options with a clear explanation of why they match.

Who are the intended users of the application?

The application is intended for the general public, especially people who need to make food decisions quickly or have specific restrictions. Key users include students and educational staff, office workers, people with dietary requirements or food allergies, budget-conscious diners, tourists and visitors, and other time-constrained users.

2.  User Inputs

What information or data will users provide to BiteFinder?

BiteFinder will collect only the information needed to generate relevant recommendations. Inputs include:
- Location - current device location with permission, or a manually entered postal code, address, landmark, latitude or longitude
- Maximum walking time - the longest time the user is willing to walk
- Budget - the maximum amount the user wants to spend
- Dietary requirement - for example Halal, vegan or vegetarian
- Food allergies - allergens the user needs to avoid, such as peanuts or shellfish
- Food or meal preference - preferred dish, cuisine or meal type, such as chicken rice, Japanese food, rice or noodles
- Time requirement - for example, open now or open at a specified time
- Optional natural-language request - for example, “something spicy but not too expensive”.

3.  Use of AI

How will AI be utilized within the application?

AI will help understand what the user is asking for and turn it into clear requirements. It will then compare suitable restaurants, rank the best matches, explain why they were recommended, and suggest alternatives if there is no exact match. Important and non-negotiable restrictions will be checked first before the AI ranks anything. The AI will not make up restaurant details, which will come from trusted external data and routing services. 

What outputs, insights, or recommendations will the AI generate from the user inputs?

The AI will generate several suitable food recommendations based on the user’s requirements, instead of giving only one result. For each option, it will show the restaurant and food type, price, walking time, opening status, and relevant dietary or halal certification information.

It will also explain why each option matches the user’s needs, such as being within budget, meeting dietary requirements, or being close enough to walk to. If there is no exact match, the AI will suggest the closest alternatives and clearly explain what would need to change, while keeping important dietary and allergy restrictions unchanged.

4.  Business Rules

What business rules, validations, or decision-making logic will be applied to the AI-generated outputs?

The recommendation process will follow a set of simple rules so the AI only works with valid information:

- Non negotiable and important requirements will be checked first. Dietary needs, allergies, budget limits and walking-time limits will be checked before the AI ranks any restaurants. Things like preferred cuisine, cheaper prices or shorter walking distance will be treated as preferences.
- The AI will only use approved restaurant, menu, routing and certification data. It will not make up details such as prices, opening hours, certification status or walking time. If something is missing, it will be shown as unavailable.
- User inputs will be checked before processing. For example, budget and walking time must be valid numbers, the location must be valid, and required fields cannot be left empty.
- Official dietary certification must come from a trusted source. BiteFinder will also make it clear whether information is official, restaurant-reported, third-party reported or unknown.
- BiteFinder will not claim that food is completely allergy-safe. If ingredient or cross-contamination information is unclear, users will be told to confirm with the restaurant.
- Walking time will come from a routing service, and the restaurant's opening status will be checked for the requested time.
- If there is no exact match, important dietary and allergy requirements will stay unchanged. BiteFinder will show the closest alternatives and explain what other requirements would need to change.
- Every recommendation will include a short explanation. BiteFinder will also avoid collecting unnecessary personal data and will refresh time-sensitive restaurant information instead of assuming old data is still correct.