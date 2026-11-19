"""Deterministic demo data service for the AIRWISE AI dashboard.

All values in this module are explicitly labelled sample scenarios designed to
demonstrate the AIRWISE AI interface before a live telemetry provider is connected.
"""

from app.schemas.dashboard import (
    AirQualitySummary,
    AssistantPreview,
    AssistantSamplePrompt,
    DailyRecommendation,
    DashboardResponse,
    HealthAdvisoryPanel,
    HealthGuidanceGroup,
    LocationOption,
    PollutantCard,
)

AVAILABLE_LOCATIONS: list[LocationOption] = [
    LocationOption(
        id="lagos-ng",
        city="Lagos",
        region="Lagos State",
        country="Nigeria",
        display_name="Lagos, Nigeria",
        latitude=6.5244,
        longitude=3.3792,
        timezone="Africa/Lagos",
    ),
    LocationOption(
        id="abuja-ng",
        city="Abuja",
        region="Federal Capital Territory",
        country="Nigeria",
        display_name="Abuja, Nigeria",
        latitude=9.0765,
        longitude=7.3986,
        timezone="Africa/Lagos",
    ),
    LocationOption(
        id="nairobi-ke",
        city="Nairobi",
        region="Nairobi County",
        country="Kenya",
        display_name="Nairobi, Kenya",
        latitude=-1.2921,
        longitude=36.8219,
        timezone="Africa/Nairobi",
    ),
    LocationOption(
        id="accra-gh",
        city="Accra",
        region="Greater Accra",
        country="Ghana",
        display_name="Accra, Ghana",
        latitude=5.6037,
        longitude=-0.1870,
        timezone="Africa/Accra",
    ),
]

_LOCATION_MAP: dict[str, LocationOption] = {loc.id: loc for loc in AVAILABLE_LOCATIONS}


def get_supported_locations() -> list[LocationOption]:
    """Return list of supported sample locations."""
    return AVAILABLE_LOCATIONS


def get_location_by_id(location_id: str) -> LocationOption | None:
    """Look up a configured location by its identifier without silent fallback.

    Returns None if the location_id is not one of the four configured locations.
    """
    normalized_id = location_id.strip().lower()
    return _LOCATION_MAP.get(normalized_id)



def build_demo_dashboard(location_id: str | None = None) -> DashboardResponse:
    """Build a clearly labelled demo dashboard response for the requested location.

    Defaults to Lagos, Nigeria ('lagos-ng') if location_id is omitted or unrecognized.
    """
    normalized_id = (location_id or "lagos-ng").strip().lower()
    selected = _LOCATION_MAP.get(normalized_id, _LOCATION_MAP["lagos-ng"])

    if selected.id == "lagos-ng":
        summary = AirQualitySummary(
            aqi_value=112,
            aqi_band="Unhealthy for Sensitive Groups",
            dominant_pollutant="PM2.5",
            summary_statement=(
                "DEMO SCENARIO: Elevated fine particulate matter modeled for peak traffic corridors "
                "across Mainland and Victoria Island approaches. Sensitive groups should reduce prolonged "
                "roadside exposure."
            ),
            reference_timestamp_label="Sample Scenario: Weekday Morning Commute Baseline (Not Live Telemetry)",
            weather_context="Sample meteorology: Warm humid coastal airflow (29°C, 76% RH, light SW breeze)",
        )
        pollutants = [
            PollutantCard(
                code="PM2.5",
                name="Fine Particulate Matter (<2.5 µm)",
                value=39.8,
                unit="µg/m³",
                status="Elevated",
                who_guideline_ref="24-hr reference benchmark: 15 µg/m³",
                source_hint="Vehicular exhaust, diesel backup generators, and peri-urban biomass combustion",
            ),
            PollutantCard(
                code="PM10",
                name="Coarse Particulate Matter (<10 µm)",
                value=78.4,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="24-hr reference benchmark: 45 µg/m³",
                source_hint="Unpaved road dust resuspension, construction activity, and maritime corridor traffic",
            ),
            PollutantCard(
                code="NO2",
                name="Nitrogen Dioxide",
                value=34.2,
                unit="µg/m³",
                status="Elevated",
                who_guideline_ref="24-hr reference benchmark: 25 µg/m³",
                source_hint="Congested arterial road corridors (Third Mainland & Ikorodu Road scenario)",
            ),
            PollutantCard(
                code="O3",
                name="Ground-Level Ozone",
                value=46.0,
                unit="µg/m³",
                status="Low",
                who_guideline_ref="8-hr peak reference benchmark: 100 µg/m³",
                source_hint="Secondary photochemical formation during midday solar radiation",
            ),
        ]
    elif selected.id == "abuja-ng":
        summary = AirQualitySummary(
            aqi_value=84,
            aqi_band="Moderate",
            dominant_pollutant="PM10",
            summary_statement=(
                "DEMO SCENARIO: Moderate particulate levels modeled for central Abuja districts with "
                "seasonal dry dust contribution. Generally acceptable for most residents."
            ),
            reference_timestamp_label="Sample Scenario: Dry-Season Midday Baseline (Not Live Telemetry)",
            weather_context="Sample meteorology: Dry continental breeze (31°C, 42% RH, moderate NE airflow)",
        )
        pollutants = [
            PollutantCard(
                code="PM2.5",
                name="Fine Particulate Matter (<2.5 µm)",
                value=24.5,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="24-hr reference benchmark: 15 µg/m³",
                source_hint="Urban traffic and localized commercial power generation",
            ),
            PollutantCard(
                code="PM10",
                name="Coarse Particulate Matter (<10 µm)",
                value=88.0,
                unit="µg/m³",
                status="Elevated",
                who_guideline_ref="24-hr reference benchmark: 45 µg/m³",
                source_hint="Regional dust transport and urban infrastructure development",
            ),
            PollutantCard(
                code="NO2",
                name="Nitrogen Dioxide",
                value=21.0,
                unit="µg/m³",
                status="Low",
                who_guideline_ref="24-hr reference benchmark: 25 µg/m³",
                source_hint="Expressway commuter traffic",
            ),
            PollutantCard(
                code="O3",
                name="Ground-Level Ozone",
                value=58.5,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="8-hr peak reference benchmark: 100 µg/m³",
                source_hint="Afternoon sunlight-driven photochemical reaction",
            ),
        ]
    elif selected.id == "nairobi-ke":
        summary = AirQualitySummary(
            aqi_value=68,
            aqi_band="Moderate",
            dominant_pollutant="PM2.5",
            summary_statement=(
                "DEMO SCENARIO: Moderate urban air quality modeled for Nairobi with localized traffic "
                "emissions along major commuter routes and cleaner conditions near green belts."
            ),
            reference_timestamp_label="Sample Scenario: Highland Urban Morning Baseline (Not Live Telemetry)",
            weather_context="Sample meteorology: Mild highland conditions (22°C, 60% RH, E breeze)",
        )
        pollutants = [
            PollutantCard(
                code="PM2.5",
                name="Fine Particulate Matter (<2.5 µm)",
                value=19.2,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="24-hr reference benchmark: 15 µg/m³",
                source_hint="Matatu and commercial vehicle fleet emissions",
            ),
            PollutantCard(
                code="PM10",
                name="Coarse Particulate Matter (<10 µm)",
                value=44.0,
                unit="µg/m³",
                status="Low",
                who_guideline_ref="24-hr reference benchmark: 45 µg/m³",
                source_hint="Roadside dust and industrial zone activity",
            ),
            PollutantCard(
                code="NO2",
                name="Nitrogen Dioxide",
                value=23.4,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="24-hr reference benchmark: 25 µg/m³",
                source_hint="CBD and Mombasa Road transit corridors",
            ),
            PollutantCard(
                code="O3",
                name="Ground-Level Ozone",
                value=41.0,
                unit="µg/m³",
                status="Low",
                who_guideline_ref="8-hr peak reference benchmark: 100 µg/m³",
                source_hint="Background tropospheric ozone",
            ),
        ]
    else:
        summary = AirQualitySummary(
            aqi_value=95,
            aqi_band="Moderate",
            dominant_pollutant="PM2.5",
            summary_statement=(
                "DEMO SCENARIO: Upper-moderate particulate levels modeled for coastal Accra commercial "
                "districts. Individuals with asthma should monitor symptoms near busy intersections."
            ),
            reference_timestamp_label="Sample Scenario: Coastal Urban Baseline (Not Live Telemetry)",
            weather_context="Sample meteorology: Coastal sea breeze (28°C, 74% RH, SSW wind)",
        )
        pollutants = [
            PollutantCard(
                code="PM2.5",
                name="Fine Particulate Matter (<2.5 µm)",
                value=31.0,
                unit="µg/m³",
                status="Elevated",
                who_guideline_ref="24-hr reference benchmark: 15 µg/m³",
                source_hint="Urban transport corridors and informal waste burning",
            ),
            PollutantCard(
                code="PM10",
                name="Coarse Particulate Matter (<10 µm)",
                value=66.5,
                unit="µg/m³",
                status="Moderate",
                who_guideline_ref="24-hr reference benchmark: 45 µg/m³",
                source_hint="Road dust and coastal aerosol mixing",
            ),
            PollutantCard(
                code="NO2",
                name="Nitrogen Dioxide",
                value=27.8,
                unit="µg/m³",
                status="Elevated",
                who_guideline_ref="24-hr reference benchmark: 25 µg/m³",
                source_hint="High-density commuter arteries",
            ),
            PollutantCard(
                code="O3",
                name="Ground-Level Ozone",
                value=49.0,
                unit="µg/m³",
                status="Low",
                who_guideline_ref="8-hr peak reference benchmark: 100 µg/m³",
                source_hint="Daytime photochemical equilibrium",
            ),
        ]

    health_advisory = HealthAdvisoryPanel(
        headline=f"Demo Health Advisory for {selected.display_name} ({summary.aqi_band})",
        general_advice=(
            "These recommendations illustrate how AIRWISE AI translates particulate and gas thresholds "
            "into practical public health guidance. Do not use this demo dataset for medical decisions."
        ),
        groups=[
            HealthGuidanceGroup(
                audience="Sensitive Groups (Asthma, COPD, Children, Older Adults)",
                risk_level="Elevated in sample scenario",
                guidance=(
                    "Limit prolonged outdoor exertion adjacent to heavy traffic corridors during peak hours. "
                    "Keep prescribed rescue inhalers accessible."
                ),
            ),
            HealthGuidanceGroup(
                audience="Outdoor Workers & Transit Commuters",
                risk_level="Moderate to Elevated",
                guidance=(
                    "Consider well-fitted particulate respirators (e.g., KN95/FFP2) when stationed in "
                    "slow-moving traffic or generator-dense commercial zones."
                ),
            ),
            HealthGuidanceGroup(
                audience="General Population",
                risk_level="Low to Moderate",
                guidance=(
                    "Normal outdoor activities are acceptable away from congested highways; shift high-intensity "
                    "cardio to parks or coastal/breeze-flushed windows."
                ),
            ),
        ],
    )

    daily_recommendations = [
        DailyRecommendation(
            id="rec-commute-window",
            time_window="06:30 – 09:30 Local (Sample Peak)",
            title="Mitigate In-Cabin Commute Exposure",
            description=(
                f"In this {selected.city} demo scenario, use vehicle air recirculation when queued on major "
                "arterials to lower cabin PM2.5 and NO2 ingress."
            ),
            priority="High",
            category="Commute",
        ),
        DailyRecommendation(
            id="rec-ventilation-window",
            time_window="13:00 – 16:00 Local (Sample Dispersion Window)",
            title="Schedule Natural Indoor Ventilation",
            description=(
                "Afternoon thermal mixing and sea/land breezes typically aid vertical pollutant dispersion. "
                "Prefer cross-ventilating homes away from active diesel generators."
            ),
            priority="Medium",
            category="Ventilation",
        ),
        DailyRecommendation(
            id="rec-outdoor-fitness",
            time_window="16:30 – 18:00 Local",
            title="Select Low-Traffic Green Corridors for Exercise",
            description=(
                "Route outdoor runs or walks at least 150–200 meters setback from main highways to cut "
                "ultrafine particulate exposure significantly."
            ),
            priority="Medium",
            category="Exercise",
        ),
        DailyRecommendation(
            id="rec-household-source",
            time_window="All Day",
            title="Reduce Indoor Combustion Co-Pollutants",
            description=(
                "Ensure generator exhaust is directed downwind and away from window intakes; avoid open burning "
                "of refuse in residential compounds."
            ),
            priority="Informational",
            category="Household",
        ),
    ]

    assistant_preview = AssistantPreview(
        status_label="Preview Mode — Sample Context Only (LLM & Live Sensors Not Connected)",
        capabilities_summary=(
            f"The AIRWISE AI Assistant will synthesize hyper-local pollutant readings, meteorological context, "
            f"and WHO health benchmarks for {selected.display_name}. Below are deterministic sample Q&A previews."
        ),
        sample_prompts=[
            AssistantSamplePrompt(
                id="prompt-outdoor-jog",
                question=f"Is it safe to go for an outdoor run in {selected.city} under these sample conditions?",
                preview_answer=(
                    f"[DEMO PREVIEW] With a sample AQI of {summary.aqi_value} ({summary.aqi_band}) driven by "
                    f"{summary.dominant_pollutant}, healthy adults can exercise outdoors if they avoid major road "
                    "intersections. Individuals with asthma or respiratory sensitivity should opt for indoor workouts "
                    "or wait for cleaner afternoon dispersion windows."
                ),
            ),
            AssistantSamplePrompt(
                id="prompt-pm25-driver",
                question=f"What is driving the sample PM2.5 reading in {selected.display_name}?",
                preview_answer=(
                    f"[DEMO PREVIEW] In this simulated {selected.city} scenario, fine particulates (PM2.5) are "
                    "modeled from a combination of commuter traffic exhaust, commercial diesel generators, and "
                    "localized biomass or dust sources. Connecting a live provider in upcoming milestones will "
                    "replace this with real-time telemetry."
                ),
            ),
            AssistantSamplePrompt(
                id="prompt-school-guidance",
                question="What precautions should schools take during an 'Unhealthy for Sensitive Groups' scenario?",
                preview_answer=(
                    "[DEMO PREVIEW] Schools should keep outdoor physical education moderate, monitor students with "
                    "known asthma during peak morning traffic hours, and ensure classrooms near busy roads keep "
                    "street-facing windows closed during rush hour."
                ),
            ),
        ],
    )

    return DashboardResponse(
        is_demo_data=True,
        data_mode="demo",
        data_source_label="DEMO DATA — Simulated Urban Scenario (No Live Sensor Provider Connected)",
        disclaimer=(
            "All AQI values, pollutant concentrations, and advisories shown are deterministic sample/demo data "
            "for the AIRWISE AI Day 1 foundation. They do not represent live atmospheric measurements."
        ),
        selected_location=selected,
        available_locations=AVAILABLE_LOCATIONS,
        summary=summary,
        pollutants=pollutants,
        health_advisory=health_advisory,
        daily_recommendations=daily_recommendations,
        assistant_preview=assistant_preview,
    )
