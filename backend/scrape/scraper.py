
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import json
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time


urls = [
    'https://vit.ac.in',
    'https://vit.ac.in/',
    'https://vit.ac.in/about-vit',
    'https://vit.ac.in/vit-milestones',
    'https://vit.ac.in/governance',
    'https://vit.ac.in/true-green',
    'https://vit.ac.in/all-events',
    'https://vit.ac.in/nirf-2',
    'https://vit.ac.in/mhrdugcaicte',
    'https://vit.ac.in/ranking-and-recognition',
    'https://vit.ac.in/academic-council-minutes',
    'https://vit.ac.in/schools',
    'https://vit.ac.in/academics-feedback',
    'https://vit.ac.in/anti-ragging-committee',
    'https://vit.ac.in/capability-enhancement-schemes',
    'https://vit.ac.in/transcripts-for-alumni',
    'https://vit.ac.in/alumni-events',
    'https://vit.ac.in/e-tracks',
    'https://vit.ac.in/alumni-office-contact',
    'https://vit.ac.in/guest-house',
    'https://vit.ac.in/redressal',
    'https://vit.ac.in/hotels-in-vellore',
    'https://vit.ac.in/cdc-tracker',
    'https://vit.ac.in/cdc-office',
    'https://vit.ac.in/cdc-contact-us',
    'https://vit.ac.in/internationalrelations',
    'https://vit.ac.in/inbound-exchange-programs-vit-india',
    'https://vit.ac.in/research',
    'https://vit.ac.in/iprcell',
    'https://vit.ac.in/green-vit',
    'https://vit.ac.in/policies-core-values',
    'https://vit.ac.in/events-photos-videos',
    'https://vit.ac.in/news',
    'https://vit.ac.in/visit-of-associate-professor-dr-yong-wang-from-binghamton-university-new-york-usa',
    'https://vit.ac.in/interview-with-prof-anil-sahasrabhudhe',
    'https://vit.ac.in/bosch-mou',
    'https://vit.ac.in/oracle-university',
    'https://vit.ac.in/mou-with-dell-technologies',
    'https://vit.ac.in/mou-with-wipro',
    'https://vit.ac.in/chancellors-visit-to-university-of-jaffna',
    'https://vit.ac.in/qs-world-university-ranking-2025',
    'https://vit.ac.in/stars-day-2024',
    'https://vit.ac.in/inauguration-of-summer-camp',
    'https://vit.ac.in/infocus',
    'https://vit.ac.in/galleries',
    'https://vit.ac.in/contactus',
    'https://vit.ac.in/committee-for-sustainability-initiatives-2',
    'https://vit.ac.in/committee-for-ensuring-equality-diversity-and-inclusivity-2',
    'https://vit.ac.in/research-guide-directory-schools-centres-july-2024-vellore-campus',
    'https://vit.ac.in/dr-g-viswanathan',
    'https://vit.ac.in/deans',
    'https://vit.ac.in/directors',
    'https://vit.ac.in/centre-technical-support',
    'https://vit.ac.in/academic-block-geo-tagged-photos',
    'https://vit.ac.in/library-photos',
    'https://vit.ac.in/campus-amenities-photos',
    'https://vit.ac.in/auditoriums-geo-tagged-photos',
    'https://vit.ac.in/policy-document',
    'https://vit.ac.in/impact-ranking-2024',
    'https://vit.ac.in/impact-ranking-2022',
    'https://vit.ac.in/impact-ranking-2021',
    'https://vit.ac.in/community-radio-programmes',
    'https://vit.ac.in/community-radio-event',
    'https://vit.ac.in/community-radiovideo',
    'https://vit.ac.in/past-events-2',
    'https://vit.ac.in/swimming',
    'https://vit.ac.in/audited-financial-statement-0',
    'https://vit.ac.in/faculty-orientation-programme',
    'https://vit.ac.in/on-campus-fdp',
    'https://vit.ac.in/online-fdp',
    'https://vit.ac.in/one-week-fdp',
    'https://vit.ac.in/hybrid-fdp',
    'https://vit.ac.in/staff-development-programme',
    'https://vit.ac.in/event-brochure',
    'https://vit.ac.in/asc-event-calendar',
    'https://vit.ac.in/weekend-dialouge',
    'https://vit.ac.in/video-gallery',
    'https://vit.ac.in/asc-people',
    'https://vit.ac.in/scheme',
    'https://vit.ac.in/school-healthcare-science-and-engineering-shine',
    'https://vit.ac.in/chennai-2',
    'https://vit.ac.in/ap-2',
    'https://vit.ac.in/bhopal',
    'https://vit.ac.in/programmes-offered-ug-admissions',
    'https://vit.ac.in/ug-downloads',
    'https://vit.ac.in/testimonials-sap',
    'https://vit.ac.in/george-washington-university',
    'https://vit.ac.in/international-webinars-sap',
    'https://vit.ac.in/international-projects-sap',
    'https://vit.ac.in/africa',
    'https://vit.ac.in/asia-pacific',
    'https://vit.ac.in/australia',
    'https://vit.ac.in/europe',
    'https://vit.ac.in/middle-east-and-west-asia',
    'https://vit.ac.in/north-america',
    'https://vit.ac.in/south-america',
    'https://vit.ac.in/about-academic-research',
    'https://vit.ac.in/research-credentials',
    'https://vit.ac.in/dr-m-rasool',
    'https://vit.ac.in/dr-rajasekaran-r',
    'https://vit.ac.in/dr-sakthivadivel-d',
    'https://vit.ac.in/physical-department-members',
    'https://vit.ac.in/awards',
    'https://vit.ac.in/gymnasium',
    'https://vit.ac.in/fitness',
    'https://vit.ac.in/about-us/infrastructure/gandhi-block',
    'https://vit.ac.in/about/vision-mission',
    'https://vit.ac.in/about/leadership',
    'https://vit.ac.in/about/administrative-offices',
    'https://vit.ac.in/about/infrastructure',
    'https://vit.ac.in/about/sustainability',
    'https://vit.ac.in/about/community-outreach',
    'https://vit.ac.in/about/communityradio',
    'https://vit.ac.in/about/news-letter',
    'https://vit.ac.in/about/infrastructure/main-building',
    'https://vit.ac.in/about/infrastructure/silver-jubilee-tower',
    'https://vit.ac.in/about/infrastructure/technology-tower',
    'https://vit.ac.in/about/infrastructure/sirmvishveshvaraiya-building',
    'https://vit.ac.in/about/infrastructure/cbmr',
    'https://vit.ac.in/about/infrastructure/gdnaidu-block',
    'https://vit.ac.in/about/infrastructure/cdmm-building',
    'https://vit.ac.in/about/infrastructure/almudailar-block',
    'https://vit.ac.in/about/infrastructure/',
    'https://vit.ac.in/about/sustainability/energyconservationprogramme',
    'https://vit.ac.in/about/sustainability/recyclingprogramme',
    'https://vit.ac.in/about/sustainability/transportationpolicy',
    'https://vit.ac.in/about/sustainability/promotingsustainablepractices',
    'https://vit.ac.in/academics-more/semester-abroad-program-sap',
    'https://vit.ac.in/academics-more/contact-us',
    'https://vit.ac.in/academics/home',
    'https://vit.ac.in/academics/ffcs',
    'https://vit.ac.in/academics/library',
    'https://vit.ac.in/academics/transcripts',
    'https://vit.ac.in/academics/centers',
    'https://vit.ac.in/admission/pg/fee-structure',
    'https://vit.ac.in/admission/ug/fee-structure',
    'https://vit.ac.in/admissions/overview',
    'https://vit.ac.in/admissions/programmes-offered',
    'https://vit.ac.in/admissions/research',
    'https://vit.ac.in/admissions/international/overview',
    'https://vit.ac.in/admissions/research/',
    'https://vit.ac.in/all-courses/ug',
    'https://vit.ac.in/all-courses/pg',
    'https://vit.ac.in/all-courses/pg/',
    'https://vit.ac.in/all-courses/pg/master-of-business-administration',
    'https://vit.ac.in/all-courses/pg/mtech-programmes',
    'https://vit.ac.in/all-courses/pg/master-of-computer-application',
    'https://vit.ac.in/all-courses/pg/mscprogrammes',
    'https://vit.ac.in/all-courses/pg/master-of-social-work',
    'https://vit.ac.in/all-courses/pg/mdesindustrial-design',
    'https://vit.ac.in/all-courses/pg/master-of-architecture',
    'https://vit.ac.in/all-courses/pg/llm-degree-programmes',
    'https://vit.ac.in/all-courses/pg/integrated-mtech-programmes',
    'https://vit.ac.in/all-courses/pg/integrated-msc',
    'https://vit.ac.in/all-courses/ug/',
    'https://vit.ac.in/all-courses/ug/bdes-industrial-design',
    'https://vit.ac.in/all-courses/ug/b.arch',
    'https://vit.ac.in/all-courses/ug/bsc-computer-science-and-bca',
    'https://vit.ac.in/all-courses/ug/bachelor-commerce-bcom-and-bachelor-business-administration-bba',
    'https://vit.ac.in/all-courses/ug/bsc-multimedia-and-animation-and-bsc-visual-communication',
    'https://vit.ac.in/all-courses/ug/bsc-hospitality-hotel-administration',
    'https://vit.ac.in/all-courses/ug/bschons-agriculture',
    'https://vit.ac.in/all-events/page/2',
    'https://vit.ac.in/ariia-ranking/',
    'https://vit.ac.in/campus-category/newsletter',
    'https://vit.ac.in/campus-category/clubs',
    'https://vit.ac.in/campus-category/chapters',
    'https://vit.ac.in/campus-category/campus-events',
    'https://vit.ac.in/campus-category/grievancecell',
    'https://vit.ac.in/campus-category/programme-representatives',
    'https://vit.ac.in/campus-category/student-council',
    'https://vit.ac.in/campus/teams/projects-lab',
    'https://vit.ac.in/campuslife/overview',
    'https://vit.ac.in/campuslife/fests',
    'https://vit.ac.in/campuslife/sports',
    'https://vit.ac.in/campuslife/hostels',
    'https://vit.ac.in/campuslife/healthservices',
    'https://vit.ac.in/campuslife/otheramenities',
    'https://vit.ac.in/campuslife/studentswelfare',
    'https://vit.ac.in/cdc-highlights/',
    'https://vit.ac.in/cdc-overview/',
    'https://vit.ac.in/centers/tlce',
    'https://vit.ac.in/centers/arc',
    'https://vit.ac.in/centers/cfm',
    'https://vit.ac.in/centers/cnbt',
    'https://vit.ac.in/centers/co2',
    'https://vit.ac.in/centers/cbcmt',
    'https://vit.ac.in/centers/tifac',
    'https://vit.ac.in/centers/cce',
    'https://vit.ac.in/centers/cimr',
    'https://vit.ac.in/centers/cnr',
    'https://vit.ac.in/centers/cbst',
    'https://vit.ac.in/centers/cdmm',
    'https://vit.ac.in/event/vitaa-the-distinguished-alumni-awards-2025',
    'https://vit.ac.in/event/vision-to-action-empowering-entrepreneurs-2',
    'https://vit.ac.in/event/design-for-manufacturing',
    'https://vit.ac.in/event/aicte-training-and-learning-academy-atal-sponsored-6-days-fdp-on-micro-and-fiber-optic-sensors',
    'https://vit.ac.in/event/value-added-programme-on-exploring-matlab-simulink',
    'https://vit.ac.in/event/value-added-program-on-introduction-to-power-system-softwares-vac-1824',
    'https://vit.ac.in/event/2024-region-10-ieee-computer-society-summer-school-on-ai-and-iot-applications-in-smart-environments',
    'https://vit.ac.in/event/gravitas-2024',
    'https://vit.ac.in/event/11th-edition-of-vit-biosummit-2024',
    'https://vit.ac.in/event/a-five-day-workshop-on-computational-mathematics-with-matlab',
    'https://vit.ac.in/event/five-days-faculty-development-program-fdp-on-future-ready-antenna-design-cutting-edge-solutions-for-5g-mm-wave-and-beyond',
    'https://vit.ac.in/event/2-day-hands-on-workshop-on-power-and-energy-simulation-software-with-ai-techniques-pessait-2024',
    'https://vit.ac.in/event/scripting-languages-for-electronic-design-automation',
    'https://vit.ac.in/event/python-hack-a-thonon-midas-solutions',
    'https://vit.ac.in/event/third-annual-international-conference-on-population-ageing-and-labour',
    'https://vit.ac.in/event/national-conference-on-theoretical-and-numerical-approaches-in-water-wave-mechanics',
    'https://vit.ac.in/event/one-day-workshop-on-embedded-systems-architecture-and-arm-processor-hands-on',
    'https://vit.ac.in/event/vac-on-design-and-fabrication-of-printed-circuit-boards-using-auto-lab',
    'https://vit.ac.in/event/one-day-national-workshop-on-sustainable-iot-use-cases-with-5g-aws-cloud',
    'https://vit.ac.in/event/one-day-national-workshop-on-innovative-applications-of-industry-5-0',
    'https://vit.ac.in/event/aicte-training-and-learning-academy-atal-sponsored-six-days-faculty-development-program-on-design-and-development-of-micro-smart-grid-intended-for-smart-city-development-and-enhancing-e-mobility',
    'https://vit.ac.in/event/affordable-medical-device-development-hackathon',
    'https://vit.ac.in/event/enhancing-decision-making-with-insightful-data-analysis-for-real-time-usecases',
    'https://vit.ac.in/event/value-added-programme-on-exploring-matlab-simulink-2',
    'https://vit.ac.in/event/value-added-program-on-vac2401-hands-on-training-on-matlab-software-2',
    'https://vit.ac.in/event/advanced-molecular-modelling-drug-designing-by-ai-ml-approach',
    'https://vit.ac.in/event/value-added-course-on-industry-5-0',
    'https://vit.ac.in/files/selected-candidates-instructions-july-2024.pdf',
    'https://vit.ac.in/files/Strategic_Plan/index.html',
    'https://vit.ac.in/files/acad_feedback/2014-2015/index.html',
    'https://vit.ac.in/files/acad_feedback/2015-2016/index.html',
    'https://vit.ac.in/files/acad_feedback/2016-2017/index.html',
    'https://vit.ac.in/files/acad_feedback/2017-2018/index.html',
    'https://vit.ac.in/files/acad_feedback/2018-2019/index.html',
    'https://vit.ac.in/files/acad_feedback/2019-2020/index.html',
    'https://vit.ac.in/files/acad_feedback/2020-2021/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR-2021-22/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2014-15/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2015-16/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2016-17/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2017-18/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2018-19/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2019-20/index.html',
    'https://vit.ac.in/files/acad_feedback/ATR2020-21/index.html',
    'https://vit.ac.in/files/acad_feedback/Feedback-2021-2022/index.html',
    'https://vit.ac.in/files/acad_feedback/Feedback-Analysis-2021-2022/index.html',
    'https://vit.ac.in/files/acad_feedback/Templates/AY-2020-2021/index.html',
    'https://vit.ac.in/files/acad_feedback/stakeholders/index.html',
    'https://vit.ac.in/files/ebooks/ATR-2022-23/mobile/index.html',
    'https://vit.ac.in/files/ebooks/Ariia-2021/',
    'https://vit.ac.in/files/ebooks/Feedback-Analysis-2022-2023/mobile/index.html',
    'https://vit.ac.in/files/ebooks/Stakeholder-2022-2023/mobile/index.html',
    'https://vit.ac.in/files/ebooks/nirf-engineering/index.html',
    'https://vit.ac.in/files/ebooks/nirf-innovation/index.html',
    'https://vit.ac.in/files/ebooks/nirf-law/index.html',
    'https://vit.ac.in/files/ebooks/nirf-overall/index.html',
    'https://vit.ac.in/files/organogram/index.html',
    'https://vit.ac.in/guest-house/',
    'https://vit.ac.in/internationalrelations/itp',
    'https://vit.ac.in/internationalrelations/partneruniversities',
    'https://vit.ac.in/internationalrelations/partneruniversities/',
    'https://vit.ac.in/news-gallery/vit-agri-expo-uzhavar-kalanjiyam-2024',
    'https://vit.ac.in/news-gallery/riviera-2024',
    'https://vit.ac.in/ranking-and-recognition/',
    'https://vit.ac.in/research/academic',
    'https://vit.ac.in/research/sponsored-research',
    'https://vit.ac.in/research/centers-list',
    'https://vit.ac.in/research/projects',
    'https://vit.ac.in/research/funding-agency',
    'https://vit.ac.in/research/call-for-proposals',
    'https://vit.ac.in/research/industrial-consultancy',
    'https://vit.ac.in/research/vit-seed-grant',
    'https://vit.ac.in/research/latest-project',
    'https://vit.ac.in/school/course/hot/ug',
    'https://vit.ac.in/school/course/sas/pg',
    'https://vit.ac.in/school/course/sbst/ug',
    'https://vit.ac.in/school/course/sbst/pg',
    'https://vit.ac.in/school/course/sce/ug',
    'https://vit.ac.in/school/course/sce/pg',
    'https://vit.ac.in/school/course/scheme/ug',
    'https://vit.ac.in/school/course/smec/ug',
    'https://vit.ac.in/school/course/smec/pg',
    'https://vit.ac.in/school/course/ssl/ug',
    'https://vit.ac.in/school/course/ssl/pg',
    'https://vit.ac.in/school/course/v-sparc/ug',
    'https://vit.ac.in/school/course/v-sparc/pg',
    'https://vit.ac.in/school/course/vaial/ug',
    'https://vit.ac.in/school/course/vsign/ug',
    'https://vit.ac.in/school/course/vsign/pg',
    'https://vit.ac.in/schools/sas',
    'https://vit.ac.in/schools/vitbs',
    'https://vit.ac.in/schools/school-of-computer-science-and-engineering',
    'https://vit.ac.in/schools/v-sparc',
    'https://vit.ac.in/schools/smec',
    'https://vit.ac.in/schools/school-of-electrical-engineering',
    'https://vit.ac.in/schools/hot',
    'https://vit.ac.in/schools/school-of-computer-science-engineering-and-information-systems',
    'https://vit.ac.in/schools/vsign',
    'https://vit.ac.in/schools/ssl',
    'https://vit.ac.in/schools/school-of-electronics-engineering',
    'https://vit.ac.in/schools/sce',
    'https://vit.ac.in/schools/sbst',
    'https://vit.ac.in/schools/vaial',
    'https://vit.ac.in/schools/vsmart',
    'https://vit.ac.in/schools/school-of-computer-science-and-engineering-for-ug-courses',
    'https://vit.ac.in/schools/school-of-computer-science-engineering-and-information-systems-for-ug-courses',
    'https://vit.ac.in/schools/school-of-electronics-engineering-for-ug-courses',
    'https://vit.ac.in/schools/school-of-electrical-engineering-for-ug-courses',
    'https://vit.ac.in/schools/school-of-computer-science-engineering-and-information-systems-for-pg-courses',
    'https://vit.ac.in/schools/school-of-electronics-engineering-for-pg-courses',
    'https://vit.ac.in/schools/school-of-electrical-engineering-for-pg-courses',
    'https://vit.ac.in/schools/school-of-computer-science-and-engineering-for-pg-courses',
    'https://vit.ac.in/sites/default/files/template-for-two-page-research-proposal.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-61-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-62-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-63-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-64-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-65-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-66-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-67-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-68-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-69-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/Academic-Council-Meeting-Minutes/Minutes-of-the-70-Meeting.pdf',
    'https://vit.ac.in/sites/default/files/academic/Academic-Regulations.pdf',
    'https://vit.ac.in/sites/default/files/iqac/UGC-VIT-Vellore-Mandatory-Disclosure.pdf',
    'https://vit.ac.in/sites/default/files/iqac/VIT-Vellore-Mandatory-Disclosure.pdf',
    'https://vit.ac.in/sites/default/files/vitree/VITREE-January-2025-Eligibility-criteria.pdf',
    'https://vit.ac.in/sites/default/files/vitree/VITREE-January-2025-Session-Syllabus.pdf',
    'https://vit.ac.in/sites/default/files/vitree/VITREE-January-2025-Information-Brochure.pdf',
    'https://vit.ac.in/sites/default/files/vitree/VITREE-January-2025-Test-City.pdf',
    'https://vit.ac.in/vit-rank/',
    'https://vit.ac.in/vitol/',
    'https://vit.ac.in/vitol/index.html',
    'https://vit.ac.in/vitol/online-courses.html',
    'https://vit.ac.in/vitol/training-on-moocs.html',
    'https://vit.ac.in/vitol/vitol-in-news.html',
    'https://vit.ac.in/vitol/vitol-team.html',
    'https://vit.ac.in/vitol/UGC-AICTE-Mandatory-Disclosures-2-1.pdf',
    'https://vit.ac.in/vitol/contact-us.html',
    'https://vit.ac.in/wp-content/uploads/2023/06/sports_achievements_201415.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/Phy-Edu-Achievements-2015-2016.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/Phy-Edu-Achievements-2016-2017.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/Phy-Edu-Achievements-2017-2018.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/Phy-Edu-Achievements-2018-2019.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/EventAchievements2019-20.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/EventAchievements2020-21.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/06/EventAchievements2021-22.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/July_Newsletter-2018.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/June_Newsletter-2018_2.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/May_Newsletter-2018.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/May_Newsletter-2018-1.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/MarchNewsletter_0.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/Feb_Newletter-2018.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/Jan_Newletter-2018.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/Dec_Newletter-2017.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/November_Newletter-2017.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/08/accreditation.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/09/Maintaining-physical-academic-Policy.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/10/In-a-historic-decision-60-Higher-Educational-Institution.pdf',
    'https://vit.ac.in/wp-content/uploads/2023/11/Student-Code-of-Conduct.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Fall-Semester-2023-24-Freshers-02-08-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Fall-Semester-2023-24-for-Seniors-20-03-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-IV-2023-24-Senior-MBA-Students-13-04-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-V-2023-24-17-08-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-III-and-VI-2022-23-04-01-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Winter-Semester-2023-24-01-08-2023.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Fall-Semester-2022-23-for-Freshers-06-09-2022.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Fall-Semester-2022-23-for-Seniors-12-05-2022.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-I-and-IV-2022%E2%80%9323-17-06-2022.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-II-and-V-2022-23-16-09-22.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Trimester-III-and-VI-2022-23-04-01-2023-1.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-for-Winter-Semester-2022-23-for-Fresher-23-11-2022.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/04/Acad-Calen-Revised-for-Winter-Semester-2022-23-for-Seniors-15-11-2022.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/08/Academic-Calendar-for-Winter-Semester-2024-25.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/08/library-policy.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/08/E-Resources_Fair_Access_and_Download_Policy.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/09/Sports-Achievements-2022-23.pdf',
    'https://vit.ac.in/wp-content/uploads/2024/09/Sports-Achievements-2023-2024.pdf',
]



REMOVE_HEADINGS = {
    "VIT @ Connect",
    "Other Links",
    "Quick Links",
    "VISITORS",
    "Committees @ VIT",
    "Don't Trust Fake Website/ Page / Channels",
    "BEWARE OF ILLEGAL/FAKE WEBSITES",
    "Last Updated",
    "Others",
    "Beware of VITEEE fake websites",
    "Announcements"
}

REMOVE_TEXT_CONTAINS = [
    "Campus Tour",
    "Student Login",
    "Parent Login",
    "VIT Intranet",
    "VITAA Website",
    "Last Updated:",
    "Copyrights ©",
    "Admissions Open",
    "Beware of fraudulent",
]


def is_bad_heading(text: str) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    return any(h.lower() in t for h in REMOVE_HEADINGS)



def load_existing(filepath: str) -> dict:
    p = Path(filepath)
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}



def clean_data(data: dict) -> dict:
    cleaned = {}
    for url, sections in data.items():
        if not sections:
            continue

        clean_sections = {}
        for heading, content in sections.items():
            if not heading.strip():
                continue
            if not content:
                continue
            if isinstance(content, dict) and not any(content.values()):
                continue
            if isinstance(content, list) and not any(
                item.strip() if isinstance(item, str) else item
                for item in content
            ):
                continue
            clean_sections[heading] = content

        if clean_sections:
            cleaned[url] = clean_sections

    return cleaned



def save_json(filepath: str, new_data: dict):
    existing = load_existing(filepath)
    existing.update(new_data)
    cleaned = clean_data(existing)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
    print(f"   Saved to {filepath} ({len(cleaned)} URLs total)")



def scrape_url(url):
    print(f"\nScraping: {url}")
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
            }
        )
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Remove layout noise
        for tag in soup.find_all(['header', 'footer', 'nav', 'aside']):
            tag.decompose()

        for div in soup.find_all(class_=lambda x: x and any(
            k in str(x).lower()
            for k in ['header', 'footer', 'menu', 'navigation', 'sidebar',
                      'announcement', 'breadcrumb', 'popup', 'newsletter']
        )):
            div.decompose()

        page_data = defaultdict(list)
        current_heading = f"{url.split('/')[-1]} - Introduction"

        for elem in soup.find_all(['h1', 'h2', 'h3', 'p', 'table', 'ul', 'ol']):
            if elem.name.startswith('h'):
                heading = elem.get_text(separator=' ', strip=True)
                if heading:
                    current_heading = heading
                continue

            if is_bad_heading(current_heading):
                continue

            texts = []
            links = []

            for t in elem.stripped_strings:
                cleaned = t.strip()
                if cleaned:
                    texts.append(cleaned)

            for a in elem.find_all('a', href=True):
                link_text = a.get_text(strip=True)
                link_url = urljoin(url, a['href'])
                if link_url and not link_url.startswith("javascript"):
                    links.append(f"{link_text} ({link_url})")

            combined = " ".join(texts)
            if links:
                combined += " | " + " | ".join(links)
            combined = combined.strip()

            if not combined:
                continue
            if any(bad.lower() in combined.lower() for bad in REMOVE_TEXT_CONTAINS):
                continue
            if len(combined) < 8:
                continue
            if combined not in page_data[current_heading]:
                page_data[current_heading].append(combined)

        # FAQ extraction
        faqs = soup.select('.elementor-tab-title, .elementor-tab-content')
        current_q = None

        for elem in faqs:
            classes = elem.get('class', [])
            if 'elementor-tab-title' in classes:
                current_q = elem.get_text(strip=True)
            elif 'elementor-tab-content' in classes:
                answer = elem.get_text(strip=True)
                if current_q and answer:
                    faq_text = f"Q: {current_q} | A: {answer}"
                    if not any(bad.lower() in faq_text.lower() for bad in REMOVE_TEXT_CONTAINS):
                        page_data["Frequently Asked Questions"].append(faq_text)

        cleaned_page_data = {
            heading: content
            for heading, content in page_data.items()
            if not is_bad_heading(heading) and content
        }

        return url, cleaned_page_data

    except Exception as e:
        print(f" Error scraping {url}: {e}")
        return url, {}



all_data = {}
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(scrape_url, url): url for url in urls}
    for future in as_completed(futures):
        url, data = future.result()
        if data:
            all_data[url] = data


save_json('filter1.json', all_data)
print("\n FILTER 1 DONE")


# ---------------------------
# SELENIUM SETUP (FILTER 2)
# ---------------------------
options = Options()
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-extensions")
options.add_argument("--disable-infobars")
options.add_argument("--no-first-run")
options.add_argument("--disable-default-apps")
options.add_argument("--blink-settings=imagesEnabled=false")
options.page_load_strategy = 'eager'

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

wait = WebDriverWait(driver, 8)


# ---------------------------
# CONVERT LIST → DICT
# ---------------------------
def convert_to_dict(data_list):
    result = {}
    for item in data_list:
        if is_bad_heading(item):
            continue
        parts = item.split("\n", 1)
        if len(parts) == 2:
            name = parts[0].strip()
            description = " ".join(parts[1].split())
        else:
            name = parts[0].strip()
            description = ""
        if not is_bad_heading(name):
            result[name] = description
    return result


# ---------------------------
# POPUP SCRAPER
# ---------------------------
def scrape_popup_page(url):
    print(f"\n🔗 Scraping popups: {url}")
    driver.get(url)

    try:
        cards = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, ".eae-popup-link")
        ))
        print(f"  → Found {len(cards)} items")
    except:
        print(" No popup cards found")
        return {}

    section_data = []

    for i in range(len(cards)):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, ".eae-popup-link")
            card = cards[i]

            driver.execute_script("arguments[0].scrollIntoView(true);", card)
            time.sleep(0.3)

            driver.execute_script("arguments[0].click();", card)

            popup = wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".mfp-content")
            ))

            text = popup.text.strip()

            if is_bad_heading(text):
                print(f"  → Skipping item {i+1} — noise")
                continue

            section_data.append(text)
            print(f"  ✔ Item {i+1}")

            try:
                close_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".mfp-close")
                ))
                driver.execute_script("arguments[0].click();", close_btn)
            except:
                driver.execute_script(
                    "document.dispatchEvent(new KeyboardEvent('keydown', {'key':'Escape'}));"
                )

            wait.until(EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, ".mfp-content")
            ))

        except Exception as e:
            print(f"   Error at item {i+1}: {e}")
            continue

    try:
        title_raw = driver.find_element(By.TAG_NAME, "h1").text.strip()
        title = "Filtered Section" if is_bad_heading(title_raw) else title_raw
    except:
        title = url.split("/")[-1]

    structured_data = convert_to_dict(section_data)

    if is_bad_heading(title):
        return {}

    return {title: structured_data}


# ---------------------------
# MAIN LOOP
# ---------------------------
final_output = {}

for url in urls:
    result = scrape_popup_page(url)
    if result:
        final_output[url] = result

driver.quit()

# Save Filter 2
save_json('filter2.json', final_output)
print("\nFILTER 2 DONE")
