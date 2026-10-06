# save as check_sushi.py in Team-Project/
import data_manager as dm

halal = dm.load_halal_certified()
places = dm.fetch_nearby_restaurants((1.4295, 103.8350), {"max_walk_minutes": 15})

print(f"Total places returned: {len(places)}\n")

for p in places:
    if "sushi" in p["name"].lower() or "japan" in p["name"].lower():
        cuisines = dm._cuisines_from_types(
            p.get("types", []),
            primary_type=p.get("primary_type"),
            primary_display=p.get("primary_type_display"),
        )
        is_h, conf, _ = dm._is_halal(p, halal)
        print(f"{p['name']}")
        print(f"  primary_type: {p.get('primary_type')}")
        print(f"  primary_display: {p.get('primary_type_display')!r}")
        print(f"  types: {p.get('types')}")
        print(f"  cuisines: {cuisines}")
        print(f"  halal: {is_h}  conf: {conf:.2f}")
        print()

# Show every halal-certified place nearby
print("--- All halal-certified places in this fetch ---")
for p in places:
    is_h, _, _ = dm._is_halal(p, halal)
    if is_h:
        cuisines = dm._cuisines_from_types(
            p.get("types", []),
            primary_type=p.get("primary_type"),
            primary_display=p.get("primary_type_display"),
        )
        print(f"  {p['name'][:40]:40} cuisines={cuisines}")