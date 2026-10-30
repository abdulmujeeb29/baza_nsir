"""Registry of NISR tables to load. Values always come from the raw files, never from here."""

EICV_STATS = "Columns: value (estimate, %), std_error, ci_low and ci_high (95% confidence interval), cv (%), design_effect."


def _t(table_id, source_key, sheet, ref, indicator, unit, notes="", geo="national, province, district", **extra):
    return dict(table_id=table_id, source_key=source_key, sheet=sheet, nisr_table_ref=ref,
                indicator_name=indicator, unit=unit, notes=notes, geography_levels=geo, **extra)


def _eicv(table_id, sheet, indicator, notes=""):
    ref = sheet
    return _t(table_id, "eicv7_main", sheet, ref, indicator, "%",
              (notes + " " + EICV_STATS).strip(), "national, urban_rural, province, district",
              first_col_name="value")


def _util(table_id, number, indicator, notes="", geo="national, district"):
    sheet = f"Table.{number}"
    return _t(table_id, "eicv7_util", sheet, "Table " + number, indicator, "% of households",
              notes, geo, short_names=True, rename={"total_nber_of_hhs_in_000s": "households_thousands"})


def _lfs(table_id, sheet, indicator, notes=""):
    return _t(table_id, "lfs2026q2", sheet, sheet, indicator, "% or count",
              (notes + " Long format: one row per indicator, group and quarter. Columns: indicator, group, year, quarter, period (e.g. 2026Q2), value. "
               "The latest quarter is 2026Q2.").strip(), "national", parser="lfs")


TABLES = [
    # Census 2022 (RPHC5), district level
    _t("census_t1_population", "census2022", "Table 1", "Table 1", "population, residents, people, population density, sex", "count; % share; people per km2",
       "Resident population counts by sex, share of national population (%), and population density (people per square km).",
       rename={"population_share_pct_of_the_total_population_both_sexes": "population_share_pct"}),
    _t("census_t2_urban_rural_population", "census2022", "Table 2", "Table 2", "urban population, rural population, urbanisation", "count; %",
       "Population by residence: counts and percentage urban and rural."),
    _t("census_t21_internet_use", "census2022", "Table 21", "Table 21", "internet use, online, used internet by age group", "% of population",
       "Percentage of people who used the internet, for population aged 10+, 16+ and 21+, by sex."),
    _t("census_t25_mobile_phone", "census2022", "Table 25", "Table 25", "mobile phone ownership, households with a phone", "% of households",
       "Percentage of private households where at least one member owns a mobile phone, by sex of head and residence."),
    _t("census_t28_health_insurance", "census2022", "Table 28", "Table 28", "health insurance, medical insurance, mutuelle, coverage", "% of population",
       "Prevalence of medical insurance by residence (total, urban, rural) and sex. Use total_both_sexes for the overall rate."),
    _t("census_t40_birth_registration", "census2022", "Table 40", "Table 40", "birth registration rate, civil registration", "% of births",
       "Birth registration rate by residence and sex."),
    _t("census_t45_youth_share", "census2022", "Table 45", "Table 45", "youth share, young people aged 16 to 30", "% of population",
       "Share of youth (16 to 30 years) in the population by residence and sex.",
       rename={"urban_bothsexea": "urban_both_sexes"}),
    _t("census_t54_disability", "census2022", "Table 54", "Table 54", "disability, persons with disabilities aged 5+", "count; %",
       "Number and percentage of the population aged 5 and above with a disability, by sex."),
    _t("census_t59_female_headed_households", "census2022", "Table 59", "Table 59", "female headed households, households headed by women", "count; %",
       "Number and percentage of households headed by women, total, urban and rural. The source sheet spells Ngoma as 'goma'; it is mapped to Ngoma."),
    _t("census_t60_household_size", "census2022", "Table 60", "Table 60", "mean household size, average household size", "persons per household",
       "Mean size of private households by sex of head and residence."),
    _t("census_t68_improved_water", "census2022", "Table 68", "Table 68", "improved drinking water, water access", "% of households",
       "Percentage of private households with access to improved drinking water, by residence and sex of head. Use rwanda_total for the overall rate."),
    _t("census_t74_electricity_access", "census2022", "Table 74", "Table 74", "electricity access, power, households with electricity", "% of households",
       "Proportion of households with access to electricity, by sex of head and residence. Use sex_of_the_household_head_all for the overall rate."),
    _t("census_t75_lighting_source", "census2022", "Table 75", "Table 75", "main source of lighting, electricity from REG, solar, lighting energy", "% of households",
       "Distribution of private households by main source of energy for lighting (REG grid electricity, solar, candles, flashlight and others)."),
    _t("census_t76_cooking_energy", "census2022", "Table 76", "Table 76", "cooking energy, cooking fuel, firewood, charcoal, gas", "% of households",
       "Percentage of private households by main source of energy for cooking."),
    _t("census_t79_agricultural_households", "census2022", "Table 79", "Table 79", "agricultural households, farming households, agriculture", "count; %",
       "Number and percentage of private agricultural households, total, urban and rural."),
    # EICV7 2023/24 Main Indicators, annex district tables
    _eicv("eicv7_a9_23_poverty_rate", "Table A9.23", "poverty rate, headcount poverty, poor, poverty by district",
          "Headcount poverty rate (% of population below the poverty line). The first row (label 'Poverty Rate') is the national rate."),
    _eicv("eicv7_a3_7_health_insurance", "Table A3.7", "health insurance coverage, mutuelle, medical insurance"),
    _eicv("eicv7_a5_14_electricity_lighting", "Table A5.14", "electricity as main source of lighting, electricity access, power"),
    _eicv("eicv7_a5_15_internet_at_home", "Table A5.15", "internet access at home, online, connectivity, including mobile phones"),
    _eicv("eicv7_a5_16_improved_water", "Table A5.16", "improved drinking water, water access"),
    _eicv("eicv7_a5_17_improved_sanitation", "Table A5.17", "improved sanitation, toilets, latrines"),
    _eicv("eicv7_a5_19_smartphone", "Table A5.19", "smartphone ownership, households owning a smartphone"),
    _eicv("eicv7_a6_20_workforce_ratio", "Table A6.20", "workforce to population ratio, employment, work"),
    # EICV7 Utilities and Amenities thematic report
    _util("eicv7_util_a05_safe_water", "A.05", "safely managed drinking water, basic, limited, unimproved, surface water",
          "Distribution of households by drinking water service level. Last column is total households in thousands."),
    _util("eicv7_util_a07_safe_sanitation", "A.07", "safely managed sanitation, basic, limited, unimproved, open defecation",
          "Distribution of households by sanitation service level. Last column is total households in thousands."),
    _util("eicv7_util_a09_cooking_fuel", "A.09", "primary cooking fuel, firewood, charcoal, gas, biogas",
          "Distribution of households by main cooking fuel. Last column is total households in thousands."),
    _util("eicv7_util_a28_road_distance", "A.28", "walking time to nearest all-weather road, road access, distance",
          "Distribution of households by walking time to the nearest all-weather road."),
    _util("eicv7_util_a31_transport_distance", "A.31", "walking distance to public transport stage, bus, transport access",
          "Distribution of households by walking time to the nearest public transport stage."),
    _util("eicv7_util_a36_ict_devices", "A.36", "ICT devices, radio, computer, mobile phone, smartphone, television, TV",
          "Percentage of households owning at least one of each ICT device."),
    _util("eicv7_util_a37_internet_usage", "A.37", "internet usage frequency, internet service use, online",
          "Distribution of households by how often they use internet services."),
    _util("eicv7_util_b07_electricity_lighting", "B.07", "electricity as primary source of lighting, electricity access, power",
          "Estimate (value) with std_error, ci_low, ci_high and unweighted_count. Rows are Rwanda, provinces, urban/rural groupings and the 30 districts.",
          geo="national, province, district, other"),
    # Labour Force Survey 2026 Q2, national
    _lfs("lfs_2026q2_indicators_rwanda", "LFIndicatorsRw", "unemployment rate, labour force participation, employment-to-population ratio, jobs, labour",
         "Summary labour force indicators for Rwanda (group = Total). LU1 is the unemployment rate."),
    _lfs("lfs_2026q2_indicators_by_sex", "LFIndicatorsSex", "unemployment by sex, male, female, women, men, labour force",
         "Labour force indicators by sex (group = Male or Female)."),
    _lfs("lfs_2026q2_indicators_urban_rural", "LFIndicatorsUrRur", "unemployment urban rural, labour force by residence",
         "Labour force indicators by area of residence (group = Urban or Rural)."),
    _lfs("lfs_2026q2_indicators_youth_adult", "LFIndicatorsYouthAdult", "youth unemployment, young people, adults, labour force by age",
         "Labour force indicators for youth (16 to 30) and adults (31+)."),
]
