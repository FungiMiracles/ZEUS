def przelicz_region_demografia(region):
    """
    Utrzymuje spójność:
    region_populacja = suma miast + ludność pozamiejska
    """

    # 🔒 NORMALIZACJA NULL
    region.region_populacja = region.region_populacja or 0
    region.region_ludnosc_pozamiejska = region.region_ludnosc_pozamiejska or 0

    ludnosc_miast = sum(
        (m.miasto_populacja or 0)
        for m in region.miasta
    )

    region.region_ludnosc_pozamiejska = (
        region.region_populacja - ludnosc_miast
    )

    if region.region_ludnosc_pozamiejska < 0:
        raise ValueError(
            "Ludność miast przekracza populację regionu"
        )
