User Input -> IO -> AI -> LOGIC -> USER DATA -> RESTAURANT JSON
-> IO (looks for geocode, places api)
-> AI (User reccomendations list restaurant)
-> LOGIC (Validate halal from MUIS / vegetarian / user navigation / google gets halal unofficial or none and checks with MUIS approved (yes -> change unofficial to official / no -> do nothing))
-> DATA (Clean restaurant data ^ / user approved lisst of resturants)

User profile {
    User Signup - user data
    - Usual locations
    - Walking or driving
    - Distance they willing to travel usually
    - Budget
    - Liked cuisines
    -> User does /Search or AI prompts after user creation
}

Not saved {
    Where are you now? -> get currrent location either from saved or postal or address
    Walking or driving?
    Distance willing to travel?
    Choose from liked cuisines? or try something new?
    Same budget?
    Other preferences today?
}