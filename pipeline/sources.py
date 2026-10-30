"""Official public aggregate workbooks, as listed in the project brief."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://statistics.gov.rw"
SOURCES = [
    dict(key="census2022", filename="PHC5-2022_Main_Indicators.xlsx", url=BASE + "/sites/default/files/documents/2025-02/PHC5-2022_Main_Indicators.xlsx", survey="Census 2022 (RPHC5)", year="2022", report_page_url=BASE + "/data-sources/censuses/Population-and-Housing-Census/fifth-population-and-housing-census-2022/main-indicators-5th-rwanda-population-and-housing-census-phc"),
    dict(key="eicv7_main", filename="EICV7_Tables_MainIndicatorReport.xlsx", url=BASE + "/sites/default/files/documents/2025-04/EICV7_Tables_MainIndicatorReport.xlsx", survey="EICV7 Main Indicators", year="2023/24", report_page_url=BASE + "/statistical-publications/poverty-and-social-protection/eicv7-main-indicators-report-202324"),
    dict(key="eicv7_util", filename="Tables_EICV7_Utilities_Amenities_Thematic_Report.xlsx", url=BASE + "/sites/default/files/documents/2025-06/Tables_EICV7_Utilities_Amenities_Thematic_Report.xlsx", survey="EICV7 Utilities and Amenities", year="2023/24", report_page_url=BASE + "/integrated-household-living-conditions-survey-7-eicv-7/eicv7-thematic-report-utilities-and-amenities-202324"),
    dict(key="eicv7_poverty", filename="EICV7_Tables_Rwanda_Poverty_Profile.xlsx", url=BASE + "/sites/default/files/documents/2025-05/EICV7_Tables_Rwanda_Poverty_Profile.xlsx", survey="EICV7 Poverty Profile", year="2023/24", report_page_url=BASE + "/data-sources/surveys/EICV/integrated-household-living-conditions-survey-7-eicv-7/eicv7-poverty-profile-report-202324"),
    dict(key="lfs2026q2", filename="RW_Quarterly_LFS_Tables_2026Q2.xlsx", url=BASE + "/sites/default/files/documents/2026-07/RW_Quarterly_LFS_Tables_2026Q2.xlsx", survey="Labour Force Survey Q2", year="2026", report_page_url=BASE + "/data-sources/surveys/Labour-Force-Survey/labour-force-survey-2026/labour-force-survey-2026-q2"),
]
SOURCE_BY_KEY = {source["key"]: source for source in SOURCES}
