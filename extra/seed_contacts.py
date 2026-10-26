import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["chatbot_db"]
contacts = db["contacts"]

data = [
    # ── Counsellors ───────────────────────────────────────────
    {"category": "counsellor", "name": "Dr. Rita Bhattacharjee", "qualifications": "PhD in Counselling Psychology, MBA(HRM)", "role": "Head of Department, Counselling Psychologist", "department": "Counselling Division", "campus": "Vellore", "location": "Room no. SMV G-12 – Hexagon Building", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Dr. Dinesh Babu", "qualifications": "MBBS, MD (Psychiatry)", "role": "Visiting Consultant Psychiatrist", "department": "SNHRC Health Centre", "campus": "Vellore", "location": "ALM block, First floor, Room No.11", "email": None, "phone": None, "availability": "Tuesday & Friday 3:00pm to 6:00pm", "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mr. Felix Emmanuel J N", "qualifications": "MSW, MSc (PSY), MA (SOC), MA (PA), MPhil (SOC)", "role": "Senior Student Counsellor Level 2", "department": "Counselling Division", "campus": "Vellore", "location": "TT720 Technology Tower", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mr. Parthiban D", "qualifications": "MSc Psychology", "role": "Senior Student Counsellor Level 2", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. SJT 326 Silver Jubilee Tower", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Dr. Jetson Satya Gospel", "qualifications": "MSW, MBA, MSc, PhD", "role": "Senior Student Counsellor Level 3", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No PRP 206 Pearl Research Park", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mr. Clinton Joseph A", "qualifications": "MSW (Medical and Psychiatry)", "role": "Senior Student Counsellor Level 2", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. MB228A Dr. MGR Block", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Dr. Dhanalakshmi N", "qualifications": "MSc Psychology, PhD", "role": "Senior Student Counsellor Level 2", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No PRP 206 Pearl Research Park", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mrs. Reshma K P", "qualifications": "MSW (Medical and Psychiatry)", "role": "Student Counsellor", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. MG F-414 Mahatma Gandhi Block", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mr. R. Muralitharan", "qualifications": None, "role": "Student Counsellor", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. PRP 145E Pearl Research Park", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Ms. Beulah Valarmathi Chandran", "qualifications": "MSc Counselling Psychology", "role": "Student Counsellor", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. SJT 612-13A Silver Jubilee Tower", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Ms. Lakshmi A", "qualifications": "MA Applied Psychology", "role": "Student Counsellor", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. SJT 427 Silver Jubilee Tower", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Ms. Jessica Jesudassan", "qualifications": "MA Clinical Psychology, BEd, PG Dip in Sexual Abuse Counselling", "role": "Residential Student Counsellor", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. PRP 314B Pearl Research Park", "email": None, "phone": None, "source": "https://vit.ac.in/counselling-division"},
    {"category": "counsellor", "name": "Mr. Blessing Calvin G", "qualifications": "MSc Applied Psychology", "role": "Senior Student Counsellor Level 2", "department": "Counselling Division", "campus": "Vellore", "location": "Cabin No. 630 SJT", "email": "blessing.calvin@vit.ac.in", "phone": None, "source": "https://vit.ac.in/counselling-division"},

    # ── ICC Members Vellore ───────────────────────────────────
    {"category": "icc_member", "name": "Dr. Shanthi C", "role": "Convenor", "designation": "Professor HAG, SBST", "campus": "Vellore", "phone": "96007 55022", "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Ms. Radhika R", "role": "Member Secretary", "designation": "Visiting Faculty Law, Academy for Prisons and Correctional Administration", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Dr. Mahalakshmi P", "role": "Member", "designation": "Professor Grade 2, SELECT", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Dr. Gothandam K M", "role": "Member", "designation": "Professor HAG, SBST", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Dr. Kannabiran K", "role": "Member", "designation": "Professor HAG, SBST", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Dr. Aruna Singh", "role": "Member", "designation": "Professor Grade 1, SCHEME", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Sharanya Pal", "role": "Student Representative", "designation": "Student (22MSI0160)", "campus": "Vellore", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Ms. Sudha R", "role": "Member", "designation": "Manager, TBI", "campus": "Vellore", "phone": "0416 220 2302", "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},

    # ── ICC Members Chennai ───────────────────────────────────
    {"category": "icc_member", "name": "Dr. M. Helen Santhi M", "role": "Convenor", "designation": "Professor, SCE", "campus": "Chennai", "phone": "9443186924", "email": "helensanthi.m@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Ms. Jeyalekshmi B S", "role": "HR Team Member", "designation": "HR Team", "campus": "Chennai", "phone": "9994480859", "email": "jeyalekshmi.bs@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Ms. Radhika R", "role": "Member", "designation": "Visiting Faculty Law", "campus": "Chennai", "phone": None, "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Dr. Aruna R", "role": "Member", "designation": "Asst. Professor, VITBS", "campus": "Chennai", "phone": "9047712387", "email": "aruna.r@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Ms. S. Banumathi", "role": "Member", "designation": None, "campus": "Chennai", "phone": "6369407144", "email": "banumathi.s@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Nivedha S", "role": "Student Secretary", "designation": "PG Student (21MIS1119)", "campus": "Chennai", "phone": "8122543056", "email": "nivedha.s2021@vitstudent.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Lighittha P R", "role": "Student Secretary", "designation": "UG Student (22BLC1236)", "campus": "Chennai", "phone": "9940088718", "email": "lighittha.pr@vitstudent.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_member", "name": "Mrs. Mary Joseph", "role": "Member", "designation": "Section Supervisor, Administration", "campus": "Chennai", "phone": "9840300478", "email": "maryjoseph@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},

    # ── ICC General Contacts ──────────────────────────────────
    {"category": "icc_general", "committee": "Internal Complaints Committee", "campus": "Vellore", "phone": "96007 55022, 0416 220 2302", "email": "icc@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
    {"category": "icc_general", "committee": "Internal Complaints Committee", "campus": "Chennai", "phone": None, "email": "women.gcell@vit.ac.in", "source": "https://vit.ac.in/internal-complaints-committee"},
]

async def seed():
    await contacts.delete_many({})
    await contacts.insert_many(data)
    print(f"Inserted {len(data)} documents into contacts collection")
    print("Seeding complete!")

asyncio.run(seed())