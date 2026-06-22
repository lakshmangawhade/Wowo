# family_registry.py — canonical family slugs and normalization
from __future__ import annotations

import re

# Canonical slugs aligned with km_01a router JSON
STAGE_FAMILY_MAP: dict[str, str] = {
    "climate_energy": "km_final_st_01_climate_energy.json",
    "pollution_chemicals_air_soil": "km_final_st_02_pollution_chemicals_air_soil.json",
    "water_marine_fisheries": "km_final_st_03_water_marine_fisheries.json",
    "waste_circular_products": "km_final_st_04_waste_circular_products.json",
    "biodiversity_ecosystems_land": "km_final_st_05_biodiversity_ecosystems_land.json",
    "workforce_labor_rights": "km_final_st_06_workforce_labor_rights.json",
    "communities_indigenous_rights": "km_final_st_07_communities_indigenous_rights.json",
    "consumers_products_privacy": "km_final_st_08_consumers_products_privacy.json",
    "governance_reporting_conduct": "km_final_st_09_governance_reporting_conduct.json",
}

FAMILY_ID_TO_SLUG: dict[str, str] = {
    "KM_FINAL_ST_01_CLIMATE_ENERGY": "climate_energy",
    "KM_FINAL_ST_02_POLLUTION_CHEMICALS_AIR_SOIL": "pollution_chemicals_air_soil",
    "KM_FINAL_ST_03_WATER_MARINE_FISHERIES": "water_marine_fisheries",
    "KM_FINAL_ST_04_WASTE_CIRCULAR_PRODUCTS": "waste_circular_products",
    "KM_FINAL_ST_05_BIODIVERSITY_ECOSYSTEMS_LAND": "biodiversity_ecosystems_land",
    "KM_FINAL_ST_06_WORKFORCE_LABOR_RIGHTS": "workforce_labor_rights",
    "KM_FINAL_ST_07_COMMUNITIES_INDIGENOUS_RIGHTS": "communities_indigenous_rights",
    "KM_FINAL_ST_08_CONSUMERS_PRODUCTS_PRIVACY": "consumers_products_privacy",
    "KM_FINAL_ST_09_GOVERNANCE_REPORTING_CONDUCT": "governance_reporting_conduct",
}

# Ground-truth / legacy slug aliases → canonical router slug
GT_FAMILY_ALIASES: dict[str, str] = {
    "climate_carbon_and_energy": "climate_energy",
    "air_soil_and_pollution": "pollution_chemicals_air_soil",
    "water_marine_and_fisheries": "water_marine_fisheries",
    "waste_and_circularity": "waste_circular_products",
    "biodiversity_ecosystems_and_species": "biodiversity_ecosystems_land",
    "products_consumers_and_data": "consumers_products_privacy",
    "workforce_and_labor": "workforce_labor_rights",
    "governance_reporting_and_business_conduct": "governance_reporting_conduct",
    "communities_and_indigenous_rights": "communities_indigenous_rights",
    "chemicals_hazardous_substances_and_restricted_products": "pollution_chemicals_air_soil",
    "land_buildings_and_construction": "biodiversity_ecosystems_land",
}

# Canonical router slug → primary GT-compatible label (for eval output)
CANONICAL_TO_GT_LABEL: dict[str, str] = {
    "climate_energy": "climate_carbon_and_energy",
    "pollution_chemicals_air_soil": "air_soil_and_pollution",
    "water_marine_fisheries": "water_marine_and_fisheries",
    "waste_circular_products": "waste_and_circularity",
    "biodiversity_ecosystems_land": "biodiversity_ecosystems_and_species",
    "consumers_products_privacy": "products_consumers_and_data",
    "workforce_labor_rights": "workforce_and_labor",
    "communities_indigenous_rights": "communities_and_indigenous_rights",
    "governance_reporting_conduct": "governance_reporting_and_business_conduct",
}

# Topics that strongly signal 'chemicals_hazardous_substances_and_restricted_products'
# (not just generic air/soil pollution) — derived from GT analysis
_CHEMICALS_SIGNAL_TOPICS: frozenset[str] = frozenset({
    "Chemical Regulation",
    "Chemical Safety",
    "Hazardous Substances",
    "Restriction of Hazardous Substances",
    "Elimination of Persistent Organic Pollutants",
    "Electrical Equipment",
})

# Topics that signal 'air_soil_and_pollution' but NOT chemicals
_AIR_SOIL_SIGNAL_TOPICS: frozenset[str] = frozenset({
    "Agricultural Pollution",
    "Soil Conservation",
    "Soil Quality Standards",
    "Transboundary Air Pollution Control",
    "Marine Environment Protection",
    "Marine Protected Areas",
    "Stormwater Management",
    "Emergency Preparedness",
    "Work Environment",
    "Air Quality",
    "Ambient Air Quality Standards",
    "Industrial Emissions",
    "Marine Pollution",
    "Contaminated Land Remediation",
    "Emissions Trading Schemes",
    "Acidification Reduction",
})

# Topics that signal 'land_buildings_and_construction'
_LAND_BUILDINGS_SIGNAL_TOPICS: frozenset[str] = frozenset({
    "Land Use Planning",
    "Building Performance Standards",
    "Energy Efficiency in Building Construction",
    "Emission Thresholds for Construction Products",
})

# Topics that signal 'biodiversity_ecosystems_and_species'
_BIODIVERSITY_SIGNAL_TOPICS: frozenset[str] = frozenset({
    "Biodiversity Conservation",
    "Ecosystem Restoration",
    "Habitat Restoration",
    "Protected Area Designation",
    "Endangered Species Protection",
    "Invasive Species Control",
    "Wildlife Trade Regulation",
    "Pollinator Protection",
    "Direct Impact Drivers of Biodiversity Loss",
    "Impacts on the State of Species",
    "Impacts on the Extent and Conditions of Ecosystems",
    "Impacts on and Dependencies on Ecosystem Services",
    "Animal Welfare",
})


def _refine_pollution_family_labels(
    canonical_slugs: list[str],
    specific_topics_str: str,
) -> list[str]:
    """
    Resolve ambiguous canonical slugs to GT-compatible labels using reconciled
    SpecificTopics as a signal.

    - 'pollution_chemicals_air_soil' → 'air_soil_and_pollution' and/or
      'chemicals_hazardous_substances_and_restricted_products'
    - 'biodiversity_ecosystems_land' → 'biodiversity_ecosystems_and_species' and/or
      'land_buildings_and_construction'
    """
    topics: set[str] = set()
    for part in re.split(r"[;,]", specific_topics_str or ""):
        t = part.strip()
        if t:
            topics.add(t)

    result: list[str] = []

    for slug in canonical_slugs:
        if slug == "pollution_chemicals_air_soil":
            has_chemicals = bool(topics & _CHEMICALS_SIGNAL_TOPICS)
            has_air_soil = bool(topics & _AIR_SOIL_SIGNAL_TOPICS)
            # Default to air_soil when ambiguous or when no specific signal
            if has_air_soil or (not has_chemicals):
                if "air_soil_and_pollution" not in result:
                    result.append("air_soil_and_pollution")
            if has_chemicals:
                lbl = "chemicals_hazardous_substances_and_restricted_products"
                if lbl not in result:
                    result.append(lbl)

        elif slug == "biodiversity_ecosystems_land":
            has_bio = bool(topics & _BIODIVERSITY_SIGNAL_TOPICS)
            has_land = bool(topics & _LAND_BUILDINGS_SIGNAL_TOPICS)
            # Default to biodiversity when ambiguous
            if has_bio or (not has_land):
                if "biodiversity_ecosystems_and_species" not in result:
                    result.append("biodiversity_ecosystems_and_species")
            if has_land:
                if "land_buildings_and_construction" not in result:
                    result.append("land_buildings_and_construction")

        else:
            gt_label = CANONICAL_TO_GT_LABEL.get(slug, slug)
            if gt_label not in result:
                result.append(gt_label)

    return result


STAGE_ORDER: dict[str, int] = {
    "km_04_orchestrator_extraction": 0,
    "km_01a_specific_topic_family_router": 1,
    "family_st_kms": 2,
    "km_01z_specific_topic_reconciler": 3,
    "km_02_applicable_sectors": 4,
    "km_03_esrs_mapping": 5,
}


def canonical_family_slug(value: str) -> str:
    slug = (value or "").strip()
    if not slug:
        return ""
    slug = FAMILY_ID_TO_SLUG.get(slug, slug)
    slug = GT_FAMILY_ALIASES.get(slug, slug)
    return slug


def normalize_routed_families(router_out: dict) -> list[str]:
    """Normalize router output to canonical family slugs."""
    raw = router_out.get("topic_families_to_run")
    if raw is None and router_out.get("primary_family"):
        raw = router_out.get("primary_family")

    if raw is None:
        return []

    if isinstance(raw, str):
        items = [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    slugs: list[str] = []
    for item in items:
        if isinstance(item, dict):
            candidate = (
                item.get("slug")
                or item.get("family_id")
                or item.get("family")
                or ""
            )
        else:
            candidate = str(item)

        slug = canonical_family_slug(str(candidate))
        if slug in STAGE_FAMILY_MAP and slug not in slugs:
            slugs.append(slug)

    return slugs


def format_router_families(router_out: dict, specific_topics: str = "") -> str:
    """Return GT-compatible family labels (not internal canonical slugs).

    When *specific_topics* is provided the pollution/chemicals canonical family
    is resolved to 'air_soil_and_pollution', 'chemicals_hazardous_substances_and_restricted_products',
    or both, depending on which SpecificTopic labels were actually reconciled.
    """
    slugs = normalize_routed_families(router_out)
    labels = _refine_pollution_family_labels(slugs, specific_topics)
    return "; ".join(labels)


def is_upstream_stage(stage: str, relative_to: str) -> bool:
    return STAGE_ORDER.get(stage, -1) < STAGE_ORDER.get(relative_to, 99)
